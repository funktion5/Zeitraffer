import json

import pytest

import src.config as config_module
from src.privacy.anonymize import (
	BLUR_FEATHER_RANGE,
	BLUR_PADDING_RANGE,
	BLUR_STRENGTH_RANGE,
	MIN_PERSON_SCORE_RANGE,
	TOP_SHARE_RANGE,
	parse_blur_settings,
	parse_drop_rules,
)
from src.settings import (
	ALLOWED_KEYS,
	ALLOWED_KEYS_BY_SCOPE,
	load_valid_settings,
	merge_settings,
	read_settings_file,
	validate_settings,
)


# (key, lowest allowed, highest allowed): the integer rules of the allowlist.
INT_BOUNDS = [
	("timelapse.crf", 18, 35),
	("timelapse.daily_framerate", 1, 60),
	("timelapse.monthly_framerate", 1, 60),
	("timelapse.yearly_framerate", 1, 60),
	# At least 7, the flagger's own minimum: it refuses to start with fewer days.
	("flagger.retention_days", 7, 365),
	("daylight_buffer_minutes", 0, 240),
	*[(f"automatic_daylight_buffer_minutes.{month}", 0, 240) for month in range(1, 13)],
	# At least 1: the interval window rejects 0. At most 120: with the target between 10:00 and
	# 14:00 the whole window then stays in daylight, also in December.
	("interval_window.tolerance_minutes", 1, 120),
	# Never above the shortest window the job checks them against (30 days; 365, a year without a
	# 29 February): the job raises for anything higher.
	("min_coverage_days.monthly", 1, 30),
	("min_coverage_days.yearly", 1, 365),
	("log_retention_days", 1, 365),
]

NON_INT_KEYS = {"ignored_cameras", "flagger.cameras", "interval_window.target_time"}

# The privacy scope: fixed keys, and two maps keyed by a camera name ("*").
PRIVACY_KEYS = {
	"privacy.blur_cameras",
	"privacy.blur.strength",
	"privacy.blur.padding_ratio",
	"privacy.blur.feather",
	"privacy.ignore_top_share_per_camera.*",
	"privacy.min_person_score.*",
	"privacy.ignore_boxes.*",
}

# (key, lowest, highest, is the highest itself allowed?): the limits the blur code enforces.
FLOAT_BOUNDS = [
	("privacy.blur.strength", 0.05, 0.5, True),
	("privacy.blur.padding_ratio", 0.05, 1.0, True),
	("privacy.blur.feather", 0.0, 1.0, True),
	("privacy.ignore_top_share_per_camera.SLSV", 0.0, 0.5, False),
	("privacy.min_person_score.SLSV", 0.0, 0.5, True),
]

GOOD_BOX_LISTS = [
	[],
	[[0, 0, 1, 1]],
	[[703, 557, 742, 643], [1676, 636, 1720, 736]],
	[[0, 0, 20000, 20000]],
	[[index, index, index + 1, index + 1] for index in range(50)],
]

BAD_BOX_LISTS = [
	"box",
	{"a": 1},
	None,
	[None],
	[[1, 2, 3]],
	[[1, 2, 3, 4, 5]],
	[[1.0, 2, 3, 4]],
	[[True, 0, 2, 2]],
	[["1", 2, 3, 4]],
	[[-1, 0, 5, 5]],
	[[5, 0, 5, 5]],
	[[6, 0, 5, 5]],
	[[0, 5, 5, 5]],
	[[0, 6, 5, 5]],
	[[0, 0, 20001, 5]],
	[[0, 0, 5, 20001]],
	[[[1, 2, 3, 4]]],
	[[1, 2, 3, 4]] * 51,
]


# The submitted and stored shape is nested: "timelapse.crf" is {"timelapse": {"crf": ...}}.
def nest(dotted_key: str, value: object) -> dict:
	result: object = value

	for part in reversed(dotted_key.split(".")):
		result = {part: result}

	return result


def test_tests_never_read_a_real_settings_file():
	assert not config_module.SETTINGS_PATH.exists()
	assert config_module.SETTINGS_PATH != config_module.PROJECT_ROOT / "config" / "settings.json"


