"""Copy the camera frames the nightly run needs from the storage box into a local folder.

For hosts that cannot mount the box (the web server): the pipeline reads ordinary local files, so
the frames are staged first and TIMELAPSE_CAMERA_ROOT points at the staging folder. Read-only on
the box; the only thing ever deleted is inside <project>/temp.

Run from anywhere (TIMELAPSE_STORAGE_BOX names the box, see src/storage_filter.py):
	python3 scripts/stage-frames.py [--target-date YYYY-MM-DD] [--cameras A B]
		[--destination PATH] [--clean-only] [--no-lock]
	python3 scripts/stage-frames.py --list-cameras

Takes state/zeitraffer-run.lock unless --no-lock (the caller already holds it). --list-cameras
only prints the cameras a nightly run covers, one per line, and touches nothing.

Exit codes: 0 = all cameras staged, 1 = some cameras failed, 2 = fatal (box unreachable, bad
arguments, unsafe destination, run lock held elsewhere).
"""

import argparse
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.date_coverage import get_coverage_date_range, get_latest_completed_date  # noqa: E402
from src.images import date_patterns, extract_date, extract_time  # noqa: E402
from src.interval_window import interval_window_from_config, resolve_target_seconds  # noqa: E402
from src.logger import logger  # noqa: E402
from src.storage_filter import (  # noqa: E402
	StorageBox,
	acquire_run_lock,
	get_storage_box,
	list_camera_files,
)

TEMP_ROOT = PROJECT_ROOT / "temp"
DEFAULT_DESTINATION = TEMP_ROOT / "camera-staging"

# Proves a folder was created by this script; without it the folder is never wiped.
STAGING_MARKER = ".stage-frames"

LISTING_TIMEOUT_SECONDS = 60

# rsync's own --timeout aborts a stalled transfer; the outer limit (per camera attempt) only
# catches a hung or trickling process. A guess until the first measured copy; tighten it then.
RSYNC_IDLE_TIMEOUT_SECONDS = 300
RSYNC_TOTAL_TIMEOUT_SECONDS = 60 * 60

# Waits after the first and the second failed attempt, so a camera gets three attempts.
RETRY_WAIT_SECONDS = (30, 120)

EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_FATAL = 2


# Names of every frame any automatic job may ask for, as a superset (the jobs still apply their own
# validation, daylight window, duplicate filter and coverage checks on the staged copy).
# Daily: the target day and the previous day, matched by filename substring exactly like
# find_images_for_dates. Monthly/Yearly: the yearly date range inside the interval window
# (Monthly is a subset of it). Weekly joins existing Daily videos and needs no frames.
def select_frame_names(names: list[str], target_date: date, config: dict) -> list[str]:
	daily_patterns = date_patterns(target_date) + date_patterns(target_date - timedelta(days=1))

	start_date, end_date = get_coverage_date_range(end_date=target_date, coverage_type="yearly")
	window = interval_window_from_config(config)
	target_seconds_by_date = resolve_target_seconds(
		window=window,
		start_date=start_date,
		end_date=end_date,
		location=config["location"],
	)
	tolerance_seconds = window.tolerance_minutes * 60

	selected = []

	for name in names:
		if not name.lower().endswith(".jpg"):
			continue

		if any(pattern in name for pattern in daily_patterns):
			selected.append(name)
			continue

		image_date = extract_date(name)

		if image_date is None or not (start_date <= image_date <= end_date):
			continue

		image_time = extract_time(name)

		if image_time is None:
			continue

		hour, minute, second = image_time
		capture_seconds = hour * 60 * 60 + minute * 60 + second

		if abs(capture_seconds - target_seconds_by_date[image_date]) <= tolerance_seconds:
			selected.append(name)

	return sorted(selected)


