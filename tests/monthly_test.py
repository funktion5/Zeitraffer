from datetime import date
from pathlib import Path

import src.jobs.monthly as monthly_module
from src.jobs.monthly import (
	get_monthly_date_range,
	run_monthly_job,
)

TEST_CONFIG = {
	"location": {
		"timezone": "Europe/Berlin",
	},
	"image_scan_stall_timeout_seconds": 10,
	"timelapse": {
		"daily_framerate": 10,
		"manual_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}

MONTHLY_FRAMERATE = TEST_CONFIG["timelapse"]["monthly_framerate"]


def test_get_monthly_date_range_returns_30_day_window():
	start_date, end_date = get_monthly_date_range(
		date(
			2026,
			9,
			20,
		)
	)

	assert start_date == date(
		2026,
		8,
		22,
	)

	assert end_date == date(
		2026,
		9,
		20,
	)


def test_get_monthly_date_range_handles_year_boundary():
	start_date, end_date = get_monthly_date_range(
		date(
			2026,
			1,
			15,
		)
	)

	assert start_date == date(
		2025,
		12,
		17,
	)

	assert end_date == date(
		2026,
		1,
		15,
	)


def test_run_monthly_job_creates_video_from_all_images(
	monkeypatch,
):
	monthly_images = [
		Path("camera_26-08-10_10-45-00-00.jpg"),
		Path("camera_26-08-10_12-00-00-00.jpg"),
		Path("camera_26-08-10_13-15-00-00.jpg"),
	]

	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		return monthly_images

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/monthly/test.mp4")

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
	)

	assert len(created_videos) == 1

	# Monthly keeps every validated image from the interval.
	assert created_videos[0]["images"] == monthly_images

	assert created_videos[0]["timelapse_type"] == "monthly"

	assert created_videos[0]["framerate"] == MONTHLY_FRAMERATE

	assert created_videos[0]["manual_run"] is False


def test_run_monthly_job_skips_camera_without_images(
	monkeypatch,
):
	created_videos = []

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		lambda **kwargs: [],
	)

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		lambda **kwargs: created_videos.append(kwargs),
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
	)

	assert created_videos == []


def test_run_monthly_job_continues_after_camera_timeout(
	monkeypatch,
):
	processed_cameras = []
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		camera = kwargs["camera"]

		processed_cameras.append(camera)

		if camera == "Broken-Camera":
			raise TimeoutError("test timeout")

		return [Path("camera_26-08-10_12-00-00-00.jpg")]

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Working-Camera/monthly/test.mp4")

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=[
			"Broken-Camera",
			"Working-Camera",
		],
		framerate=MONTHLY_FRAMERATE,
	)

	assert processed_cameras == [
		"Broken-Camera",
		"Working-Camera",
	]

	assert len(created_videos) == 1

	assert created_videos[0]["camera"] == "Working-Camera"

	assert created_videos[0]["framerate"] == MONTHLY_FRAMERATE


def test_run_monthly_job_uses_rolling_30_day_window(
	monkeypatch,
):
	captured_calls = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		captured_calls.append(kwargs)

		return []

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
		target_date=date(2026, 9, 20),
	)

	assert captured_calls[0]["start_date"] == date(
		2026,
		8,
		22,
	)

	assert captured_calls[0]["end_date"] == date(
		2026,
		9,
		20,
	)


def test_run_monthly_job_uses_explicit_target_date(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		15,
	)

	interval_calls = []
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		interval_calls.append(kwargs)

		return [Path("camera_26-09-15_12-00-00-00.jpg")]

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Camera-A/monthly/test.mp4")

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	monthly_module.run_monthly_job(
		config=TEST_CONFIG,
		cameras=[
			"Camera-A",
		],
		framerate=MONTHLY_FRAMERATE,
		target_date=target_date,
		manual_run=True,
	)

	assert interval_calls[0]["start_date"] == date(
		2026,
		8,
		17,
	)

	assert interval_calls[0]["end_date"] == target_date

	assert created_videos[0]["manual_run"] is True