def test_allowed_keys_lists_every_leaf():
	assert "timelapse.crf" in ALLOWED_KEYS
	assert "automatic_daylight_buffer_minutes.11" in ALLOWED_KEYS
	assert "min_coverage_days.yearly" in ALLOWED_KEYS
	assert not [key for key in ALLOWED_KEYS if key.startswith(("privacy", "location"))]
	assert len([key for key in ALLOWED_KEYS if key.startswith("automatic_daylight")]) == 12
	assert len(set(ALLOWED_KEYS)) == len(ALLOWED_KEYS)
	assert set(ALLOWED_KEYS) == {key for key, _, _ in INT_BOUNDS} | NON_INT_KEYS


@pytest.mark.parametrize(("key", "low", "high"), INT_BOUNDS)
def test_validate_accepts_each_key_at_both_bounds(key, low, high):
	for value in (low, high):
		clean, errors = validate_settings(nest(key, value))

		assert errors == []
		assert clean == nest(key, value)


@pytest.mark.parametrize(("key", "low", "high"), INT_BOUNDS)
def test_validate_rejects_one_below_and_one_above_each_bound(key, low, high):
	for value in (low - 1, high + 1):
		clean, errors = validate_settings(nest(key, value))

		assert clean == {}
		assert len(errors) == 1
		assert errors[0].startswith(key)


@pytest.mark.parametrize("value", [17, 36, True, "28", 28.0, None, [28]])
def test_validate_rejects_out_of_range_and_wrong_types(value):
	clean, errors = validate_settings({"timelapse": {"crf": value}})

	assert clean == {}
	assert len(errors) == 1
	assert errors[0].startswith("timelapse.crf")


@pytest.mark.parametrize(
	("submitted", "key"),
	[
		({"privacy": {"blur_cameras": []}}, "privacy.blur_cameras"),
		({"location": {"timezone": "UTC"}}, "location.timezone"),
		({"timelapse": {"ffmpeg_threads": 8}}, "timelapse.ffmpeg_threads"),
		({"image_scan_stall_timeout_seconds": 5}, "image_scan_stall_timeout_seconds"),
		({"automatic_daylight_buffer_minutes": {"13": 30}}, "automatic_daylight_buffer_minutes.13"),
		# A dotted key must not sneak past the nesting.
		({"timelapse.crf": 30}, "timelapse.crf"),
		({"_note": "changed"}, "_note"),
	],
)
def test_validate_rejects_keys_outside_the_allowlist(submitted, key):
	clean, errors = validate_settings(submitted)

	assert clean == {}
	assert len(errors) == 1
	assert errors[0].startswith(key)


@pytest.mark.parametrize("raw", [[1], "crf", None, 30])
def test_validate_rejects_a_submission_that_is_not_an_object(raw):
	assert validate_settings(raw) == ({}, ["Ungültige Eingabe"])


# A crafted request or a hand-edited file must be refused like any invalid input, not end in a
# traceback (for the file: not stop the night run).
def deeply_nested(depth: int) -> str:
	return '{"a":' * depth + "1" + "}" * depth


# Built in a loop: json.loads' depth limit varies with the Python version (src/ runs on 3.11 too).
def test_validate_refuses_a_submission_too_deep_to_walk():
	raw: object = 1

	for _ in range(2000):
		raw = {"a": raw}

	assert validate_settings(raw) == ({}, ["Ungültige Eingabe"])


def test_read_settings_file_ignores_a_file_json_cannot_read(tmp_path):
	path = tmp_path / "deep.json"
	path.write_text(deeply_nested(12000), encoding="utf-8")

	assert read_settings_file(path) == {}


# Loading must never raise, whichever way the file is too deep: it can stop the night run otherwise.
@pytest.mark.parametrize("depth", [2000, 12000])
def test_load_valid_settings_survives_a_file_nested_too_deep(tmp_path, depth):
	path = tmp_path / "deep.json"
	path.write_text(deeply_nested(depth), encoding="utf-8")

	assert load_valid_settings(path) == {}


