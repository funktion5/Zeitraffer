import subprocess
from datetime import date, time
from pathlib import Path

import pytest

import src.video as video_module
from src.interval_window import SUNSET, IntervalWindow
from src.privacy.anonymize import PrivacyCheckError, parse_drop_rules
from src.video import (
	cleanup_temp_directory,
	copy_images_to_temp,
	create_concat_file,
	create_concat_video,
	create_image_timelapse,
	create_temp_directory,
	create_timelapse,
	cleanup_automatic_video_retention,
	get_video_path,
	x264_preset_arguments,
)

COMPLETE_JPEG = b"\xff\xd8 test image \xff\xd9"


# A manual/historical video embeds its daylight buffer so two runs for the
# same date but different buffers don't overwrite each other.
def test_get_video_path_embeds_buffer_only_for_manual_run():
	manual_path = get_video_path(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		timelapse_type="weekly",
		manual_run=True,
		daylight_buffer_minutes=60,
	)

	assert manual_path == Path(
		"videos/Scheunenviertel/manual-runs/weekly/Scheunenviertel_2026-09-14_60min.mp4"
	)


# Automatic videos must never embed the buffer, even if one is passed.
def test_get_video_path_ignores_buffer_for_automatic_run():
	automatic_path = get_video_path(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		timelapse_type="weekly",
		manual_run=False,
		daylight_buffer_minutes=60,
	)

	assert automatic_path == Path("videos/Scheunenviertel/weekly/Scheunenviertel_2026-09-14.mp4")


# A manual video without an explicit buffer keeps the pre-existing filename.
def test_get_video_path_manual_run_without_buffer_omits_suffix():
	manual_path = get_video_path(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		timelapse_type="daily",
		manual_run=True,
	)

	assert manual_path == Path(
		"videos/Scheunenviertel/manual-runs/daily/Scheunenviertel_2026-09-14.mp4"
	)


# Monthly/Yearly never use a daylight buffer; this must be a structural
# guarantee of get_video_path() itself, not just something call sites happen
# to respect today, so a future caller can't silently produce a mismatched
# filename.
@pytest.mark.parametrize("timelapse_type", ["monthly", "yearly"])
def test_get_video_path_rejects_buffer_for_monthly_and_yearly(timelapse_type):
	with pytest.raises(ValueError, match="does not use a daylight buffer"):
		get_video_path(
			camera="Scheunenviertel",
			target_date=date(2026, 9, 14),
			timelapse_type=timelapse_type,
			manual_run=True,
			daylight_buffer_minutes=60,
		)


# Copy source images into a normalized sequential frame structure.
def test_copy_images_to_temp(tmp_path: Path):
	source_directory = tmp_path / "source"
	temp_directory = tmp_path / "temp"

	source_directory.mkdir()
	temp_directory.mkdir()

	images = []

	for index in range(3):
		image = source_directory / f"image_{index}.jpg"
		image.write_bytes(COMPLETE_JPEG)
		images.append(image)

	copied_images = copy_images_to_temp(
		images,
		temp_directory,
	)

	assert [original for original, _ in copied_images] == images
	assert [frame.name for _, frame in copied_images] == [
		"frame_000001.jpg",
		"frame_000002.jpg",
		"frame_000003.jpg",
	]

	assert all(frame.exists() for _, frame in copied_images)


# A cut-off camera upload is left out and the frame numbers stay gapless for FFmpeg.
def test_copy_images_to_temp_skips_truncated_images(tmp_path: Path):
	source_directory = tmp_path / "source"
	temp_directory = tmp_path / "temp"

	source_directory.mkdir()
	temp_directory.mkdir()

	contents = [COMPLETE_JPEG, b"\xff\xd8 cut off \xf9\xe3", COMPLETE_JPEG, b"\xd9"]
	images = []

	for index, content in enumerate(contents):
		image = source_directory / f"image_{index}.jpg"
		image.write_bytes(content)
		images.append(image)

	copied_images = copy_images_to_temp(
		images,
		temp_directory,
	)

	assert copied_images == [
		(images[0], temp_directory / "frame_000001.jpg"),
		(images[2], temp_directory / "frame_000002.jpg"),
	]
	assert sorted(path.name for path in temp_directory.iterdir()) == [
		"frame_000001.jpg",
		"frame_000002.jpg",
	]
	assert images[1].exists()


