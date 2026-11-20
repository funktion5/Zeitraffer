import functools
import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import PROJECT_ROOT
from src.storage.frame_source import FrameSource, build_frame_source
from src.image_worker import run_isolated_worker
from src.logger import logger

# Read from the environment so isolated worker processes inherit an alternative source
# (e.g. the NAS archive) without any argument plumbing. None when unset: there is no default
# folder, the source is then chosen from the storage box (see src/storage/frame_source.py).
_camera_root_setting = os.environ.get("TIMELAPSE_CAMERA_ROOT")
CAMERA_ROOT = Path(_camera_root_setting) if _camera_root_setting else None

# Every camera ends a complete JPEG with this marker; an upload cut off part-way lacks it.
JPEG_END_MARKER = b"\xff\xd9"


@dataclass
class ImageRange:
	earliest_date: date | None
	latest_date: date | None
	unrecognized_files: int


# Built on every call, not once at import, so a patched CAMERA_ROOT keeps working in tests. Which
# source it is, is decided in src/storage/frame_source.py by TIMELAPSE_FRAME_SOURCE.
def get_frame_source() -> FrameSource:
	return build_frame_source(CAMERA_ROOT, PROJECT_ROOT)


# Workers inherit the cache root through the environment, so it has to be chosen here, in the
# parent, before the first worker starts. Also fails early when the ssh source is misconfigured.
def _prepare_frame_source() -> None:
	get_frame_source()


# Returns all available cameras from the frame source, sorted: a source need not list in order.
def get_cameras():
	return sorted(get_frame_source().list_cameras())


# Fetched frames are unblurred, so every job removes them after each camera outcome. A failed
# removal (an OSError) must be seen but must not stop the later cameras: it is logged here and the
# caller counts it as a failure (a camera already built then counts as created and failed; the
# failure must show). Anything else, such as an invalid TIMELAPSE_FRAME_SOURCE, is a setup error
# and ends the run loudly.
def release_camera_frames(camera: str) -> bool:
	try:
		get_frame_source().release(camera)

	except OSError:
		logger.exception(f"Could not remove fetched frames for camera: {camera}")

		return False

	return True


# Return the requested cameras without duplicates; unknown names are an error.
def require_cameras(
	requested_cameras: list[str],
	available_cameras: list[str],
) -> list[str]:
	cameras = list(dict.fromkeys(requested_cameras))
	missing_cameras = [camera for camera in cameras if camera not in available_cameras]

	if missing_cameras:
		missing_camera_names = ", ".join(missing_cameras)
		logger.error(f"Requested cameras not found: {missing_camera_names}")
		raise ValueError(f"Requested cameras not found: {missing_camera_names}")

	return cameras


# The date formats used by the camera systems; a filename containing one belongs to that day.
# Must cover every date block in _DATE_BLOCKS ("%y-%m-%d" also matches inside "%Y-%m-%d"), or the
# Daily and the blur round never see a name the reader would accept.
def date_patterns(target_date: date) -> tuple[str, ...]:
	return (
		target_date.strftime("%Y%m%d"),
		target_date.strftime("%y%m%d"),
		target_date.strftime("%y-%m-%d"),
		target_date.strftime("%Y_%m%d"),
	)


# Scan the camera directory once and group images for requested dates.
def find_images_for_dates(
	camera: str,
	target_dates: list[date],
	progress_callback: Callable[[], None] | None = None,
	report_unreadable: bool = False,
) -> dict[date, list[Path]]:
	source = get_frame_source()
	unique_dates = list(dict.fromkeys(target_dates))

	patterns_by_date = {target_date: date_patterns(target_date) for target_date in unique_dates}
	images_by_date = {target_date: [] for target_date in unique_dates}
	image_count = 0
	unreadable = []

	# List the camera once and match known date formats by filename.
	for name in source.list_names(camera):
		if progress_callback is not None:
			progress_callback()

		if not name.lower().endswith(".jpg"):
			continue

		# The Daily reads the whole listing anyway; a name without date and time is lost to the
		# Monthly, Yearly and flagger, so the night should say so.
		if report_unreadable:
			image_count += 1

			if extract_date(name) is None or extract_time(name) is None:
				unreadable.append(name)

		for target_date, target_patterns in patterns_by_date.items():
			if not any(date_pattern in name for date_pattern in target_patterns):
				continue

			# The pattern can match inside a time (bsv_steinhude_202403261030.jpg contains 261030,
			# the 2026-10-30 string), so the date the name really carries decides. An unreadable
			# date stays, as in storage_filter.list_images_for_dates.
			name_date = extract_date(name)

			if name_date is not None and name_date != target_date:
				continue

			images_by_date[target_date].append(source.path_for(camera, name))
			break

	if unreadable:
		logger.warning(
			f"[{camera}] {len(unreadable)} of {image_count} image names cannot be read, "
			f"e.g. {unreadable[0]}"
		)

	return {target_date: sorted(images) for target_date, images in images_by_date.items()}


