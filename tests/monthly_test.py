from datetime import date, timedelta
from pathlib import Path

import src.jobs.monthly as monthly_module
from src.jobs.monthly import run_monthly_job


TEST_CONFIG = {
	"location": {
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"image_scan_stall_timeout_seconds": 10,
	"timelapse": {
		"daily_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}

MONTHLY_FRAMERATE = TEST_CONFIG["timelapse"]["monthly_framerate"]
TARGET_DATE = date(2026, 9, 20)
START_DATE = date(2026, 8, 22)


def create_complete_monthly_images() -> list[Path]:
	return [
		Path(f"camera_{current_date:%y-%m-%d}_12-00-00-00.jpg")
		for current_date in (START_DATE + timedelta(days=offset) for offset in range(30))
	]


# A Monthly must be created when every day in the 30-day window is covered.
def test_run_monthly_job_creates_video_with_complete_coverage(
	monkeypatch,
	caplog,
):
	monthly_images = create_complete_monthly_images()

	# Monthly keeps all validated images, including additional images on covered days.
	monthly_images.append(Path("camera_26-09-20_13-00-00-00.jpg"))

	created_videos = []

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		lambda **kwargs: monthly_images,
	)

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/monthly/test.mp4")

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	assert len(created_videos) == 1

	assert created_videos[0]["camera"] == "Test-Camera"
	assert created_videos[0]["target_date"] == TARGET_DATE
	assert created_videos[0]["images"] == monthly_images
	assert created_videos[0]["timelapse_type"] == "monthly"
	assert created_videos[0]["framerate"] == MONTHLY_FRAMERATE
	assert created_videos[0]["manual_run"] is False
	assert f"Found {len(monthly_images)} selected Monthly images" in caplog.text


# A Monthly must not be created when no validated images exist.
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
		target_date=TARGET_DATE,
	)

	assert created_videos == []


# A Monthly must not be created when at least one required day is missing.
def test_run_monthly_job_skips_incomplete_coverage(
	monkeypatch,
	caplog,
):
	monthly_images = create_complete_monthly_images()

	# Remove one required day from the 30-day window.
	missing_date = date(2026, 9, 5)

	monthly_images = [
		image for image in monthly_images if missing_date.strftime("%y-%m-%d") not in image.name
	]

	created_videos = []

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		lambda **kwargs: monthly_images,
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
		target_date=TARGET_DATE,
	)

	assert created_videos == []

	assert "Monthly coverage incomplete: 29 of 30 days available" in caplog.text


# A failed camera must not stop later cameras from being processed.
def test_run_monthly_job_continues_after_camera_timeout(
	monkeypatch,
	caplog,
):
	processed_cameras = []
	created_videos = []

	monthly_images = create_complete_monthly_images()

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		camera = kwargs["camera"]

		processed_cameras.append(camera)

		if camera == "Broken-Camera":
			raise TimeoutError("test timeout")

		return monthly_images

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
		target_date=TARGET_DATE,
	)

	assert processed_cameras == [
		"Broken-Camera",
		"Working-Camera",
	]

	assert len(created_videos) == 1
	assert created_videos[0]["camera"] == "Working-Camera"
	assert "created=1 | skipped=0 | failed=1" in caplog.text


# Monthly must request the exact rolling 30-day window from image discovery.
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
		target_date=TARGET_DATE,
	)

	assert captured_calls == [
		{
			"camera": "Test-Camera",
			"start_date": START_DATE,
			"end_date": TARGET_DATE,
			"stall_timeout_seconds": TEST_CONFIG["image_scan_stall_timeout_seconds"],
			"remove_duplicates_by_date": True,
		}
	]


# Historical Monthly runs must keep the explicit target date and manual output mode.
def test_run_monthly_job_uses_explicit_target_date(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		15,
	)

	start_date = date(
		2026,
		8,
		17,
	)

	monthly_images = [
		Path(f"camera_{current_date:%y-%m-%d}_12-00-00-00.jpg")
		for current_date in (start_date + timedelta(days=offset) for offset in range(30))
	]

	interval_calls = []
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		interval_calls.append(kwargs)

		return monthly_images

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Camera-A/manual-runs/monthly/test.mp4")

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
			"Camera-A",
		],
		framerate=MONTHLY_FRAMERATE,
		target_date=target_date,
		manual_run=True,
	)

	assert interval_calls[0]["start_date"] == start_date
	assert interval_calls[0]["end_date"] == target_date
	assert interval_calls[0]["remove_duplicates_by_date"] is True

	assert created_videos[0]["target_date"] == target_date
	assert created_videos[0]["manual_run"] is True


# Automatic Monthly runs must clean up older automatic Monthly videos.
def test_run_monthly_job_cleans_automatic_retention(
	monkeypatch,
):
	monthly_images = create_complete_monthly_images()

	video_path = Path("videos/Scheunenviertel/monthly/Scheunenviertel_2026-09-20.mp4")

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		lambda **kwargs: monthly_images,
	)

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		lambda **kwargs: video_path,
	)

	retention_calls = []

	monkeypatch.setattr(
		monthly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	assert retention_calls == [
		{
			"camera": "Scheunenviertel",
			"timelapse_type": "monthly",
			"current_video": video_path,
		}
	]


# Historical Monthly runs must never clean up automatic Monthly videos.
def test_run_monthly_job_skips_retention_for_manual_run(
	monkeypatch,
):
	monthly_images = create_complete_monthly_images()

	video_path = Path("videos/Scheunenviertel/manual-runs/monthly/Scheunenviertel_2026-09-20.mp4")

	monkeypatch.setattr(
		monthly_module,
		"find_interval_images_isolated",
		lambda **kwargs: monthly_images,
	)

	monkeypatch.setattr(
		monthly_module,
		"create_timelapse",
		lambda **kwargs: video_path,
	)

	retention_calls = []

	monkeypatch.setattr(
		monthly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
		manual_run=True,
	)

	assert retention_calls == []
