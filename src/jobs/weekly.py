import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.logger import logger
from src.video import (
	TEMP_ROOT,
	VIDEO_ROOT,
	cleanup_temp_directory,
	create_concat_file,
	create_concat_video,
)


# Return the expected Daily video paths for the rolling 7-day window.
def get_expected_weekly_video_paths(
	camera: str,
	end_date: date,
) -> list[Path]:
	start_date = end_date - timedelta(days=6)

	return [
		(VIDEO_ROOT / camera / "daily" / f"{camera}_{current_date.isoformat()}.mp4")
		for current_date in (start_date + timedelta(days=offset) for offset in range(7))
	]


# Return existing Daily videos inside the rolling 7-day window.
def get_weekly_daily_videos(
	camera: str,
	end_date: date,
) -> list[Path]:
	expected_paths = get_expected_weekly_video_paths(
		camera=camera,
		end_date=end_date,
	)

	return [video_path for video_path in expected_paths if video_path.exists()]


# Return missing Daily videos inside the rolling 7-day window.
def get_missing_weekly_video_paths(
	camera: str,
	end_date: date,
) -> list[Path]:
	expected_paths = get_expected_weekly_video_paths(
		camera=camera,
		end_date=end_date,
	)

	return [video_path for video_path in expected_paths if not video_path.exists()]


# Return the output path for the current Weekly video.
def get_weekly_output_path(
	camera: str,
) -> Path:
	return VIDEO_ROOT / camera / "weekly" / f"{camera}_weekly.mp4"


# Return the temporary working directory for a Weekly job.
def get_weekly_temp_directory(
	camera: str,
	end_date: date,
) -> Path:
	return TEMP_ROOT / camera / "weekly" / end_date.isoformat()


# Create the current Weekly video from available Daily videos.
def create_weekly_video(
	camera: str,
	end_date: date,
) -> Path | None:
	expected_videos = get_expected_weekly_video_paths(
		camera=camera,
		end_date=end_date,
	)

	available_videos = [
		video_path for video_path in expected_videos if video_path.exists()
	]

	missing_videos = [
		video_path for video_path in expected_videos if not video_path.exists()
	]

	# Log every missing Daily video inside the rolling window.
	for missing_video in missing_videos:
		logger.warning(f"Missing Daily video: {missing_video}")

	if missing_videos:
		logger.warning(
			"Weekly will be created with "
			f"{len(available_videos)} of "
			f"{len(expected_videos)} Daily videos."
		)

	# A Weekly cannot be created when no Daily videos are available.
	if not available_videos:
		logger.warning(
			f"No Daily videos available - skipping Weekly for camera: {camera}"
		)

		return None

	temp_directory = get_weekly_temp_directory(
		camera=camera,
		end_date=end_date,
	)

	concat_path = create_concat_file(
		videos=available_videos,
		temp_directory=temp_directory,
	)

	output_path = get_weekly_output_path(camera)

	video_path = create_concat_video(
		concat_path=concat_path,
		output_path=output_path,
	)

	# Temporary Weekly files are only removed after successful processing.
	cleanup_temp_directory(temp_directory)

	return video_path


# Run the automatic Weekly timelapse workflow.
def run_weekly_job(
	config: dict,
	cameras: list[str],
	target_date: date | None = None,
) -> None:
	location = config["location"]

	timezone = ZoneInfo(location["timezone"])

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	end_date = target_date

	logger.info("-" * 80)

	logger.info(f"Starting Weekly timelapse job for rolling window ending {end_date}")

	# Process each camera independently.
	for camera in cameras:
		logger.info(f"Processing Weekly for camera: {camera}")

		try:
			video_path = create_weekly_video(
				camera=camera,
				end_date=end_date,
			)

		except (
			OSError,
			subprocess.CalledProcessError,
		):
			logger.exception(f"Failed to process Weekly for camera: {camera}")

			continue

		if video_path is None:
			continue

		logger.info(f"Finished Weekly for camera: {camera}")

		logger.debug(f"Video path: {video_path}")

	logger.info(f"Weekly timelapse job finished for rolling window ending {end_date}")
