import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from frame_source_fakes import RecordingFrameSource

import src.date_coverage as date_coverage_module
import src.images as images_module
import src.jobs.daily as daily_module
from src.image_worker import WorkerExitedError

TEST_CONFIG = {
	"location": {
		"latitude": 52.0,
		"longitude": 9.0,
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"automatic_daylight_buffer_minutes": {
		**{str(month): 30 for month in range(1, 13)},
		"4": 60,
		"5": 90,
		"6": 90,
		"7": 90,
		"8": 60,
	},
	"image_scan_stall_timeout_seconds": 10,
	"timelapse": {
		"daily_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}

DAILY_FRAMERATE = TEST_CONFIG["timelapse"]["daily_framerate"]

TEST_SUNRISE = datetime(
	2026,
	9,
	16,
	7,
	0,
	tzinfo=UTC,
)

TEST_SUNSET = datetime(
	2026,
	9,
	16,
	19,
	0,
	tzinfo=UTC,
)


# A daily job must create a timelapse for yesterday.
def test_run_daily_job_creates_yesterdays_timelapse(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		16,
	)

	images = [
		Path("image_1.jpg"),
		Path("image_2.jpg"),
	]

	class FakeDateTime:
		@classmethod
		def now(
			cls,
			tz=None,
		):
			return datetime(
				2026,
				9,
				17,
				2,
				0,
				tzinfo=tz,
			)

	monkeypatch.setattr(
		date_coverage_module,
		"datetime",
		FakeDateTime,
	)

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)

	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		lambda **kwargs: images,
	)

	create_timelapse_calls = []

	def fake_create_timelapse(
		camera,
		target_date,
		images,
		timelapse_type,
		framerate,
		manual_run=False,
		daylight_buffer_minutes=None,
		blur_people=False,
	):
		create_timelapse_calls.append(
			{
				"camera": camera,
				"target_date": target_date,
				"images": images,
				"timelapse_type": timelapse_type,
				"framerate": framerate,
				"manual_run": manual_run,
			}
		)

		return Path(f"videos/{camera}/{timelapse_type}/{camera}_{target_date.isoformat()}.mp4")

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		lambda **kwargs: None,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=[
			"Test-Camera",
		],
		framerate=DAILY_FRAMERATE,
	)

	assert create_timelapse_calls == [
		{
			"camera": "Test-Camera",
			"target_date": target_date,
			"images": images,
			"timelapse_type": "daily",
			"framerate": DAILY_FRAMERATE,
			"manual_run": False,
		}
	]


# Keep daily videos belonging to the rolling seven-day window.
def test_cleanup_daily_retention_keeps_seven_day_window(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		daily_module,
		"VIDEO_ROOT",
		video_root,
	)

	camera = "Scheunenviertel"

	target_date = date(
		2026,
		9,
		16,
	)

	daily_directory = video_root / camera / "daily"

	daily_directory.mkdir(parents=True)

	expected_dates = [
		date(
			2026,
			9,
			day,
		)
		for day in range(
			10,
			17,
		)
	]

	expected_videos = []

	for current_date in expected_dates:
		video = daily_directory / f"{camera}_{current_date.isoformat()}.mp4"

		video.write_bytes(b"daily video")

		expected_videos.append(video)

	outdated_video = daily_directory / f"{camera}_2026-09-09.mp4"

	outdated_video.write_bytes(b"outdated video")

	daily_module.cleanup_daily_retention(
		camera=camera,
		target_date=target_date,
	)

	assert all(video.exists() for video in expected_videos)

	assert not outdated_video.exists()


# Missing days must not cause older daily videos to remain as replacements.
def test_cleanup_daily_retention_does_not_fill_gaps(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		daily_module,
		"VIDEO_ROOT",
		video_root,
	)

	camera = "Scheunenviertel"

	target_date = date(
		2026,
		9,
		16,
	)

	daily_directory = video_root / camera / "daily"

	daily_directory.mkdir(parents=True)

	existing_dates = [
		date(
			2026,
			9,
			10,
		),
		date(
			2026,
			9,
			11,
		),
		date(
			2026,
			9,
			12,
		),
		date(
			2026,
			9,
			13,
		),
		date(
			2026,
			9,
			15,
		),
		date(
			2026,
			9,
			16,
		),
	]

	for current_date in existing_dates:
		(daily_directory / f"{camera}_{current_date.isoformat()}.mp4").write_bytes(b"daily video")

	older_video = daily_directory / f"{camera}_2026-09-09.mp4"

	older_video.write_bytes(b"older video")

	daily_module.cleanup_daily_retention(
		camera=camera,
		target_date=target_date,
	)

	assert not older_video.exists()

	remaining_videos = list(daily_directory.glob("*.mp4"))

	assert len(remaining_videos) == 6


