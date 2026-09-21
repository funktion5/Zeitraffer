from datetime import date, timedelta
from pathlib import Path

import src.jobs.yearly as yearly_module
from src.jobs.yearly import (
	get_yearly_date_range,
	run_yearly_job,
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

YEARLY_FRAMERATE = TEST_CONFIG["timelapse"]["yearly_framerate"]


def test_get_yearly_date_range_returns_exact_365_day_window():
	end_date = date(
		2026,
		9,
		17,
	)

	start_date, result_end_date = get_yearly_date_range(
		end_date=end_date,
	)

	assert start_date == date(
		2025,
		9,
		18,
	)

	# The rolling window must contain exactly 365 calendar days.
	assert result_end_date == end_date

	assert (result_end_date - start_date).days == 364


def test_run_yearly_job_creates_video_from_selected_images(
	monkeypatch,
):
	interval_images = [
		Path("camera_26-09-15_11-50-00-00.jpg"),
		Path("camera_26-09-15_12-05-00-00.jpg"),
		Path("camera_26-09-16_12-10-00-00.jpg"),
	]

	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		return interval_images

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/yearly/test.mp4")

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: interval_images,
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
	)

	# Yearly keeps up to five selected frames per available day.
	assert created_videos[0]["images"] == [
		Path("camera_26-09-15_11-50-00-00.jpg"),
		Path("camera_26-09-15_12-05-00-00.jpg"),
		Path("camera_26-09-16_12-10-00-00.jpg"),
	]

	assert created_videos[0]["framerate"] == YEARLY_FRAMERATE


def test_run_yearly_job_skips_camera_without_images(
	monkeypatch,
):
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		return []

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
	)

	# A camera without usable frames must not create a Yearly video.
	assert created_videos == []


def test_run_yearly_job_continues_after_camera_timeout(
	monkeypatch,
):
	created_videos = []

	def fake_find_interval_images_isolated(
		camera,
		**kwargs,
	):
		if camera == "Broken-Camera":
			raise TimeoutError("stalled")

		return [Path("camera_26-09-15_12-00-00-00.jpg")]

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Working-Camera/yearly/test.mp4")

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=[
			"Broken-Camera",
			"Working-Camera",
		],
		framerate=YEARLY_FRAMERATE,
	)

	# One failed camera must not stop later cameras.
	assert len(created_videos) == 1

	assert created_videos[0]["camera"] == "Working-Camera"

	assert created_videos[0]["framerate"] == YEARLY_FRAMERATE


def test_run_yearly_job_logs_warning_when_days_are_missing(
	monkeypatch,
	caplog,
):
	images = [Path("camera_26-09-15_12-00-00-00.jpg")]

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: images,
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		lambda **kwargs: Path("videos/Test-Camera/yearly/test.mp4"),
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
	)

	# Partial coverage must be visible without blocking video creation.
	assert "Yearly will be created with 1 of 1825 possible frames." in caplog.text


def test_run_yearly_job_does_not_log_creation_warning_without_images(
	monkeypatch,
	caplog,
):
	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: [],
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
	)

	# A skipped Yearly must not claim that a video will be created.
	assert "Yearly will be created with" not in caplog.text

	assert "No valid Yearly images available" in caplog.text


def test_run_yearly_job_does_not_warn_when_all_days_are_available(
	monkeypatch,
	caplog,
):
	images = [
		Path(f"camera_{current_date:%y-%m-%d}_{hour:02d}-{minute:02d}-00-00.jpg")
		for current_date in (
			date(
				2025,
				9,
				18,
			)
			+ timedelta(days=offset)
			for offset in range(365)
		)
		for hour, minute in [
			(
				11,
				50,
			),
			(
				11,
				55,
			),
			(
				12,
				0,
			),
			(
				12,
				5,
			),
			(
				12,
				10,
			),
		]
	]

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: images,
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		lambda **kwargs: Path("videos/Test-Camera/yearly/test.mp4"),
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
	)

	# Complete coverage does not need a missing-frames warning.
	assert "Yearly will be created with" not in caplog.text


def test_run_yearly_job_uses_explicit_target_date(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		15,
	)

	interval_calls = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		interval_calls.append(kwargs)

		return []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	yearly_module.run_yearly_job(
		config=TEST_CONFIG,
		cameras=[
			"Camera-A",
		],
		framerate=YEARLY_FRAMERATE,
		target_date=target_date,
	)

	assert interval_calls[0]["start_date"] == date(
		2025,
		9,
		16,
	)

	assert interval_calls[0]["end_date"] == target_date
