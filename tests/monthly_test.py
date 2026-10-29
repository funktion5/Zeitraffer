import subprocess
from datetime import date, time, timedelta
from pathlib import Path

from frame_source_fakes import RecordingFrameSource

import src.images as images_module
import src.jobs.monthly as monthly_module
from src.image_worker import WorkerExitedError
from src.jobs.monthly import run_monthly_job
from src.interval_window import SUNSET, IntervalWindow


TEST_CONFIG = {
	"location": {
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"interval_window": {
		"target_time": "12:00",
		"tolerance_minutes": 90,
	},
	"min_coverage_days": {
		"monthly": 25,
		"yearly": 300,
	},
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


def run_monthly_with_missing_days(
	monkeypatch,
	missing_day_count: int,
) -> list[dict]:
	missing_dates = {START_DATE + timedelta(days=offset) for offset in range(missing_day_count)}
	monthly_images = [
		image
		for image in create_complete_monthly_images()
		if not any(missing.strftime("%y-%m-%d") in image.name for missing in missing_dates)
	]
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

	monkeypatch.setattr(monthly_module, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(
		monthly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: None,
	)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	return created_videos


# Exactly the configured minimum (25 of 30) still creates the video and logs the gap.
def test_run_monthly_job_creates_video_at_minimum_coverage(
	monkeypatch,
	caplog,
):
	created_videos = run_monthly_with_missing_days(monkeypatch, missing_day_count=5)

	assert len(created_videos) == 1
	# The missing days are left out, not filled.
	assert len(created_videos[0]["images"]) == 25
	assert (
		"Monthly coverage partial: 25 of 30 days available (minimum 25) | "
		"missing: 2026-08-22 to 2026-08-26"
	) in caplog.text


# One day below the minimum must skip the camera.
def test_run_monthly_job_skips_below_minimum_coverage(
	monkeypatch,
	caplog,
):
	created_videos = run_monthly_with_missing_days(monkeypatch, missing_day_count=6)

	assert created_videos == []
	assert (
		"Monthly coverage too low: 24 of 30 days available (minimum 25) - "
		"skipping camera: Test-Camera"
	) in caplog.text


# The threshold comes from config.json, not from a hardcoded value.
def test_run_monthly_job_uses_configured_minimum(
	monkeypatch,
	caplog,
):
	monkeypatch.setitem(TEST_CONFIG, "min_coverage_days", {"monthly": 30, "yearly": 300})

	created_videos = run_monthly_with_missing_days(monkeypatch, missing_day_count=1)

	assert created_videos == []
	assert "29 of 30 days available (minimum 30)" in caplog.text


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
			"target_seconds_by_date": {
				START_DATE + timedelta(days=offset): 12 * 60 * 60
				for offset in range((TARGET_DATE - START_DATE).days + 1)
			},
			"tolerance_minutes": 90,
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


# A historical override moves the scan window and names the video after it.
def test_run_monthly_job_applies_interval_window_override(
	monkeypatch,
):
	scan_calls = []
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		scan_calls.append(kwargs)

		return create_complete_monthly_images()

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/manual-runs/monthly/test.mp4")

	monkeypatch.setattr(
		monthly_module, "find_interval_images_isolated", fake_find_interval_images_isolated
	)
	monkeypatch.setattr(monthly_module, "create_timelapse", fake_create_timelapse)

	window = IntervalWindow(target=time(18, 30), tolerance_minutes=60)

	run_monthly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
		manual_run=True,
		interval_window=window,
	)

	assert scan_calls[0]["tolerance_minutes"] == 60
	assert set(scan_calls[0]["target_seconds_by_date"].values()) == {18 * 60 * 60 + 30 * 60}
	assert created_videos[0]["interval_window"] == window


# Sunset resolves a different centre per day from the configured location.
def test_run_monthly_job_resolves_sunset_per_day(
	monkeypatch,
):
	scan_calls = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		scan_calls.append(kwargs)

		return []

	monkeypatch.setattr(
		monthly_module, "find_interval_images_isolated", fake_find_interval_images_isolated
	)

	config = {
		**TEST_CONFIG,
		"location": {
			"latitude": 52.472,
			"longitude": 9.333,
			"timezone": "Europe/Berlin",
		},
	}

	run_monthly_job(
		config=config,
		cameras=["Test-Camera"],
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
		manual_run=True,
		interval_window=IntervalWindow(target=SUNSET, tolerance_minutes=60),
	)

	target_seconds_by_date = scan_calls[0]["target_seconds_by_date"]

	assert min(target_seconds_by_date) == START_DATE
	assert max(target_seconds_by_date) == TARGET_DATE
	# Evening centres that differ between days, never the 12:00 default.
	assert all(seconds > 16 * 60 * 60 for seconds in target_seconds_by_date.values())
	assert len(set(target_seconds_by_date.values())) > 1


# Replace everything the Monthly job reaches outside itself and return the event log.
def patch_monthly_job(monkeypatch, find, create_error=None, release_errors=None):
	events = []

	def fake_create_timelapse(camera, **kwargs):
		events.append(f"create:{camera}")

		if create_error is not None:
			raise create_error

		return Path(f"videos/{camera}/monthly/video.mp4")

	monkeypatch.setattr(monthly_module, "find_interval_images_isolated", find)
	monkeypatch.setattr(monthly_module, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(monthly_module, "cleanup_automatic_video_retention", lambda **kwargs: None)
	monkeypatch.setattr(
		images_module,
		"get_frame_source",
		lambda: RecordingFrameSource(events, release_errors),
	)

	return events


def run_monthly(cameras):
	run_monthly_job(
		config=TEST_CONFIG,
		cameras=cameras,
		framerate=MONTHLY_FRAMERATE,
		target_date=TARGET_DATE,
	)


# A camera whose frames cannot be fetched counts as failed; the others still run and any
# partly fetched frames of the failed camera are removed.
def test_fetch_error_counts_as_failed_and_other_cameras_still_run(
	monkeypatch,
	caplog,
):
	def fake_find_interval_images_isolated(camera, **kwargs):
		# The worker forwards a failed fetch to the parent as a plain OSError.
		if camera == "Unreachable-Camera":
			raise OSError("rsync from the box failed")

		return create_complete_monthly_images()

	events = patch_monthly_job(monkeypatch, fake_find_interval_images_isolated)

	run_monthly(["Unreachable-Camera", "Working-Camera"])

	assert events == [
		"release:Unreachable-Camera",
		"create:Working-Camera",
		"release:Working-Camera",
	]
	assert "created=1 | skipped=0 | failed=1" in caplog.text


# A worker that dies is not an OSError, but it only costs that camera: the others still run.
def test_a_dead_worker_fails_that_camera_and_other_cameras_still_run(
	monkeypatch,
	caplog,
):
	def fake_find_interval_images_isolated(camera, **kwargs):
		if camera == "Crashed-Camera":
			raise WorkerExitedError("Interval image scan worker exited unexpectedly")

		return create_complete_monthly_images()

	events = patch_monthly_job(monkeypatch, fake_find_interval_images_isolated)

	run_monthly(["Crashed-Camera", "Working-Camera"])

	assert events == [
		"release:Crashed-Camera",
		"create:Working-Camera",
		"release:Working-Camera",
	]
	assert "created=1 | skipped=0 | failed=1" in caplog.text


# Zero frames after the filters is a skip, not a failure, and the fetched frames still go.
def test_zero_frames_is_skipped_not_failed(
	monkeypatch,
	caplog,
):
	events = patch_monthly_job(monkeypatch, lambda **kwargs: [])

	run_monthly(["Test-Camera"])

	assert events == ["release:Test-Camera"]
	assert "created=0 | skipped=1 | failed=0" in caplog.text


# The frames are unblurred, so they may only be removed after the video is built from them.
def test_release_runs_after_success(
	monkeypatch,
):
	events = patch_monthly_job(monkeypatch, lambda **kwargs: create_complete_monthly_images())

	run_monthly(["Test-Camera"])

	assert events == ["create:Test-Camera", "release:Test-Camera"]


# A failed video build must not leave the fetched frames behind.
def test_release_runs_when_the_video_build_raises(
	monkeypatch,
	caplog,
):
	events = patch_monthly_job(
		monkeypatch,
		lambda **kwargs: create_complete_monthly_images(),
		create_error=subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"]),
	)

	run_monthly(["Test-Camera"])

	assert events == ["create:Test-Camera", "release:Test-Camera"]
	assert "created=0 | skipped=0 | failed=1" in caplog.text


# A cleanup that fails is logged loudly and counted, but it must not stop the later cameras.
def test_release_error_is_logged_and_later_cameras_still_run(
	monkeypatch,
	caplog,
):
	events = patch_monthly_job(
		monkeypatch,
		lambda **kwargs: create_complete_monthly_images(),
		release_errors={"First-Camera": OSError("cannot remove the frame cache")},
	)

	run_monthly(["First-Camera", "Second-Camera"])

	assert events == [
		"create:First-Camera",
		"release:First-Camera",
		"create:Second-Camera",
		"release:Second-Camera",
	]
	assert "Could not remove fetched frames for camera: First-Camera" in caplog.text
	assert "| failed=1 |" in caplog.text
