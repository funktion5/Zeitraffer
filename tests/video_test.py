import subprocess
from datetime import date
from pathlib import Path

import pytest

import src.video as video_module
from src.video import (
	cleanup_temp_directory,
	copy_images_to_temp,
	create_concat_file,
	create_concat_video,
	create_image_timelapse,
	create_temp_directory,
	create_timelapse,
	cleanup_automatic_video_retention,
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
		image.write_bytes(b"test image")
		images.append(image)

	copied_images = copy_images_to_temp(
		images,
		temp_directory,
	)

	assert len(copied_images) == 3
	assert copied_images[0].name == "frame_000001.jpg"
	assert copied_images[1].name == "frame_000002.jpg"
	assert copied_images[2].name == "frame_000003.jpg"

	assert all(image.exists() for image in copied_images)


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

	expected_output = video_root / "Scheunenviertel" / "manual" / "Scheunenviertel_2026-09-14.mp4"

	temporary_output = (
		expected_output.parent / f".{expected_output.stem}.tmp{expected_output.suffix}"
	)

	popen_calls = []

	class FakeProcess:
		pid = 12345

		def __init__(self, command):
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
		timelapse_type="manual",
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


# A failed image timelapse must preserve the existing working output.
def test_create_image_timelapse_keeps_existing_output_on_error(
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

	output_path = video_root / "Scheunenviertel" / "daily" / "Scheunenviertel_2026-09-14.mp4"

	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	output_path.write_bytes(b"old working daily")

	class FakeProcess:
		pid = 12345

		def __init__(self, command):
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
		create_image_timelapse(
			camera="Scheunenviertel",
			target_date=date(2026, 9, 14),
			temp_directory=temp_directory,
			timelapse_type="daily",
			framerate=10,
		)

	assert output_path.exists()
	assert output_path.read_bytes() == b"old working daily"


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
		tmp_path / "videos" / "Scheunenviertel" / "manual" / "Scheunenviertel_2026-09-14.mp4"
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
		timelapse_type="manual",
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

		def __init__(self, command):
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

		def __init__(self, command):
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