def test_validate_keeps_valid_values_next_to_invalid_ones():
	clean, errors = validate_settings({"timelapse": {"crf": 30, "daily_framerate": 99}})

	assert clean == {"timelapse": {"crf": 30}}
	assert len(errors) == 1
	assert errors[0].startswith("timelapse.daily_framerate")


@pytest.mark.parametrize("key", ["ignored_cameras", "flagger.cameras"])
def test_validate_accepts_plain_camera_names(key):
	names = ["Alpha", "SLSV", "Strand-allee_2.0"]
	clean, errors = validate_settings(nest(key, names))

	assert errors == []
	assert clean == nest(key, names)
	assert validate_settings(nest(key, [])) == (nest(key, []), [])


@pytest.mark.parametrize("key", ["ignored_cameras", "flagger.cameras"])
@pytest.mark.parametrize(
	"names",
	[["../x"], ["a/b"], [""], [".hidden"], ["ok", "bad name"], ["x\n"], [1], "Alpha", {"a": 1}],
)
def test_validate_rejects_bad_camera_names(key, names):
	clean, errors = validate_settings(nest(key, names))

	assert clean == {}
	assert len(errors) == 1
	assert errors[0].startswith(key)


# The target time of the interval window is a daylight hour: the slider on the page runs from
# 10:00 to 14:00, and nothing outside it may be saved.
@pytest.mark.parametrize("value", ["10:00", "12:00", "14:00", "10:15", "13:59"])
def test_validate_accepts_a_target_time_in_daylight(value):
	clean, errors = validate_settings({"interval_window": {"target_time": value}})

	assert errors == []
	assert clean == {"interval_window": {"target_time": value}}


@pytest.mark.parametrize(
	"value",
	["09:59", "14:01", "00:00", "23:59", "23:00", "00:30", "24:00", "12:60", "1200", "", "12:00\n"]
	+ ["7:30", 1200, None],
)
def test_validate_rejects_a_target_time_outside_daylight_or_malformed(value):
	clean, errors = validate_settings({"interval_window": {"target_time": value}})

	assert clean == {}
	assert len(errors) == 1
	assert errors[0].startswith("interval_window.target_time")


def test_merge_replaces_leaves_and_merges_the_month_map():
	base = {
		"timelapse": {"crf": 28, "ffmpeg_threads": 2},
		"automatic_daylight_buffer_minutes": {str(month): 60 for month in range(1, 13)},
		"ignored_cameras": ["Reolink", "SVG"],
	}
	clean = {
		"timelapse": {"crf": 30},
		"automatic_daylight_buffer_minutes": {"11": 45},
		"ignored_cameras": ["Alpha"],
	}

	merged = merge_settings(base, clean)

	assert merged["timelapse"] == {"crf": 30, "ffmpeg_threads": 2}
	assert merged["automatic_daylight_buffer_minutes"]["11"] == 45
	assert merged["automatic_daylight_buffer_minutes"]["10"] == 60
	assert len(merged["automatic_daylight_buffer_minutes"]) == 12
	assert merged["ignored_cameras"] == ["Alpha"]


def test_merge_does_not_change_its_inputs():
	base = {"timelapse": {"crf": 28}, "ignored_cameras": ["Reolink"]}
	clean = {"timelapse": {"crf": 30}}

	merge_settings(base, clean)

	assert base == {"timelapse": {"crf": 28}, "ignored_cameras": ["Reolink"]}
	assert clean == {"timelapse": {"crf": 30}}


def test_merge_with_nothing_to_apply_equals_the_base():
	base = {"test": "value", "timelapse": {"crf": 28}}

	assert merge_settings(base, {}) == base


def test_read_settings_file_ignores_missing_broken_and_non_object_files(tmp_path):
	broken = tmp_path / "broken.json"
	broken.write_text("{not json", encoding="utf-8")
	not_an_object = tmp_path / "list.json"
	not_an_object.write_text("[1]", encoding="utf-8")
	not_utf8 = tmp_path / "binary.json"
	not_utf8.write_bytes(b"\xff\xfe\x00")

	assert read_settings_file(tmp_path / "missing.json") == {}
	assert read_settings_file(broken) == {}
	assert read_settings_file(not_an_object) == {}
	assert read_settings_file(not_utf8) == {}


