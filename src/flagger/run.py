import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2

from src.config import automatic_daylight_buffer_for
from src.flagger.groups import best_flag
from src.flagger.report import FlaggedImage, build_manifest, copy_name, write_report
from src.flagger.yolox import Forward, detect_image
from src.images import find_daily_images_isolated, image_moment
from src.logger import logger
from src.solar import get_sun_times


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

		image = cv2.imread(str(path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)

		# Not fail-closed like the blur job: a missed flag costs nothing.
		if image is None:
			logger.warning(f"Skipping unreadable image: {path.name}")
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
