import subprocess

from datetime import date


from src.date_coverage import (
	check_coverage,
	get_coverage_date_range,
	get_latest_completed_date,
	get_min_coverage_days,
)
from src.images import (
	find_interval_images_isolated,
)
from src.interval_window import (
	IntervalWindow,
	interval_window_from_config,
	resolve_target_seconds,
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
	interval_window: IntervalWindow | None = None,
) -> None:
	location = config["location"]

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = get_latest_completed_date(config["location"]["timezone"])

	start_date, end_date = get_coverage_date_range(
		end_date=target_date,
		coverage_type="yearly",
	)

	# Not always 365: this window is a true calendar year, so it's 366 days
	# whenever a leap day falls inside it.
	total_days = (end_date - start_date).days + 1

	min_coverage_days = get_min_coverage_days(
		config=config,
		coverage_type="yearly",
		total_days=total_days,
	)

	# Automatic runs always use the configured default window.
	window = interval_window or interval_window_from_config(config)

	# Shared by the scan window and the closest-to-centre ranking.
	target_seconds_by_date = resolve_target_seconds(
		window=window,
		start_date=start_date,
		end_date=end_date,
		location=location,
	)

	stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]

	logger.info("-" * 80)

	mode = "historical" if manual_run else "automatic"
	run_context = format_run_context(
		mode=mode,
		cameras=cameras,
	)

	logger.info(
		f"Starting Yearly timelapse job for {start_date} to {end_date} | "
		f"window={window.describe()} | {run_context}"
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
				target_seconds_by_date=target_seconds_by_date,
				tolerance_minutes=window.tolerance_minutes,
			)

			logger.info(f"Found {len(interval_images)} selected interval images")

			if not interval_images:
				logger.warning(f"No valid Yearly images available - skipping camera: {camera}")
				skipped_count += 1

				continue

			if not check_coverage(
				images=interval_images,
				start_date=start_date,
				end_date=end_date,
				min_coverage_days=min_coverage_days,
				label="Yearly",
				camera=camera,
			):
				skipped_count += 1
				continue

			yearly_images = select_yearly_images_isolated(
				camera=camera,
				images=interval_images,
				stall_timeout_seconds=stall_timeout_seconds,
				target_seconds_by_date=target_seconds_by_date,
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
				interval_window=interval_window,
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
