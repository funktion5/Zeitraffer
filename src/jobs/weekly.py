import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.date_coverage import get_coverage_date_range, get_missing_dates
from src.images import (
	extract_time,
	filter_duplicate_images_isolated,
	find_images_isolated,
)
from src.logger import RUN_ID, format_run_context, logger
from src.solar import get_sun_times
from src.video import (
	TEMP_ROOT,
	VIDEO_ROOT,
	cleanup_temp_directory,
	create_concat_file,
	create_concat_video,
	create_timelapse,
	get_video_path,
	cleanup_automatic_video_retention,
)


# Collect validated daylight images for every date in a Weekly window.
def collect_weekly_images(
	camera: str,
	end_date: date,
	location: dict,
	daylight_buffer_minutes: int,
	stall_timeout_seconds: float,
) -> tuple[list[Path], list[date]]:
	start_date, end_date = get_coverage_date_range(
		end_date=end_date,
		coverage_type="weekly",
	)

	weekly_images = []

	for offset in range((end_date - start_date).days + 1):
		current_date = start_date + timedelta(days=offset)

		sunrise, sunset = get_sun_times(
			target_date=current_date,
			latitude=location["latitude"],
			longitude=location["longitude"],
			timezone=location["timezone"],
		)

		daily_images = find_images_isolated(
			camera=camera,
			target_date=current_date,
			sunrise=sunrise,
			sunset=sunset,
			daylight_buffer_minutes=daylight_buffer_minutes,
			stall_timeout_seconds=stall_timeout_seconds,
			log_duplicates=False,
		)

		if not daily_images:
			continue

		# Daily selection already excludes filenames without a recognized time.
		daily_images.sort(key=lambda image_path: extract_time(image_path.name))

		weekly_images.extend(daily_images)

	weekly_images = filter_duplicate_images_isolated(
		camera=camera,
		images=weekly_images,
		stall_timeout_seconds=stall_timeout_seconds,
	)

	missing_dates = get_missing_dates(
		images=weekly_images,
		start_date=start_date,
		end_date=end_date,
	)

	return weekly_images, missing_dates


# Create a historical Weekly directly from seven complete days of images.
def create_manual_weekly_video(
	config: dict,
	camera: str,
	end_date: date,
) -> Path | None:
	weekly_images, missing_dates = collect_weekly_images(
		camera=camera,
		end_date=end_date,
		location=config["location"],
		daylight_buffer_minutes=config["daylight_buffer_minutes"],
		stall_timeout_seconds=config["image_scan_stall_timeout_seconds"],
	)

	if missing_dates:
		for missing_date in missing_dates:
			logger.warning(f"Missing Weekly image date: {missing_date}")

		logger.warning(
			f"Weekly image coverage incomplete: {7 - len(missing_dates)} of 7 days available - "
			f"skipping camera: {camera}"
		)

		return None

	logger.info("Weekly image coverage complete: 7 of 7 days")
	logger.info(f"Found {len(weekly_images)} selected Weekly images")

	return create_timelapse(
		camera=camera,
		target_date=end_date,
		images=weekly_images,
		timelapse_type="weekly",
		framerate=config["timelapse"]["daily_framerate"],
		manual_run=True,
		daylight_buffer_minutes=config["daylight_buffer_minutes"],
	)


# Return the expected Daily video paths for the rolling 7-day window.
def get_expected_weekly_video_paths(
	camera: str,
	end_date: date,
) -> list[Path]:
	start_date, end_date = get_coverage_date_range(
		end_date=end_date,
		coverage_type="weekly",
	)

	return [
		(VIDEO_ROOT / camera / "daily" / f"{camera}_{current_date.isoformat()}.mp4")
		for current_date in (
			start_date + timedelta(days=offset)
			for offset in range((end_date - start_date).days + 1)
		)
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


# Return the output path for an automatic Weekly video.
def get_automatic_weekly_output_path(
	camera: str,
	end_date: date,
) -> Path:
	return get_video_path(
		camera=camera,
		target_date=end_date,
		timelapse_type="weekly",
	)


# Return the temporary working directory for a Weekly job.
def get_weekly_temp_directory(
	camera: str,
	end_date: date,
) -> Path:
	return TEMP_ROOT / camera / "weekly" / end_date.isoformat()


# Create the current Weekly video from available Daily videos.
def create_automatic_weekly_video(
	camera: str,
	end_date: date,
) -> Path | None:
	expected_videos = get_expected_weekly_video_paths(
		camera=camera,
		end_date=end_date,
	)

	available_videos = [video_path for video_path in expected_videos if video_path.exists()]

	missing_videos = [video_path for video_path in expected_videos if not video_path.exists()]

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
		logger.warning(f"No Daily videos available - skipping Weekly for camera: {camera}")

		return None

	temp_directory = get_weekly_temp_directory(
		camera=camera,
		end_date=end_date,
	)

	concat_path = create_concat_file(
		videos=available_videos,
		temp_directory=temp_directory,
	)

	output_path = get_automatic_weekly_output_path(
		camera=camera,
		end_date=end_date,
	)

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
	manual_run: bool = False,
) -> None:
	location = config["location"]

	timezone = ZoneInfo(location["timezone"])

	# Default to the latest completed calendar day.
	if target_date is None:
		target_date = datetime.now(tz=timezone).date() - timedelta(days=1)

	end_date = target_date

	logger.info("-" * 80)

	mode = "historical" if manual_run else "automatic"
	run_context = format_run_context(
		mode=mode,
		cameras=cameras,
	)

	logger.info(
		f"Starting Weekly timelapse job for rolling window ending {end_date} | {run_context}"
	)

	created_count = 0
	skipped_count = 0
	failed_count = 0

	# Process each camera independently.
	for camera in cameras:
		logger.info(f"Processing Weekly for camera: {camera}")

		try:
			if manual_run:
				video_path = create_manual_weekly_video(
					config=config,
					camera=camera,
					end_date=end_date,
				)

			else:
				video_path = create_automatic_weekly_video(
					camera=camera,
					end_date=end_date,
				)

			if video_path is None:
				skipped_count += 1
				continue

			if not manual_run:
				cleanup_automatic_video_retention(
					camera=camera,
					timelapse_type="weekly",
					current_video=video_path,
				)

		except (
			OSError,
			subprocess.CalledProcessError,
		):
			logger.exception(f"Failed to process Weekly for camera: {camera}")
			failed_count += 1

			continue

		created_count += 1

		logger.info(f"Finished Weekly for camera: {camera}")

		logger.debug(f"Video path: {video_path}")

	logger.info(
		f"Weekly timelapse job finished for rolling window ending {end_date} | "
		f"created={created_count} | skipped={skipped_count} | failed={failed_count} | "
		f"run_id={RUN_ID}"
	)