# Nothing left to encode is a per-camera error, not an empty or broken video.
def test_copy_images_to_temp_raises_when_every_image_is_truncated(tmp_path: Path):
	image = tmp_path / "image.jpg"
	image.write_bytes(b"\xff\xd8 cut off")

	with pytest.raises(OSError, match="No complete images"):
		copy_images_to_temp(
			[image],
			tmp_path,
		)


# Recreate an existing temp directory so no old frames survive a new run.
def test_create_temp_directory_removes_old_content(
	tmp_path: Path,
	monkeypatch,
):
	temp_root = tmp_path / "temp"

	monkeypatch.setattr(
		video_module,
		"TEMP_ROOT",
		temp_root,
	)

	old_directory = temp_root / "Scheunenviertel" / "2026-09-14"

	old_directory.mkdir(parents=True)

	old_file = old_directory / "frame_000001.jpg"

	old_file.write_bytes(b"old image")

	temp_directory = create_temp_directory(
		"Scheunenviertel",
		date(2026, 9, 14),
	)

	assert temp_directory.exists()
	assert temp_directory.is_dir()
	assert not old_file.exists()
	assert list(temp_directory.iterdir()) == []


# Remove the complete temporary working directory after a successful run.
def test_cleanup_temp_directory(
	tmp_path: Path,
):
	temp_directory = tmp_path / "Scheunenviertel" / "2026-09-14"

	temp_directory.mkdir(parents=True)

	frame = temp_directory / "frame_000001.jpg"

	frame.write_bytes(b"test image")

	cleanup_temp_directory(temp_directory)

	assert not temp_directory.exists()


