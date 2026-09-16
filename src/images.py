import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


CAMERA_ROOT = Path("/mnt/cameras")


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


# Finds all images belonging to a specific camera and date.
def find_images_for_date(camera: str, target_date):
	camera_path = CAMERA_ROOT / camera

	# Support the different date formats used by the camera systems.
	date_patterns = (
		target_date.strftime("%Y%m%d"),
		target_date.strftime("%y%m%d"),
		target_date.strftime("%y-%m-%d"),
	)

	images = set()

	for date_pattern in date_patterns:
		images.update(camera_path.glob(f"*{date_pattern}*.jpg"))

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
		match = re.search(pattern, filename)

		if match:
			year = int(match.group("year"))
			month = int(match.group("month"))
			day = int(match.group("day"))

			if year < 100:
				year += 2000

			# Ignore matches that do not represent a valid calendar date.
			try:
				return date(year, month, day)
			except ValueError:
				continue

	return None


# Scans a camera directory and returns its available date range and format statistics.
def get_image_range(camera: str) -> ImageRange:
	camera_path = CAMERA_ROOT / camera

	earliest_date = None
	latest_date = None
	total_files = 0
	recognized_files = 0
	unrecognized_files = 0

	for image_path in camera_path.iterdir():
		if not image_path.is_file() or image_path.suffix.lower() != ".jpg":
			continue

		total_files += 1
		image_date = extract_date(image_path.name)

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
		match = re.search(pattern, filename)

		if match:
			hour = int(match.group("hour"))
			minute = int(match.group("minute"))
			second = int(match.groupdict().get("second") or 0)

			# Ignore invalid matches that do not represent a real time.
			if hour > 23 or minute > 59 or second > 59:
				continue

			return hour, minute, second

	return None


# Selects all images for a date that were captured between sunrise and sunset.
def find_images(
	camera: str,
	target_date,
	sunrise: datetime,
	sunset: datetime,
):
	daily_images = find_images_for_date(camera, target_date)
	selected_images = []

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

		if sunrise <= timestamp <= sunset:
			selected_images.append(image_path)

	return selected_images