import os
import subprocess
from pathlib import Path

import pytest

WEB_DELETE = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-web-delete"


# Run the delete wrapper against a temporary project root instead of the real videos/.
def run_web_delete(project_root: Path, *arguments: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		["bash", str(WEB_DELETE), *arguments],
		capture_output=True,
		text=True,
		env={**os.environ, "TIMELAPSE_PROJECT_ROOT": str(project_root)},
		check=False,
	)


# Create a manual-run video in the temporary project and return its path.
def create_manual_video(project_root: Path, camera: str, job: str, filename: str) -> Path:
	video_path = project_root / "videos" / camera / "manual-runs" / job / filename
	video_path.parent.mkdir(parents=True)
	video_path.write_bytes(b"video")
	return video_path


def test_web_delete_removes_manual_run_video(tmp_path):
	video_path = create_manual_video(tmp_path, "Scheunenviertel", "yearly", "Scheunenviertel.mp4")

	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly", "Scheunenviertel.mp4")

	assert result.returncode == 0
	assert "Video erfolgreich gelöscht." in result.stdout
	assert not video_path.exists()


# The wrapper only deletes manual runs; automatic videos are managed by retention.
def test_web_delete_does_not_touch_automatic_videos(tmp_path):
	automatic_video = tmp_path / "videos" / "Scheunenviertel" / "yearly" / "Scheunenviertel.mp4"
	automatic_video.parent.mkdir(parents=True)
	automatic_video.write_bytes(b"video")

	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly", "Scheunenviertel.mp4")

	assert result.returncode == 66
	assert automatic_video.exists()


def test_web_delete_rejects_wrong_argument_count(tmp_path):
	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly")

	assert result.returncode == 64
	assert "Usage:" in result.stderr


def test_web_delete_rejects_unknown_job(tmp_path):
	create_manual_video(tmp_path, "Scheunenviertel", "alltime", "video.mp4")

	result = run_web_delete(tmp_path, "Scheunenviertel", "alltime", "video.mp4")

	assert result.returncode == 64
	assert "Invalid job." in result.stderr


# The wrapper runs with elevated rights, so no argument may leave the manual-runs folder.
@pytest.mark.parametrize("camera", ["", ".", "..", "../Scheunenviertel", "Scheunenviertel/x"])
def test_web_delete_rejects_camera_path_traversal(tmp_path, camera):
	result = run_web_delete(tmp_path, camera, "yearly", "video.mp4")

	assert result.returncode == 64
	assert "Invalid camera name." in result.stderr


@pytest.mark.parametrize("filename", ["", ".", "..", "../video.mp4", "sub/video.mp4"])
def test_web_delete_rejects_filename_path_traversal(tmp_path, filename):
	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly", filename)

	assert result.returncode == 64
	assert "Invalid filename." in result.stderr


@pytest.mark.parametrize("filename", ["video.mov", "video.mp4.txt", "mp4"])
def test_web_delete_rejects_non_mp4_files(tmp_path, filename):
	other_file = create_manual_video(tmp_path, "Scheunenviertel", "yearly", filename)

	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly", filename)

	assert result.returncode == 64
	assert "Invalid video type." in result.stderr
	assert other_file.exists()


def test_web_delete_reports_missing_video(tmp_path):
	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly", "missing.mp4")

	assert result.returncode == 66
	assert "Video not found." in result.stderr


# A symlink could point anywhere; neither the link nor its target may be deleted.
def test_web_delete_refuses_symlinks(tmp_path):
	target = tmp_path / "outside.mp4"
	target.write_bytes(b"keep")
	link = tmp_path / "videos" / "Scheunenviertel" / "manual-runs" / "yearly" / "link.mp4"
	link.parent.mkdir(parents=True)
	link.symlink_to(target)

	result = run_web_delete(tmp_path, "Scheunenviertel", "yearly", "link.mp4")

	assert result.returncode == 66
	assert link.is_symlink()
	assert target.read_bytes() == b"keep"
