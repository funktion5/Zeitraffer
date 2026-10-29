import subprocess
from datetime import date, time, timedelta
from pathlib import Path

from frame_source_fakes import RecordingFrameSource

import src.images as images_module
import src.jobs.yearly as yearly_module
from src.jobs.yearly import run_yearly_job
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

YEARLY_FRAMERATE = TEST_CONFIG["timelapse"]["yearly_framerate"]
TARGET_DATE = date(2026, 9, 17)
START_DATE = date(2025, 9, 18)


def create_complete_yearly_images() -> list[Path]:
	return [
		Path(f"camera_{current_date:%y-%m-%d}_12-00-00-00.jpg")
		for current_date in (START_DATE + timedelta(days=offset) for offset in range(365))
	]


# A Yearly must be created when every day in the 365-day window is covered.
def test_run_yearly_job_creates_video_with_complete_coverage(
	monkeypatch,
	caplog,
):
	interval_images = create_complete_yearly_images()

	selected_images = [
		Path("camera_25-09-18_11-55-00-00.jpg"),
		Path("camera_25-09-18_12-00-00-00.jpg"),
		Path("camera_25-09-18_12-05-00-00.jpg"),
	]

	selection_calls = []
	created_videos = []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	def fake_select_yearly_images_isolated(
		**kwargs,
	):
		selection_calls.append(kwargs)

		return selected_images

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/yearly/test.mp4")

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		fake_select_yearly_images_isolated,
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
		target_date=TARGET_DATE,
	)

	assert len(selection_calls) == 1
	assert selection_calls[0]["camera"] == "Test-Camera"
	assert selection_calls[0]["images"] == interval_images

	assert len(created_videos) == 1
	assert created_videos[0]["camera"] == "Test-Camera"
	assert created_videos[0]["target_date"] == TARGET_DATE
	assert created_videos[0]["images"] == selected_images
	assert created_videos[0]["timelapse_type"] == "yearly"
	assert created_videos[0]["framerate"] == YEARLY_FRAMERATE
	assert created_videos[0]["manual_run"] is False
	assert f"Found {len(interval_images)} selected interval images" in caplog.text


# A Yearly must not be created when no validated images exist.
def test_run_yearly_job_skips_camera_without_images(
	monkeypatch,
):
	selection_called = False
	created_videos = []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: [],
	)

	def fake_select_yearly_images_isolated(
		**kwargs,
	):
		nonlocal selection_called
		selection_called = True

		return []

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		fake_select_yearly_images_isolated,
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		lambda **kwargs: created_videos.append(kwargs),
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	assert selection_called is False
	assert created_videos == []


def run_yearly_with_missing_days(
	monkeypatch,
	missing_day_count: int,
) -> tuple[list[dict], list[bool]]:
	missing_dates = {START_DATE + timedelta(days=offset) for offset in range(missing_day_count)}
	missing_names = {missing.strftime("%y-%m-%d") for missing in missing_dates}
	interval_images = [
		image
		for image in create_complete_yearly_images()
		if image.name.split("_")[1] not in missing_names
	]
	selection_calls = []
	created_videos = []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	def fake_select_yearly_images_isolated(
		**kwargs,
	):
		selection_calls.append(True)

		return kwargs["images"]

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/yearly/test.mp4")

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		fake_select_yearly_images_isolated,
	)
	monkeypatch.setattr(yearly_module, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(
		yearly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: None,
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	return created_videos, selection_calls


# Exactly the configured minimum (300 of 365) still creates the video and logs the gap.
def test_run_yearly_job_creates_video_at_minimum_coverage(
	monkeypatch,
	caplog,
):
	created_videos, selection_calls = run_yearly_with_missing_days(
		monkeypatch,
		missing_day_count=65,
	)

	assert len(created_videos) == 1
	assert selection_calls == [True]
	assert len(created_videos[0]["images"]) == 300
	assert (
		"Yearly coverage partial: 300 of 365 days available (minimum 300) | "
		"missing: 2025-09-18 to 2025-11-21"
	) in caplog.text


# One day below the minimum must skip the camera before frame selection runs.
def test_run_yearly_job_skips_below_minimum_coverage(
	monkeypatch,
	caplog,
):
	created_videos, selection_calls = run_yearly_with_missing_days(
		monkeypatch,
		missing_day_count=66,
	)

	assert created_videos == []
	assert selection_calls == []
	assert (
		"Yearly coverage too low: 299 of 365 days available (minimum 300) - "
		"skipping camera: Test-Camera"
	) in caplog.text


# Historical runs use the same threshold as automatic ones.
def test_run_yearly_job_applies_minimum_to_historical_run(
	monkeypatch,
	caplog,
):
	interval_images = [
		image for image in create_complete_yearly_images() if "25-09-18" not in image.name
	]
	created_videos = []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)
	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/manual-runs/yearly/test.mp4")

	monkeypatch.setattr(yearly_module, "create_timelapse", fake_create_timelapse)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
		manual_run=True,
	)

	assert len(created_videos) == 1
	assert created_videos[0]["manual_run"] is True
	assert "Yearly coverage partial: 364 of 365 days available (minimum 300)" in caplog.text


