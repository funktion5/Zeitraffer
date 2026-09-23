import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import src.images as images_module
import src.jobs.weekly as weekly_module

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
	},
}


# Collect Daily-style images for every date in the Weekly window.
def test_collect_weekly_images_uses_daily_selection_for_seven_dates(
	monkeypatch,
):
	end_date = date(2026, 9, 16)
	start_date = date(2026, 9, 10)
	solar_calls = []
	image_calls = []

	def fake_get_sun_times(**kwargs):
		solar_calls.append(kwargs)

		target_date = kwargs["target_date"]

		return (
			datetime(target_date.year, target_date.month, target_date.day, 6, 30),
			datetime(target_date.year, target_date.month, target_date.day, 19, 30),
		)

	def fake_find_images_isolated(**kwargs):
		image_calls.append(kwargs)

		target_date = kwargs["target_date"]

		return [
			Path(f"Scheunenviertel_{target_date:%y-%m-%d}_18-00-00-00.jpg"),
			Path(f"Scheunenviertel_{target_date:%y-%m-%d}_07-00-00-00.jpg"),
		]

	monkeypatch.setattr(weekly_module, "get_sun_times", fake_get_sun_times)
	monkeypatch.setattr(weekly_module, "find_images_isolated", fake_find_images_isolated)

	duplicate_filter_calls = []

	def fake_filter_duplicate_images_isolated(**kwargs):
		duplicate_filter_calls.append(kwargs)

		return kwargs["images"]

	monkeypatch.setattr(
		weekly_module,
		"filter_duplicate_images_isolated",
		fake_filter_duplicate_images_isolated,
	)

	images, missing_dates = weekly_module.collect_weekly_images(
		camera="Scheunenviertel",
		end_date=end_date,
		location=TEST_CONFIG["location"],
		daylight_buffer_minutes=TEST_CONFIG["daylight_buffer_minutes"],
		stall_timeout_seconds=TEST_CONFIG["image_scan_stall_timeout_seconds"],
	)

	expected_dates = [start_date + timedelta(days=offset) for offset in range(7)]

	assert [call["target_date"] for call in solar_calls] == expected_dates
	assert [call["target_date"] for call in image_calls] == expected_dates
	assert all(call["latitude"] == 52.0 for call in solar_calls)
	assert all(call["longitude"] == 9.0 for call in solar_calls)
	assert all(call["timezone"] == "Europe/Berlin" for call in solar_calls)
	assert all(call["camera"] == "Scheunenviertel" for call in image_calls)
	assert all(call["daylight_buffer_minutes"] == 90 for call in image_calls)
	assert all(call["stall_timeout_seconds"] == 10 for call in image_calls)
	assert len(images) == 14
	assert images[0].name == "Scheunenviertel_26-09-10_07-00-00-00.jpg"
	assert images[-1].name == "Scheunenviertel_26-09-16_18-00-00-00.jpg"
	assert missing_dates == []
	assert duplicate_filter_calls == [
		{
			"camera": "Scheunenviertel",
			"images": images,
			"stall_timeout_seconds": 10,
		}
	]


# Report every date without usable images while keeping available frames.
def test_collect_weekly_images_reports_missing_dates(
	monkeypatch,
):
	missing = {
		date(2026, 9, 12),
		date(2026, 9, 15),
	}

	monkeypatch.setattr(
		weekly_module,
		"get_sun_times",
		lambda target_date, **kwargs: (
			datetime(target_date.year, target_date.month, target_date.day, 6, 30),
			datetime(target_date.year, target_date.month, target_date.day, 19, 30),
		),
	)

	monkeypatch.setattr(
		weekly_module,
		"find_images_isolated",
		lambda target_date, **kwargs: (
			[]
			if target_date in missing
			else [Path(f"Scheunenviertel_{target_date:%y-%m-%d}_12-00-00-00.jpg")]
		),
	)

	monkeypatch.setattr(
		weekly_module,
		"filter_duplicate_images_isolated",
		lambda camera, images, stall_timeout_seconds: images,
	)

	images, missing_dates = weekly_module.collect_weekly_images(
		camera="Scheunenviertel",
		end_date=date(2026, 9, 16),
		location=TEST_CONFIG["location"],
		daylight_buffer_minutes=90,
		stall_timeout_seconds=10,
	)

	assert len(images) == 5
	assert missing_dates == [
		date(2026, 9, 12),
		date(2026, 9, 15),
	]