# Camera folders on the box: directories only, hidden ones are not listed by `ls -l`.
def list_box_cameras(storage_box: StorageBox) -> list[str]:
	directory = storage_box.base_directory or "."

	try:
		result = storage_box.run(f"ls -l {shlex.quote(directory)}", LISTING_TIMEOUT_SECONDS)

	except subprocess.TimeoutExpired as error:
		raise TimeoutError("Storage box camera listing timed out") from error

	if result.returncode != 0:
		raise OSError(f"Storage box camera listing failed: {result.stderr.strip()}")

	cameras = []

	for line in result.stdout.splitlines():
		fields = line.split(maxsplit=8)

		if len(fields) == 9 and fields[0].startswith("d"):
			cameras.append(fields[8])

	return sorted(cameras)


# Deleting is only ever allowed strictly inside <project>/temp, after resolving symlinks and "..".
def guard_destination(destination: Path) -> Path:
	resolved = destination.resolve()
	temp_root = TEMP_ROOT.resolve()

	if resolved == temp_root or temp_root not in resolved.parents:
		raise ValueError(f"Staging destination must be inside {temp_root}: {resolved}")

	return resolved


# Only a folder this script created (marker file) or an empty one may be removed, so a mistyped
# --destination such as temp/<camera> can never wipe the pipeline's own working frames.
def wipe_destination(destination: Path) -> None:
	if not destination.exists():
		return

	if not destination.is_dir():
		raise ValueError(f"Staging destination is not a folder: {destination}")

	if (destination / STAGING_MARKER).is_file():
		shutil.rmtree(destination)

	elif not any(destination.iterdir()):
		destination.rmdir()

	else:
		raise ValueError(
			f"Refusing to delete {destination}: no {STAGING_MARKER} marker, so it was not created "
			"by this script"
		)


def create_destination(destination: Path) -> None:
	destination.mkdir(parents=True, exist_ok=True)
	(destination / STAGING_MARKER).touch()


# Copy the selected frames of one camera. A failure keeps what was copied so the next attempt only
# transfers the rest; stage() removes the folder once the last attempt has failed, so the
# pipeline never sees a half-copied camera.
def copy_camera(
	storage_box: StorageBox,
	camera: str,
	names: list[str],
	destination: Path,
) -> None:
	camera_destination = destination / camera
	camera_destination.mkdir(parents=True, exist_ok=True)

	# Whatever an earlier attempt left that is not in this selection (a frame gone from the box, or
	# rsync's temporary file after a killed transfer) must not reach the pipeline.
	wanted = set(names)

	for leftover in camera_destination.iterdir():
		if leftover.name not in wanted and leftover.is_file():
			leftover.unlink()

	# An empty folder still makes the camera visible to the pipeline, which then logs "skipped"
	# exactly as it would on the Pi.
	if not names:
		return

	command = [
		"rsync",
		"-t",
		"--from0",
		"--files-from=-",
		f"--timeout={RSYNC_IDLE_TIMEOUT_SECONDS}",
		"-e",
		"ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
		f"{storage_box.remote}:{storage_box.camera_directory(camera)}/",
		f"{camera_destination}/",
	]

	try:
		result = subprocess.run(
			command,
			input="\0".join(names).encode() + b"\0",
			capture_output=True,
			timeout=RSYNC_TOTAL_TIMEOUT_SECONDS,
			check=False,
		)

	except (subprocess.TimeoutExpired, OSError) as error:
		raise OSError(f"rsync did not finish for camera {camera}: {error}") from error

	if result.returncode != 0:
		raise OSError(
			f"rsync failed for camera {camera} (exit {result.returncode}): "
			f"{result.stderr.decode(errors='replace').strip()}"
		)


# Stage one camera, retrying only transient failures (OSError, which includes TimeoutError). Every
# attempt lists the folder again, since files may have changed. A config or code error is not
# caught here: it would fail the same way every time and must stop the script. Returns the staged
# frame count.
def stage_camera(
	storage_box: StorageBox,
	camera: str,
	target_date: date,
	config: dict,
	destination: Path,
) -> int:
	def try_once() -> int:
		names = select_frame_names(
			list(list_camera_files(storage_box, camera)),
			target_date,
			config,
		)
		copy_camera(storage_box, camera, names, destination)

		return len(names)

	for attempt, wait_seconds in enumerate(RETRY_WAIT_SECONDS, start=1):
		try:
			return try_once()

		except OSError as error:
			logger.warning(
				f"Staging attempt {attempt} failed for camera {camera}, "
				f"retrying in {wait_seconds} s: {error}"
			)
			time.sleep(wait_seconds)

	# The last attempt is not caught: its error goes to stage(), which removes the camera folder.
	return try_once()


