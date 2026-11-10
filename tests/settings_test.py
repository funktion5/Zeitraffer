import json

import pytest

import src.config as config_module
from src.settings import (
	ALLOWED_KEYS,
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
	("flagger.retention_days", 1, 365),
	("daylight_buffer_minutes", 0, 240),
	*[(f"automatic_daylight_buffer_minutes.{month}", 0, 240) for month in range(1, 13)],
	("interval_window.tolerance_minutes", 0, 240),
	("min_coverage_days.monthly", 1, 31),
	("min_coverage_days.yearly", 1, 366),
	("log_retention_days", 1, 365),
]

NON_INT_KEYS = {"ignored_cameras", "flagger.cameras", "interval_window.target_time"}


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


@pytest.mark.parametrize("value", ["12:00", "00:00", "23:59"])
def test_validate_accepts_a_time_of_day(value):
	clean, errors = validate_settings({"interval_window": {"target_time": value}})

	assert errors == []
	assert clean == {"interval_window": {"target_time": value}}


@pytest.mark.parametrize("value", ["24:00", "12:60", "1200", "", "12:00\n", "7:30", 1200, None])
def test_validate_rejects_a_bad_time_of_day(value):
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
