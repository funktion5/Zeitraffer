import subprocess
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.diagnostics import log_missing_images_diagnostic
from src.images import find_images_isolated
from src.logger import logger
from src.solar import get_sun_times
from src.video import VIDEO_ROOT, create_timelapse


# Keep only daily videos belonging to the rolling seven-day window.
def cleanup_daily_retention(
	camera: str,
	target_date: date,
) -> None:
	daily_directory = VIDEO_ROOT / camera / "daily"

	if not daily_directory.exists():
		return

	# The rolling window includes the target date and the six previous days.
	start_date = target_date - timedelta(days=6)

	allowed_videos = {
		daily_directory / f"{camera}_{current_date.isoformat()}.mp4"
		for current_date in (start_date + timedelta(days=offset) for offset in range(7))
	}

	# Remove daily videos outside the current seven-day window.
	for existing_video in daily_directory.glob(f"{camera}_*.mp4"):
		if existing_video in allowed_videos:
			continue

		logger.debug(f"Removing outdated daily video: {existing_video}")

		existing_video.unlink()


# Run the automatic daily timelapse workflow.
def run_daily_job(
	config: dict,
	cameras: list[str],
	framerate: int,
	target_date: date | None = None,
) -> None:
	location = config["location"]

	timezone = ZoneInfo(location["timezone"])

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	logger.info("-" * 80)

	logger.info(f"Starting daily timelapse job for {target_date}")

	daylight_buffer_minutes = config["daylight_buffer_minutes"]

	# Stop only scans that make no progress for the configured timeout.
	image_scan_stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]

	logger.info(f"Daylight buffer: {daylight_buffer_minutes} minutes")

	# Solar times are shared by all cameras for the selected date.
	sunrise, sunset = get_sun_times(
		target_date=target_date,
		latitude=location["latitude"],
		longitude=location["longitude"],
		timezone=location["timezone"],
	)

	logger.info(f"Sunrise: {sunrise}")

	logger.info(f"Sunset: {sunset}")

	# Process each camera independently.
	for camera in cameras:
		logger.info(f"Processing camera: {camera}")

		try:
			# Run image discovery in an isolated worker so a blocked camera
			# cannot stall the complete daily job.
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
				timelapse_type="daily",
				framerate=framerate,
			)

			# Retention is only updated after a new daily video was
			# created successfully.
			cleanup_daily_retention(
				camera=camera,
				target_date=target_date,
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

	logger.info(f"Daily timelapse job finished for {target_date}")
