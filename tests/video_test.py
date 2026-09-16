from pathlib import Path
from datetime import date
from src.video import (
    cleanup_temp_directory,
    copy_images_to_temp,
    create_temp_directory,
    create_timelapse,
)
import pytest


def test_copy_images_to_temp(tmp_path: Path):
    # Create isolated source and temp directories for the test.
    source_directory = tmp_path / "source"
    temp_directory = tmp_path / "temp"

    source_directory.mkdir()
    temp_directory.mkdir()

    # Create three fake image files as test input.
    images = []

    for index in range(3):
        image = source_directory / f"image_{index}.jpg"
        image.write_bytes(b"test image")
        images.append(image)

    # Copy the images into the temp directory.
    copied_images = copy_images_to_temp(images, temp_directory)

    # Verify that all images were copied.
    assert len(copied_images) == 3

    # Verify that the copied images use the expected sequential frame names.
    assert copied_images[0].name == "frame_000001.jpg"
    assert copied_images[1].name == "frame_000002.jpg"
    assert copied_images[2].name == "frame_000003.jpg"

    # Verify that all returned frame paths actually exist.
    assert all(image.exists() for image in copied_images)


def test_create_temp_directory_removes_old_content(tmp_path: Path, monkeypatch):
    # Redirect TEMP_ROOT to pytest's isolated temporary directory.
    # This prevents the test from touching the real project temp directory.
    temp_root = tmp_path / "temp"
    monkeypatch.setattr("src.video.TEMP_ROOT", temp_root)

    # Simulate leftovers from a previous timelapse run.
    old_directory = temp_root / "Scheunenviertel" / "2026-09-14"
    old_directory.mkdir(parents=True)

    old_file = old_directory / "frame_000001.jpg"
    old_file.write_bytes(b"old image")

    # Prepare the temp directory for a new run.
    temp_directory = create_temp_directory(
        "Scheunenviertel",
        date(2026, 9, 14),
    )

    # Verify that the directory was recreated successfully.
    assert temp_directory.exists()
    assert temp_directory.is_dir()

    # Verify that leftovers from the previous run were removed.
    assert not old_file.exists()

    # Verify that the new temp directory starts completely empty.
    assert list(temp_directory.iterdir()) == []

    

def test_cleanup_temp_directory(tmp_path: Path):
    # Create a temporary directory containing a simulated frame.
    temp_directory = tmp_path / "Scheunenviertel" / "2026-09-14"
    temp_directory.mkdir(parents=True)

    frame = temp_directory / "frame_000001.jpg"
    frame.write_bytes(b"test image")

    # Remove the complete temporary working directory.
    cleanup_temp_directory(temp_directory)

    # Verify that the directory and its contents were removed.
    assert not temp_directory.exists()


def test_create_timelapse(tmp_path: Path, monkeypatch):
	# Prepare fake input and output paths without using real camera files.
	images = [
		tmp_path / "image_1.jpg",
		tmp_path / "image_2.jpg",
	]
	temp_directory = tmp_path / "temp"
	video_path = tmp_path / "video.mp4"

	# Track the order in which the processing steps are called.
	calls = []

	# Replace the individual processing steps with controlled test functions.
	def fake_create_temp_directory(camera, target_date):
		calls.append("create_temp_directory")
		return temp_directory

	def fake_copy_images_to_temp(images, temp_directory):
		calls.append("copy_images_to_temp")
		return []

	def fake_create_video(camera, target_date, temp_directory):
		calls.append("create_video")
		return video_path

	def fake_cleanup_temp_directory(temp_directory):
		calls.append("cleanup_temp_directory")

	monkeypatch.setattr(
		"src.video.create_temp_directory",
		fake_create_temp_directory,
	)
	monkeypatch.setattr(
		"src.video.copy_images_to_temp",
		fake_copy_images_to_temp,
	)
	monkeypatch.setattr(
		"src.video.create_video",
		fake_create_video,
	)
	monkeypatch.setattr(
		"src.video.cleanup_temp_directory",
		fake_cleanup_temp_directory,
	)

	# Run the complete timelapse workflow.
	result = create_timelapse(
		camera="Scheunenviertel",
		target_date=date(2026, 9, 14),
		images=images,
	)

	# Verify that all processing steps run in the expected order.
	assert calls == [
		"create_temp_directory",
		"copy_images_to_temp",
		"create_video",
		"cleanup_temp_directory",
	]

	# Verify that the generated video path is returned.
	assert result == video_path

def test_create_timelapse_keeps_temp_files_on_video_error(
	tmp_path: Path,
	monkeypatch,
):
	# Prepare isolated paths for the simulated timelapse job.
	images = [
		tmp_path / "image_1.jpg",
		tmp_path / "image_2.jpg",
	]
	temp_directory = tmp_path / "temp"

	cleanup_called = False

	def fake_create_temp_directory(camera, target_date):
		return temp_directory

	def fake_copy_images_to_temp(images, temp_directory):
		return []

	# Simulate an FFmpeg/video creation failure.
	def fake_create_video(camera, target_date, temp_directory):
		raise RuntimeError("FFmpeg failed")

	def fake_cleanup_temp_directory(temp_directory):
		nonlocal cleanup_called
		cleanup_called = True

	monkeypatch.setattr(
		"src.video.create_temp_directory",
		fake_create_temp_directory,
	)
	monkeypatch.setattr(
		"src.video.copy_images_to_temp",
		fake_copy_images_to_temp,
	)
	monkeypatch.setattr(
		"src.video.create_video",
		fake_create_video,
	)
	monkeypatch.setattr(
		"src.video.cleanup_temp_directory",
		fake_cleanup_temp_directory,
	)

	# The video error should propagate to the caller.
	with pytest.raises(RuntimeError, match="FFmpeg failed"):
		create_timelapse(
			camera="Scheunenviertel",
			target_date=date(2026, 9, 14),
			images=images,
		)

	# Cleanup must not run after a failed video creation.
	assert cleanup_called is False