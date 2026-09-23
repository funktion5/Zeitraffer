from datetime import date
from pathlib import Path

import pytest

from src.date_coverage import (
	get_coverage_date_range,
	get_missing_dates,
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


def test_get_coverage_date_range_returns_365_day_yearly_window():
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
