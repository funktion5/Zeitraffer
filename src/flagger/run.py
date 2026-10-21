import argparse
import sys
import time
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from src.config import PROJECT_ROOT, automatic_daylight_buffer_for, load_config
from src.date_coverage import get_latest_completed_date
from src.flagger.groups import best_flag
from src.flagger.report import (
	FlaggedImage,
	build_manifest,
	cleanup_old_reports,
	copy_name,
	write_report,
)
from src.flagger.settings import load_flagger_settings
from src.flagger.yolox import Forward, OnnxForward, detect_image, detector_id
from src.images import (
	JPEG_END_MARKER,
	find_daily_images_isolated,
	get_cameras,
	image_moment,
	require_cameras,
)
from src.logger import configure_file_logging, logger
from src.solar import get_sun_times
from src.storage_filter import RUN_LOCK_PATH, acquire_run_lock

# The shared run lock of cron, web jobs and the storage filter: never alongside an encode.
LOCK_PATH = RUN_LOCK_PATH
VIDEO_ROOT = PROJECT_ROOT / "videos"
DEFAULT_MODEL = PROJECT_ROOT / "models" / "object_detection_yolox_2022nov.onnx"
# Folder name of a test-mode report below --out.
TEST_CAMERA = "adhoc"


@dataclass(frozen=True)
class ImageScan:
	flagged: list[FlaggedImage]
	# Images that were analysed.
	checked: int
	# Unreadable images and names without a parseable time; skipped, never guessed.
	failed: int


def scan_images(
	images: list[Path],
	forward: Forward,
	timezone: str,
	tiles: int = 2,
) -> ImageScan:
	flagged = []
	checked = 0
	failed = 0

	for path in images:
		# image_moment only knows lowercase ".jpg"; the file listing accepts any case.
		taken_at = image_moment(copy_name(path), timezone)

		if taken_at is None:
			logger.warning(f"Skipping image without a parseable time: {path.name}")
			failed += 1
			continue

		# One read for both checks. A cut-off upload has no end marker and would decode with a
		# grey lower part. Not fail-closed like the blur job: a missed flag costs nothing.
		data = path.read_bytes()
		image = None

		if data.endswith(JPEG_END_MARKER):
			flags = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
			image = cv2.imdecode(np.frombuffer(data, np.uint8), flags)

		if image is None:
			logger.warning(f"Skipping unreadable or truncated image: {path.name}")
			failed += 1
			continue

		checked += 1
		best = best_flag(detect_image(image, forward, tiles))

		if best is not None:
			height, width = image.shape[:2]
			flagged.append(
				FlaggedImage(
					path=path, detection=best, taken_at=taken_at, image_size=(width, height)
				)
			)

	return ImageScan(flagged=flagged, checked=checked, failed=failed)


# The same images the automatic Daily video uses for that camera and day.
def select_daily_images(config: dict, camera: str, target_date: date) -> list[Path]:
	location = config["location"]
	sunrise, sunset = get_sun_times(
		target_date=target_date,
		latitude=location["latitude"],
		longitude=location["longitude"],
		timezone=location["timezone"],
	)

	return find_daily_images_isolated(
		camera=camera,
		target_date=target_date,
		sunrise=sunrise,
		sunset=sunset,
		previous_date=target_date - timedelta(days=1),
		daylight_buffer_minutes=automatic_daylight_buffer_for(config, target_date),
		stall_timeout_seconds=config["image_scan_stall_timeout_seconds"],
	)


