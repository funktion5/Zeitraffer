import json

from src.config import (
	CONFIG_PATH,
	PROJECT_ROOT,
	load_config,
)


def test_config_path_points_to_expected_location():
	assert CONFIG_PATH == (PROJECT_ROOT / "config" / "cameras.json")


def test_config_file_exists():
	assert CONFIG_PATH.exists()
	assert CONFIG_PATH.is_file()


def test_config_file_contains_valid_json():
	with CONFIG_PATH.open(
		"r",
		encoding="utf-8",
	) as file:
		config = json.load(file)

	assert isinstance(
		config,
		dict,
	)


def test_load_config_returns_expected_structure():
	config = load_config()

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
