"""Fetch the Monthly/Yearly window images of the NAS camera tar archives onto the Pi.

The NAS is only reachable over FTP. Uploading unpacked images back costs one data connection
per file (~3 min per tar), so instead each tar is streamed down once with `rclone cat` and only
the .jpg members inside the interval window are written flat (basename only) to
<output>/<camera>/. yearly-backfill.py then reads them via TIMELAPSE_CAMERA_ROOT=<output>.
Finished tars are recorded per window, so a stopped run resumes. Never writes to the NAS.

Run from anywhere:
	.venv/bin/python3 nas/nas-extract.py --cameras BSV-Steinhude
	.venv/bin/python3 nas/nas-extract.py --all-cameras [--exclude A B] [--limit N]
		[--window-time HH:MM|sunset] [--window-tolerance-minutes N]
"""

import argparse
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.images import extract_date, extract_time  # noqa: E402
from src.interval_window import (  # noqa: E402
	IntervalWindow,
	interval_window_from_config,
	parse_window_time,
	resolve_target_seconds,
)
from src.storage_filter import acquire_run_lock  # noqa: E402

DEFAULT_SOURCE = "nas:Webcams/storagebox-mirror/tar"
DEFAULT_OUTPUT = Path.home() / "nas-cameras"
STATE_DIRECTORY = PROJECT_ROOT / "state"
LOCK_PATH = STATE_DIRECTORY / "nas-extract.lock"
LOG_PATH = PROJECT_ROOT / "logs" / "nas-extract.log"

TAR_NAME_PATTERN = re.compile(r"^backup_(?P<camera>.+)_(?P<date>\d{8})\.tar$")

logger = logging.getLogger("nas-extract")


def parse_arguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	selection = parser.add_mutually_exclusive_group(required=True)
	selection.add_argument("--cameras", nargs="+", help="Only fetch these cameras.")
	selection.add_argument("--all-cameras", action="store_true", help="Fetch every camera.")
	parser.add_argument("--exclude", nargs="+", default=[], help="Cameras to leave out.")
	parser.add_argument("--limit", type=int, help="Stop after this many tars (for a timing test).")
	parser.add_argument(
		"--output",
		type=Path,
		default=DEFAULT_OUTPUT,
		help=f"Camera root to write into (default {DEFAULT_OUTPUT}).",
	)
	parser.add_argument(
		"--source",
		default=DEFAULT_SOURCE,
		help=f"rclone folder holding the tars (default {DEFAULT_SOURCE}).",
	)
	parser.add_argument("--window-time", help="Window centre HH:MM or 'sunset' (default: config).")
	parser.add_argument("--window-tolerance-minutes", type=int, help="Default: config.")
	parser.add_argument(
		"--until-date",
		type=date.fromisoformat,
		help="Skip images dated after this day (YYYY-MM-DD), e.g. years the storage box covers.",
	)
	return parser.parse_args()


def configure_logging() -> None:
	LOG_PATH.parent.mkdir(exist_ok=True)
	formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

	for handler in (logging.StreamHandler(), logging.FileHandler(LOG_PATH)):
		handler.setFormatter(formatter)
		logger.addHandler(handler)

	logger.setLevel(logging.INFO)


def build_window(args: argparse.Namespace, config: dict) -> IntervalWindow:
	default = interval_window_from_config(config)

	return IntervalWindow(
		target=parse_window_time(args.window_time) if args.window_time else default.target,
		tolerance_minutes=args.window_tolerance_minutes or default.tolerance_minutes,
	)


class WindowFilter:
	"""Decide per file name whether an image falls inside the interval window."""

	def __init__(self, window: IntervalWindow, location: dict, until: date | None = None) -> None:
		self.window = window
		self.location = location
		self.until = until
		self.tolerance_seconds = window.tolerance_minutes * 60
		# Sunset moves daily, so the centre is resolved lazily and cached per date.
		self.target_by_date: dict[date, int] = {}

	def accepts(self, name: str) -> bool | None:
		"""True/False for a parsed name, None if the date or time format is unknown."""
		image_date = extract_date(name)
		image_time = extract_time(name)

		if image_date is None or image_time is None:
			return None

		if self.until is not None and image_date > self.until:
			return False

		if image_date not in self.target_by_date:
			self.target_by_date.update(
				resolve_target_seconds(self.window, image_date, image_date, self.location)
			)

		hour, minute, second = image_time
		capture_seconds = hour * 60 * 60 + minute * 60 + second

		# Same rule as find_interval_images, so nothing the backfill would use is dropped.
		return abs(capture_seconds - self.target_by_date[image_date]) <= self.tolerance_seconds


def list_tars(source: str) -> list[tuple[str, str, int]]:
	"""Return (camera, tar name, size) for every recognised tar, oldest first per camera."""
	output = subprocess.run(
		["rclone", "lsf", "--files-only", "--format", "sp", "--separator", ";", source],
		capture_output=True,
		text=True,
		check=True,
	).stdout

	tars = []

	for line in output.splitlines():
		size, _, name = line.partition(";")
		match = TAR_NAME_PATTERN.match(name)

		if match is None:
			logger.warning(f"Skipping unrecognised file name: {name}")
			continue

		tars.append((match["camera"], name, int(size)))

	return sorted(tars, key=lambda tar: (tar[0], tar[1]))


