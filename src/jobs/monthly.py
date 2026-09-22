import subprocess
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.images import find_interval_images_isolated
from src.logger import logger
from src.video import create_timelapse
from src.date_coverage import (
	get_coverage_date_range,
	get_missing_dates,
)


# Run the automatic Monthly timelapse workflow.
def run_monthly_job(
	config: dict,
	cameras: list[str],
	framerate: int,
	target_date: date | None = None,
	manual_run: bool = False,
) -> None:
	timezone = ZoneInfo(config["location"]["timezone"])

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	start_date, end_date = get_coverage_date_range(
		end_date=target_date,
		coverage_type="monthly",
	)

	stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]

	logger.info("-" * 80)

	logger.info(f"Starting Monthly timelapse job for {start_date} to {end_date}")

	for camera in cameras:
		logger.info(f"Processing Monthly for camera: {camera}")

		try:
			monthly_images = find_interval_images_isolated(
				camera=camera,
				start_date=start_date,
				end_date=end_date,
				stall_timeout_seconds=stall_timeout_seconds,
			)

			logger.info(f"Found {len(monthly_images)} validated Monthly images")

			if not monthly_images:
				logger.warning(f"No valid Monthly images available - skipping camera: {camera}")
				continue

			missing_dates = get_missing_dates(
				images=monthly_images,
				start_date=start_date,
				end_date=end_date,
			)

			if missing_dates:
				logger.warning(
					f"Monthly coverage incomplete: "
					f"{30 - len(missing_dates)} of 30 days available - "
					f"skipping camera: {camera}"
				)

				for missing_date in missing_dates:
					logger.debug(f"Missing Monthly date: {missing_date}")

				continue

			logger.info("Monthly coverage complete: 30 of 30 days")

			video_path = create_timelapse(
				camera=camera,
				target_date=end_date,
				images=monthly_images,
				timelapse_type="monthly",
				framerate=framerate,
				manual_run=manual_run,
			)

			logger.info(f"Finished Monthly for camera: {camera}")

			logger.debug(f"Video path: {video_path}")

		except (
			OSError,
			TimeoutError,
			subprocess.CalledProcessError,
		):
			logger.exception(f"Failed to process Monthly for camera: {camera}")

	logger.info(f"Monthly timelapse job finished for {start_date} to {end_date}")