# Create video safely and replace the final output only after FFmpeg succeeds.
def test_create_image_timelapse_uses_prefixed_output_path(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"
	temp_directory = tmp_path / "temp"

	temp_directory.mkdir()

	monkeypatch.setattr(
		video_module,
		"VIDEO_ROOT",
		video_root,
	)

	expected_output = video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-14.mp4"

	temporary_output = (
		expected_output.parent / f".{expected_output.stem}.tmp{expected_output.suffix}"
	)

	popen_calls = []

	class FakeProcess:
		pid = 12345

		def __init__(self, command, stderr=None):
			popen_calls.append(command)
			self.poll_calls = 0

		def poll(self):
			self.poll_calls += 1

			if self.poll_calls == 1:
				return None

			return 0

		def wait(self):
			temporary_output.write_bytes(b"new video")

			return 0

	monkeypatch.setattr(
		video_module.subprocess,
		"Popen",
		FakeProcess,
	)

	class FakeMemoryInfo:
		rss = 50 * 1024 * 1024

	class FakePsutilProcess:
		def __init__(self, pid):
			self.pid = pid

		def cpu_percent(
			self,
			interval=None,
		):
			return 125.0

		def memory_info(self):
			return FakeMemoryInfo()

	monkeypatch.setattr(
		video_module.psutil,
		"Process",
		FakePsutilProcess,
	)

	monkeypatch.setattr(
		video_module.psutil,
		"cpu_percent",
		lambda: 42.0,
	)

	class FakeVirtualMemory:
		percent = 35.0

	monkeypatch.setattr(
		video_module.psutil,
		"virtual_memory",
		lambda: FakeVirtualMemory(),
	)

	monkeypatch.setattr(
		video_module.time,
		"sleep",
		lambda seconds: None,
	)

	result = create_image_timelapse(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		temp_directory=temp_directory,
		timelapse_type="daily",
		framerate=10,
	)

	assert result == expected_output
	assert expected_output.exists()
	assert expected_output.read_bytes() == b"new video"
	assert not temporary_output.exists()

	assert popen_calls == [
		[
			"ffmpeg",
			"-y",
			"-framerate",
			"10",
			"-i",
			str(temp_directory / "frame_%06d.jpg"),
			"-c:v",
			"libx264",
			"-threads",
			"2",
			"-pix_fmt",
			"yuv420p",
			str(temporary_output),
		]
	]


def test_x264_preset_is_not_set_by_default(monkeypatch):
	monkeypatch.delenv("TIMELAPSE_X264_PRESET", raising=False)

	assert x264_preset_arguments() == []


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_x264_preset_counts_as_unset(monkeypatch, value):
	monkeypatch.setenv("TIMELAPSE_X264_PRESET", value)

	assert x264_preset_arguments() == []


def test_x264_preset_comes_from_the_environment(monkeypatch):
	monkeypatch.setenv("TIMELAPSE_X264_PRESET", "ultrafast")

	assert x264_preset_arguments() == ["-preset", "ultrafast"]


# A typo must stop the encode instead of silently producing a different video.
def test_unknown_x264_preset_is_refused(monkeypatch):
	monkeypatch.setenv("TIMELAPSE_X264_PRESET", "ultrafst")

	with pytest.raises(ValueError, match="TIMELAPSE_X264_PRESET"):
		x264_preset_arguments()


# The preset goes right after the codec, and without it the command stays exactly as before.
@pytest.mark.parametrize(
	("preset", "expected"),
	[(None, []), ("ultrafast", ["-preset", "ultrafast"])],
)
def test_image_timelapse_command_carries_the_preset(tmp_path: Path, monkeypatch, preset, expected):
	if preset is None:
		monkeypatch.delenv("TIMELAPSE_X264_PRESET", raising=False)
	else:
		monkeypatch.setenv("TIMELAPSE_X264_PRESET", preset)

	captured = {}

	def fake_encode_video(ffmpeg_arguments, output_path, description):
		captured["arguments"] = ffmpeg_arguments

		return output_path

	monkeypatch.setattr(video_module, "encode_video", fake_encode_video)
	monkeypatch.setattr(video_module, "VIDEO_ROOT", tmp_path / "videos")

	create_image_timelapse(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		temp_directory=tmp_path / "temp",
		timelapse_type="daily",
		framerate=10,
	)

	arguments = captured["arguments"]
	codec_index = arguments.index("libx264")

	assert arguments[codec_index + 1 : codec_index + 1 + len(expected)] == expected
	assert arguments[codec_index + 1 + len(expected)] == "-threads"


# A failed image timelapse must preserve the existing working output.
def test_create_image_timelapse_keeps_existing_output_on_error(
	tmp_path: Path,
	monkeypatch,
	caplog,
):
	video_root = tmp_path / "videos"
	temp_directory = tmp_path / "temp"

	temp_directory.mkdir()

	monkeypatch.setattr(
		video_module,
		"VIDEO_ROOT",
		video_root,
	)

	output_path = video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-14.mp4"

	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	output_path.write_bytes(b"old working daily")

	class FakeProcess:
		pid = 12345

		def __init__(self, command, stderr=None):
			self.command = command
			stderr.write(b"Invalid image data found when processing input\n")

		def poll(self):
			return 1

		def wait(self):
			return 1

	monkeypatch.setattr(
		video_module.subprocess,
		"Popen",
		FakeProcess,
	)

	monkeypatch.setattr(
		video_module.psutil,
		"Process",
		lambda pid: None,
	)

	with pytest.raises(
		subprocess.CalledProcessError,
	):
		create_image_timelapse(
			camera="Scheunenviertel",
			target_date=date(2026, 9, 14),
			temp_directory=temp_directory,
			timelapse_type="daily",
			framerate=10,
		)

	assert output_path.exists()
	assert output_path.read_bytes() == b"old working daily"
	assert "FFmpeg failed with exit code 1" in caplog.text
	assert "Invalid image data found when processing input" in caplog.text


# Run the complete image-based timelapse workflow in the expected order.
def test_create_timelapse(
	tmp_path: Path,
	monkeypatch,
):
	images = [
		tmp_path / "image_1.jpg",
		tmp_path / "image_2.jpg",
	]

	temp_directory = tmp_path / "temp"

	video_path = (
		tmp_path / "videos" / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-14.mp4"
	)

	calls = []

	def fake_create_temp_directory(
		camera,
		target_date,
	):
		calls.append("create_temp_directory")

		return temp_directory

	def fake_copy_images_to_temp(
		images,
		temp_directory,
	):
		calls.append("copy_images_to_temp")

		return []

	def fake_create_image_timelapse(
		camera,
		target_date,
		temp_directory,
		timelapse_type,
		framerate,
		manual_run=False,
		daylight_buffer_minutes=None,
		interval_window=None,
		blur_people=False,
	):
		calls.append("create_image_timelapse")

		return video_path

	def fake_cleanup_temp_directory(
		temp_directory,
	):
		calls.append("cleanup_temp_directory")

	monkeypatch.setattr(
		video_module,
		"create_temp_directory",
		fake_create_temp_directory,
	)

	monkeypatch.setattr(
		video_module,
		"copy_images_to_temp",
		fake_copy_images_to_temp,
	)

	monkeypatch.setattr(
		video_module,
		"create_image_timelapse",
		fake_create_image_timelapse,
	)

	monkeypatch.setattr(
		video_module,
		"cleanup_temp_directory",
		fake_cleanup_temp_directory,
	)

	result = create_timelapse(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		images=images,
		timelapse_type="daily",
		framerate=10,
	)

	assert calls == [
		"create_temp_directory",
		"copy_images_to_temp",
		"create_image_timelapse",
		"cleanup_temp_directory",
	]

	assert result == video_path


# Keep temporary files available for debugging after video creation fails.
def test_create_timelapse_keeps_temp_on_video_error(
	tmp_path: Path,
	monkeypatch,
):
	temp_directory = tmp_path / "temp"

	cleanup_called = False

	def fake_create_temp_directory(
		camera,
		target_date,
	):
		return temp_directory

	def fake_copy_images_to_temp(
		images,
		temp_directory,
	):
		return []

	def fake_create_image_timelapse(
		camera,
		target_date,
		temp_directory,
		timelapse_type,
		framerate,
		manual_run=False,
		daylight_buffer_minutes=None,
		interval_window=None,
		blur_people=False,
	):
		raise subprocess.CalledProcessError(
			returncode=1,
			cmd=["ffmpeg"],
		)

	def fake_cleanup_temp_directory(
		temp_directory,
	):
		nonlocal cleanup_called
		cleanup_called = True

	monkeypatch.setattr(
		video_module,
		"create_temp_directory",
		fake_create_temp_directory,
	)

	monkeypatch.setattr(
		video_module,
		"copy_images_to_temp",
		fake_copy_images_to_temp,
	)

	monkeypatch.setattr(
		video_module,
		"create_image_timelapse",
		fake_create_image_timelapse,
	)

	monkeypatch.setattr(
		video_module,
		"cleanup_temp_directory",
		fake_cleanup_temp_directory,
	)

	with pytest.raises(
		subprocess.CalledProcessError,
	):
		create_timelapse(
			camera="Scheunenviertel",
			target_date=date(2026, 9, 14),
			images=[],
			timelapse_type="daily",
			framerate=10,
		)

	assert cleanup_called is False


# Create an FFmpeg concat file containing videos in the supplied order.
def test_create_concat_file(
	tmp_path: Path,
):
	temp_directory = tmp_path / "concat"

	videos = [
		tmp_path / "video_1.mp4",
		tmp_path / "video_2.mp4",
		tmp_path / "video_3.mp4",
	]

	for video in videos:
		video.touch()

	concat_path = create_concat_file(
		videos=videos,
		temp_directory=temp_directory,
	)

	assert concat_path == (temp_directory / "concat.txt")

	assert concat_path.read_text(
		encoding="utf-8",
	) == (
		f"file '{videos[0].resolve()}'\n"
		f"file '{videos[1].resolve()}'\n"
		f"file '{videos[2].resolve()}'\n"
	)


# Create a concat video and replace the target only after FFmpeg succeeds.
def test_create_concat_video(
	tmp_path: Path,
	monkeypatch,
):
	concat_path = tmp_path / "concat.txt"

	concat_path.touch()

	output_path = tmp_path / "videos" / "Scheunenviertel" / "weekly" / "Scheunenviertel_weekly.mp4"

	temporary_output = output_path.parent / f".{output_path.stem}.tmp{output_path.suffix}"

	popen_calls = []

	class FakeProcess:
		pid = 12345

		def __init__(self, command, stderr=None):
			popen_calls.append(command)
			self.poll_calls = 0

		def poll(self):
			self.poll_calls += 1

			if self.poll_calls == 1:
				return None

			return 0

		def wait(self):
			temporary_output.write_bytes(b"new weekly video")

			return 0

	monkeypatch.setattr(
		video_module.subprocess,
		"Popen",
		FakeProcess,
	)

	class FakeMemoryInfo:
		rss = 50 * 1024 * 1024

	class FakePsutilProcess:
		def __init__(self, pid):
			self.pid = pid

		def cpu_percent(
			self,
			interval=None,
		):
			return 120.0

		def memory_info(self):
			return FakeMemoryInfo()

	monkeypatch.setattr(
		video_module.psutil,
		"Process",
		FakePsutilProcess,
	)

	monkeypatch.setattr(
		video_module.psutil,
		"cpu_percent",
		lambda: 25.0,
	)

	class FakeVirtualMemory:
		percent = 40.0

	monkeypatch.setattr(
		video_module.psutil,
		"virtual_memory",
		lambda: FakeVirtualMemory(),
	)

	monkeypatch.setattr(
		video_module.time,
		"sleep",
		lambda seconds: None,
	)

	result = create_concat_video(
		concat_path=concat_path,
		output_path=output_path,
	)

	assert result == output_path
	assert output_path.exists()

	assert output_path.read_bytes() == b"new weekly video"

	assert not temporary_output.exists()

	assert popen_calls == [
		[
			"ffmpeg",
			"-y",
			"-f",
			"concat",
			"-safe",
			"0",
			"-i",
			str(concat_path),
			"-c",
			"copy",
			str(temporary_output),
		]
	]


# A failed concat must preserve the existing working output.
def test_create_concat_video_keeps_existing_output_on_error(
	tmp_path: Path,
	monkeypatch,
):
	concat_path = tmp_path / "concat.txt"

	concat_path.touch()

	output_path = tmp_path / "videos" / "Scheunenviertel" / "weekly" / "Scheunenviertel_weekly.mp4"

	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	output_path.write_bytes(b"old working weekly")

	class FakeProcess:
		pid = 12345

		def __init__(self, command, stderr=None):
			self.command = command

		def poll(self):
			return 1

		def wait(self):
			return 1

	monkeypatch.setattr(
		video_module.subprocess,
		"Popen",
		FakeProcess,
	)

	monkeypatch.setattr(
		video_module.psutil,
		"Process",
		lambda pid: None,
	)

	with pytest.raises(
		subprocess.CalledProcessError,
	):
		create_concat_video(
			concat_path=concat_path,
			output_path=output_path,
		)

	assert output_path.exists()

	assert output_path.read_bytes() == b"old working weekly"


# Automatic retention must keep only the newly created video.
def test_cleanup_automatic_video_retention_keeps_current_video(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		video_module,
		"VIDEO_ROOT",
		video_root,
	)

	video_directory = video_root / "Scheunenviertel" / "monthly"

	video_directory.mkdir(parents=True)

	old_video = video_directory / "Scheunenviertel_2026-09-20.mp4"
	current_video = video_directory / "Scheunenviertel_2026-09-21.mp4"

	old_video.touch()
	current_video.touch()

	cleanup_automatic_video_retention(
		camera="Scheunenviertel",
		timelapse_type="monthly",
		current_video=current_video,
	)

	assert not old_video.exists()
	assert current_video.exists()


# Automatic retention must remove every older matching video.
def test_cleanup_automatic_video_retention_removes_multiple_old_videos(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		video_module,
		"VIDEO_ROOT",
		video_root,
	)

	video_directory = video_root / "Scheunenviertel" / "yearly"

	video_directory.mkdir(parents=True)

	old_videos = [
		video_directory / "Scheunenviertel_2024-09-21.mp4",
		video_directory / "Scheunenviertel_2025-09-21.mp4",
	]

	current_video = video_directory / "Scheunenviertel_2026-09-21.mp4"

	for video in old_videos:
		video.touch()

	current_video.touch()

	cleanup_automatic_video_retention(
		camera="Scheunenviertel",
		timelapse_type="yearly",
		current_video=current_video,
	)

	assert all(not video.exists() for video in old_videos)
	assert current_video.exists()


# Automatic retention must ignore unrelated files and manual-run directories.
def test_cleanup_automatic_video_retention_ignores_unrelated_files(
	tmp_path: Path,
	monkeypatch,
):
	video_root = tmp_path / "videos"

	monkeypatch.setattr(
		video_module,
		"VIDEO_ROOT",
		video_root,
	)

	video_directory = video_root / "Scheunenviertel" / "weekly"
	manual_directory = video_root / "Scheunenviertel" / "manual-runs" / "weekly"

	video_directory.mkdir(parents=True)
	manual_directory.mkdir(parents=True)

	current_video = video_directory / "Scheunenviertel_2026-09-21.mp4"
	unrelated_file = video_directory / "notes.txt"
	manual_video = manual_directory / "Scheunenviertel_2026-08-01.mp4"

	current_video.touch()
	unrelated_file.touch()
	manual_video.touch()

	cleanup_automatic_video_retention(
		camera="Scheunenviertel",
		timelapse_type="weekly",
		current_video=current_video,
	)

	assert current_video.exists()
	assert unrelated_file.exists()
	assert manual_video.exists()


# A historical Monthly/Yearly with a custom window must not overwrite the default video.
@pytest.mark.parametrize("timelapse_type", ["monthly", "yearly"])
def test_get_video_path_embeds_interval_window_for_manual_run(timelapse_type):
	fixed_path = get_video_path(
		camera="Cam",
		target_date=date(2025, 6, 30),
		timelapse_type=timelapse_type,
		manual_run=True,
		interval_window=IntervalWindow(target=time(18, 30), tolerance_minutes=60),
	)
	sunset_path = get_video_path(
		camera="Cam",
		target_date=date(2025, 6, 30),
		timelapse_type=timelapse_type,
		manual_run=True,
		interval_window=IntervalWindow(target=SUNSET, tolerance_minutes=45),
	)

	assert fixed_path == Path(
		f"videos/Cam/manual-runs/{timelapse_type}/Cam_2025-06-30_1830-60min.mp4"
	)
	assert sunset_path == Path(
		f"videos/Cam/manual-runs/{timelapse_type}/Cam_2025-06-30_sunset-45min.mp4"
	)


def test_get_video_path_rejects_interval_window_for_automatic_run():
	with pytest.raises(ValueError, match="only allowed for manual runs"):
		get_video_path(
			camera="Cam",
			target_date=date(2025, 6, 30),
			timelapse_type="monthly",
			manual_run=False,
			interval_window=IntervalWindow(target=time(18, 30), tolerance_minutes=60),
		)


@pytest.mark.parametrize("timelapse_type", ["daily", "weekly"])
def test_get_video_path_rejects_interval_window_for_daily_and_weekly(timelapse_type):
	with pytest.raises(ValueError, match="does not use an interval window"):
		get_video_path(
			camera="Cam",
			target_date=date(2025, 6, 30),
			timelapse_type=timelapse_type,
			manual_run=True,
			interval_window=IntervalWindow(target=time(18, 30), tolerance_minutes=60),
		)


# A blurred video must never share a name with an unblurred one.
def test_get_video_path_adds_blur_suffix_for_manual_daily():
	path = get_video_path(
		camera="SLSV",
		target_date=date(2026, 6, 28),
		timelapse_type="daily",
		manual_run=True,
		daylight_buffer_minutes=60,
		blur_people=True,
	)

	assert path == Path("videos/SLSV/manual-runs/daily/SLSV_2026-06-28_60min_blur.mp4")


# The calendar-year backfill may blur too; the old unblurred video keeps its own name.
def test_get_video_path_adds_blur_suffix_for_manual_yearly():
	path = get_video_path(
		camera="SLSV",
		target_date=date(2025, 12, 31),
		timelapse_type="yearly",
		manual_run=True,
		blur_people=True,
	)

	assert path == Path("videos/SLSV/manual-runs/yearly/SLSV_2025-12-31_blur.mp4")


@pytest.mark.parametrize(
	("timelapse_type", "manual_run"),
	[
		("daily", False),
		("weekly", True),
		("monthly", True),
		("yearly", False),
	],
)
def test_get_video_path_rejects_blur_outside_manual_daily_and_yearly(timelapse_type, manual_run):
	with pytest.raises(ValueError, match="only allowed for manual daily and yearly"):
		get_video_path(
			camera="SLSV",
			target_date=date(2026, 6, 28),
			timelapse_type=timelapse_type,
			manual_run=manual_run,
			blur_people=True,
		)


def patch_timelapse_steps(monkeypatch, tmp_path: Path, calls: list) -> list[Path]:
	frames = [tmp_path / "frame_000001.jpg", tmp_path / "frame_000002.jpg"]

	monkeypatch.setattr(video_module, "create_temp_directory", lambda camera, target_date: tmp_path)
	monkeypatch.setattr(
		video_module,
		"copy_images_to_temp",
		lambda images, temp_directory: calls.append("copy") or list(zip(images, frames)),
	)
	monkeypatch.setattr(
		video_module,
		"create_image_timelapse",
		lambda **kwargs: calls.append(("encode", kwargs["blur_people"])) or Path("out.mp4"),
	)
	monkeypatch.setattr(
		video_module,
		"cleanup_temp_directory",
		lambda temp_directory: calls.append("cleanup"),
	)

	return frames


def test_create_timelapse_blurs_copies_before_encoding(tmp_path: Path, monkeypatch):
	calls = []
	frames = patch_timelapse_steps(monkeypatch, tmp_path, calls)
	images = [Path("/mnt/cameras/SLSV/a.jpg"), Path("/mnt/cameras/SLSV/b.jpg")]

	monkeypatch.setattr(video_module, "DETECTOR_COMMAND", ["detector"])
	monkeypatch.setattr(video_module, "BLUR_SETTINGS", {"strength": 0.1})
	monkeypatch.setattr(
		video_module,
		"anonymize_frames",
		lambda **kwargs: calls.append(("anonymize", kwargs)),
	)

	create_timelapse(
		camera="SLSV",
		target_date=date(2026, 6, 28),
		images=images,
		timelapse_type="daily",
		framerate=10,
		manual_run=True,
		blur_people=True,
	)

	assert calls[0] == "copy"
	assert calls[1] == (
		"anonymize",
		{
			"camera": "SLSV",
			"originals": images,
			"frames": frames,
			"detector_command": ["detector"],
			"blur_settings": {"strength": 0.1},
			"drop_rules": parse_drop_rules(video_module.CONFIG["privacy"]),
		},
	)
	assert calls[2:] == [("encode", True), "cleanup"]


def test_create_timelapse_does_not_encode_after_privacy_failure(tmp_path: Path, monkeypatch):
	calls = []
	patch_timelapse_steps(monkeypatch, tmp_path, calls)

	def failing_anonymize(**kwargs):
		raise PrivacyCheckError("detector failed")

	monkeypatch.setattr(video_module, "anonymize_frames", failing_anonymize)

	with pytest.raises(PrivacyCheckError):
		create_timelapse(
			camera="SLSV",
			target_date=date(2026, 6, 28),
			images=[Path("a.jpg"), Path("b.jpg")],
			timelapse_type="daily",
			framerate=10,
			manual_run=True,
			blur_people=True,
		)

	assert calls == ["copy"]


def test_create_timelapse_skips_privacy_step_by_default(tmp_path: Path, monkeypatch):
	calls = []
	patch_timelapse_steps(monkeypatch, tmp_path, calls)
	monkeypatch.setattr(
		video_module,
		"anonymize_frames",
		lambda **kwargs: calls.append("anonymize"),
	)

	create_timelapse(
		camera="SLSV",
		target_date=date(2026, 6, 28),
		images=[Path("a.jpg")],
		timelapse_type="daily",
		framerate=10,
	)

	assert "anonymize" not in calls