# Coverage must be checked again after Weekly duplicate filtering.
def test_collect_weekly_images_reports_date_removed_by_duplicate_filtering(
	monkeypatch,
	tmp_path,
):
	monkeypatch.setattr(
		weekly_module,
		"get_sun_times",
		lambda target_date, **kwargs: (
			datetime(target_date.year, target_date.month, target_date.day, 6, 30),
			datetime(target_date.year, target_date.month, target_date.day, 19, 30),
		),
	)

	removed_date = date(2026, 9, 12)
	images_by_date = {}

	for offset in range(7):
		current_date = date(2026, 9, 10) + timedelta(days=offset)
		image_path = tmp_path / f"Scheunenviertel_{current_date:%y-%m-%d}_12-00-00-00.jpg"

		if current_date in {
			date(2026, 9, 11),
			removed_date,
		}:
			image_path.write_bytes(b"repeated camera frame")

		else:
			image_path.write_bytes(current_date.isoformat().encode())

		images_by_date[current_date] = image_path

	monkeypatch.setattr(
		weekly_module,
		"find_images_isolated",
		lambda target_date, **kwargs: [images_by_date[target_date]],
	)

	monkeypatch.setattr(
		weekly_module,
		"filter_duplicate_images_isolated",
		lambda camera, images, stall_timeout_seconds: images_module.filter_duplicate_images(
			camera=camera,
			images=images,
		),
	)

	images, missing_dates = weekly_module.collect_weekly_images(
		camera="Scheunenviertel",
		end_date=date(2026, 9, 16),
		location=TEST_CONFIG["location"],
		daylight_buffer_minutes=90,
		stall_timeout_seconds=10,
	)

	assert len(images) == 6
	assert missing_dates == [removed_date]


# Create a historical Weekly directly from a complete image sequence.
def test_create_manual_weekly_video_uses_collected_images(
	monkeypatch,
):
	end_date = date(2026, 9, 16)
	weekly_images = [
		Path("Scheunenviertel_26-09-10_07-00-00-00.jpg"),
		Path("Scheunenviertel_26-09-16_18-00-00-00.jpg"),
	]
	collection_calls = []

	def fake_collect_weekly_images(**kwargs):
		collection_calls.append(kwargs)

		return weekly_images, []

	monkeypatch.setattr(
		weekly_module,
		"collect_weekly_images",
		fake_collect_weekly_images,
	)

	timelapse_calls = []
	video_path = Path(
		"videos/Scheunenviertel/manual-runs/weekly/Scheunenviertel_2026-09-16.mp4"
	)

	def fake_create_timelapse(**kwargs):
		timelapse_calls.append(kwargs)

		return video_path

	monkeypatch.setattr(weekly_module, "create_timelapse", fake_create_timelapse)

	result = weekly_module.create_manual_weekly_video(
		config=TEST_CONFIG,
		camera="Scheunenviertel",
		end_date=end_date,
	)

	assert result == video_path
	assert collection_calls == [
		{
			"camera": "Scheunenviertel",
			"end_date": end_date,
			"location": TEST_CONFIG["location"],
			"daylight_buffer_minutes": 90,
			"stall_timeout_seconds": 10,
		}
	]
	assert timelapse_calls == [
		{
			"camera": "Scheunenviertel",
			"target_date": end_date,
			"images": weekly_images,
			"timelapse_type": "weekly",
			"framerate": 10,
			"manual_run": True,
		}
	]


