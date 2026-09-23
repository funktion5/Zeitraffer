import subprocess
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.images import find_interval_images_isolated
from src.logger import RUN_ID, format_run_context, logger
from src.video import create_timelapse
from src.video import cleanup_automatic_video_retention
from src.date_coverage import (
	format_date_ranges,
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

	mode = "historical" if manual_run else "automatic"
	run_context = format_run_context(
		mode=mode,
		cameras=cameras,
	)

	logger.info(f"Starting Monthly timelapse job for {start_date} to {end_date} | {run_context}")

	created_count = 0
	skipped_count = 0
	failed_count = 0

	for camera in cameras:
		logger.info(f"Processing Monthly for camera: {camera}")

		try:
			monthly_images = find_interval_images_isolated(
				camera=camera,
				start_date=start_date,
				end_date=end_date,
				stall_timeout_seconds=stall_timeout_seconds,
				remove_duplicates_by_date=True,
			)

			logger.info(f"Found {len(monthly_images)} selected Monthly images")

			if not monthly_images:
				logger.warning(f"No valid Monthly images available - skipping camera: {camera}")
				skipped_count += 1
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

				logger.debug(f"Missing Monthly dates: {format_date_ranges(missing_dates)}")

				skipped_count += 1

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

			if not manual_run:
				cleanup_automatic_video_retention(
					camera=camera,
					timelapse_type="monthly",
					current_video=video_path,
				)

			logger.info(f"Finished Monthly for camera: {camera}")

			logger.debug(f"Video path: {video_path}")

			created_count += 1

		except (
			OSError,
			TimeoutError,
			subprocess.CalledProcessError,
		):
			logger.exception(f"Failed to process Monthly for camera: {camera}")
			failed_count += 1

	logger.info(
		f"Monthly timelapse job finished for {start_date} to {end_date} | "
		f"created={created_count} | skipped={skipped_count} | failed={failed_count} | "
		f"run_id={RUN_ID}"
	)
