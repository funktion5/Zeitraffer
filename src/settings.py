import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.logger import logger

# The limits the blur code enforces, taken from there so that nothing the page accepts can stop the
# nightly blur run (it raises a PrivacyCheckError for anything outside them).
from src.privacy.anonymize import (
	BLUR_FEATHER_RANGE,
	BLUR_PADDING_RANGE,
	BLUR_STRENGTH_RANGE,
	MIN_PERSON_SCORE_RANGE,
	TOP_SHARE_RANGE,
)

# The same plain-name pattern the storage listing and the web pages apply: a camera name ends up in
# file paths. fullmatch, because "$" would accept a trailing newline.
CAMERA_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
TIME_OF_DAY_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
# A camera name as a settings KEY: no dot, because the dot separates the parts of a key path.
CAMERA_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

# Sanity limits for ignore boxes (pixel coordinates of a camera image).
BOX_COORDINATE_MAX = 20000
BOXES_PER_CAMERA_MAX = 50


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
	low: str
	high: str

	@property
	def description(self) -> str:
		return f"muss eine Uhrzeit von {self.low} bis {self.high} sein (Format HH:MM)"

	def accepts(self, value: object) -> bool:
		if not isinstance(value, str) or TIME_OF_DAY_PATTERN.fullmatch(value) is None:
			return False

		# Zero-padded HH:MM sorts like the clock, so a text comparison is enough.
		return self.low <= value <= self.high


@dataclass(frozen=True)
class FloatRule:
	low: float
	high: float
	# The top-share limit is "below 0.5", not "up to 0.5".
	high_included: bool = True

	@property
	def description(self) -> str:
		upper = "bis" if self.high_included else "bis unter"

		return f"muss eine Zahl von {self.low:g} {upper} {self.high:g} sein"

	def accepts(self, value: object) -> bool:
		# bool is a subclass of int. NaN and infinity fail the comparisons below.
		if isinstance(value, bool) or not isinstance(value, (int, float)):
			return False

		if self.high_included:
			return self.low <= value <= self.high

		return self.low <= value < self.high


def _is_box(box: object) -> bool:
	if not isinstance(box, list) or len(box) != 4:
		return False

	for coordinate in box:
		if isinstance(coordinate, bool) or not isinstance(coordinate, int):
			return False

		if not 0 <= coordinate <= BOX_COORDINATE_MAX:
			return False

	# The same shape the blur code requires: x1 right of x0 and y1 below y0.
	return box[2] > box[0] and box[3] > box[1]


@dataclass(frozen=True)
class BoxListRule:
	description = (
		f"muss eine Liste von höchstens {BOXES_PER_CAMERA_MAX} Rahmen [x0, y0, x1, y1] sein"
	)

	def accepts(self, value: object) -> bool:
		return (
			isinstance(value, list)
			and len(value) <= BOXES_PER_CAMERA_MAX
			and all(_is_box(box) for box in value)
		)


Rule = IntRule | CameraNamesRule | TimeOfDayRule | FloatRule | BoxListRule

_DAYLIGHT_BUFFER = IntRule(0, 240)

# Everything the settings page may change, by dotted leaf key. Anything not listed here (the whole
# "privacy" block, "location", ffmpeg threads, the scan timeout) is refused on purpose.
GENERAL_RULES: dict[str, Rule] = {
	"timelapse.crf": IntRule(18, 35),
	"timelapse.daily_framerate": IntRule(1, 60),
	"timelapse.monthly_framerate": IntRule(1, 60),
	"timelapse.yearly_framerate": IntRule(1, 60),
	"ignored_cameras": CameraNamesRule(),
	"flagger.cameras": CameraNamesRule(),
	"flagger.retention_days": IntRule(1, 365),
	"daylight_buffer_minutes": _DAYLIGHT_BUFFER,
	**{f"automatic_daylight_buffer_minutes.{month}": _DAYLIGHT_BUFFER for month in range(1, 13)},
	# The noon picture is a daylight picture: a target between 10:00 and 14:00 and a tolerance of at
	# most 120 minutes keep the whole window in daylight in every month and inside one calendar day
	# (the window code rejects one that crosses midnight, and a tolerance below 1).
	"interval_window.target_time": TimeOfDayRule("10:00", "14:00"),
	"interval_window.tolerance_minutes": IntRule(1, 120),
	"min_coverage_days.monthly": IntRule(1, 31),
	"min_coverage_days.yearly": IntRule(1, 366),
	"log_retention_days": IntRule(1, 365),
}

ALLOWED_KEYS: tuple[str, ...] = tuple(GENERAL_RULES)

