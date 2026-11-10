import json
import os
from pathlib import Path

import pytest

from src.settings import ALLOWED_KEYS
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


def write_config(folder: Path, base: dict | str | None, settings: dict | str | None = None) -> None:
	config = folder / "config"
	config.mkdir(parents=True, exist_ok=True)

	if base is not None:
		(config / "config.json").write_text(base if isinstance(base, str) else json.dumps(base))

	if settings is not None:
		text = settings if isinstance(settings, str) else json.dumps(settings)
		(config / "settings.json").write_text(text)


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