# Retention must run after a daily video was created successfully.
def test_run_daily_job_cleans_up_retention_after_success(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		16,
	)

	images = [Path("image.jpg")]

	class FakeDateTime:
		@classmethod
		def now(
			cls,
			tz=None,
		):
			return datetime(
				2026,
				9,
				17,
				2,
				0,
				tzinfo=tz,
			)

	monkeypatch.setattr(
		date_coverage_module,
		"datetime",
		FakeDateTime,
	)

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)

	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		lambda **kwargs: images,
	)

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		lambda **kwargs: Path("videos/Scheunenviertel/daily/Scheunenviertel_2026-09-16.mp4"),
	)

	cleanup_calls = []

	def fake_cleanup_daily_retention(
		camera,
		target_date,
	):
		cleanup_calls.append(
			{
				"camera": camera,
				"target_date": target_date,
			}
		)

	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		fake_cleanup_daily_retention,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		framerate=DAILY_FRAMERATE,
	)

	assert cleanup_calls == [
		{
			"camera": "Scheunenviertel",
			"target_date": target_date,
		}
	]


# Retention must not run when daily video creation fails.
def test_run_daily_job_does_not_cleanup_retention_on_video_error(
	monkeypatch,
):
	images = [Path("image.jpg")]

	class FakeDateTime:
		@classmethod
		def now(
			cls,
			tz=None,
		):
			return datetime(
				2026,
				9,
				17,
				2,
				0,
				tzinfo=tz,
			)

	monkeypatch.setattr(
		date_coverage_module,
		"datetime",
		FakeDateTime,
	)

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)

	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		lambda **kwargs: images,
	)

	def fake_create_timelapse(
		**kwargs,
	):
		raise subprocess.CalledProcessError(
			returncode=1,
			cmd=["ffmpeg"],
		)

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	cleanup_called = False

	def fake_cleanup_daily_retention(
		camera,
		target_date,
	):
		nonlocal cleanup_called
		cleanup_called = True

	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		fake_cleanup_daily_retention,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		framerate=DAILY_FRAMERATE,
	)

	assert cleanup_called is False


# A stalled camera must not prevent later cameras from being processed.
def test_run_daily_job_continues_after_image_scan_timeout(
	monkeypatch,
	caplog,
):
	images = [Path("image.jpg")]

	class FakeDateTime:
		@classmethod
		def now(
			cls,
			tz=None,
		):
			return datetime(
				2026,
				9,
				17,
				2,
				0,
				tzinfo=tz,
			)

	monkeypatch.setattr(
		date_coverage_module,
		"datetime",
		FakeDateTime,
	)

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)

	def fake_find_daily_images_isolated(
		camera,
		**kwargs,
	):
		# Simulate one camera whose image scan stops making progress.
		if camera == "Stalled-Camera":
			raise TimeoutError("Image scan stalled")

		return images

	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		fake_find_daily_images_isolated,
	)

	created_cameras = []

	def fake_create_timelapse(
		camera,
		**kwargs,
	):
		created_cameras.append(camera)

		return Path(f"videos/{camera}/daily/video.mp4")

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		lambda **kwargs: None,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=[
			"Stalled-Camera",
			"Working-Camera",
		],
		framerate=DAILY_FRAMERATE,
	)

	assert created_cameras == ["Working-Camera"]
	assert "created=1 | skipped=0 | failed=1" in caplog.text


# A day containing only previous-day content must not replace a Daily video.
def test_run_daily_job_skips_when_reference_filter_removes_all_images(
	monkeypatch,
	caplog,
):
	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)
	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		lambda **kwargs: [],
	)
	monkeypatch.setattr(
		daily_module,
		"log_missing_images_diagnostic",
		lambda camera: None,
	)

	def fail_video_creation(**kwargs):
		raise AssertionError("video creation must be skipped")

	def fail_retention_cleanup(**kwargs):
		raise AssertionError("retention must be skipped")

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		fail_video_creation,
	)
	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		fail_retention_cleanup,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=["Test-Camera"],
		framerate=DAILY_FRAMERATE,
		target_date=date(2026, 9, 16),
	)

	assert "Found 0 images - skipping camera." in caplog.text
	assert "created=0 | skipped=1 | failed=0" in caplog.text