# Notation blocks for date and time in an image name. Every date block is combined with every
# separator and time block, so a new camera works as long as it writes one of these notations.
_DATE_BLOCKS = (
	r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})",
	r"(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})",
	r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})",
	r"(?P<year>\d{2})-(?P<month>\d{2})-(?P<day>\d{2})",
	# Cafe-am-Meer legacy: promenade_YYYY_MMDD_HHMMSS_01.jpg.
	r"(?P<year>\d{4})_(?P<month>\d{2})(?P<day>\d{2})",
)
_SEPARATORS = ("", "T", "_", "-")
_TIME_BLOCKS = (
	r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
	r"(?P<hour>\d{2})(?P<minute>\d{2})",
	r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})",
	# P/T legacy: two digits of hundredths glued to the seconds.
	r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\d{2}",
)
# The lookahead finds overlapping matches at every position; a combination only counts as a
# whole, with no digit directly before or after it.
_NAME_PATTERNS = tuple(
	re.compile(rf"(?<!\d)(?=(?:{date_block}){re.escape(separator)}(?:{time_block})(?!\d))")
	for date_block in _DATE_BLOCKS
	for separator in _SEPARATORS
	for time_block in _TIME_BLOCKS
)
_DIGIT = re.compile(r"\d")


# Where the combinations match depends only on a name's shape (digits as 9), and a camera has few
# shapes; caching per shape keeps 80 patterns as fast as the old list over 200,000 names.
@functools.lru_cache(maxsize=1024)
def _matches_for_shape(shape: str) -> tuple[tuple[re.Pattern, int], ...]:
	return tuple(
		(pattern, match.start()) for pattern in _NAME_PATTERNS for match in pattern.finditer(shape)
	)


def _valid_date(match: re.Match) -> date | None:
	year = int(match.group("year"))

	if year < 100:
		year += 2000

	if not 2000 <= year <= 2099:
		return None

	try:
		return date(year, int(match.group("month")), int(match.group("day")))
	except ValueError:
		return None


def _valid_time(match: re.Match) -> tuple[int, int, int] | None:
	hour = int(match.group("hour"))
	minute = int(match.group("minute"))
	second = int(match.groupdict().get("second") or 0)

	if hour > 23 or minute > 59 or second > 59:
		return None

	return (hour, minute, second)


# Date and time of one name. Readings with a valid date AND time compete first; when they
# disagree the name is ambiguous and stays unreadable instead of being guessed.
@functools.lru_cache(maxsize=8192)
def _read_name(filename: str) -> tuple[date | None, tuple[int, int, int] | None]:
	dates = set()
	times = set()
	full_readings = set()

	for pattern, position in _matches_for_shape(_DIGIT.sub("9", filename)):
		match = pattern.match(filename, position)
		image_date = _valid_date(match)
		image_time = _valid_time(match)

		if image_date is not None:
			dates.add(image_date)

		if image_time is not None:
			times.add(image_time)

		if image_date is not None and image_time is not None:
			full_readings.add((image_date, image_time))

	if len(full_readings) == 1:
		return next(iter(full_readings))

	if full_readings:
		return (None, None)

	# Without a full reading, each part stands alone, and only if every match agrees on it.
	return (
		next(iter(dates)) if len(dates) == 1 else None,
		next(iter(times)) if len(times) == 1 else None,
	)


# The capture date from an image name, or None when no notation reads it unambiguously.
def extract_date(filename: str) -> date | None:
	return _read_name(filename)[0]