def test_read_settings_file_returns_the_parsed_object(tmp_path):
	path = tmp_path / "settings.json"
	path.write_text('{"timelapse": {"crf": 30}}', encoding="utf-8")

	assert read_settings_file(path) == {"timelapse": {"crf": 30}}


def test_load_valid_settings_drops_invalid_values_with_a_warning(tmp_path, caplog):
	path = tmp_path / "settings.json"
	path.write_text(
		json.dumps({"timelapse": {"crf": 30, "ffmpeg_threads": 99}, "log_retention_days": "x"}),
		encoding="utf-8",
	)

	with caplog.at_level("WARNING"):
		clean = load_valid_settings(path)

	assert clean == {"timelapse": {"crf": 30}}
	assert "timelapse.ffmpeg_threads" in caplog.text
	assert "log_retention_days" in caplog.text


def test_load_config_applies_valid_values_and_drops_invalid_ones(tmp_path, monkeypatch):
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	path = tmp_path / "settings.json"
	path.write_text(
		json.dumps({"timelapse": {"crf": 30, "ffmpeg_threads": 99}, "log_retention_days": "x"}),
		encoding="utf-8",
	)
	monkeypatch.setattr(config_module, "SETTINGS_PATH", path)

	config = config_module.load_config()

	assert config["timelapse"]["crf"] == 30
	assert config["timelapse"]["ffmpeg_threads"] == base["timelapse"]["ffmpeg_threads"]
	assert config["log_retention_days"] == base["log_retention_days"]


@pytest.mark.parametrize("content", ["{not json", "[1]", '"text"', "null"])
def test_load_config_survives_a_broken_settings_file(tmp_path, monkeypatch, content):
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	path = tmp_path / "settings.json"
	path.write_text(content, encoding="utf-8")
	monkeypatch.setattr(config_module, "SETTINGS_PATH", path)

	assert config_module.load_config() == base


def test_load_config_without_a_settings_file_equals_config_json():
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))

	assert config_module.load_config() == base


# The privacy values live in a second file and scope, so the two tabs of the web UI never touch each
# other's settings.
def patch_files(tmp_path, monkeypatch, general, privacy):
	general_path = tmp_path / "general.json"
	privacy_path = tmp_path / "privacy.json"

	for path, content in ((general_path, general), (privacy_path, privacy)):
		if content is not None:
			text = content if isinstance(content, str) else json.dumps(content)
			path.write_text(text, encoding="utf-8")

	monkeypatch.setattr(config_module, "SETTINGS_PATH", general_path)
	monkeypatch.setattr(config_module, "PRIVACY_SETTINGS_PATH", privacy_path)


def test_tests_never_read_a_real_privacy_settings_file():
	assert not config_module.PRIVACY_SETTINGS_PATH.exists()
	assert config_module.PRIVACY_SETTINGS_PATH != (
		config_module.PROJECT_ROOT / "config" / "settings-privacy.json"
	)


def test_scopes_have_their_own_allowlists():
	assert ALLOWED_KEYS_BY_SCOPE["general"] == ALLOWED_KEYS
	assert set(ALLOWED_KEYS_BY_SCOPE["privacy"]) == PRIVACY_KEYS
	assert not set(ALLOWED_KEYS_BY_SCOPE["general"]) & set(ALLOWED_KEYS_BY_SCOPE["privacy"])


def test_the_privacy_scope_accepts_its_keys_and_refuses_general_ones():
	clean, errors = validate_settings({"privacy": {"blur_cameras": ["Alpha"]}}, "privacy")

	assert errors == []
	assert clean == {"privacy": {"blur_cameras": ["Alpha"]}}

	clean, errors = validate_settings({"timelapse": {"crf": 30}}, "privacy")

	assert clean == {}
	assert errors[0].startswith("timelapse.crf")


