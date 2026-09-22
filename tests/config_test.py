import json

import src.config as config_module


TEST_CONFIG = {
	"location": {
		"latitude": 52.0,
		"longitude": 9.0,
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"image_scan_stall_timeout_seconds": 10,
	"log_retention_days": 30,
	"ignored_cameras": [
		"Camera-A",
		"Camera-B",
	],
	"timelapse": {
		"daily_framerate": 10,
		"manual_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}


def test_load_config_returns_expected_structure(
	tmp_path,
	monkeypatch,
):
	config_path = tmp_path / "cameras.json"

	config_path.write_text(
		json.dumps(TEST_CONFIG),
		encoding="utf-8",
	)

	monkeypatch.setattr(
		config_module,
		"CONFIG_PATH",
		config_path,
	)

	config = config_module.load_config()

	assert set(config) == {
		"location",
		"daylight_buffer_minutes",
		"image_scan_stall_timeout_seconds",
		"log_retention_days",
		"ignored_cameras",
		"timelapse",
	}

	assert set(config["location"]) == {
		"latitude",
		"longitude",
		"timezone",
	}

	assert isinstance(
		config["location"]["latitude"],
		(
			int,
			float,
		),
	)

	assert isinstance(
		config["location"]["longitude"],
		(
			int,
			float,
		),
	)

	assert isinstance(
		config["location"]["timezone"],
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

	assert set(config["timelapse"]) == {
		"daily_framerate",
		"manual_framerate",
		"monthly_framerate",
		"yearly_framerate",
	}

	assert all(
		isinstance(
			framerate,
			int,
		)
		for framerate in config["timelapse"].values()
	)


def test_load_config_uses_mocked_config_path(
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
