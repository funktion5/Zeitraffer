import argparse
import csv
import fcntl
import shlex
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import src.images as images_module
from src.config import PROJECT_ROOT, load_config
from src.images import extract_date, get_cameras
from src.logger import LOG_TIMEZONE, cleanup_old_logs, configure_file_logging, logger

REPORT_ROOT = PROJECT_ROOT / "reports" / "storage-filter"
RUN_LOCK_PATH = PROJECT_ROOT / "state" / "zeitraffer-run.lock"
REPORT_COLUMNS = ("camera", "path", "reason")
MOUNTS_PATH = Path("/proc/mounts")

# Mirror /etc/timelapse/mount.env, which only root may read. User and host come
# from the live mount; keep these two in sync with mount.env by hand.
STORAGE_BOX_PORT = 23
STORAGE_BOX_KEY = Path.home() / ".ssh" / "storagebox_ed25519"

# A listing of ~240k files takes a few seconds.
LISTING_TIMEOUT_SECONDS = 60

# Measured on the storage box: 1,000 files per sha256sum call take 10-20 s, and
# 4 parallel calls scale almost linearly. More would compete with the mount.
HASH_BATCH_SIZE = 1000
PARALLEL_HASH_CALLS = 4
HASH_TIMEOUT_SECONDS = 180

# Long duplicate checks otherwise print nothing until the report is written.
PROGRESS_LOG_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class StorageBox:
	remote: str
	base_directory: str

	def camera_directory(self, camera: str) -> str:
		if not self.base_directory:
			return camera

		return f"{self.base_directory.rstrip('/')}/{camera}"

	# Run one read-only command on the storage box's own shell.
	def run(self, command: str, timeout_seconds: float) -> subprocess.CompletedProcess:
		return subprocess.run(
			[
				"ssh",
				"-p",
				str(STORAGE_BOX_PORT),
				"-i",
				str(STORAGE_BOX_KEY),
				"-o",
				"BatchMode=yes",
				"-o",
				"StrictHostKeyChecking=yes",
				self.remote,
				command,
			],
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			check=False,
		)


# Return the storage box behind the live camera mount.
def get_storage_box(mounts_path: Path = MOUNTS_PATH) -> StorageBox:
	camera_root = str(images_module.CAMERA_ROOT)

	for line in mounts_path.read_text().splitlines():
		fields = line.split()

		if len(fields) >= 3 and fields[1] == camera_root and fields[2] == "fuse.sshfs":
			remote, _, base_directory = fields[0].partition(":")
			return StorageBox(remote=remote, base_directory=base_directory)

	raise OSError(f"No SSHFS mount found at {camera_root}")


# Map regular file names to their size from `ls -l` output.
def parse_ls_output(output: str) -> dict[str, int]:
	file_sizes: dict[str, int] = {}

	for line in output.splitlines():
		fields = line.split(maxsplit=8)

		# The "total" line, directories and symlinks are skipped.
		if len(fields) < 9 or not fields[0].startswith("-"):
			continue

		file_sizes[fields[8]] = int(fields[4])

	return file_sizes


# One `ls -l` on the storage box replaces one SSHFS stat per file, which took
# up to ~45 minutes for 190k files instead of a few seconds.
def list_camera_files(storage_box: StorageBox, camera: str) -> dict[str, int]:
	directory = storage_box.camera_directory(camera)

	try:
		result = storage_box.run(f"ls -l {shlex.quote(directory)}", LISTING_TIMEOUT_SECONDS)

	except subprocess.TimeoutExpired as error:
		raise TimeoutError(f"Storage box listing timed out for camera: {camera}") from error

	if result.returncode != 0:
		raise OSError(f"Storage box listing failed for camera {camera}: {result.stderr.strip()}")

	return parse_ls_output(result.stdout)