@pytest.mark.parametrize("names", [["../x"], ["a/b"], [""], [1], "Alpha"])
def test_blur_cameras_must_be_plain_names(names):
	clean, errors = validate_settings(nest("privacy.blur_cameras", names), "privacy")

	assert clean == {}
	assert errors[0].startswith("privacy.blur_cameras")


def test_load_config_lays_both_files_over_config_json(tmp_path, monkeypatch):
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	patch_files(
		tmp_path,
		monkeypatch,
		{"timelapse": {"crf": 30}},
		{"privacy": {"blur_cameras": ["Alpha"]}},
	)

	config = config_module.load_config()

	assert config["timelapse"]["crf"] == 30
	assert config["privacy"]["blur_cameras"] == ["Alpha"]
	assert config["privacy"]["blur"] == base["privacy"]["blur"]


def test_each_file_only_applies_its_own_scope(tmp_path, monkeypatch):
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	patch_files(
		tmp_path,
		monkeypatch,
		{"privacy": {"blur_cameras": ["Evil"]}},
		{"timelapse": {"crf": 30}},
	)

	config = config_module.load_config()

	assert config["privacy"]["blur_cameras"] == base["privacy"]["blur_cameras"]
	assert config["timelapse"]["crf"] == base["timelapse"]["crf"]


def test_a_broken_privacy_file_leaves_the_general_values_alone(tmp_path, monkeypatch):
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	patch_files(tmp_path, monkeypatch, {"timelapse": {"crf": 30}}, "{not json")

	config = config_module.load_config()

	assert config["timelapse"]["crf"] == 30
	assert config["privacy"] == base["privacy"]


def test_settings_path_for_follows_the_patched_paths(tmp_path, monkeypatch):
	patch_files(tmp_path, monkeypatch, {}, {})

	assert config_module.settings_path_for("general") == tmp_path / "general.json"
	assert config_module.settings_path_for("privacy") == tmp_path / "privacy.json"


# The page's explanations and sliders quote these limits: if the blur code ever changes them, this
# test says the page has to follow.
def test_the_ranges_are_the_ones_the_blur_code_enforces():
	assert BLUR_STRENGTH_RANGE == (0.05, 0.5)
	assert BLUR_PADDING_RANGE == (0.05, 1.0)
	assert BLUR_FEATHER_RANGE == (0.0, 1.0)
	assert TOP_SHARE_RANGE == (0.0, 0.5)
	assert MIN_PERSON_SCORE_RANGE == (0.0, 0.5)


@pytest.mark.parametrize(("key", "low", "high", "high_included"), FLOAT_BOUNDS)
def test_float_rules_accept_their_bounds_and_values_between(key, low, high, high_included):
	inside = [low, (low + high) / 2, high if high_included else high - 0.001]

	for value in inside:
		clean, errors = validate_settings(nest(key, value), "privacy")

		assert errors == []
		assert clean == nest(key, value)


@pytest.mark.parametrize(("key", "low", "high", "high_included"), FLOAT_BOUNDS)
def test_float_rules_reject_values_outside_their_bounds(key, low, high, high_included):
	outside = [low - 0.001, high + 0.001, *([] if high_included else [high])]

	for value in outside:
		clean, errors = validate_settings(nest(key, value), "privacy")

		assert clean == {}
		assert len(errors) == 1
		assert errors[0].startswith(key)


@pytest.mark.parametrize(
	"value",
	[True, False, "0.1", None, [0.1], {"a": 1}, float("nan"), float("inf"), float("-inf")],
)
def test_float_rules_reject_wrong_types_and_non_finite_numbers(value):
	clean, errors = validate_settings(nest("privacy.blur.strength", value), "privacy")

	assert clean == {}
	assert errors[0].startswith("privacy.blur.strength")


def test_float_rules_accept_whole_numbers():
	for key, value in (("privacy.blur.feather", 0), ("privacy.blur.feather", 1)):
		clean, errors = validate_settings(nest(key, value), "privacy")

		assert errors == []
		assert clean == nest(key, value)