def load_done(done_path: Path) -> set[str]:
	if not done_path.exists():
		return set()

	return set(done_path.read_text().split())


def mark_done(done_path: Path, tar_name: str) -> None:
	with done_path.open("a") as done_file:
		done_file.write(tar_name + "\n")


def fetch_tar(
	source: str, tar_name: str, target: Path, window_filter: WindowFilter
) -> dict[str, int]:
	"""Stream one tar from the NAS and write its in-window .jpg members flat into target."""
	counts = dict.fromkeys(("kept", "outside", "unknown_format", "other", "existing"), 0)

	download = subprocess.Popen(["rclone", "cat", f"{source}/{tar_name}"], stdout=subprocess.PIPE)

	try:
		# "r|*" reads the stream sequentially, so the tar never has to exist on disk.
		with tarfile.open(fileobj=download.stdout, mode="r|*") as archive:
			for member in archive:
				name = os.path.basename(member.name)

				if not member.isfile():
					continue

				# Basename only: the folder chains differ per camera and the date is in the
				# file name, so flattening loses nothing and blocks path traversal.
				if not name.lower().endswith(".jpg") or name.startswith("."):
					counts["other"] += 1
					continue

				accepted = window_filter.accepts(name)

				if accepted is None:
					counts["unknown_format"] += 1
					continue

				if not accepted:
					counts["outside"] += 1
					continue

				destination = target / name

				if destination.exists():
					counts["existing"] += 1
					continue

				# Write under a temporary name so an interrupted run never leaves a
				# truncated image that a later scan would treat as valid.
				partial = target / f".{name}.part"

				with partial.open("wb") as output:
					shutil.copyfileobj(archive.extractfile(member), output)

				os.utime(partial, (member.mtime, member.mtime))
				partial.replace(destination)
				counts["kept"] += 1

	finally:
		download.stdout.close()
		return_code = download.wait()

	if return_code != 0:
		raise subprocess.CalledProcessError(return_code, ["rclone", "cat", tar_name])

	return counts


def handle_sigterm(signum, frame):
	# Turn SIGTERM into a normal exit so the finally blocks stop the download cleanly.
	raise SystemExit(f"Stopped by signal {signum}")


def main() -> int:
	args = parse_arguments()
	configure_logging()
	signal.signal(signal.SIGTERM, handle_sigterm)

	config = json.loads((PROJECT_ROOT / "config" / "config.json").read_text())
	window = build_window(args, config)
	window_filter = WindowFilter(window, config["location"], args.until_date)
	# One record per window: a later sunset fetch must not skip tars fetched for 12:00.
	done_path = STATE_DIRECTORY / f"nas-extract-done_{window.label()}.txt"
	STATE_DIRECTORY.mkdir(exist_ok=True)

	with acquire_run_lock(LOCK_PATH):
		tars = list_tars(args.source)
		done = load_done(done_path)
		excluded = set(args.exclude)
		wanted = set(args.cameras) if args.cameras else None

		pending = [
			tar
			for tar in tars
			if tar[1] not in done
			and tar[0] not in excluded
			and (wanted is None or tar[0] in wanted)
		]

		if args.limit is not None:
			pending = pending[: args.limit]

		total_bytes = sum(tar[2] for tar in pending)
		logger.info("-" * 80)
		logger.info(
			f"Starting NAS fetch | source={args.source} | window={window.describe()} | "
			f"until={args.until_date} | output={args.output} | "
			f"tars={len(pending)} ({total_bytes / 2**30:.1f} GiB) | already done={len(done)}"
		)

		done_bytes = 0
		run_started = time.monotonic()

		for index, (camera, tar_name, size) in enumerate(pending, start=1):
			target = args.output / camera

			if target.is_symlink():
				# Old setup pointed cameras at NAS folders; never write through such a link.
				logger.error(f"Skipping {camera}: {target} is a symlink, replace it with a folder")
				continue

			target.mkdir(parents=True, exist_ok=True)

			try:
				started = time.monotonic()
				counts = fetch_tar(args.source, tar_name, target, window_filter)
				mark_done(done_path, tar_name)
				logger.info(
					f"Done {tar_name} | {size / 2**20:.0f} MiB | "
					+ " ".join(f"{key}={value}" for key, value in counts.items())
					+ f" | {time.monotonic() - started:.0f}s"
				)

			except (OSError, subprocess.CalledProcessError, tarfile.TarError):
				# One broken tar or a network hiccup must not end the night; a later run
				# retries it because it was not marked done.
				logger.exception(f"Failed {tar_name}, will retry on the next run")

			done_bytes += size
			elapsed = time.monotonic() - run_started
			remaining = elapsed / done_bytes * (total_bytes - done_bytes) if done_bytes else 0
			logger.info(
				f"Progress {index}/{len(pending)} | "
				f"{100 * done_bytes / total_bytes if total_bytes else 100:.1f}% | "
				f"ETA {remaining / 60:.0f} min"
			)

	logger.info("NAS fetch finished")
	return 0


if __name__ == "__main__":
	sys.exit(main())