# The privacy tab of the web UI has its own scope, file and rules, so a save on one tab never
# touches the other tab's settings. The blur camera list comes first; the other privacy keys follow
# with their own rule types.
PRIVACY_RULES: dict[str, Rule] = {
	"privacy.blur_cameras": CameraNamesRule(),
	"privacy.blur.strength": FloatRule(*BLUR_STRENGTH_RANGE),
	"privacy.blur.padding_ratio": FloatRule(*BLUR_PADDING_RANGE),
	"privacy.blur.feather": FloatRule(*BLUR_FEATHER_RANGE),
	# A "*" is one camera name: one value per camera, so one camera never touches another's.
	# The value for all cameras (privacy.ignore_top_share) stays with config.json: the page sets one
	# per camera. The blur code takes 0 up to BELOW half the image.
	"privacy.ignore_top_share_per_camera.*": FloatRule(*TOP_SHARE_RANGE, high_included=False),
	"privacy.min_person_score.*": FloatRule(*MIN_PERSON_SCORE_RANGE),
	"privacy.ignore_boxes.*": BoxListRule(),
}

SCOPES: dict[str, dict[str, Rule]] = {"general": GENERAL_RULES, "privacy": PRIVACY_RULES}

ALLOWED_KEYS_BY_SCOPE: dict[str, tuple[str, ...]] = {
	name: tuple(rules) for name, rules in SCOPES.items()
}


def set_leaf(target: dict, dotted_key: str, value: object) -> None:
	*parents, leaf = dotted_key.split(".")

	for part in parents:
		target = target.setdefault(part, {})

	target[leaf] = value


# The value at a dotted key of a nested dict, or the default when any part of the path is missing.
def get_leaf(source: dict, dotted_key: str, default: object = None) -> object:
	node: object = source

	for part in dotted_key.split("."):
		if not isinstance(node, dict) or part not in node:
			return default

		node = node[part]

	return node


# Where config.json has no value for a camera under one of these prefixes, the camera's default is
# another key: a top share of its own that equals the global one changes nothing, so it is no
# override (and the camera keeps following the global value if that is changed later).
DEFAULT_FROM: dict[str, str] = {
	"privacy.ignore_top_share_per_camera": "privacy.ignore_top_share",
}

_ABSENT = object()


# The value config.json gives a key: its own, else the default named in DEFAULT_FROM, else the
# default argument.
def base_leaf(base: dict, dotted_key: str, default: object = None) -> object:
	value = get_leaf(base, dotted_key, _ABSENT)

	if value is not _ABSENT:
		return value

	source = DEFAULT_FROM.get(dotted_key.rpartition(".")[0])

	return get_leaf(base, source, default) if source else default


# The leaves of a nested dict as {dotted key: value}. A dict is a branch; a list, a number or a text
# is a leaf.
def flatten_leaves(nested: dict, prefix: str = "") -> dict[str, object]:
	leaves: dict[str, object] = {}

	for key, value in nested.items():
		path = f"{prefix}.{key}" if prefix else str(key)

		if isinstance(value, dict):
			leaves.update(flatten_leaves(value, path))
		else:
			leaves[path] = value

	return leaves


# The rule of a key path: an exact key, or "<prefix>.*" for a plain camera name below the prefix.
def _rule_for(rules: dict[str, Rule], path: str) -> Rule | None:
	rule = rules.get(path)

	if rule is not None:
		return rule

	prefix, _, camera = path.rpartition(".")

	if prefix and CAMERA_KEY_PATTERN.fullmatch(camera):
		return rules.get(f"{prefix}.*")

	return None


# Checks a submitted or stored settings object, nested like config.json. Returns the leaves that
# passed (nested again) and one German message per rejected leaf, each starting with its dotted
# key. A leaf is the value at an allowlisted key; a dict anywhere else is walked into, so a key
# outside the allowlist is always named in an error and never silently kept.
def validate_settings(raw: object, scope: str = "general") -> tuple[dict, list[str]]:
	if not isinstance(raw, dict):
		return {}, ["Ungültige Eingabe"]

	rules = SCOPES[scope]
	clean: dict = {}
	errors: list[str] = []

	def walk(node: dict, prefix: str) -> None:
		for key, value in node.items():
			path = f"{prefix}.{key}" if prefix else str(key)
			rule = _rule_for(rules, path)

			# A dot inside a key would let "timelapse.crf" skip the nesting.
			if "." in str(key):
				errors.append(f"{path}: nicht änderbar")
			elif rule is not None:
				if rule.accepts(value):
					set_leaf(clean, path, value)
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
def load_valid_settings(path: Path, scope: str = "general") -> dict:
	clean, errors = validate_settings(read_settings_file(path), scope)

	for error in errors:
		logger.warning(f"Settings value ignored: {error}")

	return clean
