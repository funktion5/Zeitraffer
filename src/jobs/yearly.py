import subprocess

from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

from src.date_coverage import (
	format_date_ranges,
	get_coverage_date_range,
	get_missing_dates,
)
from src.images import (
	find_interval_images_isolated,
)
from src.logger import RUN_ID, format_run_context, logger
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

	mode = "historical" if manual_run else "automatic"
	run_context = format_run_context(
		mode=mode,
		cameras=cameras,
	)

	logger.info(
		f"Starting Yearly timelapse job for {start_date} to {end_date} | {run_context}"
	)

	created_count = 0
	skipped_count = 0
	failed_count = 0

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

			logger.info(f"Found {len(interval_images)} selected interval images")

			if not interval_images:
				logger.warning(f"No valid Yearly images available - skipping camera: {camera}")
				skipped_count += 1

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

				logger.debug(f"Missing Yearly dates: {format_date_ranges(missing_dates)}")

				skipped_count += 1

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
				skipped_count += 1

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
			failed_count += 1

			continue

		created_count += 1

		logger.info(f"Finished Yearly for camera: {camera}")

		logger.debug(f"Video path: {video_path}")

	logger.info(
		f"Yearly timelapse job finished for {start_date} to {end_date} | "
		f"created={created_count} | skipped={skipped_count} | failed={failed_count} | "
		f"run_id={RUN_ID}"
	)
