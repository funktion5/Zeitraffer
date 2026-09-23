import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import src.jobs.daily as daily_module

TEST_CONFIG = {
	"location": {
		"latitude": 52.0,
		"longitude": 9.0,
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"image_scan_stall_timeout_seconds": 10,
	"timelapse": {
		"daily_framerate": 10,
		"manual_framerate": 10,
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
		daily_module,
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
		"find_images_isolated",
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
		daily_module,
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
		"find_images_isolated",
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
		daily_module,
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
		"find_images_isolated",
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
		daily_module,
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

	def fake_find_images_isolated(
		camera,
		**kwargs,
	):
		# Simulate one camera whose image scan stops making progress.
		if camera == "Stalled-Camera":
			raise TimeoutError("Image scan stalled")

		return images

	monkeypatch.setattr(
		daily_module,
		"find_images_isolated",
		fake_find_images_isolated,
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

	def fake_find_images_isolated(
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
		"find_images_isolated",
		fake_find_images_isolated,
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

	assert image_calls[0]["target_date"] == target_date
	assert image_calls[0]["remove_duplicates"] is True

	assert video_calls[0]["target_date"] == target_date

	assert retention_calls[0]["target_date"] == target_date