# Returns the cameras that could not be staged.
def stage(
	storage_box: StorageBox,
	cameras: list[str],
	target_date: date,
	config: dict,
	destination: Path,
) -> list[str]:
	failed = []

	for camera in cameras:
		if "/" in camera or camera in (".", ".."):
			logger.error(f"Refusing unsafe camera folder name: {camera!r}")
			failed.append(camera)
			continue

		try:
			frame_count = stage_camera(storage_box, camera, target_date, config, destination)

		except OSError:
			logger.exception(f"Failed to stage camera after all attempts: {camera}")
			shutil.rmtree(destination / camera, ignore_errors=True)
			failed.append(camera)
			continue

		logger.info(f"Staged {frame_count} frames for camera: {camera}")

	return failed


def parse_arguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--target-date", type=date.fromisoformat)
	parser.add_argument("--cameras", nargs="+")
	parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
	parser.add_argument("--clean-only", action="store_true")
	# For the nightly wrapper, which already holds state/zeitraffer-run.lock for the whole run.
	parser.add_argument("--no-lock", action="store_true")
	# For the nightly wrapper's per-camera loop: only prints, never wipes or copies anything.
	parser.add_argument("--list-cameras", action="store_true")

	return parser.parse_args()


# The cameras a nightly run covers: everything on the box except ignored_cameras, one per line on
# stdout (the logger writes to stderr, so the list stays clean).
def list_cameras() -> int:
	config = load_config()

	try:
		available = list_box_cameras(get_storage_box())

	except OSError:
		logger.exception("Storage box is not reachable")
		return EXIT_FATAL

	ignored = set(config.get("ignored_cameras", []))
	sys.stdout.write("".join(f"{camera}\n" for camera in available if camera not in ignored))

	return EXIT_OK


def main() -> int:
	arguments = parse_arguments()

	if arguments.list_cameras:
		return list_cameras()

	try:
		destination = guard_destination(arguments.destination)

	except ValueError as error:
		logger.error(str(error))
		return EXIT_FATAL

	# Wiping frames while a run reads them would break that run, so the shared run lock comes first.
	try:
		with nullcontext() if arguments.no_lock else acquire_run_lock():
			return run(arguments, destination)

	except (RuntimeError, ValueError) as error:
		logger.error(str(error))
		return EXIT_FATAL

	# An uncaught exception would exit 1, which means "some cameras failed" to the wrapper.
	except Exception:
		logger.exception("Unexpected error while staging")
		return EXIT_FATAL


def run(arguments: argparse.Namespace, destination: Path) -> int:
	# Stale frames from an earlier run must never leak into this one.
	wipe_destination(destination)

	if arguments.clean_only:
		logger.info(f"Removed staging folder: {destination}")
		return EXIT_OK

	config = load_config()
	target_date = arguments.target_date or get_latest_completed_date(config["location"]["timezone"])

	try:
		storage_box = get_storage_box()
		available = list_box_cameras(storage_box)

	except OSError:
		logger.exception("Storage box is not reachable")
		return EXIT_FATAL

	if arguments.cameras:
		missing = [camera for camera in arguments.cameras if camera not in available]

		if missing:
			logger.error(f"Requested cameras not found on the box: {', '.join(missing)}")
			return EXIT_FATAL

		cameras = list(dict.fromkeys(arguments.cameras))

	else:
		ignored = set(config.get("ignored_cameras", []))
		cameras = [camera for camera in available if camera not in ignored]

	create_destination(destination)
	logger.info(f"Staging {len(cameras)} cameras for {target_date} into {destination}")

	failed = stage(storage_box, cameras, target_date, config, destination)

	if failed:
		logger.error(f"Staging failed for: {', '.join(failed)}")
		return EXIT_SOME_FAILED

	return EXIT_OK


if __name__ == "__main__":
	sys.exit(main())
