from datetime import date
from pathlib import Path

import pytest

from src.date_coverage import (
	format_date_ranges,
	get_coverage_date_range,
	get_missing_dates,
	get_previous_year_date,
)


# Consecutive missing dates must be compacted without hiding isolated dates.
def test_format_date_ranges_compacts_consecutive_dates():
	assert (
		format_date_ranges(
			[
				date(2026, 9, 5),
				date(2026, 9, 3),
				date(2026, 9, 4),
				date(2026, 9, 8),
				date(2026, 9, 8),
			]
		)
		== "2026-09-03 to 2026-09-05, 2026-09-08"
	)


# Weekly coverage includes the end date and handles calendar boundaries.
@pytest.mark.parametrize(
	("target_date", "expected_start"),
	[
		(date(2026, 9, 16), date(2026, 9, 10)),
		(date(2026, 9, 3), date(2026, 8, 28)),
		(date(2026, 1, 3), date(2025, 12, 28)),
		(date(2024, 3, 2), date(2024, 2, 25)),
	],
)
def test_get_coverage_date_range_returns_seven_day_weekly_window(
	target_date,
	expected_start,
):
	start_date, end_date = get_coverage_date_range(
		end_date=target_date,
		coverage_type="weekly",
	)

	assert start_date == expected_start
	assert end_date == target_date
	assert (end_date - start_date).days == 6


def test_get_coverage_date_range_returns_30_day_monthly_window():
	start_date, end_date = get_coverage_date_range(
		end_date=date(
			2026,
			9,
			20,
		),
		coverage_type="monthly",
	)

	assert start_date == date(
		2026,
		8,
		22,
	)

	assert end_date == date(
		2026,
		9,
		20,
	)


def test_get_coverage_date_range_returns_calendar_year_yearly_window():
	start_date, end_date = get_coverage_date_range(
		end_date=date(
			2026,
			9,
			20,
		),
		coverage_type="yearly",
	)

	assert start_date == date(
		2025,
		9,
		21,
	)

	assert end_date == date(
		2026,
		9,
		20,
	)

	assert (end_date - start_date).days == 364


# The headline leap-year bug: a fixed 365-day window would start on
# 2024-01-02, silently dropping Jan 1st from "the year 2024" even though
# 2024 is a leap year and genuinely has 366 days.
def test_get_coverage_date_range_yearly_window_is_366_days_when_it_spans_a_leap_day():
	start_date, end_date = get_coverage_date_range(
		end_date=date(2024, 12, 31),
		coverage_type="yearly",
	)

	assert start_date == date(2024, 1, 1)
	assert end_date == date(2024, 12, 31)
	assert (end_date - start_date).days + 1 == 366


# A window that doesn't touch any Feb 29 stays the familiar 365 days.
def test_get_coverage_date_range_yearly_window_is_365_days_without_a_leap_day():
	start_date, end_date = get_coverage_date_range(
		end_date=date(2025, 12, 31),
		coverage_type="yearly",
	)

	assert start_date == date(2025, 1, 1)
	assert end_date == date(2025, 12, 31)
	assert (end_date - start_date).days + 1 == 365


def test_get_previous_year_date_returns_same_calendar_date():
	assert get_previous_year_date(date(2026, 9, 20)) == date(2025, 9, 20)


# Feb 29 has no equivalent date one year before it in a non-leap year, so it
# maps to Feb 28 instead of raising.
def test_get_previous_year_date_maps_leap_day_to_feb_28():
	assert get_previous_year_date(date(2024, 2, 29)) == date(2023, 2, 28)


def test_get_missing_dates_returns_empty_when_all_days_exist():
	images = [
		Path("camera_26-09-01_12-00-00-00.jpg"),
		Path("camera_26-09-02_12-00-00-00.jpg"),
		Path("camera_26-09-03_12-00-00-00.jpg"),
	]

	result = get_missing_dates(
		images=images,
		start_date=date(
			2026,
			9,
			1,
		),
		end_date=date(
			2026,
			9,
			3,
		),
	)

	assert result == []


def test_get_missing_dates_returns_missing_days():
	images = [
		Path("camera_26-09-01_12-00-00-00.jpg"),
		Path("camera_26-09-03_12-00-00-00.jpg"),
	]

	result = get_missing_dates(
		images=images,
		start_date=date(
			2026,
			9,
			1,
		),
		end_date=date(
			2026,
			9,
			4,
		),
	)

	assert result == [
		date(
			2026,
			9,
			2,
		),
		date(
			2026,
			9,
			4,
		),
	]


def test_get_missing_dates_counts_multiple_images_on_same_day_once():
	images = [
		Path("camera_26-09-01_11-50-00-00.jpg"),
		Path("camera_26-09-01_12-00-00-00.jpg"),
		Path("camera_26-09-01_12-10-00-00.jpg"),
		Path("camera_26-09-02_12-00-00-00.jpg"),
	]

	result = get_missing_dates(
		images=images,
		start_date=date(
			2026,
			9,
			1,
		),
		end_date=date(
			2026,
			9,
			2,
		),
	)

	assert result == []