# Hash files on the storage box, so only the hashes cross the network. Reading
# them over SSHFS instead took ~43 ms per file (2+ hours for one camera).
def hash_camera_files(storage_box: StorageBox, camera: str, names: list[str]) -> dict[str, str]:
	directory = storage_box.camera_directory(camera)
	paths = " ".join(shlex.quote(f"{directory}/{name}") for name in names)

	try:
		result = storage_box.run(f"sha256sum {paths}", HASH_TIMEOUT_SECONDS)

	except subprocess.TimeoutExpired as error:
		raise TimeoutError(f"Storage box hashing timed out for camera: {camera}") from error

	hashes: dict[str, str] = {}
	prefix = f"{directory}/"

	for line in result.stdout.splitlines():
		image_hash, _, path = line.partition("  ")

		if path.startswith(prefix):
			hashes[path.removeprefix(prefix)] = image_hash

	# A file that vanished or was unreadable must fail loudly, not look unique.
	if result.returncode != 0 or len(hashes) != len(names):
		raise OSError(f"Storage box hashing failed for camera {camera}: {result.stderr.strip()}")

	return hashes


# Split files into empty ones and same-day groups of equal size.
def group_files(
	file_sizes: dict[str, int],
	today: date,
) -> tuple[list[str], list[list[str]]]:
	empty_names: list[str] = []
	same_size_by_day: dict[tuple[date, int], list[str]] = {}

	for name, size in file_sizes.items():
		if not name.lower().endswith(".jpg"):
			continue

		image_date = extract_date(name)

		# Today's images may still be uploading; unknown names are never guessed.
		if image_date is None or image_date >= today:
			continue

		if size == 0:
			empty_names.append(name)
			continue

		same_size_by_day.setdefault((image_date, size), []).append(name)

	# Only same-day files of equal size can be duplicates.
	duplicate_groups = [
		sorted(names) for _, names in sorted(same_size_by_day.items()) if len(names) > 1
	]

	return sorted(empty_names), duplicate_groups


# Keep the first file of each group per content; every later copy is a duplicate.
def find_duplicates(duplicate_groups: list[list[str]], hashes: dict[str, str]) -> list[str]:
	duplicates: list[str] = []

	for names in duplicate_groups:
		seen_hashes: set[str] = set()

		for name in names:
			if hashes[name] in seen_hashes:
				duplicates.append(name)
				continue

			seen_hashes.add(hashes[name])

	return duplicates


def hash_in_batches(
	storage_box: StorageBox,
	camera: str,
	names: list[str],
) -> dict[str, str]:
	batches = [
		names[start : start + HASH_BATCH_SIZE] for start in range(0, len(names), HASH_BATCH_SIZE)
	]
	hashes: dict[str, str] = {}
	last_progress_log = time.monotonic()

	executor = ThreadPoolExecutor(max_workers=PARALLEL_HASH_CALLS)

	try:
		futures = [
			executor.submit(hash_camera_files, storage_box, camera, batch) for batch in batches
		]

		for future in as_completed(futures):
			hashes.update(future.result())

			if time.monotonic() - last_progress_log >= PROGRESS_LOG_INTERVAL_SECONDS:
				logger.info(
					f"Storage filter: camera {camera} | "
					f"checked {len(hashes)}/{len(names)} files for duplicates"
				)
				last_progress_log = time.monotonic()

	finally:
		# On a failed batch or Ctrl+C, drop the queued batches: only the calls
		# already running finish, instead of hashing the rest of the camera.
		executor.shutdown(wait=True, cancel_futures=True)

	return hashes


# Collect empty images and same-day duplicates for one camera.
def find_deletion_candidates(
	storage_box: StorageBox,
	camera: str,
	today: date,
) -> list[tuple[Path, str]]:
	file_sizes = list_camera_files(storage_box, camera)
	empty_names, duplicate_groups = group_files(file_sizes, today)
	names_to_hash = [name for names in duplicate_groups for name in names]

	logger.info(
		f"Storage filter: camera {camera} | listed={len(file_sizes)} | "
		f"empty={len(empty_names)} | checking {len(names_to_hash)} files for duplicates"
	)

	hashes = hash_in_batches(storage_box, camera, names_to_hash)
	camera_path = images_module.CAMERA_ROOT / camera

	candidates = [(camera_path / name, "empty") for name in empty_names]
	candidates.extend(
		(camera_path / name, "duplicate") for name in find_duplicates(duplicate_groups, hashes)
	)

	return sorted(candidates)


