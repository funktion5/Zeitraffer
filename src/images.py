import hashlib
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from multiprocessing import Queue
from pathlib import Path

from src.image_worker import run_isolated_worker
from src.logger import logger

CAMERA_ROOT = Path("/mnt/cameras")

# Report scan progress at most once per second.
IMAGE_SCAN_PROGRESS_INTERVAL_SECONDS = 1


@dataclass
class ImageRange:
	earliest_date: date | None
	latest_date: date | None
	total_files: int
	recognized_files: int
	unrecognized_files: int


# Returns all available camera directories from the mounted camera storage.
def get_cameras():
	return sorted(
		path.name
		for path in CAMERA_ROOT.iterdir()
		if path.is_dir() and not path.name.startswith(".")
	)


# Scan the camera directory once and match known date formats by filename.
def find_images_for_date(
	camera: str,
	target_date: date,
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	camera_path = CAMERA_ROOT / camera

	# Support the different date formats used by the camera systems.
	date_patterns = (
		target_date.strftime("%Y%m%d"),
		target_date.strftime("%y%m%d"),
		target_date.strftime("%y-%m-%d"),
	)

	images = []

	# Track the last reported progress so large scans do not flood the queue.
	last_progress_report = time.monotonic()

	# Scan the camera directory once and match known date formats by filename.
	with os.scandir(camera_path) as entries:
		for entry in entries:
			if progress_callback is not None:
				now = time.monotonic()

		# Report only periodic progress while directory entries are still arriving.
				if now - last_progress_report >= IMAGE_SCAN_PROGRESS_INTERVAL_SECONDS:
					progress_callback()
					last_progress_report = now

			if not entry.name.lower().endswith(".jpg"):
				continue

			if not any(date_pattern in entry.name for date_pattern in date_patterns):
				continue

			images.append(camera_path / entry.name)

	return sorted(images)


# Extracts the capture date from the different camera filename formats.
def extract_date(filename: str):
	date_patterns = (
		# YYYYMMDDT... format.
		r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})T",
		# Reolink: ..._00_YYYYMMDDHHMMSS.jpg
		r"_00_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})\d{6}\.jpg$",
		# BSV legacy format: bsv_steinhude_YYYYMMDDHHMM.jpg
		r"^bsv_steinhude_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})\d{4}\.jpg$",
		# YY-MM-DD format.
		r"(?P<year>\d{2})-(?P<month>\d{2})-(?P<day>\d{2})",
		# Prefix_YYMMDD_... format.
		r"_(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})_",
		# Prefix_YYMMDDHHMM... format.
		r"_(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})\d{4}\.jpg$",
		# P/T + YYMMDDHHMMSSxx format.
		r"^[A-Za-z](?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})\d{8}\.jpg$",
	)

	for pattern in date_patterns:
		match = re.search(
			pattern,
			filename,
		)

		if match:
			year = int(match.group("year"))
			month = int(match.group("month"))
			day = int(match.group("day"))

			if year < 100:
				year += 2000

			# Ignore matches that do not represent a valid calendar date.
			try:
				return date(
					year,
					month,
					day,
				)
			except ValueError:
				continue

	return None


# Inspect filenames without triggering additional file metadata lookups.
def get_image_range(
	camera: str,
) -> ImageRange:
	camera_path = CAMERA_ROOT / camera

	earliest_date = None
	latest_date = None
	total_files = 0
	recognized_files = 0
	unrecognized_files = 0

	# Inspect filenames without triggering additional file metadata lookups.
	with os.scandir(camera_path) as entries:
		for entry in entries:
			if not entry.name.lower().endswith(".jpg"):
				continue

			total_files += 1

			image_date = extract_date(entry.name)

			# Track files whose filename format is not supported.
			if image_date is None:
				unrecognized_files += 1
				continue

			recognized_files += 1

			if earliest_date is None or image_date < earliest_date:
				earliest_date = image_date

			if latest_date is None or image_date > latest_date:
				latest_date = image_date

	return ImageRange(
		earliest_date=earliest_date,
		latest_date=latest_date,
		total_files=total_files,
		recognized_files=recognized_files,
		unrecognized_files=unrecognized_files,
	)


