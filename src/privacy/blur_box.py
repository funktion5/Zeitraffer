"""Blur people and licence plates in new camera images on the storage box, in place.

One round per run (cron). Per camera in ``privacy.blur_cameras``: list today's and the two
previous days' images with their upload times over SSH, skip what the state file already has and
record night images. Every settled daytime image is downloaded and detected on the local copy;
only if something is found is the original backed up on the box (it must be exactly the judged
bytes), the copy blurred, uploaded and swapped in. Images without findings cause no write at all.
Newest first, so after an outage the image the website shows next is done first.

Everything goes over SSH with timeouts, never through the SSHFS mount (it can hang or serve stale
data); every write goes through BoxWriter. Anything unclear leaves the image as it is and is
retried next round; images that can never be written (too old, unknown name) are recorded as
``refused`` and logged as errors, never skipped silently.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import PROJECT_ROOT, load_config
from src.images import image_moment
from src.logger import configure_file_logging, logger
from src.privacy.anonymize import (
	BlurSettings,
	DropRules,
	PrivacyCheckError,
	_probe_dimensions,
	blur_frame,
	filter_boxes,
	parse_blur_settings,
	parse_drop_rules,
	run_detector,
)
from src.privacy.box_writer import (
	BoxWriteDeferred,
	BoxWriter,
	BoxWriteRefused,
)
from src.solar import get_sun_times
from src.storage_filter import (
	StorageBox,
	acquire_run_lock,
	get_storage_box,
	list_images_for_dates,
)

DEFAULT_STATE_ROOT = PROJECT_ROOT / "state" / "privacy" / "box"
WORK_ROOT = PROJECT_ROOT / "temp" / "blur-box"
# Own lock, not the shared timelapse run lock: the nightly run can take hours and only reads,
# so it must not block blur rounds. Two blur rounds never overlap.
BLUR_LOCK_PATH = PROJECT_ROOT / "state" / "privacy-blur.lock"

# A camera upload in progress keeps touching the file; wait until it has been quiet this long.
DEFAULT_SETTLE_SECONDS = 15

# An upload still incomplete after this long has stalled; it is then logged as an error every
# round instead of waiting quietly. Not recorded, in case it completes after all.
STALLED_AFTER_SECONDS = 600

# Per camera and round: no new image is started after this, so a long backlog cannot keep fresh
# uploads waiting. The next round lists again and starts with the newest image.
DEFAULT_TIME_BUDGET_SECONDS = 40

# The nightly catch-up (--catch-up): two summer days of SLSV (~288 images x 8 s) fit, while a
# stalled box still releases the run lock in time for the videos.
CATCH_UP_BUDGET_SECONDS = 45 * 60

# One image takes ~8 s to detect; a hung detector must not hold the round for the batch default.
DETECTOR_TIMEOUT_SECONDS = 120

REPLACING = "replacing"
JPEG_END_MARKER = b"\xff\xd9"

# Today plus two days back: after an outage of up to two days, missed daytime images still reach
# the writer's logged "older than" refusal instead of silently falling out of the listing.
LISTED_DAYS = 3

# Per-image failures that leave the image untouched for the next round.
IMAGE_ERRORS = (
	OSError,
	PrivacyCheckError,
	subprocess.CalledProcessError,
	subprocess.TimeoutExpired,
)


@dataclass(frozen=True)
class Daylight:
	location: dict
	buffer_minutes: int


@dataclass
class BoxRoundSummary:
	blurred: int = 0
	clean: int = 0
	night: int = 0
	settling: int = 0
	refused: int = 0
	failed: int = 0
	postponed: int = 0


def sha256_file(path: Path) -> str:
	with path.open("rb") as file:
		return hashlib.file_digest(file, "sha256").hexdigest()


# A camera JPEG ends with the end-of-image marker; a partial upload almost never does.
def is_complete_jpeg(path: Path) -> bool:
	with path.open("rb") as file:
		if file.seek(0, os.SEEK_END) < 2:
			return False

		file.seek(-2, os.SEEK_END)

		return file.read(2) == JPEG_END_MARKER


# Same window as the Daily videos, so every frame that can end up in a video gets checked.
def is_daylight(moment: datetime, daylight: Daylight) -> bool:
	sunrise, sunset = get_sun_times(
		target_date=moment.date(),
		latitude=daylight.location["latitude"],
		longitude=daylight.location["longitude"],
		timezone=daylight.location["timezone"],
	)
	buffer = timedelta(minutes=daylight.buffer_minutes)

	return sunrise - buffer <= moment <= sunset + buffer


# One file per camera and month (by write time): the audit trail stays complete, while a round
# only reads the months its listing can reach.
def _state_path(state_root: Path, camera: str, moment: datetime) -> Path:
	return state_root / camera / f"{moment:%Y-%m}.jsonl"


# A later line for the same image replaces an earlier one; a broken line counts as unprocessed.
def load_processed(state_root: Path, camera: str, now: datetime) -> dict[str, dict]:
	months = dict.fromkeys(
		_state_path(state_root, camera, now - timedelta(days=offset))
		for offset in range(LISTED_DAYS)
	)
	# Before monthly files there was one file per camera; still read, so nothing is done twice.
	paths = [state_root / f"{camera}.jsonl", *sorted(months)]
	processed: dict[str, dict] = {}

	for path in paths:
		if not path.exists():
			continue

		for line in path.read_text(encoding="utf-8").splitlines():
			try:
				entry = json.loads(line)
				processed[entry["image"]] = entry

			except (json.JSONDecodeError, KeyError, TypeError):
				continue

	return processed


def record_processed(state_root: Path, camera: str, entry: dict, now: datetime) -> None:
	path = _state_path(state_root, camera, now)
	path.parent.mkdir(parents=True, exist_ok=True)

	# A power cut mid-write leaves a line without "\n"; never glue the next entry onto it.
	torn = False

	if path.exists() and path.stat().st_size:
		with path.open("rb") as existing:
			existing.seek(-1, os.SEEK_END)
			torn = existing.read(1) != b"\n"

	with path.open("a", encoding="utf-8") as file:
		file.write(("\n" if torn else "") + json.dumps(entry) + "\n")
		file.flush()
		os.fsync(file.fileno())


# Night only if both the filename clock and the upload time say so: a drifted camera clock or a
# name without a readable time must not let a daytime image pass unchecked.
def _is_night(moment: datetime | None, uploaded: int, daylight: Daylight) -> bool:
	if moment is None or is_daylight(moment, daylight):
		return False

	return not is_daylight(datetime.fromtimestamp(uploaded, moment.tzinfo), daylight)


# Coordinates only, never image content; they show recurring false positives.
# [x0, y0, x1, y1, score] plus the detector's label when it gave one.
def _as_lists(boxes: list) -> list[list]:
	return [
		[
			*(round(v) for v in (box.x0, box.y0, box.x1, box.y1)),
			round(box.score, 3),
			*([box.label] if box.label else []),
		]
		for box in boxes
	]


# One image from download to swap. Returns "blurred", "clean" or "settling"; anything else raises
# and leaves the image as it is: BoxWriteRefused (never writable) or IMAGE_ERRORS (retried).
def _process_image(
	writer: BoxWriter,
	camera: str,
	name: str,
	age_seconds: float,
	work_dir: Path,
	detector_command: list[str],
	settings: BlurSettings,
	rules: DropRules,
	state_root: Path,
	now: datetime,
) -> str:
	# Refuse before spending a download and a detection on an image that may never be written.
	writer.check(camera, name)

	# Detect first, on a local copy of the box's bytes; only an image with findings is backed
	# up and written.
	work_copy = work_dir / name
	writer.fetch(camera, name, work_copy)

	# A stalled upload can outlast the settle time, so completeness is checked as well.
	if not is_complete_jpeg(work_copy):
		if age_seconds >= STALLED_AFTER_SECONDS:
			raise PrivacyCheckError(
				f"{name} has been incomplete for over {STALLED_AFTER_SECONDS // 60} minutes."
			)

		return "settling"

	judged_hash = sha256_file(work_copy)
	detector, boxes_by_frame = run_detector(detector_command, [work_copy], DETECTOR_TIMEOUT_SECONDS)
	boxes = boxes_by_frame[work_copy]
	size = _probe_dimensions(work_copy) if boxes else None
	ignored = []

	if size:
		boxes, ignored = filter_boxes(boxes, size[1], rules, camera)

	entry = {"image": name, "detector": detector, "original_sha256": judged_hash}

	# Recorded, so a skipped box can always be traced afterwards.
	if ignored:
		entry["ignored_boxes"] = _as_lists(ignored)

	# The box must still hold exactly the judged bytes: the camera may rewrite the image during
	# detection. Nothing found then means nothing to write at all.
	if not boxes:
		if writer.image_hash(camera, name) != judged_hash:
			raise PrivacyCheckError(f"{name} on the box differs from the checked copy; retrying.")

		record_processed(state_root, camera, {**entry, "status": "clean"}, now)

		return "clean"

	backup = writer.backup(camera, name, judged_hash)
	entry["backup"] = backup.backup_name

	blur_frame(work_copy, boxes, settings, size)

	# A refusal here (e.g. blurring changed nothing) is not the image's fault: retry, not record.
	try:
		entry["blurred_sha256"] = writer.upload_blurred(backup, work_copy)

	except BoxWriteRefused as error:
		raise PrivacyCheckError(f"Blurred copy of {name} not uploaded: {error}") from error

	entry["boxes"] = _as_lists(boxes)

	# Written before the swap: after a power cut the next round can tell whether it happened.
	record_processed(state_root, camera, {**entry, "status": REPLACING}, now)
	writer.replace(backup, entry["blurred_sha256"])
	record_processed(state_root, camera, {**entry, "status": "blurred"}, now)

	return "blurred"


def process_box_camera(
	writer: BoxWriter,
	storage_box: StorageBox,
	camera: str,
	detector_command: list[str],
	settings: BlurSettings,
	daylight: Daylight,
	state_root: Path,
	now: datetime,
	settle_seconds: float = DEFAULT_SETTLE_SECONDS,
	time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
	rules: DropRules | None = None,
) -> BoxRoundSummary:
	summary = BoxRoundSummary()
	rules = rules or DropRules()
	timezone = daylight.location["timezone"]
	processed = load_processed(state_root, camera, now)

	today = now.date()
	days = [today - timedelta(days=offset) for offset in range(LISTED_DAYS)]
	uploaded = list_images_for_dates(storage_box, camera, days)
	daytime: list[str] = []

	for name, mtime in uploaded.items():
		entry = processed.get(name)

		if entry is not None and entry.get("status") != REPLACING:
			continue

		if _is_night(image_moment(name, timezone), mtime, daylight):
			record_processed(state_root, camera, {"image": name, "status": "night"}, now)
			summary.night += 1
			continue

		daytime.append(name)

	work_dir = WORK_ROOT / camera
	work_dir.mkdir(parents=True, exist_ok=True)

	# Newest first, so after a backlog the image the website shows next is done first.
	# A name without a readable time sorts last; the writer refuses it.
	oldest = datetime.min.replace(tzinfo=ZoneInfo(timezone))
	daytime.sort(key=lambda name: image_moment(name, timezone) or oldest, reverse=True)

	started = time.monotonic()

	try:
		for index, name in enumerate(daytime):
			# At least one image per round, so an image slower than the budget still gets done.
			if index and time.monotonic() - started >= time_budget_seconds:
				summary.postponed = len(daytime) - index
				break

			entry = processed.get(name, {})
			age_seconds = now.timestamp() - uploaded[name]

			# One image at a time; a failure of any kind affects only that image.
			try:
				# A power cut between swap and record: the box shows whether the swap happened.
				if entry.get("status") == REPLACING and writer.image_hash(
					camera, name
				) == entry.get("blurred_sha256"):
					record_processed(state_root, camera, {**entry, "status": "blurred"}, now)
					summary.blurred += 1
					continue

				if age_seconds < settle_seconds:
					summary.settling += 1
					continue

				status = _process_image(
					writer,
					camera,
					name,
					age_seconds,
					work_dir,
					detector_command,
					settings,
					rules,
					state_root,
					now,
				)

			except BoxWriteDeferred as error:
				logger.warning(f"[{camera}] Deferred {name}: {error}")
				summary.failed += 1
				continue

			except BoxWriteRefused as error:
				logger.error(f"[{camera}] Refused, stays unblurred: {name}: {error}")
				record_processed(
					state_root,
					camera,
					{"image": name, "status": "refused", "reason": str(error)},
					now,
				)
				summary.refused += 1
				continue

			except IMAGE_ERRORS as error:
				logger.error(f"[{camera}] Not processed, retrying next round: {name}: {error}")
				summary.failed += 1
				continue

			if status == "clean":
				summary.clean += 1
			elif status == "settling":
				summary.settling += 1
			else:
				summary.blurred += 1

	finally:
		for path in work_dir.iterdir():
			path.unlink(missing_ok=True)

	return summary


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Pixelate people and licence plates in new camera images on the storage box."
	)
	selection = parser.add_mutually_exclusive_group(required=True)
	selection.add_argument(
		"--cameras",
		nargs="+",
		help="Process only these cameras; each must be listed in privacy.blur_cameras.",
	)
	selection.add_argument(
		"--all-blur-cameras",
		action="store_true",
		help="Process every camera in privacy.blur_cameras (the cron job).",
	)
	parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_ROOT)
	parser.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_SECONDS)
	parser.add_argument(
		"--catch-up",
		action="store_true",
		help="Long time budget per camera (45 min instead of 40 s): handle the open images of "
		"the listed days in one run (before the nightly timelapse run).",
	)

	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
	args = parse_arguments(argv)
	configure_file_logging("privacy")

	config = load_config()
	privacy = config.get("privacy") or {}
	detector_command = privacy.get("detector_command")
	blur_cameras = privacy.get("blur_cameras") or []

	if not detector_command:
		logger.error("privacy.detector_command is not set.")
		return 1

	cameras = blur_cameras if args.all_blur_cameras else list(dict.fromkeys(args.cameras))
	not_listed = [camera for camera in cameras if camera not in blur_cameras]

	if not cameras or not_listed:
		logger.error(f"Not in privacy.blur_cameras, nothing written: {not_listed or 'no cameras'}")
		return 1

	# A typo in the blur or drop settings stops the round before anything is touched.
	try:
		settings = parse_blur_settings(privacy.get("blur"))
		rules = parse_drop_rules(privacy)

	except PrivacyCheckError as error:
		logger.error(f"Invalid privacy settings, nothing written: {error}")
		return 1

	location = config["location"]
	daylight = Daylight(location, config["daylight_buffer_minutes"])
	exit_code = 0

	with ExitStack() as stack:
		# Another blur round holds the lock: skip this one, the next picks the images up.
		try:
			stack.enter_context(acquire_run_lock(BLUR_LOCK_PATH))

		except RuntimeError as error:
			logger.info(f"Skipped: {error}")
			return 0

		try:
			storage_box = get_storage_box()

		except OSError as error:
			logger.error(f"No storage box: {error}")
			return 1

		# Only the selected cameras are writable in this run.
		try:
			writer = BoxWriter(
				storage_box.remote,
				storage_box.base_directory,
				cameras,
				location["timezone"],
				upload_root=WORK_ROOT,
			)

		except (BoxWriteRefused, ZoneInfoNotFoundError) as error:
			logger.error(f"Cannot write to the storage box: {error}")
			return 1

		for camera in cameras:
			try:
				# A missing folder would otherwise just list as "no images".
				if not writer.camera_exists(camera):
					logger.error(f"[{camera}] Camera folder not found on the storage box")
					exit_code = 1
					continue

				summary = process_box_camera(
					writer,
					storage_box,
					camera,
					detector_command,
					settings,
					daylight,
					args.state_dir,
					datetime.now(ZoneInfo(location["timezone"])),
					args.settle_seconds,
					# The catch-up runs before the nightly videos, when no fresh upload waits.
					time_budget_seconds=(
						CATCH_UP_BUDGET_SECONDS if args.catch_up else DEFAULT_TIME_BUDGET_SECONDS
					),
					rules=rules,
				)

			except (OSError, PrivacyCheckError, subprocess.SubprocessError) as error:
				logger.error(f"[{camera}] Round aborted, nothing replaced after this: {error}")
				exit_code = 1
				continue

			if summary.failed or summary.refused:
				exit_code = 1

			logger.info(
				f"[{camera}] blurred={summary.blurred} clean={summary.clean} "
				f"night={summary.night} settling={summary.settling} "
				f"refused={summary.refused} failed={summary.failed} "
				f"postponed={summary.postponed}"
			)

	return exit_code


if __name__ == "__main__":
	sys.exit(main())
