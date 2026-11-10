import json
import os
from pathlib import Path

import pytest

from src.settings import ALLOWED_KEYS, ALLOWED_KEYS_BY_SCOPE
from web_php_test import PROJECT_ROOT_CALL, run_php


# An arbitrary but fixed modification time.
FILE_TIME = 1_700_000_000

BASE = {
	"location": {"latitude": 52.472, "longitude": 9.333, "timezone": "Europe/Berlin"},
	"timelapse": {"crf": 28, "ffmpeg_threads": 2},
	"automatic_daylight_buffer_minutes": {str(month): 60 for month in range(1, 13)},
	"ignored_cameras": ["Old"],
	"flagger": {"cameras": ["Alpha"], "retention_days": 30},
	"privacy": {"blur_cameras": ["Blur"]},
}


# run_php swaps the project root once per folder, so a test that needs two states uses two folders.
def php(folder: Path, code: str):
	folder.mkdir(parents=True, exist_ok=True)

	return run_php(
		folder,
		"video-library.php",
		{PROJECT_ROOT_CALL: json.dumps(str(folder))},
		code,
	)


def write_config(
	folder: Path,
	base: dict | str | None,
	settings: dict | str | None = None,
	privacy: dict | str | None = None,
) -> None:
	config = folder / "config"
	config.mkdir(parents=True, exist_ok=True)

	if base is not None:
		(config / "config.json").write_text(base if isinstance(base, str) else json.dumps(base))

	for name, content in (("settings.json", settings), ("settings-privacy.json", privacy)):
		if content is not None:
			text = content if isinstance(content, str) else json.dumps(content)
			(config / name).write_text(text)


def effective(folder: Path) -> dict:
	return php(folder, "echo json_encode(readProjectConfig());")


def test_overlay_changes_allowlisted_keys_only(tmp_path):
	write_config(
		tmp_path,
		BASE,
		{
			"timelapse": {"crf": 30, "ffmpeg_threads": 99},
			"ignored_cameras": ["New"],
			"flagger": {"retention_days": 7},
			"privacy": {"blur_cameras": []},
			"location": {"timezone": "UTC"},
		},
	)

	config = effective(tmp_path)

	assert config["timelapse"] == {"crf": 30, "ffmpeg_threads": 2}
	assert config["ignored_cameras"] == ["New"]
	assert config["flagger"] == {"cameras": ["Alpha"], "retention_days": 7}
	assert config["privacy"] == BASE["privacy"]
	assert config["location"] == BASE["location"]


def test_month_map_merges_by_month(tmp_path):
	write_config(tmp_path, BASE, {"automatic_daylight_buffer_minutes": {"11": 45}})

	buffers = effective(tmp_path)["automatic_daylight_buffer_minutes"]

	assert buffers["11"] == 45
	assert buffers["10"] == 60
	assert len(buffers) == 12


def test_a_literal_dotted_key_in_the_file_is_not_applied(tmp_path):
	write_config(tmp_path, BASE, {"timelapse.crf": 30, "_note": "changed"})

	config = effective(tmp_path)

	assert config["timelapse"]["crf"] == 28
	assert "_note" not in config


@pytest.mark.parametrize("settings", [None, "{not json", "[1]", '"text"', "null", ""])
def test_missing_and_broken_settings_file_give_the_base(tmp_path, settings):
	write_config(tmp_path, BASE, settings)

	assert effective(tmp_path) == BASE


def test_settings_still_apply_when_config_json_is_missing(tmp_path):
	write_config(tmp_path, None, {"timelapse": {"crf": 30}})

	assert effective(tmp_path) == {"timelapse": {"crf": 30}}


def test_base_config_ignores_the_settings_file(tmp_path):
	write_config(tmp_path, BASE, {"timelapse": {"crf": 30}})

	assert php(tmp_path, "echo json_encode(readBaseConfig());") == BASE


@pytest.mark.parametrize("base", [None, "{not json", '"text"'])
def test_a_missing_or_broken_config_json_gives_an_empty_base(tmp_path, base):
	write_config(tmp_path, base)

	assert php(tmp_path, "echo json_encode(readBaseConfig());") == []


def test_settings_mtime_is_zero_without_a_file(tmp_path):
	write_config(tmp_path / "none", BASE)

	assert php(tmp_path / "none", "echo json_encode(readSettingsMtime());") == 0


def test_settings_mtime_is_the_file_time_in_whole_seconds(tmp_path):
	folder = tmp_path / "saved"
	write_config(folder, BASE, {})
	os.utime(folder / "config" / "settings.json", (FILE_TIME, FILE_TIME))

	assert php(folder, "echo json_encode(readSettingsMtime());") == FILE_TIME


# PHP repeats only the key names, so this is what stops the two lists from drifting apart.
def test_php_key_list_equals_the_python_allowlist(tmp_path):
	keys = php(tmp_path, "echo json_encode(SETTINGS_ALLOWED_KEYS);")

	assert len(keys) == len(set(keys))
	assert sorted(keys) == sorted(ALLOWED_KEYS)


# Both libraries read the config through the one shared reader, so a saved setting reaches them.
def test_both_libraries_use_the_shared_reader(tmp_path):
	write_config(
		tmp_path,
		BASE,
		{"ignored_cameras": ["New"], "flagger": {"cameras": ["Beta"]}},
	)
	highlights = tmp_path / "php-src" / "highlights-library.php"

	result = php(
		tmp_path,
		f"require_once {json.dumps(str(highlights))};\n"
		"echo json_encode([getIgnoredCameras(), readHighlightsConfig()['flagger']['cameras']]);",
	)

	assert result == [["New"], ["Beta"]]