# Extracts the capture time from the different camera filename formats.
def extract_time(filename: str):
	time_patterns = (
		r"^[A-Za-z]\d{6}(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\d{2}\.jpg$",
		r"_\d{8}(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.jpg$",
		r"_\d{6}(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\d{2}\.jpg$",
		r"_\d{6}(?P<hour>\d{2})(?P<minute>\d{2})\.jpg$",
		r"_(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})-\d{2}\.jpg$",
		r"_\d{6}_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.jpg$",
		r"T(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
	)

	for pattern in time_patterns:
		match = re.search(
			pattern,
			filename,
		)

		if match:
			hour = int(match.group("hour"))
			minute = int(match.group("minute"))
			second = int(match.groupdict().get("second") or 0)

			# Ignore invalid matches that do not represent a real time.
			if hour > 23 or minute > 59 or second > 59:
				continue

			return (
				hour,
				minute,
				second,
			)

	return None


# Selects all images for a date that were captured between sunrise and sunset.
def find_images(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	daylight_buffer_minutes: int,
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	# Forward scan progress to the isolated worker supervisor when provided.
	daily_images = find_images_for_date(
		camera=camera,
		target_date=target_date,
		progress_callback=progress_callback,
	)

	selected_images = []

	start_time = sunrise - timedelta(minutes=daylight_buffer_minutes)
	end_time = sunset + timedelta(minutes=daylight_buffer_minutes)

	for image_path in daily_images:
		image_time = extract_time(image_path.name)

		# Ignore files whose timestamp cannot be extracted.
		if image_time is None:
			continue

		hour, minute, second = image_time

		# Combine the date and extracted capture time for daylight comparison.
		timestamp = datetime(
			target_date.year,
			target_date.month,
			target_date.day,
			hour,
			minute,
			second,
			tzinfo=sunrise.tzinfo,
		)

		if start_time <= timestamp <= end_time:
			selected_images.append(image_path)

	return selected_images


# Find all images inside the date range and daily target-time window.
def find_interval_images(
	camera: str,
	start_date: date,
	end_date: date,
	target_hour: int = 12,
	target_minute: int = 0,
	tolerance_minutes: int = 90,
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	camera_path = CAMERA_ROOT / camera
	images: list[
		tuple[
			date,
			int,
			Path,
		]
	] = []

	target_seconds = target_hour * 60 * 60 + target_minute * 60

	tolerance_seconds = tolerance_minutes * 60

	last_progress_report = time.monotonic()

	with os.scandir(camera_path) as entries:
		for entry in entries:
			if progress_callback is not None:
				now = time.monotonic()

				if now - last_progress_report >= IMAGE_SCAN_PROGRESS_INTERVAL_SECONDS:
					progress_callback()
					last_progress_report = now

			if not entry.name.lower().endswith(".jpg"):
				continue

			image_date = extract_date(entry.name)

			if image_date is None:
				continue

			if not (start_date <= image_date <= end_date):
				continue

			image_time = extract_time(entry.name)

			if image_time is None:
				continue

			hour, minute, second = image_time

			capture_seconds = hour * 60 * 60 + minute * 60 + second

			distance_seconds = abs(capture_seconds - target_seconds)

			if distance_seconds > tolerance_seconds:
				continue

			images.append(
				(
					image_date,
					capture_seconds,
					camera_path / entry.name,
				)
			)

	images.sort()

	return [
		image_path
		for (
			_image_date,
			_capture_seconds,
			image_path,
		) in images
	]


# Calculate an image content hash without loading the complete file into memory.
def get_image_hash(
	image_path: Path,
	progress_callback: Callable[[], None] | None = None,
) -> str:
	hasher = hashlib.sha256()
	last_progress_report = time.monotonic()

	with image_path.open("rb") as image_file:
		while chunk := image_file.read(1024 * 1024):
			hasher.update(chunk)

			if progress_callback is not None:
				now = time.monotonic()

				# Avoid flooding the worker queue while hashing large files.
				if now - last_progress_report >= IMAGE_SCAN_PROGRESS_INTERVAL_SECONDS:
					progress_callback()
					last_progress_report = now

	return hasher.hexdigest()


# Remove empty files before images are passed to further processing.
def filter_empty_images(
	camera: str,
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	valid_images = []
	empty_images = []

	for image_path in images:
		file_size = image_path.stat().st_size

		if progress_callback is not None:
			progress_callback()

		if file_size == 0:
			empty_images.append(image_path)
			continue

		valid_images.append(image_path)

	if empty_images:
		logger.warning(
			f"Camera {camera}: removed {len(empty_images)} empty image files"
		)

		for image_path in empty_images:
			logger.debug(f"Empty image: {image_path.name}")

	return valid_images


# Log byte-identical source images without removing them.
def log_duplicate_source_data(
	camera: str,
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> None:
	images_by_size: dict[int, list[Path]] = {}

	for image_path in images:
		file_size = image_path.stat().st_size

		if progress_callback is not None:
			progress_callback()

		images_by_size.setdefault(
			file_size,
			[],
		).append(image_path)

	duplicate_groups = []

	# Only equal-sized files can contain identical source data.
	for same_size_images in images_by_size.values():
		if len(same_size_images) < 2:
			continue

		images_by_hash: dict[str, list[Path]] = {}

		for image_path in same_size_images:
			image_hash = get_image_hash(
				image_path=image_path,
				progress_callback=progress_callback,
			)

			images_by_hash.setdefault(
				image_hash,
				[],
			).append(image_path)

		for matching_images in images_by_hash.values():
			if len(matching_images) > 1:
				duplicate_groups.append(matching_images)

	if duplicate_groups:
		duplicate_images = sum(len(group) for group in duplicate_groups)

		logger.warning(
			f"Camera {camera}: detected "
			f"{duplicate_images} images with duplicate source data "
			f"in {len(duplicate_groups)} duplicate groups"
		)

		for group in duplicate_groups:
			logger.debug(
				"Duplicate image data: "
				+ ", ".join(image_path.name for image_path in group)
			)


# Validate selected images before they are passed to video processing.
def validate_images(
	camera: str,
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	valid_images = filter_empty_images(
		camera=camera,
		images=images,
		progress_callback=progress_callback,
	)

	log_duplicate_source_data(
		camera=camera,
		images=valid_images,
		progress_callback=progress_callback,
	)

	return valid_images


# Run image discovery in a separate process so blocked filesystem access
# cannot stall the complete application.
def _find_images_worker(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	daylight_buffer_minutes: int,
	result_queue: Queue,
) -> None:
	def report_progress():
		# Notify the parent that the directory scan is still making progress.
		result_queue.put(
			(
				"progress",
				None,
			)
		)

	try:
		images = find_images(
			camera=camera,
			target_date=target_date,
			sunrise=sunrise,
			sunset=sunset,
			daylight_buffer_minutes=daylight_buffer_minutes,
			progress_callback=report_progress,
		)

		# Validate only selected images to avoid unnecessary metadata access.
		images = validate_images(
			camera=camera,
			images=images,
			progress_callback=report_progress,
		)

		result_queue.put(
			(
				"success",
				images,
			)
		)

	except OSError as error:
		# Forward expected filesystem errors to the parent process.
		result_queue.put(
			(
				"error",
				str(error),
			)
		)


# Find and validate interval images inside the isolated worker.
def _find_interval_images_worker(
	camera: str,
	start_date: date,
	end_date: date,
	target_hour: int,
	target_minute: int,
	tolerance_minutes: int,
	result_queue: Queue,
) -> None:
	def report_progress():
		result_queue.put(
			(
				"progress",
				None,
			)
		)

	try:
		images = find_interval_images(
			camera=camera,
			start_date=start_date,
			end_date=end_date,
			target_hour=target_hour,
			target_minute=target_minute,
			tolerance_minutes=tolerance_minutes,
			progress_callback=report_progress,
		)

		# Remove unusable files before job-specific selection.
		images = filter_empty_images(
			camera=camera,
			images=images,
			progress_callback=report_progress,
		)

		result_queue.put(
			(
				"success",
				images,
			)
		)

	except OSError as error:
		result_queue.put(
			(
				"error",
				str(error),
			)
		)


# Run image discovery with a stall timeout that resets whenever progress arrives.
def find_images_isolated(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	daylight_buffer_minutes: int,
	stall_timeout_seconds: float,
) -> list[Path]:
	return run_isolated_worker(
		camera=camera,
		target=_find_images_worker,
		args=(
			camera,
			target_date,
			sunrise,
			sunset,
			daylight_buffer_minutes,
		),
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Image scan",
	)


# Run interval discovery and validation with an inactivity timeout.
def find_interval_images_isolated(
	camera: str,
	start_date: date,
	end_date: date,
	stall_timeout_seconds: float,
	target_hour: int = 12,
	target_minute: int = 0,
	tolerance_minutes: int = 90,
) -> list[Path]:
	return run_isolated_worker(
		camera=camera,
		target=_find_interval_images_worker,
		args=(
			camera,
			start_date,
			end_date,
			target_hour,
			target_minute,
			tolerance_minutes,
		),
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Interval image scan",
	)