# A Yearly selection that returns no usable frames must not create a video.
def test_run_yearly_job_skips_when_selection_returns_no_images(
	monkeypatch,
):
	interval_images = create_complete_yearly_images()

	created_videos = []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: [],
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		lambda **kwargs: created_videos.append(kwargs),
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	assert created_videos == []


# A failed camera must not stop later cameras from being processed.
def test_run_yearly_job_continues_after_camera_timeout(
	monkeypatch,
	caplog,
):
	interval_images = create_complete_yearly_images()

	processed_cameras = []
	created_videos = []

	def fake_find_interval_images_isolated(
		camera,
		**kwargs,
	):
		processed_cameras.append(camera)

		if camera == "Broken-Camera":
			raise TimeoutError("stalled")

		return interval_images

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
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=[
			"Broken-Camera",
			"Working-Camera",
		],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	assert processed_cameras == [
		"Broken-Camera",
		"Working-Camera",
	]

	assert len(created_videos) == 1
	assert created_videos[0]["camera"] == "Working-Camera"
	assert "created=1 | skipped=0 | failed=1" in caplog.text


# Complete coverage must be logged and must not emit the old partial-frame warning.
def test_run_yearly_job_logs_complete_coverage(
	monkeypatch,
	caplog,
):
	interval_images = create_complete_yearly_images()

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
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
		target_date=TARGET_DATE,
	)

	assert "Yearly coverage complete: 365 of 365 days" in caplog.text


# A leap-spanning window must report 366, not a hardcoded 365, confirming
# the dynamic day count actually reaches the log message.
def test_run_yearly_job_logs_complete_coverage_with_leap_year_366_days(
	monkeypatch,
	caplog,
):
	leap_target_date = date(2024, 12, 31)
	leap_start_date = date(2024, 1, 1)

	interval_images = [
		Path(f"camera_{current_date:%y-%m-%d}_12-00-00-00.jpg")
		for current_date in (leap_start_date + timedelta(days=offset) for offset in range(366))
	]

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
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
		target_date=leap_target_date,
	)

	assert "Yearly coverage complete: 366 of 366 days" in caplog.text
	assert "Yearly will be created with" not in caplog.text


# Yearly must request the exact rolling 365-day window from image discovery.
def test_run_yearly_job_uses_rolling_365_day_window(
	monkeypatch,
):
	captured_calls = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		captured_calls.append(kwargs)

		return []

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
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
		}
	]


# Historical Yearly runs must keep the explicit target date and manual output mode.
def test_run_yearly_job_uses_explicit_target_date(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		15,
	)

	start_date = date(
		2025,
		9,
		16,
	)

	interval_images = [
		Path(f"camera_{current_date:%y-%m-%d}_12-00-00-00.jpg")
		for current_date in (start_date + timedelta(days=offset) for offset in range(365))
	]

	interval_calls = []
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		interval_calls.append(kwargs)

		return interval_images

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Camera-A/manual-runs/yearly/test.mp4")

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=[
			"Camera-A",
		],
		framerate=YEARLY_FRAMERATE,
		target_date=target_date,
		manual_run=True,
	)

	assert interval_calls[0]["start_date"] == start_date
	assert interval_calls[0]["end_date"] == target_date

	assert created_videos[0]["target_date"] == target_date
	assert created_videos[0]["manual_run"] is True


