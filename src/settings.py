import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.logger import logger

# The same plain-name pattern the storage listing and the web pages apply: a camera name ends up in
# file paths. fullmatch, because "$" would accept a trailing newline.
CAMERA_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
TIME_OF_DAY_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


@dataclass(frozen=True)
class IntRule:
	low: int
	high: int

	@property
	def description(self) -> str:
		return f"muss eine ganze Zahl von {self.low} bis {self.high} sein"

	def accepts(self, value: object) -> bool:
		# bool is a subclass of int: True must not pass as 1.
		if isinstance(value, bool) or not isinstance(value, int):
			return False

		return self.low <= value <= self.high


@dataclass(frozen=True)
class CameraNamesRule:
	description = "muss eine Liste von Kameranamen sein"

	def accepts(self, value: object) -> bool:
		return isinstance(value, list) and all(
			isinstance(name, str) and CAMERA_NAME_PATTERN.fullmatch(name) is not None
			for name in value
		)


@dataclass(frozen=True)
class TimeOfDayRule:
	description = "muss eine Uhrzeit im Format HH:MM sein"

	def accepts(self, value: object) -> bool:
		return isinstance(value, str) and TIME_OF_DAY_PATTERN.fullmatch(value) is not None


Rule = IntRule | CameraNamesRule | TimeOfDayRule

_DAYLIGHT_BUFFER = IntRule(0, 240)

# Everything the settings page may change, by dotted leaf key. Anything not listed here (the whole
# "privacy" block, "location", ffmpeg threads, the scan timeout) is refused on purpose.
RULES: dict[str, Rule] = {
	"timelapse.crf": IntRule(18, 35),
	"timelapse.daily_framerate": IntRule(1, 60),
	"timelapse.monthly_framerate": IntRule(1, 60),
	"timelapse.yearly_framerate": IntRule(1, 60),
	"ignored_cameras": CameraNamesRule(),
	"flagger.cameras": CameraNamesRule(),
	"flagger.retention_days": IntRule(1, 365),
	"daylight_buffer_minutes": _DAYLIGHT_BUFFER,
	**{f"automatic_daylight_buffer_minutes.{month}": _DAYLIGHT_BUFFER for month in range(1, 13)},
	"interval_window.target_time": TimeOfDayRule(),
	"interval_window.tolerance_minutes": IntRule(0, 240),
	"min_coverage_days.monthly": IntRule(1, 31),
	"min_coverage_days.yearly": IntRule(1, 366),
	"log_retention_days": IntRule(1, 365),
}

ALLOWED_KEYS: tuple[str, ...] = tuple(RULES)


def _set_leaf(target: dict, dotted_key: str, value: object) -> None:
	*parents, leaf = dotted_key.split(".")

	for part in parents:
		target = target.setdefault(part, {})

	target[leaf] = value


# Checks a submitted or stored settings object, nested like config.json. Returns the leaves that
# passed (nested again) and one German message per rejected leaf, each starting with its dotted
# key. A leaf is the value at an allowlisted key; a dict anywhere else is walked into, so a key
# outside the allowlist is always named in an error and never silently kept.
def validate_settings(raw: object) -> tuple[dict, list[str]]:
	if not isinstance(raw, dict):
		return {}, ["Ungültige Eingabe"]

	clean: dict = {}
	errors: list[str] = []

	def walk(node: dict, prefix: str) -> None:
		for key, value in node.items():
			path = f"{prefix}.{key}" if prefix else str(key)

			# A dot inside a key would let "timelapse.crf" skip the nesting.
			if "." in str(key):
				errors.append(f"{path}: nicht änderbar")
			elif path in RULES:
				rule = RULES[path]

				if rule.accepts(value):
					_set_leaf(clean, path, value)
				else:
					errors.append(f"{path}: {rule.description}")
			elif isinstance(value, dict):
				walk(value, path)
			else:
				errors.append(f"{path}: nicht änderbar")

	walk(raw, "")

	return clean, errors


# Lays the validated settings over the base config. Dicts merge key by key (so one month of the
# daylight buffer changes only that month); lists and numbers replace. Neither input is changed.
def merge_settings(base: dict, clean: dict) -> dict:
	merged = dict(base)

	for key, value in clean.items():
		if isinstance(value, dict) and isinstance(merged.get(key), dict):
			merged[key] = merge_settings(merged[key], value)
		else:
			merged[key] = value

	return merged


# A missing, unreadable, broken or non-object file means "no settings": a bad file must never stop
# the night run, so it is logged and ignored.
def read_settings_file(path: Path) -> dict:
	try:
		with path.open("r", encoding="utf-8") as file:
			content = json.load(file)

	except FileNotFoundError:
		return {}

	except (OSError, ValueError) as error:
		logger.warning(f"Settings file ignored ({path.name}): {error}")

		return {}

	if not isinstance(content, dict):
		logger.warning(f"Settings file ignored ({path.name}): the content is not a JSON object")

		return {}

	return content


# What load_config() lays over config.json: the valid part of the file, a warning for the rest.
def load_valid_settings(path: Path) -> dict:
	clean, errors = validate_settings(read_settings_file(path))

	for error in errors:
		logger.warning(f"Settings value ignored: {error}")

	return clean