# Write to a temporary file first, so a crash never leaves a half-written list
# that someone could delete from.
def write_report(
	camera: str,
	candidates: list[tuple[Path, str]],
	report_path: Path,
) -> None:
	# 770 like logs/ and temp/: www-data must not read the report tree.
	report_path.parent.parent.mkdir(mode=0o770, exist_ok=True)
	report_path.parent.mkdir(mode=0o770, exist_ok=True)
	temp_path = report_path.with_name(f".{report_path.name}.tmp")

	# utf-8-sig and ";" so German Excel opens it correctly with a double-click.
	with temp_path.open("w", encoding="utf-8-sig", newline="") as report_file:
		writer = csv.writer(report_file, delimiter=";")
		writer.writerow(REPORT_COLUMNS)
		writer.writerows((camera, str(path), reason) for path, reason in candidates)

	temp_path.replace(report_path)


# Share the cron/web lock so a scan never competes with a timelapse run.
@contextmanager
def acquire_run_lock(lock_path: Path = RUN_LOCK_PATH) -> Iterator[None]:
	lock_path.parent.mkdir(exist_ok=True)

	with lock_path.open("a") as lock_file:
		try:
			fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

		except BlockingIOError:
			raise RuntimeError(f"Another timelapse run holds the lock: {lock_path}") from None

		yield


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Report empty and same-day duplicate images per camera. Never deletes."
	)

	camera_selection = parser.add_mutually_exclusive_group(required=True)

	camera_selection.add_argument(
		"--cameras",
		nargs="+",
		help="Scan the named cameras, including ones listed in ignored_cameras.",
	)

	camera_selection.add_argument(
		"--all-cameras",
		action="store_true",
		help="Scan every camera that is not listed in ignored_cameras.",
	)

	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
	args = parse_arguments(argv)
	config = load_config()

	configure_file_logging("filter")
	cleanup_old_logs(retention_days=config["log_retention_days"])

	available_cameras = get_cameras()

	if args.all_cameras:
		ignored_cameras = set(config.get("ignored_cameras", []))
		cameras = [camera for camera in available_cameras if camera not in ignored_cameras]

	else:
		cameras = list(dict.fromkeys(args.cameras))
		missing_cameras = [camera for camera in cameras if camera not in available_cameras]

		if missing_cameras:
			missing_camera_names = ", ".join(missing_cameras)
			logger.error(f"Requested cameras not found: {missing_camera_names}")
			raise ValueError(f"Requested cameras not found: {missing_camera_names}")

	try:
		storage_box = get_storage_box()

	except OSError:
		logger.exception("Storage filter needs the SSHFS camera mount to be up.")
		raise

	run_started = datetime.now(tz=LOG_TIMEZONE)
	failed_cameras: list[str] = []

	with acquire_run_lock():
		for camera in cameras:
			logger.info(f"Storage filter: scanning camera {camera}")

			try:
				candidates = find_deletion_candidates(
					storage_box=storage_box,
					camera=camera,
					today=run_started.date(),
				)
				report_path = REPORT_ROOT / f"{camera}_{run_started:%Y-%m-%d_%H%M%S}.csv"
				write_report(camera=camera, candidates=candidates, report_path=report_path)

			except (OSError, TimeoutError):
				logger.exception(f"Storage filter failed for camera: {camera}")
				failed_cameras.append(camera)
				continue

			empty_count = sum(1 for _, reason in candidates if reason == "empty")
			logger.info(
				f"Storage filter: camera {camera} | empty={empty_count} | "
				f"duplicate={len(candidates) - empty_count} | report={report_path}"
			)

	return 1 if failed_cameras else 0


if __name__ == "__main__":
	raise SystemExit(main())
