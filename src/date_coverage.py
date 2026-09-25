from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from src.images import extract_date


CoverageType = Literal[
	"weekly",
	"monthly",
	"yearly",
]


COVERAGE_DAYS = {
	"weekly": 7,
	"monthly": 30,
}


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
