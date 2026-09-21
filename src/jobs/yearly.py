import subprocess
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.images import (
	extract_date,
	extract_time,
	find_interval_images_isolated,
	get_image_hash,
)
from src.logger import logger
from src.video import create_timelapse
from src.yearly_selection import select_yearly_images_isolated


# Return the exact rolling 365-day window including the end date.
def get_yearly_date_range(
	end_date: date,
) -> tuple[date, date]:
	start_date = end_date - timedelta(days=364)

	return (
		start_date,
		end_date,
	)


def select_unique_yearly_images(
	images: list[Path],
	target_hour: int = 12,
	target_minute: int = 0,
	images_per_day: int = 5,
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	images_by_date: dict[
		date,
		list[
			tuple[
				int,
				int,
				Path,
			]
		],
	] = {}

	target_seconds = target_hour * 60 * 60 + target_minute * 60

	for image_path in images:
		image_date = extract_date(image_path.name)

		image_time = extract_time(image_path.name)

		if image_date is None or image_time is None:
			continue

		hour, minute, second = image_time

		capture_seconds = hour * 60 * 60 + minute * 60 + second

		distance_seconds = abs(capture_seconds - target_seconds)

		images_by_date.setdefault(
			image_date,
			[],
		).append(
			(
				distance_seconds,
				capture_seconds,
				image_path,
			)
		)

	selected_images: list[Path] = []

	for image_date in sorted(images_by_date):
		candidates = sorted(images_by_date[image_date])

		daily_images: list[
			tuple[
				int,
				int,
				Path,
			]
		] = []

		seen_hashes: set[str] = set()

		for candidate in candidates:
			image_path = candidate[2]

			image_hash = get_image_hash(
				image_path=image_path,
				progress_callback=progress_callback,
			)

			if image_hash in seen_hashes:
				continue

			seen_hashes.add(image_hash)

			daily_images.append(candidate)

			if len(daily_images) >= images_per_day:
				break

		# Keep the selected frames chronological within each day.
		daily_images.sort(
			key=lambda candidate: (
				candidate[1],
				candidate[2],
			)
		)

		selected_images.extend(candidate[2] for candidate in daily_images)

	return selected_images


# Run the automatic Yearly timelapse workflow.
def run_yearly_job(
	config: dict,
	cameras: list[str],
	framerate: int,
) -> None:
	location = config["location"]

	timezone = ZoneInfo(location["timezone"])

	# Yearly ends on the latest completed calendar day.
	end_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	start_date, end_date = get_yearly_date_range(end_date=end_date)

	stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]

	logger.info("-" * 80)

	logger.info(f"Starting Yearly timelapse job for {start_date} to {end_date}")

	for camera in cameras:
		logger.info(f"Processing Yearly for camera: {camera}")

		try:
			# Search and validate source images before Yearly selection.
			interval_images = find_interval_images_isolated(
				camera=camera,
				start_date=start_date,
				end_date=end_date,
				stall_timeout_seconds=stall_timeout_seconds,
			)

			logger.info(f"Found {len(interval_images)} validated interval images")

			yearly_images = select_yearly_images_isolated(
				camera=camera,
				images=interval_images,
				stall_timeout_seconds=stall_timeout_seconds,
				images_per_day=5,
			)

			if not yearly_images:
				logger.warning(
					f"No valid Yearly images available - skipping camera: {camera}"
				)

				continue

			# Yearly uses five frames per day across the rolling 365-day window.
			expected_yearly_frames = 365 * 5

			logger.info(f"Selected {len(yearly_images)} Yearly images")

			if len(yearly_images) < expected_yearly_frames:
				logger.warning(
					"Yearly will be created with "
					f"{len(yearly_images)} of "
					f"{expected_yearly_frames} possible frames."
				)

			video_path = create_timelapse(
				camera=camera,
				target_date=end_date,
				images=yearly_images,
				timelapse_type="yearly",
				framerate=framerate,
			)

		except (
			OSError,
			TimeoutError,
			subprocess.CalledProcessError,
		):
			# Operational errors only skip the affected camera.
			logger.exception(f"Failed to process Yearly for camera: {camera}")

			continue

		logger.info(f"Finished Yearly for camera: {camera}")

		logger.debug(f"Video path: {video_path}")

	logger.info(f"Yearly timelapse job finished for {start_date} to {end_date}")