# Automatic Yearly runs must clean up older automatic Yearly videos.
def test_run_yearly_job_cleans_automatic_retention(
	monkeypatch,
):
	interval_images = create_complete_yearly_images()

	video_path = Path("videos/Scheunenviertel/yearly/Scheunenviertel_2026-09-17.mp4")

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		lambda **kwargs: video_path,
	)

	retention_calls = []

	monkeypatch.setattr(
		yearly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
	)

	assert retention_calls == [
		{
			"camera": "Scheunenviertel",
			"timelapse_type": "yearly",
			"current_video": video_path,
		}
	]


# Historical Yearly runs must never clean up automatic Yearly videos.
def test_run_yearly_job_skips_retention_for_manual_run(
	monkeypatch,
):
	interval_images = create_complete_yearly_images()

	video_path = Path("videos/Scheunenviertel/manual-runs/yearly/Scheunenviertel_2026-09-17.mp4")

	monkeypatch.setattr(
		yearly_module,
		"find_interval_images_isolated",
		lambda **kwargs: interval_images,
	)

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		lambda **kwargs: kwargs["images"],
	)

	monkeypatch.setattr(
		yearly_module,
		"create_timelapse",
		lambda **kwargs: video_path,
	)

	retention_calls = []

	monkeypatch.setattr(
		yearly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
		manual_run=True,
	)

	assert retention_calls == []


# A historical override moves the scan window and names the video after it.
def test_run_yearly_job_applies_interval_window_override(
	monkeypatch,
):
	scan_calls = []
	created_videos = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		scan_calls.append(kwargs)

		return create_complete_yearly_images()

	def fake_create_timelapse(
		**kwargs,
	):
		created_videos.append(kwargs)

		return Path("videos/Test-Camera/manual-runs/yearly/test.mp4")

	monkeypatch.setattr(
		yearly_module, "find_interval_images_isolated", fake_find_interval_images_isolated
	)
	monkeypatch.setattr(yearly_module, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(
		yearly_module, "select_yearly_images_isolated", lambda **kwargs: kwargs["images"]
	)

	window = IntervalWindow(target=time(18, 30), tolerance_minutes=60)

	run_yearly_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
		target_date=TARGET_DATE,
		manual_run=True,
		interval_window=window,
	)

	assert scan_calls[0]["tolerance_minutes"] == 60
	assert set(scan_calls[0]["target_seconds_by_date"].values()) == {18 * 60 * 60 + 30 * 60}
	assert created_videos[0]["interval_window"] == window


