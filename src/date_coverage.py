from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from src.images import extract_date
from src.logger import logger


CoverageType = Literal[
	"weekly",
	"monthly",
	"yearly",
]


COVERAGE_DAYS = {
	"weekly": 7,
	"monthly": 30,
}


# Default target date for automatic runs: the latest completed calendar day.
def get_latest_completed_date(timezone: str) -> date:
	return datetime.now(tz=ZoneInfo(timezone)).date() - timedelta(days=1)


# Return the inclusive rolling date range for the selected coverage type.
# Yearly is a true calendar year ending on end_date, not a fixed day count:
# the window is 366 days whenever a leap day (Feb 29) actually falls inside
# it, and 365 otherwise.
def get_coverage_date_range(
	end_date: date,
	coverage_type: CoverageType,
) -> tuple[date, date]:
	if coverage_type == "yearly":
		start_date = get_previous_year_date(end_date) + timedelta(days=1)

	else:
		days = COVERAGE_DAYS[coverage_type]
		start_date = end_date - timedelta(days=days - 1)

	return (
		start_date,
		end_date,
	)


# Return the same calendar date one year earlier. A leap day (Feb 29) maps to
# Feb 28 when the prior year isn't itself a leap year, since Feb 29 has no
# equivalent date one year before it in that case.
def get_previous_year_date(target_date: date) -> date:
	try:
		return target_date.replace(year=target_date.year - 1)
	except ValueError:
		return date(target_date.year - 1, 2, 28)


# Read the configured minimum of covered days a Monthly/Yearly needs. Applies
# to automatic and historical runs alike; validated against the actual window
# so a typo can't silently disable the check or make it unreachable.
def get_min_coverage_days(
	config: dict,
	coverage_type: Literal["monthly", "yearly"],
	total_days: int,
) -> int:
	min_coverage_days = config["min_coverage_days"][coverage_type]

	if (
		isinstance(min_coverage_days, bool)
		or not isinstance(min_coverage_days, int)
		or not 1 <= min_coverage_days <= total_days
	):
		raise ValueError(
			f"min_coverage_days.{coverage_type} must be an integer from 1 to {total_days}: "
			f"{min_coverage_days!r}"
		)

	return min_coverage_days


# Return dates without a recognized image inside the requested range.
def get_missing_dates(
	images: list[Path],
	start_date: date,
	end_date: date,
) -> list[date]:
	available_dates = {
		image_date
		for image_path in images
		if (image_date := extract_date(image_path.name)) is not None
	}

	return [
		start_date + timedelta(days=offset)
		for offset in range((end_date - start_date).days + 1)
		if start_date + timedelta(days=offset) not in available_dates
	]


# Format dates as compact consecutive ranges for diagnostic logs.
def format_date_ranges(dates: list[date]) -> str:
	if not dates:
		return "none"

	sorted_dates = sorted(set(dates))
	ranges = []
	range_start = sorted_dates[0]
	range_end = sorted_dates[0]

	for current_date in sorted_dates[1:]:
		if current_date == range_end + timedelta(days=1):
			range_end = current_date
			continue

		ranges.append((range_start, range_end))
		range_start = current_date
		range_end = current_date

	ranges.append((range_start, range_end))

	return ", ".join(
		start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
		for start, end in ranges
	)


# Log Monthly/Yearly coverage and return whether it meets the minimum.
# Missing days are simply absent from the video, so partial coverage is only logged.
def check_coverage(
	images: list[Path],
	start_date: date,
	end_date: date,
	min_coverage_days: int,
	label: str,
	camera: str,
) -> bool:
	total_days = (end_date - start_date).days + 1

	missing_dates = get_missing_dates(
		images=images,
		start_date=start_date,
		end_date=end_date,
	)

	covered_days = total_days - len(missing_dates)

	if covered_days < min_coverage_days:
		logger.warning(
			f"{label} coverage too low: "
			f"{covered_days} of {total_days} days available "
			f"(minimum {min_coverage_days}) - skipping camera: {camera}"
		)

		logger.debug(f"Missing {label} dates: {format_date_ranges(missing_dates)}")

		return False

	if missing_dates:
		logger.warning(
			f"{label} coverage partial: "
			f"{covered_days} of {total_days} days available "
			f"(minimum {min_coverage_days}) | "
			f"missing: {format_date_ranges(missing_dates)}"
		)

	else:
		logger.info(f"{label} coverage complete: {total_days} of {total_days} days")

	return True
