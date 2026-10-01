from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

import src.interval_window as interval_window_module
from src.interval_window import (
	SUNSET,
	IntervalWindow,
	interval_window_from_config,
	parse_window_time,
	resolve_target_seconds,
)

LOCATION = {
	"latitude": 52.472,
	"longitude": 9.333,
	"timezone": "Europe/Berlin",
}

NOON_SECONDS = 12 * 60 * 60


def test_parse_window_time_accepts_hh_mm():
	assert parse_window_time("18:30") == time(18, 30)


def test_parse_window_time_accepts_sunset_keyword():
	assert parse_window_time("sunset") == SUNSET


@pytest.mark.parametrize(
	"value",
	["9:05", "09:5", "24:00", "12:60", "1830", "noon", "", "12:00:00"],
)
def test_parse_window_time_rejects_invalid_values(value):
	with pytest.raises(ValueError, match="Invalid window time"):
		parse_window_time(value)


@pytest.mark.parametrize("tolerance", [0, -5])
def test_interval_window_rejects_tolerance_below_one_minute(tolerance):
	with pytest.raises(ValueError, match="at least 1 minute"):
		IntervalWindow(target=time(12, 0), tolerance_minutes=tolerance)


@pytest.mark.parametrize("tolerance", [1.5, "90", True])
def test_interval_window_rejects_non_integer_tolerance(tolerance):
	with pytest.raises(ValueError, match="must be an integer"):
		IntervalWindow(target=time(12, 0), tolerance_minutes=tolerance)


@pytest.mark.parametrize(
	("target", "tolerance"),
	[
		(time(23, 30), 30),
		(time(0, 30), 31),
		(time(12, 0), 720),
	],
)
def test_interval_window_rejects_fixed_window_crossing_midnight(target, tolerance):
	with pytest.raises(ValueError, match="crosses midnight"):
		IntervalWindow(target=target, tolerance_minutes=tolerance)


# The window may touch 00:00:00 itself; only reaching the next day is rejected.
def test_interval_window_accepts_window_ending_just_before_midnight():
	window = IntervalWindow(target=time(0, 30), tolerance_minutes=30)

	assert window.tolerance_minutes == 30


def test_interval_window_label_and_description():
	fixed_window = IntervalWindow(target=time(18, 30), tolerance_minutes=60)
	sunset_window = IntervalWindow(target=SUNSET, tolerance_minutes=45)

	assert fixed_window.label() == "1830-60min"
	assert fixed_window.describe() == "18:30 +-60 min"
	assert sunset_window.label() == "sunset-45min"
	assert sunset_window.describe() == "sunset +-45 min"


def test_interval_window_from_config_reads_default_block():
	window = interval_window_from_config(
		{"interval_window": {"target_time": "12:00", "tolerance_minutes": 90}}
	)

	assert window == IntervalWindow(target=time(12, 0), tolerance_minutes=90)


def test_resolve_target_seconds_uses_fixed_time_for_every_date():
	result = resolve_target_seconds(
		window=IntervalWindow(target=time(12, 0), tolerance_minutes=90),
		start_date=date(2026, 9, 1),
		end_date=date(2026, 9, 3),
		location={"timezone": "Europe/Berlin"},
	)

	assert result == {
		date(2026, 9, 1): NOON_SECONDS,
		date(2026, 9, 2): NOON_SECONDS,
		date(2026, 9, 3): NOON_SECONDS,
	}


# Sunset is looked up per date, so the window moves with the season.
def test_resolve_target_seconds_uses_each_days_sunset(monkeypatch):
	timezone = ZoneInfo("Europe/Berlin")
	sunsets = {
		date(2026, 6, 1): datetime(2026, 6, 1, 21, 30, 15, tzinfo=timezone),
		date(2026, 6, 2): datetime(2026, 6, 2, 21, 31, 0, tzinfo=timezone),
	}
	lookups = []

	def fake_get_sun_times(target_date, latitude, longitude, timezone):
		lookups.append((target_date, latitude, longitude, timezone))

		return None, sunsets[target_date]

	monkeypatch.setattr(interval_window_module, "get_sun_times", fake_get_sun_times)

	result = resolve_target_seconds(
		window=IntervalWindow(target=SUNSET, tolerance_minutes=60),
		start_date=date(2026, 6, 1),
		end_date=date(2026, 6, 2),
		location=LOCATION,
	)

	assert result == {
		date(2026, 6, 1): 21 * 3600 + 30 * 60 + 15,
		date(2026, 6, 2): 21 * 3600 + 31 * 60,
	}
	assert lookups == [
		(date(2026, 6, 1), 52.472, 9.333, "Europe/Berlin"),
		(date(2026, 6, 2), 52.472, 9.333, "Europe/Berlin"),
	]


def test_resolve_target_seconds_rejects_sunset_window_crossing_midnight():
	with pytest.raises(ValueError, match="sunset on 2026-06-21 .* crosses midnight"):
		resolve_target_seconds(
			window=IntervalWindow(target=SUNSET, tolerance_minutes=180),
			start_date=date(2026, 6, 21),
			end_date=date(2026, 6, 21),
			location=LOCATION,
		)


# Real astral calculation: summer sunset in Minden is hours later than winter sunset.
def test_resolve_target_seconds_sunset_follows_the_season():
	window = IntervalWindow(target=SUNSET, tolerance_minutes=60)

	summer = resolve_target_seconds(window, date(2026, 6, 21), date(2026, 6, 21), LOCATION)
	winter = resolve_target_seconds(window, date(2026, 12, 21), date(2026, 12, 21), LOCATION)

	assert 21 * 3600 < summer[date(2026, 6, 21)] < 22 * 3600
	assert 16 * 3600 < winter[date(2026, 12, 21)] < 17 * 3600
