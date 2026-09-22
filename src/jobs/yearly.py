import subprocess

from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

from src.date_coverage import (
	get_coverage_date_range,
	get_missing_dates,
)
from src.images import (
	find_interval_images_isolated,
)
from src.logger import logger
from src.video import create_timelapse, cleanup_automatic_video_retention
from src.yearly_selection import select_yearly_images_isolated


# Run the automatic Yearly timelapse workflow.
def run_yearly_job(
	config: dict,
	cameras: list[str],
	framerate: int,
	target_date: date | None = None,
	manual_run: bool = False,
) -> None:
	location = config["location"]

	timezone = ZoneInfo(location["timezone"])

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	start_date, end_date = get_coverage_date_range(
		end_date=target_date,
		coverage_type="yearly",
	)

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

			if not interval_images:
				logger.warning(f"No valid Yearly images available - skipping camera: {camera}")

				continue

			missing_dates = get_missing_dates(
				images=interval_images,
				start_date=start_date,
				end_date=end_date,
			)

			if missing_dates:
				logger.warning(
					f"Yearly coverage incomplete: "
					f"{365 - len(missing_dates)} of 365 days available - "
					f"skipping camera: {camera}"
				)

				for missing_date in missing_dates:
					logger.debug(f"Missing Yearly date: {missing_date}")

				continue

			logger.info("Yearly coverage complete: 365 of 365 days")

			yearly_images = select_yearly_images_isolated(
				camera=camera,
				images=interval_images,
				stall_timeout_seconds=stall_timeout_seconds,
				images_per_day=5,
			)

			if not yearly_images:
				logger.warning(f"No valid Yearly images available - skipping camera: {camera}")

				continue

			logger.info(f"Selected {len(yearly_images)} Yearly images")

			video_path = create_timelapse(
				camera=camera,
				target_date=end_date,
				images=yearly_images,
				timelapse_type="yearly",
				framerate=framerate,
				manual_run=manual_run,
			)
			if not manual_run:
				cleanup_automatic_video_retention(
					camera=camera,
					timelapse_type="yearly",
					current_video=video_path,
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
