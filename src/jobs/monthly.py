import subprocess
from datetime import date

from src.date_coverage import (
	check_coverage,
	get_coverage_date_range,
	get_latest_completed_date,
	get_min_coverage_days,
)
from src.image_worker import WorkerExitedError
from src.images import find_interval_images_isolated, release_camera_frames
from src.interval_window import (
	IntervalWindow,
	interval_window_from_config,
	resolve_target_seconds,
)
from src.logger import RUN_ID, format_run_context, logger
from src.privacy.blur_gate import apply_blur_gate
from src.privacy.blur_job import blur_job_frames
from src.video import cleanup_automatic_video_retention, create_timelapse


# Run the automatic Monthly timelapse workflow.
def run_monthly_job(
	config: dict,
	cameras: list[str],
	framerate: int,
	target_date: date | None = None,
	manual_run: bool = False,
	interval_window: IntervalWindow | None = None,
) -> None:

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = get_latest_completed_date(config["location"]["timezone"])

	start_date, end_date = get_coverage_date_range(
		end_date=target_date,
		coverage_type="monthly",
	)

	total_days = (end_date - start_date).days + 1

	min_coverage_days = get_min_coverage_days(
		config=config,
		coverage_type="monthly",
		total_days=total_days,
	)

	# Automatic runs always use the configured default window.
	window = interval_window or interval_window_from_config(config)

	target_seconds_by_date = resolve_target_seconds(
		window=window,
		start_date=start_date,
		end_date=end_date,
		location=config["location"],
	)

	stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]
	blur_cameras = config.get("privacy", {}).get("blur_cameras", [])

	logger.info("-" * 80)

	mode = "historical" if manual_run else "automatic"
	run_context = format_run_context(
		mode=mode,
		cameras=cameras,
	)

	logger.info(
		f"Starting Monthly timelapse job for {start_date} to {end_date} | "
		f"window={window.describe()} | {run_context}"
	)

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
				target_seconds_by_date=target_seconds_by_date,
				tolerance_minutes=window.tolerance_minutes,
				remove_duplicates_by_date=True,
			)

			logger.info(f"Found {len(monthly_images)} selected Monthly images")

			if not monthly_images:
				logger.warning(f"No valid Monthly images available - skipping camera: {camera}")
				skipped_count += 1
				continue

			# A manual run blurs a blur camera's frames on the box before its video is built; the
			# automatic run writes nothing to the box. Before the coverage check, so a thin month
			# that builds no video still gets blurred.
			if (
				manual_run
				and camera in blur_cameras
				and not blur_job_frames(camera, monthly_images, config)
			):
				failed_count += 1
				continue

			# An automatic Monthly is public, so a blur camera's video is built from frames the box
			# blur job has confirmed only. Before the coverage check: a frame that cannot go public
			# is not a day with a picture.
			if not manual_run and camera in blur_cameras:
				monthly_images = apply_blur_gate(
					camera,
					monthly_images,
					config["location"]["timezone"],
				)

				if not monthly_images:
					logger.warning(f"[{camera}] Blur gate: no confirmed image - skipping camera.")
					skipped_count += 1
					continue

			if not check_coverage(
				images=monthly_images,
				start_date=start_date,
				end_date=end_date,
				min_coverage_days=min_coverage_days,
				label="Monthly",
				camera=camera,
			):
				skipped_count += 1
				continue

			video_path = create_timelapse(
				camera=camera,
				target_date=end_date,
				images=monthly_images,
				timelapse_type="monthly",
				framerate=framerate,
				manual_run=manual_run,
				interval_window=interval_window,
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
			WorkerExitedError,
		):
			logger.exception(f"Failed to process Monthly for camera: {camera}")
			failed_count += 1

		finally:
			# The fetched frames are unblurred: they go after every outcome of this camera,
			# including a failed fetch that left part of them behind.
			if not release_camera_frames(camera):
				failed_count += 1

	logger.info(
		f"Monthly timelapse job finished for {start_date} to {end_date} | "
		f"created={created_count} | skipped={skipped_count} | failed={failed_count} | "
		f"run_id={RUN_ID}"
	)
