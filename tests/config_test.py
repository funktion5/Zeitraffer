import json
from pathlib import Path

import pytest

import src.config as config_module


EXPECTED_ROOT_KEYS = {
	"location",
	"daylight_buffer_minutes",
	"image_scan_stall_timeout_seconds",
	"log_retention_days",
	"ignored_cameras",
	"timelapse",
}

EXPECTED_LOCATION_KEYS = {
	"latitude",
	"longitude",
	"timezone",
}

EXPECTED_TIMELAPSE_KEYS = {
	"daily_framerate",
	"manual_framerate",
	"monthly_framerate",
	"yearly_framerate",
	"ffmpeg_threads",
}


# Assert the configuration structure required by the application.
def assert_valid_config_structure(config: dict) -> None:
	assert set(config) == EXPECTED_ROOT_KEYS

	location = config["location"]

	assert set(location) == EXPECTED_LOCATION_KEYS

	assert isinstance(
		location["latitude"],
		(
			int,
			float,
		),
	)

	assert isinstance(
		location["longitude"],
		(
			int,
			float,
		),
	)

	assert isinstance(
		location["timezone"],
		str,
	)

	assert isinstance(
		config["daylight_buffer_minutes"],
		int,
	)

	assert isinstance(
		config["image_scan_stall_timeout_seconds"],
		(
			int,
			float,
		),
	)

	assert isinstance(
		config["log_retention_days"],
		int,
	)

	assert isinstance(
		config["ignored_cameras"],
		list,
	)

	assert all(
		isinstance(
			camera,
			str,
		)
		for camera in config["ignored_cameras"]
	)

	timelapse = config["timelapse"]

	assert set(timelapse) == EXPECTED_TIMELAPSE_KEYS

	assert isinstance(
		timelapse["daily_framerate"],
		int,
	)

	assert isinstance(
		timelapse["manual_framerate"],
		int,
	)

	assert isinstance(
		timelapse["monthly_framerate"],
		int,
	)

	assert isinstance(
		timelapse["yearly_framerate"],
		int,
	)

	assert isinstance(
		timelapse["ffmpeg_threads"],
		int,
	)


# The production configuration must live at config/config.json.
def test_config_path_points_to_expected_production_file():
	expected_path = (
		Path(config_module.__file__).resolve().parent.parent
		/ "config"
		/ "config.json"
	)

	assert config_module.CONFIG_PATH == expected_path


# The production configuration file must exist.
def test_production_config_file_exists():
	assert config_module.CONFIG_PATH.exists()
	assert config_module.CONFIG_PATH.is_file()


# The production configuration file must contain valid JSON.
def test_production_config_contains_valid_json():
	with config_module.CONFIG_PATH.open(
		"r",
		encoding="utf-8",
	) as config_file:
		config = json.load(config_file)

	assert isinstance(
		config,
		dict,
	)


# The production configuration must contain the structure required by the application.
def test_production_config_has_expected_structure():
	config = config_module.load_config()

	assert_valid_config_structure(config)


# Loading a custom configuration path must return that file's contents.
def test_load_config_uses_config_path(
	tmp_path,
	monkeypatch,
):
	config_path = tmp_path / "custom-config.json"

	expected_config = {
		"test": "mocked-config",
	}

	config_path.write_text(
		json.dumps(expected_config),
		encoding="utf-8",
	)

	monkeypatch.setattr(
		config_module,
		"CONFIG_PATH",
		config_path,
	)

	config = config_module.load_config()

	assert config == expected_config


# Invalid JSON must propagate the JSON parsing error to the caller.
def test_load_config_raises_for_invalid_json(
	tmp_path,
	monkeypatch,
):
	config_path = tmp_path / "invalid-config.json"

	config_path.write_text(
		"{invalid json",
		encoding="utf-8",
	)

	monkeypatch.setattr(
		config_module,
		"CONFIG_PATH",
		config_path,
	)

	with pytest.raises(json.JSONDecodeError):
		config_module.load_config()


# A missing configuration file must propagate the filesystem error.
def test_load_config_raises_when_file_is_missing(
	tmp_path,
	monkeypatch,
):
	config_path = tmp_path / "missing-config.json"

	monkeypatch.setattr(
		config_module,
		"CONFIG_PATH",
		config_path,
	)

	with pytest.raises(FileNotFoundError):
		config_module.load_config()