# Inspect filenames without triggering additional file metadata lookups.
def get_image_range(
	camera: str,
	progress_callback: Callable[[], None] | None = None,
) -> ImageRange:
	earliest_date = None
	latest_date = None
	unrecognized_files = 0

	for name in get_frame_source().list_names(camera):
		if progress_callback is not None:
			progress_callback()

		if not name.lower().endswith(".jpg"):
			continue

		image_date = extract_date(name)

		# Track files whose filename format is not supported.
		if image_date is None:
			unrecognized_files += 1
			continue

		if earliest_date is None or image_date < earliest_date:
			earliest_date = image_date

		if latest_date is None or image_date > latest_date:
			latest_date = image_date

	return ImageRange(
		earliest_date=earliest_date,
		latest_date=latest_date,
		unrecognized_files=unrecognized_files,
	)


# The capture time (hour, minute, second) from an image name, or None, as extract_date.
def extract_time(filename: str) -> tuple[int, int, int] | None:
	return _read_name(filename)[1]


# Filename date and time are local camera time; unknown or ambiguous names are never guessed.
def image_moment(name: str, timezone: str) -> datetime | None:
	image_date = extract_date(name)
	image_time = extract_time(name)

	if image_date is None or image_time is None:
		return None

	return datetime.combine(image_date, time(*image_time), ZoneInfo(timezone))