# Sunset resolves a different centre per day from the configured location.
def test_run_yearly_job_resolves_sunset_per_day(
	monkeypatch,
):
	scan_calls = []

	def fake_find_interval_images_isolated(
		**kwargs,
	):
		scan_calls.append(kwargs)

		return []

	monkeypatch.setattr(
		yearly_module, "find_interval_images_isolated", fake_find_interval_images_isolated
	)

	config = {
		**TEST_CONFIG,
		"location": {
			"latitude": 52.472,
			"longitude": 9.333,
			"timezone": "Europe/Berlin",
		},
	}

	run_yearly_job(
		config=config,
		cameras=["Test-Camera"],
		framerate=YEARLY_FRAMERATE,
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


# Replace everything the Yearly job reaches outside itself and return the event log.
def patch_yearly_job(monkeypatch, find, create_error=None, release_errors=None):
	events = []

	def recording_find(camera, **kwargs):
		events.append(f"find:{camera}")

		return find(camera=camera, **kwargs)

	def fake_select_yearly_images_isolated(camera, images, **kwargs):
		events.append(f"select:{camera}")

		return images

	def fake_create_timelapse(camera, **kwargs):
		events.append(f"create:{camera}")

		if create_error is not None:
			raise create_error

		return Path(f"videos/{camera}/yearly/video.mp4")

	monkeypatch.setattr(yearly_module, "find_interval_images_isolated", recording_find)
	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		fake_select_yearly_images_isolated,
	)
	monkeypatch.setattr(yearly_module, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(yearly_module, "cleanup_automatic_video_retention", lambda **kwargs: None)
	monkeypatch.setattr(
		images_module,
		"get_frame_source",
		lambda: RecordingFrameSource(events, release_errors),
	)

	return events


def run_yearly(cameras):
	run_yearly_job(
		config=TEST_CONFIG,
		cameras=cameras,
		framerate=YEARLY_FRAMERATE,
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

		return create_complete_yearly_images()

	events = patch_yearly_job(monkeypatch, fake_find_interval_images_isolated)

	run_yearly(["Unreachable-Camera", "Working-Camera"])

	assert events == [
		"find:Unreachable-Camera",
		"release:Unreachable-Camera",
		"find:Working-Camera",
		"select:Working-Camera",
		"create:Working-Camera",
		"release:Working-Camera",
	]
	assert "created=1 | skipped=0 | failed=1" in caplog.text


# Zero frames after the filters is a skip, not a failure, and the fetched frames still go.
def test_zero_frames_is_skipped_not_failed(
	monkeypatch,
	caplog,
):
	events = patch_yearly_job(monkeypatch, lambda **kwargs: [])

	run_yearly(["Test-Camera"])

	assert events == ["find:Test-Camera", "release:Test-Camera"]
	assert "created=0 | skipped=1 | failed=0" in caplog.text


# The frames are unblurred, so they may only be removed after the video is built from them.
def test_release_runs_after_success(
	monkeypatch,
):
	events = patch_yearly_job(monkeypatch, lambda **kwargs: create_complete_yearly_images())

	run_yearly(["Test-Camera"])

	assert events == [
		"find:Test-Camera",
		"select:Test-Camera",
		"create:Test-Camera",
		"release:Test-Camera",
	]


# A failed video build must not leave the fetched frames behind.
def test_release_runs_when_the_video_build_raises(
	monkeypatch,
	caplog,
):
	events = patch_yearly_job(
		monkeypatch,
		lambda **kwargs: create_complete_yearly_images(),
		create_error=subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"]),
	)

	run_yearly(["Test-Camera"])

	assert events[-2:] == ["create:Test-Camera", "release:Test-Camera"]
	assert "created=0 | skipped=0 | failed=1" in caplog.text


# A cleanup that fails is logged loudly and counted, but it must not stop the later cameras.
def test_release_error_is_logged_and_later_cameras_still_run(
	monkeypatch,
	caplog,
):
	events = patch_yearly_job(
		monkeypatch,
		lambda **kwargs: create_complete_yearly_images(),
		release_errors={"First-Camera": OSError("cannot remove the frame cache")},
	)

	run_yearly(["First-Camera", "Second-Camera"])

	assert "release:First-Camera" in events
	assert events[-2:] == ["create:Second-Camera", "release:Second-Camera"]
	assert "Could not remove fetched frames for camera: First-Camera" in caplog.text
	assert "failed=1" in caplog.text


# The selection hashes the files, so it must read the paths the scan fetched, in one pass, and
# the frames must still be there: nothing is released between the scan and the selection.
def test_yearly_selection_reads_the_fetched_files(
	monkeypatch,
):
	fetched = create_complete_yearly_images()
	events = patch_yearly_job(monkeypatch, lambda **kwargs: fetched)

	def fake_select_yearly_images_isolated(camera, images, **kwargs):
		events.append(f"select:{camera}")
		assert images == fetched

		return images

	monkeypatch.setattr(
		yearly_module,
		"select_yearly_images_isolated",
		fake_select_yearly_images_isolated,
	)

	run_yearly(["Test-Camera"])

	assert events.count("find:Test-Camera") == 1
	assert events.index("select:Test-Camera") < events.index("release:Test-Camera")