# Check every camera and write its report; one failing camera never stops the others.
def run_cameras(
	config: dict,
	cameras: Sequence[str],
	target_date: date,
	forward: Forward,
	video_root: Path,
	detector: str,
	now: datetime,
) -> int:
	timezone = config["location"]["timezone"]
	any_failed = False

	for camera in cameras:
		started = time.monotonic()

		try:
			images = select_daily_images(config, camera, target_date)

			if not images:
				logger.warning(f"[{camera}] no images for {target_date} - nothing written")
				continue

			scan = scan_images(images, forward, timezone)

			# Nothing readable (e.g. a flaky mount) is a failure, not "checked, nothing found",
			# and must not replace a good report from an earlier run.
			if scan.checked == 0:
				logger.error(
					f"[{camera}] none of {len(images)} images could be read - nothing written"
				)
				any_failed = True
				continue
			manifest = build_manifest(
				camera, target_date, now, detector, scan.checked, scan.flagged
			)
			write_report(video_root, camera, target_date, manifest, scan.flagged)

		except (OSError, TimeoutError) as error:
			logger.error(f"[{camera}] failed: {error}")
			any_failed = True
			continue

		seconds = time.monotonic() - started
		logger.info(
			f"[{camera}] checked={scan.checked} flagged={len(scan.flagged)} "
			f"failed={scan.failed} seconds={seconds:.0f}"
		)

	return 1 if any_failed else 0


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		prog="python3 -m src.flagger.run",
		description="Flag animals and flying objects in the Daily images.",
	)
	parser.add_argument("--cameras", nargs="+", help="override flagger.cameras from config.json")
	parser.add_argument(
		"--target-date",
		type=date.fromisoformat,
		help="day to check, YYYY-MM-DD (default: yesterday)",
	)
	parser.add_argument("--model", type=Path, default=None, help="ONNX model file")
	parser.add_argument("--images", type=Path, help="test mode: check this folder instead")
	parser.add_argument("--out", type=Path, help="test mode: write the report below this folder")

	args = parser.parse_args(argv)

	if args.images is not None and args.out is None:
		parser.error("--images needs --out")

	if args.images is not None and args.cameras:
		parser.error("--images cannot be combined with --cameras")

	return args


def main(argv: list[str] | None = None) -> int:
	args = parse_arguments(argv)
	model = args.model or DEFAULT_MODEL
	config = load_config()
	timezone = config["location"]["timezone"]
	now = datetime.now(tz=ZoneInfo(timezone))

	if args.images is not None:
		return run_folder(args, model, timezone, now)

	configure_file_logging("flagger")
	try:
		settings = load_flagger_settings(config)

	except ValueError as error:
		logger.error(f"Flagger not started: {error}")
		return 1

	cameras = list(args.cameras or settings.cameras)

	if cameras:
		try:
			ignored = set(config.get("ignored_cameras", []))
			available = [camera for camera in get_cameras() if camera not in ignored]
			cameras = require_cameras(cameras, available)

		except (OSError, ValueError) as error:
			logger.error(f"Flagger not started: {error}")
			return 1

		if not model.is_file():
			logger.error(f"Flagger not started: model file missing: {model}")
			return 1

	with ExitStack() as stack:
		# Only a held lock means "skip"; any other RuntimeError from the run must surface.
		try:
			stack.enter_context(acquire_run_lock(LOCK_PATH))

		except RuntimeError as error:
			logger.info(f"Skipped: {error}")
			return 0

		exit_code = 0

		if cameras:
			target_date = args.target_date or get_latest_completed_date(timezone)
			logger.info(f"Flagger: {target_date} for {', '.join(cameras)}")
			exit_code = run_cameras(
				config=config,
				cameras=cameras,
				target_date=target_date,
				forward=OnnxForward(model),
				video_root=VIDEO_ROOT,
				detector=detector_id(model),
				now=now,
			)

		else:
			logger.info("Flagger: no cameras configured (flagger.cameras is empty)")

		# Every nightly run cleans up, so reports of cameras dropped from the list still expire.
		# A run for an explicit date skips it: an old date would delete its own fresh report.
		if args.target_date is None:
			removed = cleanup_old_reports(VIDEO_ROOT, now.date(), settings.retention_days)

			if removed:
				logger.info(f"Flagger: removed {len(removed)} old highlight folders")

		return exit_code


# Test mode: any folder of images, no config cameras, no lock, no cleanup.
def run_folder(args: argparse.Namespace, model: Path, timezone: str, now: datetime) -> int:
	images = sorted(
		path for path in args.images.iterdir() if path.is_file() and path.suffix.lower() == ".jpg"
	)
	target_date = args.target_date or now.date()
	scan = scan_images(images, OnnxForward(model), timezone)
	manifest = build_manifest(
		TEST_CAMERA, target_date, now, detector_id(model), scan.checked, scan.flagged
	)
	folder = write_report(args.out, TEST_CAMERA, target_date, manifest, scan.flagged)

	logger.info(
		f"[{TEST_CAMERA}] checked={scan.checked} flagged={len(scan.flagged)} "
		f"failed={scan.failed} -> {folder}"
	)

	return 0


if __name__ == "__main__":
	sys.exit(main())