def test_run_daily_job_uses_explicit_target_date(
	monkeypatch,
):
	target_date = date(
		2026,
		8,
		15,
	)

	images = [Path("image.jpg")]

	sun_calls = []
	image_calls = []
	video_calls = []
	retention_calls = []

	def fake_get_sun_times(
		**kwargs,
	):
		sun_calls.append(kwargs)

		return (
			TEST_SUNRISE,
			TEST_SUNSET,
		)

	def fake_find_daily_images_isolated(
		**kwargs,
	):
		image_calls.append(kwargs)

		return images

	def fake_create_timelapse(
		**kwargs,
	):
		video_calls.append(kwargs)

		return Path("videos/Test-Camera/daily/test.mp4")

	def fake_cleanup_daily_retention(
		**kwargs,
	):
		retention_calls.append(kwargs)

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		fake_get_sun_times,
	)

	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		fake_find_daily_images_isolated,
	)

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		fake_cleanup_daily_retention,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=[
			"Test-Camera",
		],
		framerate=DAILY_FRAMERATE,
		target_date=target_date,
	)

	assert sun_calls[0]["target_date"] == target_date
	assert len(sun_calls) == 1

	assert image_calls[0]["target_date"] == target_date
	assert image_calls[0]["previous_date"] == date(2026, 8, 14)

	assert video_calls[0]["target_date"] == target_date

	assert retention_calls[0]["target_date"] == target_date


# Automatic runs take the buffer from the month table; historical runs keep the
# fixed value because it is embedded in their filename.
@pytest.mark.parametrize(
	("target_date", "manual_run", "expected_buffer"),
	[
		(date(2026, 4, 30), False, 60),
		(date(2026, 5, 1), False, 90),
		(date(2026, 8, 31), False, 60),
		(date(2026, 10, 8), False, 30),
		(date(2026, 10, 8), True, 90),
	],
)
def test_run_daily_job_selects_daylight_buffer_by_mode(
	monkeypatch,
	target_date,
	manual_run,
	expected_buffer,
):
	image_calls = []
	video_calls = []

	def fake_find_daily_images_isolated(
		**kwargs,
	):
		image_calls.append(kwargs)

		return [Path("image.jpg")]

	def fake_create_timelapse(
		**kwargs,
	):
		video_calls.append(kwargs)

		return Path("videos/Test-Camera/daily/test.mp4")

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)

	monkeypatch.setattr(
		daily_module,
		"find_daily_images_isolated",
		fake_find_daily_images_isolated,
	)

	monkeypatch.setattr(
		daily_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	monkeypatch.setattr(
		daily_module,
		"cleanup_daily_retention",
		lambda **kwargs: None,
	)

	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=[
			"Test-Camera",
		],
		framerate=DAILY_FRAMERATE,
		target_date=target_date,
		manual_run=manual_run,
	)

	assert image_calls[0]["daylight_buffer_minutes"] == expected_buffer

	# Only historical filenames carry the buffer suffix.
	assert video_calls[0]["daylight_buffer_minutes"] == (expected_buffer if manual_run else None)