# The privacy tab has its own file and scope: each file applies only its own keys.
def test_the_privacy_file_applies_privacy_keys_only(tmp_path):
	privacy = {"privacy": {"blur_cameras": ["Alpha"]}, "timelapse": {"crf": 99}}
	write_config(tmp_path, BASE, privacy=privacy)

	config = effective(tmp_path)

	assert config["privacy"]["blur_cameras"] == ["Alpha"]
	assert config["timelapse"]["crf"] == 28


def test_the_general_file_does_not_apply_privacy_keys(tmp_path):
	write_config(tmp_path, BASE, settings={"privacy": {"blur_cameras": ["Evil"]}})

	assert effective(tmp_path)["privacy"] == BASE["privacy"]


def test_both_files_apply_together(tmp_path):
	write_config(
		tmp_path,
		BASE,
		settings={"timelapse": {"crf": 30}},
		privacy={"privacy": {"blur_cameras": ["Alpha"]}},
	)

	config = effective(tmp_path)

	assert config["timelapse"]["crf"] == 30
	assert config["privacy"] == {"blur_cameras": ["Alpha"]}


@pytest.mark.parametrize("privacy", [None, "{not json", "[1]", ""])
def test_a_missing_or_broken_privacy_file_gives_the_base(tmp_path, privacy):
	write_config(tmp_path, BASE, privacy=privacy)

	assert effective(tmp_path) == BASE


def test_each_scope_has_its_own_modification_time(tmp_path):
	folder = tmp_path / "scopes"
	write_config(folder, BASE, settings={}, privacy={})
	os.utime(folder / "config" / "settings.json", (FILE_TIME, FILE_TIME))
	os.utime(folder / "config" / "settings-privacy.json", (FILE_TIME + 60, FILE_TIME + 60))

	times = php(
		folder,
		'echo json_encode([readSettingsMtime(), readSettingsMtime("general"), '
		'readSettingsMtime("privacy")]);',
	)

	assert times == [FILE_TIME, FILE_TIME, FILE_TIME + 60]


def test_a_missing_privacy_file_has_time_zero(tmp_path):
	write_config(tmp_path, BASE, settings={})

	assert php(tmp_path, 'echo json_encode(readSettingsMtime("privacy"));') == 0


def test_php_privacy_key_lists_equal_the_python_allowlist(tmp_path):
	leaves, maps = php(
		tmp_path,
		"echo json_encode([PRIVACY_SETTINGS_ALLOWED_KEYS, PRIVACY_SETTINGS_ALLOWED_MAPS]);",
	)
	keys = [*leaves, *(f"{prefix}.*" for prefix in maps)]

	assert len(keys) == len(set(keys))
	assert sorted(keys) == sorted(ALLOWED_KEYS_BY_SCOPE["privacy"])


PRIVACY_BASE = {
	**BASE,
	"privacy": {
		"blur_cameras": ["Blur"],
		"blur": {"strength": 0.08, "padding_ratio": 0.05, "feather": 0.5},
		"ignore_top_share": 0.333,
		"min_person_score": {"SLSV": 0.35},
		"ignore_boxes": {"A": [[1, 1, 2, 2]]},
	},
}


def test_the_privacy_file_applies_blur_values_and_per_camera_maps(tmp_path):
	overrides = {
		"privacy": {
			"blur": {"strength": 0.1},
			"ignore_top_share": 0.2,
			"min_person_score": {"New": 0.3},
			"ignore_boxes": {"A": [], "New": [[3, 3, 9, 9]]},
		}
	}
	write_config(tmp_path, PRIVACY_BASE, privacy=overrides)

	privacy = effective(tmp_path)["privacy"]

	assert privacy["blur"] == {"strength": 0.1, "padding_ratio": 0.05, "feather": 0.5}
	assert privacy["ignore_top_share"] == 0.2
	# One camera's value never touches another's.
	assert privacy["min_person_score"] == {"SLSV": 0.35, "New": 0.3}
	assert privacy["ignore_boxes"] == {"A": [], "New": [[3, 3, 9, 9]]}


def test_php_ignores_per_camera_keys_that_are_not_plain_names(tmp_path):
	overrides = {"privacy": {"min_person_score": {"a.b": 0.3, "../x": 0.3, "-x": 0.3, "ok": 0.3}}}
	write_config(tmp_path, PRIVACY_BASE, privacy=overrides)

	assert effective(tmp_path)["privacy"]["min_person_score"] == {"SLSV": 0.35, "ok": 0.3}


@pytest.mark.parametrize(
	"overrides",
	[
		{"privacy": {"min_person_score": 0.3, "ignore_boxes": "x"}},
		{"privacy": {"min_person_score": [0.3], "ignore_boxes": [[1, 1, 2, 2]]}},
		{"privacy": {"min_person_score": None, "ignore_boxes": {}}},
	],
)
def test_a_privacy_map_that_is_not_an_object_changes_nothing(tmp_path, overrides):
	write_config(tmp_path, PRIVACY_BASE, privacy=overrides)

	assert effective(tmp_path) == PRIVACY_BASE


def test_the_general_file_does_not_apply_per_camera_privacy_maps(tmp_path):
	settings = {"privacy": {"ignore_boxes": {"New": [[1, 1, 2, 2]]}}}
	write_config(tmp_path, PRIVACY_BASE, settings=settings)

	assert effective(tmp_path)["privacy"]["ignore_boxes"] == {"A": [[1, 1, 2, 2]]}