@pytest.mark.parametrize("boxes", GOOD_BOX_LISTS)
def test_ignore_boxes_accepts_valid_lists(boxes):
	clean, errors = validate_settings(nest("privacy.ignore_boxes.SLSV", boxes), "privacy")

	assert errors == []
	assert clean == nest("privacy.ignore_boxes.SLSV", boxes)


@pytest.mark.parametrize("boxes", BAD_BOX_LISTS)
def test_ignore_boxes_rejects_invalid_lists(boxes):
	clean, errors = validate_settings(nest("privacy.ignore_boxes.SLSV", boxes), "privacy")

	assert clean == {}
	assert len(errors) == 1
	assert errors[0].startswith("privacy.ignore_boxes.SLSV")


@pytest.mark.parametrize("camera", ["SLSV", "Alter-Winkel-Promenade", "a_b", "Cam1", "1"])
def test_per_camera_rules_accept_plain_camera_names(camera):
	submitted = {"privacy": {"min_person_score": {camera: 0.3}, "ignore_boxes": {camera: []}}}

	clean, errors = validate_settings(submitted, "privacy")

	assert errors == []
	assert clean == submitted


# A dot is the path separator, so a name with one cannot carry per-camera values.
@pytest.mark.parametrize("camera", ["a.b", "../x", "-x", "a b", "", ".hidden", "ä", "a/b"])
def test_per_camera_rules_refuse_other_names(camera):
	clean, errors = validate_settings({"privacy": {"ignore_boxes": {camera: []}}}, "privacy")

	assert clean == {}
	assert len(errors) == 1


@pytest.mark.parametrize(
	"submitted",
	[
		{"privacy": {"skip_labels": {"SLSV": ["vehicle"]}}},
		{"privacy": {"detector_command": ["x"]}},
		{"privacy": {"blur": {"other": 1}}},
		{"privacy": {"unknown": 1}},
		{"privacy": {"min_person_score": 0.3}},
		{"privacy": {"ignore_boxes": [[1, 1, 2, 2]]}},
		{"privacy": {"min_person_score": {"SLSV": {"x": 1}}}},
		# The value for all cameras stays with config.json; the page sets one per camera.
		{"privacy": {"ignore_top_share": 0.3}},
		{"privacy": {"ignore_top_share_per_camera": 0.3}},
	],
)
def test_other_privacy_keys_are_refused(submitted):
	clean, errors = validate_settings(submitted, "privacy")

	assert clean == {}
	assert errors


# What the page accepts must never stop the nightly blur run: the blur code's own checks pass.
def test_everything_the_validator_accepts_passes_the_blur_code_checks():
	privacy = {
		"blur": {"strength": 0.05, "padding_ratio": 1.0, "feather": 0},
		"ignore_top_share_per_camera": {"A": 0.49, "B": 0},
		"min_person_score": {"A": 0.5, "B": 0},
		"ignore_boxes": {"A": [[0, 0, 20000, 20000]], "B": []},
	}

	clean, errors = validate_settings({"privacy": privacy}, "privacy")

	assert errors == []

	parse_blur_settings(clean["privacy"]["blur"])
	parse_drop_rules(clean["privacy"])


def test_load_config_with_privacy_overrides_passes_the_blur_code_checks(tmp_path, monkeypatch):
	base = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))["privacy"]
	overrides = {
		"privacy": {
			"blur": {"strength": 0.1},
			"min_person_score": {"NewCam": 0.3},
			"ignore_boxes": {"NewCam": [[1, 1, 9, 9]]},
		}
	}
	patch_files(tmp_path, monkeypatch, None, overrides)

	privacy = config_module.load_config()["privacy"]

	assert privacy["blur"] == {**base["blur"], "strength": 0.1}
	# One camera's value never touches another's.
	assert privacy["min_person_score"] == {**base["min_person_score"], "NewCam": 0.3}
	assert privacy["ignore_boxes"] == {**base["ignore_boxes"], "NewCam": [[1, 1, 9, 9]]}

	parse_blur_settings(privacy["blur"])
	parse_drop_rules(privacy)