# Skip a historical Weekly when any date has no usable images.
def test_create_manual_weekly_video_requires_complete_coverage(
	monkeypatch,
	caplog,
):
	missing_dates = [
		date(2026, 9, 12),
		date(2026, 9, 15),
	]

	monkeypatch.setattr(
		weekly_module,
		"collect_weekly_images",
		lambda **kwargs: ([Path("available.jpg")], missing_dates),
	)

	timelapse_called = False

	def fake_create_timelapse(**kwargs):
		nonlocal timelapse_called
		timelapse_called = True

	monkeypatch.setattr(weekly_module, "create_timelapse", fake_create_timelapse)

	result = weekly_module.create_manual_weekly_video(
		config=TEST_CONFIG,
		camera="Scheunenviertel",
		end_date=date(2026, 9, 16),
	)

	assert result is None
	assert timelapse_called is False
	assert "Missing Weekly image date: 2026-09-12" in caplog.text
	assert "Missing Weekly image date: 2026-09-15" in caplog.text
	assert "Weekly image coverage incomplete: 5 of 7 days available" in caplog.text


# Return exactly seven expected Daily paths for the rolling window.
def test_get_expected_weekly_video_paths(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	result = weekly_module.get_expected_weekly_video_paths(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == [
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-10.mp4"),
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-11.mp4"),
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-12.mp4"),
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-13.mp4"),
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-14.mp4"),
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-15.mp4"),
		(video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-16.mp4"),
	]


# Return all seven videos when the complete rolling window exists.
def test_get_weekly_daily_videos_returns_complete_window(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	expected_videos = []

	for day in range(
		10,
		17,
	):
		video = daily_directory / f"Scheunenviertel_2026-09-{day:02d}.mp4"

		video.touch()
		expected_videos.append(video)

	result = weekly_module.get_weekly_daily_videos(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == expected_videos


# Missing days must remain missing and must not be filled by older videos.
def test_get_weekly_daily_videos_keeps_gap(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	for day in [
		10,
		11,
		12,
		13,
		15,
		16,
	]:
		(daily_directory / f"Scheunenviertel_2026-09-{day:02d}.mp4").touch()

	older_video = daily_directory / "Scheunenviertel_2026-09-09.mp4"

	older_video.touch()

	result = weekly_module.get_weekly_daily_videos(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert len(result) == 6

	assert older_video not in result

	assert (daily_directory / "Scheunenviertel_2026-09-14.mp4") not in result


# Ignore Daily videos older than the rolling seven-day window.
def test_get_weekly_daily_videos_ignores_older_videos(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	older_video = daily_directory / "Scheunenviertel_2026-09-09.mp4"

	current_video = daily_directory / "Scheunenviertel_2026-09-16.mp4"

	older_video.touch()
	current_video.touch()

	result = weekly_module.get_weekly_daily_videos(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == [current_video]


# Return available Daily videos in chronological order.
def test_get_weekly_daily_videos_returns_chronological_order(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	video_16 = daily_directory / "Scheunenviertel_2026-09-16.mp4"

	video_10 = daily_directory / "Scheunenviertel_2026-09-10.mp4"

	video_13 = daily_directory / "Scheunenviertel_2026-09-13.mp4"

	video_16.touch()
	video_10.touch()
	video_13.touch()

	result = weekly_module.get_weekly_daily_videos(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == [
		video_10,
		video_13,
		video_16,
	]


# Ignore unrelated files inside the Daily directory.
def test_get_weekly_daily_videos_ignores_unrelated_files(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	valid_video = daily_directory / "Scheunenviertel_2026-09-16.mp4"

	valid_video.touch()

	(daily_directory / "random.mp4").touch()

	(daily_directory / "notes.txt").touch()

	result = weekly_module.get_weekly_daily_videos(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == [valid_video]


# Return missing Daily paths inside the rolling seven-day window.
def test_get_missing_weekly_video_paths(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	for day in [
		10,
		11,
		12,
		13,
		15,
		16,
	]:
		(daily_directory / f"Scheunenviertel_2026-09-{day:02d}.mp4").touch()

	result = weekly_module.get_missing_weekly_video_paths(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == [(daily_directory / "Scheunenviertel_2026-09-14.mp4")]


# Create a Weekly from the available Daily videos even when days are missing.
def test_create_automatic_weekly_video_uses_available_dailies(
	tmp_path: Path,
	monkeypatch,
	caplog,
):
	video_root = tmp_path / "videos"
	temp_root = tmp_path / "temp"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	monkeypatch.setattr(
		weekly_module,
		"get_video_path",
		lambda camera, target_date, timelapse_type, manual_run=False: (
			video_root / camera / timelapse_type / f"{camera}_{target_date.isoformat()}.mp4"
		),
	)

	monkeypatch.setattr(
		weekly_module,
		"TEMP_ROOT",
		temp_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	available_video = daily_directory / "Scheunenviertel_2026-09-16.mp4"

	available_video.touch()

	concat_calls = []

	def fake_create_concat_file(
		videos,
		temp_directory,
	):
		concat_calls.append(
			{
				"videos": videos,
				"temp_directory": temp_directory,
			}
		)

		return temp_directory / "concat.txt"

	monkeypatch.setattr(
		weekly_module,
		"create_concat_file",
		fake_create_concat_file,
	)

	output_path = video_root / "Scheunenviertel" / "weekly" / "Scheunenviertel_2026-09-16.mp4"

	concat_video_calls = []

	def fake_create_concat_video(
		concat_path,
		output_path,
	):
		concat_video_calls.append(
			{
				"concat_path": concat_path,
				"output_path": output_path,
			}
		)

		return output_path

	monkeypatch.setattr(
		weekly_module,
		"create_concat_video",
		fake_create_concat_video,
	)

	cleanup_calls = []

	monkeypatch.setattr(
		weekly_module,
		"cleanup_temp_directory",
		lambda temp_directory: cleanup_calls.append(temp_directory),
	)

	result = weekly_module.create_automatic_weekly_video(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	expected_temp_directory = temp_root / "Scheunenviertel" / "weekly" / "2026-09-16"

	assert result == output_path

	assert concat_calls == [
		{
			"videos": [available_video],
			"temp_directory": (expected_temp_directory),
		}
	]

	assert concat_video_calls == [
		{
			"concat_path": (expected_temp_directory / "concat.txt"),
			"output_path": output_path,
		}
	]

	assert cleanup_calls == [expected_temp_directory]

	assert "Weekly will be created with 1 of 7 Daily videos." in caplog.text


# Skip Weekly creation when no Daily videos are available.
def test_create_automatic_weekly_video_skips_when_no_dailies_exist(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"
	temp_root = tmp_path / "temp"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	monkeypatch.setattr(
		weekly_module,
		"TEMP_ROOT",
		temp_root,
	)

	concat_file_called = False
	concat_video_called = False

	def fake_create_concat_file(
		videos,
		temp_directory,
	):
		nonlocal concat_file_called
		concat_file_called = True

	def fake_create_concat_video(
		concat_path,
		output_path,
	):
		nonlocal concat_video_called
		concat_video_called = True

	monkeypatch.setattr(
		weekly_module,
		"create_concat_file",
		fake_create_concat_file,
	)

	monkeypatch.setattr(
		weekly_module,
		"create_concat_video",
		fake_create_concat_video,
	)

	result = weekly_module.create_automatic_weekly_video(
		camera="Scheunenviertel",
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result is None
	assert concat_file_called is False
	assert concat_video_called is False


# Keep Weekly temporary files when video creation fails.
def test_create_automatic_weekly_video_keeps_temp_on_error(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"
	temp_root = tmp_path / "temp"

	monkeypatch.setattr(
		weekly_module,
		"VIDEO_ROOT",
		video_root,
	)

	monkeypatch.setattr(
		weekly_module,
		"TEMP_ROOT",
		temp_root,
	)

	daily_directory = video_root / "Scheunenviertel" / "daily"

	daily_directory.mkdir(parents=True)

	(daily_directory / "Scheunenviertel_2026-09-16.mp4").touch()

	monkeypatch.setattr(
		weekly_module,
		"create_concat_file",
		lambda videos, temp_directory: temp_directory / "concat.txt",
	)

	def fake_create_concat_video(
		concat_path,
		output_path,
	):
		raise subprocess.CalledProcessError(
			returncode=1,
			cmd=["ffmpeg"],
		)

	monkeypatch.setattr(
		weekly_module,
		"create_concat_video",
		fake_create_concat_video,
	)

	cleanup_called = False

	def fake_cleanup_temp_directory(
		temp_directory,
	):
		nonlocal cleanup_called
		cleanup_called = True

	monkeypatch.setattr(
		weekly_module,
		"cleanup_temp_directory",
		fake_cleanup_temp_directory,
	)

	try:
		weekly_module.create_automatic_weekly_video(
			camera="Scheunenviertel",
			end_date=date(
				2026,
				9,
				16,
			),
		)

	except subprocess.CalledProcessError:
		pass

	assert cleanup_called is False


# Weekly jobs must process yesterday as the end of the rolling window.
def test_run_weekly_job_uses_yesterday(
	monkeypatch,
):
	class FakeDateTime:
		@classmethod
		def now(cls, tz=None):
			return datetime(
				2026,
				9,
				17,
				2,
				0,
				tzinfo=tz,
			)

	monkeypatch.setattr(
		weekly_module,
		"datetime",
		FakeDateTime,
	)

	weekly_calls = []

	def fake_create_automatic_weekly_video(
		camera,
		end_date,
	):
		weekly_calls.append({"camera": camera, "end_date": end_date})

		return Path(f"videos/{camera}/weekly/{camera}_weekly.mp4")

	monkeypatch.setattr(
		weekly_module,
		"create_automatic_weekly_video",
		fake_create_automatic_weekly_video,
	)

	weekly_module.run_weekly_job(
		config=TEST_CONFIG,
		cameras=[
			"Camera-A",
			"Camera-B",
		],
	)

	assert weekly_calls == [
		{
			"camera": "Camera-A",
			"end_date": date(
				2026,
				9,
				16,
			),
		},
		{
			"camera": "Camera-B",
			"end_date": date(
				2026,
				9,
				16,
			),
		},
	]


def test_run_weekly_job_uses_explicit_target_date(
	monkeypatch,
):
	target_date = date(
		2026,
		8,
		15,
	)

	weekly_calls = []

	def fake_create_automatic_weekly_video(
		camera,
		end_date,
	):
		weekly_calls.append(
			{
				"camera": camera,
				"end_date": end_date,
			}
		)

		return Path(f"videos/{camera}/weekly/{camera}_weekly.mp4")

	monkeypatch.setattr(
		weekly_module,
		"create_automatic_weekly_video",
		fake_create_automatic_weekly_video,
	)

	weekly_module.run_weekly_job(
		config=TEST_CONFIG,
		cameras=[
			"Camera-A",
			"Camera-B",
		],
		target_date=target_date,
	)

	assert weekly_calls == [
		{
			"camera": "Camera-A",
			"end_date": target_date,
		},
		{
			"camera": "Camera-B",
			"end_date": target_date,
		},
	]


# Automatic Weekly runs must clean up older automatic Weekly videos.
def test_run_weekly_job_cleans_automatic_retention(
	monkeypatch,
):
	video_path = Path("videos/Scheunenviertel/weekly/Scheunenviertel_2026-09-16.mp4")

	monkeypatch.setattr(
		weekly_module,
		"create_automatic_weekly_video",
		lambda **kwargs: video_path,
	)

	retention_calls = []

	monkeypatch.setattr(
		weekly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	weekly_module.run_weekly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		target_date=date(
			2026,
			9,
			16,
		),
	)

	assert retention_calls == [
		{
			"camera": "Scheunenviertel",
			"timelapse_type": "weekly",
			"current_video": video_path,
		}
	]


# Historical Weekly runs must never clean up automatic Weekly videos.
def test_run_weekly_job_skips_retention_for_manual_run(
	monkeypatch,
):
	video_path = Path("videos/Scheunenviertel/manual-runs/weekly/Scheunenviertel_2026-09-16.mp4")
	manual_weekly_calls = []

	def fake_create_manual_weekly_video(**kwargs):
		manual_weekly_calls.append(kwargs)

		return video_path

	monkeypatch.setattr(
		weekly_module,
		"create_manual_weekly_video",
		fake_create_manual_weekly_video,
	)

	automatic_weekly_called = False

	def fake_create_automatic_weekly_video(**kwargs):
		nonlocal automatic_weekly_called
		automatic_weekly_called = True

	monkeypatch.setattr(
		weekly_module,
		"create_automatic_weekly_video",
		fake_create_automatic_weekly_video,
	)

	retention_calls = []

	monkeypatch.setattr(
		weekly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	weekly_module.run_weekly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		target_date=date(
			2026,
			9,
			16,
		),
		manual_run=True,
	)

	assert manual_weekly_calls == [
		{
			"config": TEST_CONFIG,
			"camera": "Scheunenviertel",
			"end_date": date(2026, 9, 16),
		}
	]
	assert retention_calls == []
	assert automatic_weekly_called is False


# A stalled historical scan must not stop the next camera.
def test_run_manual_weekly_continues_after_scan_timeout(
	monkeypatch,
	caplog,
):
	collection_calls = []

	def fake_collect_weekly_images(camera, **kwargs):
		collection_calls.append(camera)

		if camera == "Camera-A":
			raise TimeoutError("Image scan stalled")

		return [Path("Camera-B_26-09-16_12-00-00-00.jpg")], []

	monkeypatch.setattr(
		weekly_module,
		"collect_weekly_images",
		fake_collect_weekly_images,
	)

	created_cameras = []

	def fake_create_timelapse(camera, **kwargs):
		created_cameras.append(camera)

		return Path(f"videos/{camera}/manual-runs/weekly/{camera}_2026-09-16.mp4")

	monkeypatch.setattr(weekly_module, "create_timelapse", fake_create_timelapse)

	retention_calls = []

	monkeypatch.setattr(
		weekly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	weekly_module.run_weekly_job(
		config=TEST_CONFIG,
		cameras=["Camera-A", "Camera-B"],
		target_date=date(2026, 9, 16),
		manual_run=True,
	)

	assert collection_calls == ["Camera-A", "Camera-B"]
	assert created_cameras == ["Camera-B"]
	assert retention_calls == []
	assert "Failed to process Weekly for camera: Camera-A" in caplog.text


# A historical FFmpeg failure must be logged without running retention.
def test_run_manual_weekly_handles_ffmpeg_error(
	monkeypatch,
	caplog,
):
	monkeypatch.setattr(
		weekly_module,
		"collect_weekly_images",
		lambda **kwargs: ([Path("Scheunenviertel_26-09-16_12-00-00-00.jpg")], []),
	)

	def fake_create_timelapse(**kwargs):
		raise subprocess.CalledProcessError(
			returncode=1,
			cmd=["ffmpeg"],
		)

	monkeypatch.setattr(weekly_module, "create_timelapse", fake_create_timelapse)

	retention_calls = []

	monkeypatch.setattr(
		weekly_module,
		"cleanup_automatic_video_retention",
		lambda **kwargs: retention_calls.append(kwargs),
	)

	weekly_module.run_weekly_job(
		config=TEST_CONFIG,
		cameras=["Scheunenviertel"],
		target_date=date(2026, 9, 16),
		manual_run=True,
	)

	assert retention_calls == []
	assert "Failed to process Weekly for camera: Scheunenviertel" in caplog.text
