from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Literal

from src.solar import get_sun_times

SUNSET = "sunset"

SECONDS_PER_DAY = 24 * 60 * 60

WindowTarget = time | Literal["sunset"]


# Parse a window target as "HH:MM" or the dynamic keyword "sunset".
def parse_window_time(value: str) -> WindowTarget:
	if value == SUNSET:
		return SUNSET

	try:
		hour_text, minute_text = value.split(":")
		parsed = time(
			hour=int(hour_text),
			minute=int(minute_text),
		)

	except ValueError:
		raise ValueError(f"Invalid window time (expected HH:MM or 'sunset'): {value}") from None

	# Reject "9:5" style input so the filename label stays unambiguous.
	if len(hour_text) != 2 or len(minute_text) != 2:
		raise ValueError(f"Invalid window time (expected HH:MM or 'sunset'): {value}")

	return parsed


# Daily time window used by Monthly/Yearly image selection.
@dataclass(frozen=True)
class IntervalWindow:
	target: WindowTarget
	tolerance_minutes: int

	def __post_init__(self) -> None:
		if isinstance(self.tolerance_minutes, bool) or not isinstance(self.tolerance_minutes, int):
			raise ValueError(f"Window tolerance must be an integer: {self.tolerance_minutes!r}")

		if self.tolerance_minutes < 1:
			raise ValueError(
				f"Window tolerance must be at least 1 minute: {self.tolerance_minutes}"
			)

		# A sunset window can only be checked once its dates are known.
		if self.target != SUNSET:
			_check_inside_day(
				target_seconds=self.target.hour * 60 * 60 + self.target.minute * 60,
				tolerance_minutes=self.tolerance_minutes,
				description=f"{self.target:%H:%M}",
			)

	# Filename-safe label, e.g. "1830-60min" or "sunset-60min".
	def label(self) -> str:
		target_label = SUNSET if self.target == SUNSET else f"{self.target:%H%M}"

		return f"{target_label}-{self.tolerance_minutes}min"

	# Human-readable form for log lines.
	def describe(self) -> str:
		target_label = SUNSET if self.target == SUNSET else f"{self.target:%H:%M}"

		return f"{target_label} +-{self.tolerance_minutes} min"


# Build the default window from config.json's "interval_window" block.
def interval_window_from_config(config: dict) -> IntervalWindow:
	window_config = config["interval_window"]

	return IntervalWindow(
		target=parse_window_time(window_config["target_time"]),
		tolerance_minutes=window_config["tolerance_minutes"],
	)


# Resolve the window centre for every date, in seconds after local midnight.
def resolve_target_seconds(
	window: IntervalWindow,
	start_date: date,
	end_date: date,
	location: dict,
) -> dict[date, int]:
	target_seconds_by_date: dict[date, int] = {}

	for offset in range((end_date - start_date).days + 1):
		current_date = start_date + timedelta(days=offset)

		if window.target == SUNSET:
			_sunrise, sunset = get_sun_times(
				target_date=current_date,
				latitude=location["latitude"],
				longitude=location["longitude"],
				timezone=location["timezone"],
			)

			target_seconds = sunset.hour * 60 * 60 + sunset.minute * 60 + sunset.second

			_check_inside_day(
				target_seconds=target_seconds,
				tolerance_minutes=window.tolerance_minutes,
				description=f"sunset on {current_date} ({sunset:%H:%M})",
			)

		else:
			target_seconds = window.target.hour * 60 * 60 + window.target.minute * 60

		target_seconds_by_date[current_date] = target_seconds

	return target_seconds_by_date


# Images are grouped by their filename date, so a window must not cross midnight.
def _check_inside_day(
	target_seconds: int,
	tolerance_minutes: int,
	description: str,
) -> None:
	tolerance_seconds = tolerance_minutes * 60

	if (
		target_seconds - tolerance_seconds < 0
		or target_seconds + tolerance_seconds >= SECONDS_PER_DAY
	):
		raise ValueError(
			f"Window {description} +-{tolerance_minutes} min crosses midnight; "
			"choose a smaller tolerance or a different time."
		)
