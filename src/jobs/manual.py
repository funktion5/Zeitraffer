import subprocess
from datetime import date

from src.diagnostics import log_missing_images_diagnostic
from src.images import find_images_isolated
from src.logger import logger
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

	logger.info(f"Starting manual timelapse job for {target_date}")

	logger.info(f"Daylight buffer: {daylight_buffer_minutes} minutes")

	if requested_cameras:
		cameras = []

		# Preserve order while removing duplicate camera names.
		for requested_camera in dict.fromkeys(requested_cameras):
			if requested_camera not in available_cameras:
				logger.error(f"Requested camera not found: {requested_camera}")
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
		)

		# Existing manual videos are never recreated automatically.
		if existing_video.exists():
			logger.info(f"Manual video already exists - skipping camera: {existing_video}")
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
			)

		except (
			OSError,
			TimeoutError,
			subprocess.CalledProcessError,
		):
			# Operational errors only skip the affected camera.
			logger.exception(f"Failed to process timelapse for camera: {camera}")
			continue

		logger.info(f"Finished processing camera: {camera}")

		logger.debug(f"Video path: {video_path}")

	logger.info(f"Manual timelapse job finished for {target_date}")