# Select images already discovered for one date inside its daylight window.
def select_daylight_images(
	images: list[Path],
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	daylight_buffer_minutes: int,
) -> list[Path]:
	selected_images = []

	start_time = sunrise - timedelta(minutes=daylight_buffer_minutes)
	end_time = sunset + timedelta(minutes=daylight_buffer_minutes)

	for image_path in images:
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
	target_seconds_by_date: dict[date, int],
	tolerance_minutes: int = 90,
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	source = get_frame_source()
	images: list[tuple[date, int, Path]] = []

	tolerance_seconds = tolerance_minutes * 60

	for name in source.list_names(camera):
		if progress_callback is not None:
			progress_callback()

		if not name.lower().endswith(".jpg"):
			continue

		image_date = extract_date(name)

		if image_date is None:
			continue

		if not (start_date <= image_date <= end_date):
			continue

		image_time = extract_time(name)

		if image_time is None:
			continue

		hour, minute, second = image_time

		capture_seconds = hour * 60 * 60 + minute * 60 + second

		distance_seconds = abs(capture_seconds - target_seconds_by_date[image_date])

		if distance_seconds > tolerance_seconds:
			continue

		images.append(
			(
				image_date,
				capture_seconds,
				source.path_for(camera, name),
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
	return get_image_digest(image_path, progress_callback)[0]


# Hash an image and report whether it ends with the JPEG end marker, from the same single read, so
# the check costs nothing extra.
def get_image_digest(
	image_path: Path,
	progress_callback: Callable[[], None] | None = None,
) -> tuple[str, bool]:
	hasher = hashlib.sha256()
	tail = b""

	with image_path.open("rb") as image_file:
		while chunk := image_file.read(1024 * 1024):
			hasher.update(chunk)

			tail = (tail + chunk)[-len(JPEG_END_MARKER) :]

			if progress_callback is not None:
				progress_callback()

	return hasher.hexdigest(), tail == JPEG_END_MARKER


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
		logger.warning(f"Camera {camera}: excluded {len(empty_images)} empty image files")

	return valid_images


# Return every byte-identical image after its first occurrence.
def find_duplicate_images(
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	images_by_size: dict[int, list[Path]] = {}

	for image_path in images:
		file_size = image_path.stat().st_size

		if progress_callback is not None:
			progress_callback()

		images_by_size.setdefault(
			file_size,
			[],
		).append(image_path)

	duplicate_images = []

	# Only equal-sized files can contain identical source data.
	for same_size_images in images_by_size.values():
		if len(same_size_images) < 2:
			continue

		seen_hashes = set()

		for image_path in same_size_images:
			image_hash = get_image_hash(
				image_path=image_path,
				progress_callback=progress_callback,
			)

			if image_hash in seen_hashes:
				duplicate_images.append(image_path)
				continue

			seen_hashes.add(image_hash)

	return duplicate_images


# Exclude byte-identical images while preserving their first occurrence.
def filter_duplicate_images(
	camera: str,
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	duplicate_images = set(
		find_duplicate_images(
			images=images,
			progress_callback=progress_callback,
		)
	)

	if duplicate_images:
		logger.warning(f"Camera {camera}: filtered {len(duplicate_images)} duplicate images")

	return [image_path for image_path in images if image_path not in duplicate_images]


# Exclude current images already present in a reference sequence.
def filter_duplicate_images_against_reference(
	camera: str,
	reference_images: list[Path],
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	images_by_size: dict[int, list[tuple[Path, bool]]] = {}

	for is_reference, source_images in (
		(True, reference_images),
		(False, images),
	):
		for image_path in source_images:
			file_size = image_path.stat().st_size

			if progress_callback is not None:
				progress_callback()

			images_by_size.setdefault(
				file_size,
				[],
			).append((image_path, is_reference))

	reference_hashes_by_size: dict[int, set[str]] = {}
	current_hashes_by_size: dict[int, set[str]] = {}
	excluded_reference_duplicates = set()
	excluded_current_duplicates = set()

	# Hash only size groups that can contain matching source data.
	for file_size, same_size_images in images_by_size.items():
		has_current_image = any(not is_reference for _, is_reference in same_size_images)

		if len(same_size_images) < 2 or not has_current_image:
			continue

		reference_hashes = reference_hashes_by_size.setdefault(file_size, set())
		current_hashes = current_hashes_by_size.setdefault(file_size, set())

		for image_path, is_reference in same_size_images:
			if not is_reference:
				continue

			reference_hashes.add(
				get_image_hash(
					image_path=image_path,
					progress_callback=progress_callback,
				)
			)

		for image_path, is_reference in same_size_images:
			if is_reference:
				continue

			image_hash = get_image_hash(
				image_path=image_path,
				progress_callback=progress_callback,
			)

			if image_hash in reference_hashes:
				excluded_reference_duplicates.add(image_path)
				continue

			if image_hash in current_hashes:
				excluded_current_duplicates.add(image_path)
				continue

			current_hashes.add(image_hash)

	if excluded_reference_duplicates:
		logger.warning(
			f"Camera {camera}: filtered {len(excluded_reference_duplicates)} "
			"images duplicated from reference images"
		)

	if excluded_current_duplicates:
		logger.warning(
			f"Camera {camera}: filtered {len(excluded_current_duplicates)} duplicate images"
		)

	excluded_images = excluded_reference_duplicates | excluded_current_duplicates

	return [image_path for image_path in images if image_path not in excluded_images]


# Exclude later byte-identical images independently within each date.
def filter_duplicate_images_by_date(
	camera: str,
	images: list[Path],
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	images_by_date: dict[date, list[Path]] = {}

	for image_path in images:
		image_date = extract_date(image_path.name)

		if image_date is None:
			continue

		images_by_date.setdefault(
			image_date,
			[],
		).append(image_path)

	duplicate_images = set()

	for daily_images in images_by_date.values():
		duplicate_images.update(
			find_duplicate_images(
				images=daily_images,
				progress_callback=progress_callback,
			)
		)

	if duplicate_images:
		logger.warning(
			f"Camera {camera}: filtered {len(duplicate_images)} duplicate images within dates"
		)

	return [image_path for image_path in images if image_path not in duplicate_images]


# Find daylight images for one date and drop empty files. Runs inside the
# isolated worker so a hanging ssh or rsync call cannot stall the application.
def _find_images_worker(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	daylight_buffer_minutes: int,
	progress_callback: Callable[[], None],
) -> list[Path]:
	images = select_daylight_images(
		images=find_images_for_dates(
			camera=camera,
			target_dates=[target_date],
			progress_callback=progress_callback,
		)[target_date],
		target_date=target_date,
		sunrise=sunrise,
		sunset=sunset,
		daylight_buffer_minutes=daylight_buffer_minutes,
	)

	# Fetch and validate only selected images to avoid unnecessary metadata access.
	get_frame_source().localize(camera, images, progress_callback)

	return filter_empty_images(
		camera=camera,
		images=images,
		progress_callback=progress_callback,
	)


# Find Daily images and remove content already present on the previous day.
def _find_daily_images_worker(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	previous_date: date,
	daylight_buffer_minutes: int,
	progress_callback: Callable[[], None],
) -> list[Path]:
	images_by_date = find_images_for_dates(
		camera=camera,
		target_dates=[previous_date, target_date],
		progress_callback=progress_callback,
		report_unreadable=True,
	)
	previous_images = images_by_date[previous_date]
	current_images = select_daylight_images(
		images=images_by_date[target_date],
		target_date=target_date,
		sunrise=sunrise,
		sunset=sunset,
		daylight_buffer_minutes=daylight_buffer_minutes,
	)

	# The empty and duplicate filters read the whole previous day as well as the selected frames.
	get_frame_source().localize(camera, previous_images + current_images, progress_callback)

	previous_images = filter_empty_images(
		camera=camera,
		images=previous_images,
		progress_callback=progress_callback,
	)
	current_images = filter_empty_images(
		camera=camera,
		images=current_images,
		progress_callback=progress_callback,
	)

	return filter_duplicate_images_against_reference(
		camera=camera,
		reference_images=previous_images,
		images=current_images,
		progress_callback=progress_callback,
	)


# Find and validate interval images inside the isolated worker.
def _find_interval_images_worker(
	camera: str,
	start_date: date,
	end_date: date,
	target_seconds_by_date: dict[date, int],
	tolerance_minutes: int,
	remove_duplicates_by_date: bool,
	progress_callback: Callable[[], None],
) -> list[Path]:
	images = find_interval_images(
		camera=camera,
		start_date=start_date,
		end_date=end_date,
		tolerance_minutes=tolerance_minutes,
		progress_callback=progress_callback,
		target_seconds_by_date=target_seconds_by_date,
	)

	# Everything the job could open is fetched once; Yearly's lazy hashing then reads the cache.
	get_frame_source().localize(camera, images, progress_callback)

	# Remove unusable files before job-specific selection.
	images = filter_empty_images(
		camera=camera,
		images=images,
		progress_callback=progress_callback,
	)

	if remove_duplicates_by_date:
		images = filter_duplicate_images_by_date(
			camera=camera,
			images=images,
			progress_callback=progress_callback,
		)

	return images


# Run image discovery with a stall timeout that resets whenever progress arrives.
def find_images_isolated(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	daylight_buffer_minutes: int,
	stall_timeout_seconds: float,
) -> list[Path]:
	_prepare_frame_source()

	return run_isolated_worker(
		camera=camera,
		target=_find_images_worker,
		kwargs={
			"camera": camera,
			"target_date": target_date,
			"sunrise": sunrise,
			"sunset": sunset,
			"daylight_buffer_minutes": daylight_buffer_minutes,
		},
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Image scan",
	)


# Select Daily images against the previous day with an inactivity timeout.
def find_daily_images_isolated(
	camera: str,
	target_date: date,
	sunrise: datetime,
	sunset: datetime,
	previous_date: date,
	daylight_buffer_minutes: int,
	stall_timeout_seconds: float,
) -> list[Path]:
	_prepare_frame_source()

	return run_isolated_worker(
		camera=camera,
		target=_find_daily_images_worker,
		kwargs={
			"camera": camera,
			"target_date": target_date,
			"sunrise": sunrise,
			"sunset": sunset,
			"previous_date": previous_date,
			"daylight_buffer_minutes": daylight_buffer_minutes,
		},
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Daily image scan",
	)


# Filter duplicate images with an inactivity timeout.
def filter_duplicate_images_isolated(
	camera: str,
	images: list[Path],
	stall_timeout_seconds: float,
) -> list[Path]:
	return run_isolated_worker(
		camera=camera,
		target=filter_duplicate_images,
		kwargs={
			"camera": camera,
			"images": images,
		},
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Duplicate image filtering",
	)


# Run interval discovery and validation with an inactivity timeout.
def find_interval_images_isolated(
	camera: str,
	start_date: date,
	end_date: date,
	stall_timeout_seconds: float,
	target_seconds_by_date: dict[date, int],
	tolerance_minutes: int,
	remove_duplicates_by_date: bool = False,
) -> list[Path]:
	_prepare_frame_source()

	return run_isolated_worker(
		camera=camera,
		target=_find_interval_images_worker,
		kwargs={
			"camera": camera,
			"start_date": start_date,
			"end_date": end_date,
			"target_seconds_by_date": target_seconds_by_date,
			"tolerance_minutes": tolerance_minutes,
			"remove_duplicates_by_date": remove_duplicates_by_date,
		},
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Interval image scan",
	)
