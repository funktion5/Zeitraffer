import subprocess
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.images import find_interval_images_isolated
from src.logger import logger
from src.video import create_timelapse


# Use a rolling 30-day window ending yesterday.
# Use a rolling 30-day window ending yesterday.
def get_monthly_date_range(
	end_date: date,
) -> tuple[date, date]:
	start_date = end_date - timedelta(days=29)

	return (
		start_date,
		end_date,
	)


# Run the automatic Monthly timelapse workflow.
def run_monthly_job(
	config: dict,
	cameras: list[str],
	framerate: int,
) -> None:
	timezone = ZoneInfo(config["location"]["timezone"])

	end_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	start_date, end_date = get_monthly_date_range(end_date)

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
				logger.warning(
					f"No valid Monthly images available - skipping camera: {camera}"
				)
				continue

			video_path = create_timelapse(
				camera=camera,
				target_date=end_date,
				images=monthly_images,
				timelapse_type="monthly",
				framerate=framerate,
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
