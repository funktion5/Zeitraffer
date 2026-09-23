import subprocess
from datetime import date

from src.diagnostics import log_missing_images_diagnostic
from src.images import find_images_isolated
from src.logger import RUN_ID, format_run_context, logger
from src.solar import get_sun_times
from src.video import create_timelapse, get_video_path


# Run a manually requested timelapse job.
def run_manual_job(
	config: dict,
	available_cameras: list[str],
	target_date: date,
	requested_cameras: list[str] | None,
	framerate: int,
) -> None:
	location = config["location"]

	daylight_buffer_minutes = config["daylight_buffer_minutes"]

	# Stop only scans that make no progress for the configured timeout.
	image_scan_stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]

	logger.info("-" * 80)

	requested_camera_context = list(dict.fromkeys(requested_cameras or available_cameras))
	run_context = format_run_context(
		mode="manual",
		cameras=requested_camera_context,
	)

	logger.info(f"Starting manual timelapse job for {target_date} | {run_context}")

	logger.info(f"Daylight buffer: {daylight_buffer_minutes} minutes")

	created_count = 0
	skipped_count = 0
	failed_count = 0

	if requested_cameras:
		cameras = []

		# Preserve order while removing duplicate camera names.
		for requested_camera in dict.fromkeys(requested_cameras):
			if requested_camera not in available_cameras:
				logger.error(f"Requested camera not found: {requested_camera}")
				skipped_count += 1
				continue

			cameras.append(requested_camera)

	else:
		cameras = available_cameras

	# Solar times are shared by all cameras for the selected date.
	sunrise, sunset = get_sun_times(
		target_date=target_date,
		latitude=location["latitude"],
		longitude=location["longitude"],
		timezone=location["timezone"],
	)

	logger.info(f"Sunrise: {sunrise}")

	logger.info(f"Sunset: {sunset}")

	# Process each selected camera independently.
	for camera in cameras:
		logger.info(f"Processing camera: {camera}")

		existing_video = get_video_path(
			camera=camera,
			target_date=target_date,
			timelapse_type="manual",
			manual_run=True,
		)

		# Existing manual videos are never recreated automatically.
		if existing_video.exists():
			logger.info(f"Manual video already exists - skipping camera: {existing_video}")
			skipped_count += 1
			continue

		try:
			# Run image discovery in an isolated worker so a blocked camera
			# cannot stall the complete manual job.
			images = find_images_isolated(
				camera=camera,
				target_date=target_date,
				sunrise=sunrise,
				sunset=sunset,
				daylight_buffer_minutes=daylight_buffer_minutes,
				stall_timeout_seconds=image_scan_stall_timeout_seconds,
			)

			# Missing images only skip the affected camera.
			#
			# The additional image-range lookup is isolated because an
			# unavailable camera source must not block the complete job.
			if not images:
				logger.warning("Found 0 images - skipping camera.")

				log_missing_images_diagnostic(camera)
				skipped_count += 1

				continue

			logger.info(f"Found {len(images)} images")

			logger.debug(f"First image: {images[0].name}")

			logger.debug(f"Last image: {images[-1].name}")

			video_path = create_timelapse(
				camera=camera,
				target_date=target_date,
				images=images,
				timelapse_type="manual",
				framerate=framerate,
				manual_run=True,
			)

		except (
			OSError,
			TimeoutError,
			subprocess.CalledProcessError,
		):
			# Operational errors only skip the affected camera.
			logger.exception(f"Failed to process timelapse for camera: {camera}")
			failed_count += 1
			continue

		created_count += 1

		logger.info(f"Finished processing camera: {camera}")

		logger.debug(f"Video path: {video_path}")

	logger.info(
		f"Manual timelapse job finished for {target_date} | "
		f"created={created_count} | skipped={skipped_count} | failed={failed_count} | "
		f"run_id={RUN_ID}"
	)