# Replace everything the Daily job reaches outside itself and return the ordered event log.
def patch_daily_job(monkeypatch, find, create_error=None, release_errors=None):
	events = []

	def fake_create_timelapse(camera, **kwargs):
		events.append(f"create:{camera}")

		if create_error is not None:
			raise create_error

		return Path(f"videos/{camera}/daily/video.mp4")

	monkeypatch.setattr(
		daily_module,
		"get_sun_times",
		lambda **kwargs: (TEST_SUNRISE, TEST_SUNSET),
	)
	monkeypatch.setattr(daily_module, "find_daily_images_isolated", find)
	monkeypatch.setattr(daily_module, "log_missing_images_diagnostic", lambda camera: None)
	monkeypatch.setattr(daily_module, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(daily_module, "cleanup_daily_retention", lambda **kwargs: None)
	monkeypatch.setattr(
		images_module,
		"get_frame_source",
		lambda: RecordingFrameSource(events, release_errors),
	)

	return events


def run_daily(cameras):
	daily_module.run_daily_job(
		config=TEST_CONFIG,
		cameras=cameras,
		framerate=DAILY_FRAMERATE,
		target_date=date(2026, 9, 16),
	)


# A camera whose frames cannot be fetched counts as failed; the others still run and any
# partly fetched frames of the failed camera are removed.
def test_fetch_error_counts_as_failed_and_other_cameras_still_run(
	monkeypatch,
	caplog,
):
	def fake_find_daily_images_isolated(camera, **kwargs):
		# The worker forwards a failed fetch to the parent as a plain OSError.
		if camera == "Unreachable-Camera":
			raise OSError("rsync from the box failed")

		return [Path("image.jpg")]

	events = patch_daily_job(monkeypatch, fake_find_daily_images_isolated)

	run_daily(["Unreachable-Camera", "Working-Camera"])

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
	def fake_find_daily_images_isolated(camera, **kwargs):
		if camera == "Crashed-Camera":
			raise WorkerExitedError("Daily image scan worker exited unexpectedly")

		return [Path("image.jpg")]

	events = patch_daily_job(monkeypatch, fake_find_daily_images_isolated)

	run_daily(["Crashed-Camera", "Working-Camera"])

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
	events = patch_daily_job(monkeypatch, lambda **kwargs: [])

	run_daily(["Test-Camera"])

	assert events == ["release:Test-Camera"]
	assert "created=0 | skipped=1 | failed=0" in caplog.text


# The frames are unblurred, so they may only be removed after the video is built from them.
def test_release_runs_after_success(
	monkeypatch,
	caplog,
):
	events = patch_daily_job(monkeypatch, lambda **kwargs: [Path("image.jpg")])

	run_daily(["Test-Camera"])

	assert events == ["create:Test-Camera", "release:Test-Camera"]
	assert "created=1 | skipped=0 | failed=0" in caplog.text


# A failed video build must not leave the fetched frames behind.
def test_release_runs_when_the_video_build_raises(
	monkeypatch,
	caplog,
):
	events = patch_daily_job(
		monkeypatch,
		lambda **kwargs: [Path("image.jpg")],
		create_error=subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"]),
	)

	run_daily(["Test-Camera"])

	assert events == ["create:Test-Camera", "release:Test-Camera"]
	assert "created=0 | skipped=0 | failed=1" in caplog.text


# A cleanup that fails is logged loudly and counted, but it must not stop the later cameras.
def test_release_error_is_logged_and_later_cameras_still_run(
	monkeypatch,
	caplog,
):
	events = patch_daily_job(
		monkeypatch,
		lambda **kwargs: [Path("image.jpg")],
		release_errors={"First-Camera": OSError("cannot remove the frame cache")},
	)

	run_daily(["First-Camera", "Second-Camera"])

	assert events == [
		"create:First-Camera",
		"release:First-Camera",
		"create:Second-Camera",
		"release:Second-Camera",
	]
	assert "Could not remove fetched frames for camera: First-Camera" in caplog.text
	assert "| failed=1 |" in caplog.text


# ---- Blur gate: an automatic Daily of a blur camera is built from confirmed images only ----

BLUR_CAMERA = "Blur-Camera"
BLUR_CONFIG = {**TEST_CONFIG, "privacy": {"blur_cameras": [BLUR_CAMERA]}}


# One state file per camera and month, one JSON line per event, like blur_box.record_processed.
def write_blur_state(state_root: Path, camera: str, entries: list[dict]) -> None:
	path = state_root / camera / "2026-09.jsonl"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")


# Run one Daily for 2026-09-16 over the given images; return the event log and the images that
# reached the video build. entries None means the camera has no state at all.
def run_blur_daily(
	monkeypatch,
	tmp_path,
	images,
	entries,
	camera=BLUR_CAMERA,
	manual_run=False,
):
	state_root = tmp_path / "state"

	monkeypatch.setattr(daily_module, "BLUR_STATE_ROOT", state_root)

	if entries is not None:
		write_blur_state(state_root, camera, entries)

	events = patch_daily_job(monkeypatch, lambda **kwargs: images)
	built = []

	def fake_create_timelapse(camera, images, **kwargs):
		events.append(f"create:{camera}")
		built.append(images)

		return Path(f"videos/{camera}/daily/video.mp4")

	monkeypatch.setattr(daily_module, "create_timelapse", fake_create_timelapse)

	daily_module.run_daily_job(
		config=BLUR_CONFIG,
		cameras=[camera],
		framerate=DAILY_FRAMERATE,
		target_date=date(2026, 9, 16),
		manual_run=manual_run,
	)

	return events, built


# blurred, clean and night are confirmed; refused, replacing and no entry at all are not. The
# Daily is still built, from the confirmed images, and the left-out ones are named in the log.
def test_blur_camera_daily_is_built_from_confirmed_images_only(
	monkeypatch,
	tmp_path,
	caplog,
):
	images = [Path(f"{name}.jpg") for name in "abcdef"]
	entries = [
		{"image": "a.jpg", "status": "blurred"},
		{"image": "b.jpg", "status": "clean"},
		{"image": "c.jpg", "status": "night"},
		{"image": "d.jpg", "status": "refused", "reason": "detector failed"},
		{"image": "e.jpg", "status": "replacing"},
	]

	events, built = run_blur_daily(monkeypatch, tmp_path, images, entries)

	assert built == [images[:3]]
	assert events == [f"create:{BLUR_CAMERA}", f"release:{BLUR_CAMERA}"]
	assert "left out 3 of 6" in caplog.text
	assert all(name in caplog.text for name in ("d.jpg", "e.jpg", "f.jpg"))
	assert "created=1 | skipped=0 | failed=0" in caplog.text


# The last line of an image is the one that counts, like everywhere else in the blur state.
def test_blur_gate_last_state_line_wins(
	monkeypatch,
	tmp_path,
):
	images = [Path("a.jpg"), Path("b.jpg")]
	entries = [
		{"image": "a.jpg", "status": "refused"},
		{"image": "a.jpg", "status": "blurred"},
		{"image": "b.jpg", "status": "blurred"},
		{"image": "b.jpg", "status": "replacing"},
	]

	_, built = run_blur_daily(monkeypatch, tmp_path, images, entries)

	assert built == [[images[0]]]


# The state is keyed by file name; the fetched frames live in a folder of their own.
def test_blur_gate_matches_the_file_name_not_the_path(
	monkeypatch,
	tmp_path,
):
	images = [Path("temp/Blur-Camera/a.jpg")]

	entries = [{"image": "a.jpg", "status": "clean"}]

	_, built = run_blur_daily(monkeypatch, tmp_path, images, entries)

	assert built == [images]


# Nothing to report when every image is confirmed.
def test_blur_gate_is_silent_when_everything_is_confirmed(
	monkeypatch,
	tmp_path,
	caplog,
):
	images = [Path("a.jpg"), Path("b.jpg")]
	entries = [{"image": image.name, "status": "blurred"} for image in images]

	_, built = run_blur_daily(monkeypatch, tmp_path, images, entries)

	assert built == [images]
	assert "left out" not in caplog.text


# No confirmed image at all (the catch-up failed, or the camera has no state) is a skip, not a
# failure and not a video of unchecked frames; the fetched frames are still released.
@pytest.mark.parametrize(
	"entries",
	[
		None,
		[],
		[{"image": "a.jpg", "status": "refused"}, {"image": "b.jpg", "status": "replacing"}],
	],
)
def test_blur_gate_skips_the_camera_when_nothing_is_confirmed(
	monkeypatch,
	tmp_path,
	caplog,
	entries,
):
	images = [Path("a.jpg"), Path("b.jpg")]

	events, built = run_blur_daily(monkeypatch, tmp_path, images, entries)

	assert built == []
	assert events == [f"release:{BLUR_CAMERA}"]
	assert "created=0 | skipped=1 | failed=0" in caplog.text
	assert "left out 2 of 2" in caplog.text
	# This is not the "camera delivered no images" case.
	assert "Found 0 images" not in caplog.text


# Cameras without people are not gated and need no state.
def test_blur_gate_does_not_touch_other_cameras(
	monkeypatch,
	tmp_path,
):
	images = [Path("a.jpg"), Path("b.jpg")]

	events, built = run_blur_daily(monkeypatch, tmp_path, images, None, camera="Plain-Camera")

	assert built == [images]
	assert events == ["create:Plain-Camera", "release:Plain-Camera"]


# A historical run goes to manual-runs, not public, and is exempt from the gate.
def test_blur_gate_does_not_apply_to_historical_runs(
	monkeypatch,
	tmp_path,
):
	images = [Path("a.jpg"), Path("b.jpg")]

	_, built = run_blur_daily(monkeypatch, tmp_path, images, None, manual_run=True)

	assert built == [images]
