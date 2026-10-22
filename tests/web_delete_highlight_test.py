import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-web-delete-highlight"


# Run the wrapper against a temporary project root instead of the real videos/.
def run_wrapper(project_root: Path, *arguments: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		["bash", str(WRAPPER), *arguments],
		capture_output=True,
		text=True,
		env={**os.environ, "TIMELAPSE_PROJECT_ROOT": str(project_root)},
		check=False,
	)


# Create a highlights day folder with the given files and return it.
def make_day(project_root: Path, camera: str, date: str, *names: str) -> Path:
	day = project_root / "videos" / camera / "highlights" / date
	day.mkdir(parents=True)
	for name in names:
		(day / name).write_bytes(b"x")
	return day


def test_removes_the_image_and_nothing_else(tmp_path):
	day = make_day(tmp_path, "Cam", "2026-10-20", "a.jpg", "b.jpg", "manifest.json")
	other_day = make_day(tmp_path, "Cam", "2026-10-19", "a.jpg")

	result = run_wrapper(tmp_path, "Cam", "2026-10-20", "a.jpg")

	assert result.returncode == 0
	assert "Bild erfolgreich gelöscht." in result.stdout
	assert not (day / "a.jpg").exists()
	assert (day / "b.jpg").exists()
	assert (day / "manifest.json").exists()
	assert (other_day / "a.jpg").exists()


def test_wrong_argument_count_is_64(tmp_path):
	result = run_wrapper(tmp_path, "Cam", "2026-10-20")

	assert result.returncode == 64
	assert "Usage:" in result.stderr


# The wrapper runs with elevated rights, so no argument may leave the highlights folder.
@pytest.mark.parametrize("camera", ["", ".", "..", "../Cam", "Cam/x"])
def test_camera_traversal_is_64(tmp_path, camera):
	make_day(tmp_path, "Cam", "2026-10-20", "a.jpg")

	result = run_wrapper(tmp_path, camera, "2026-10-20", "a.jpg")

	assert result.returncode == 64
	assert "Invalid camera name." in result.stderr


@pytest.mark.parametrize("date", ["", "2026-10-2", "2026-13-45x", "../2026-10-20", "2026-10-20/x"])
def test_bad_date_is_64(tmp_path, date):
	result = run_wrapper(tmp_path, "Cam", date, "a.jpg")

	assert result.returncode == 64
	assert "Invalid date." in result.stderr


@pytest.mark.parametrize(
	"name",
	[
		"",
		".",
		"..",
		"../a.jpg",
		"sub/a.jpg",
		".hidden.jpg",
		"a.png",
		"a.jpg.txt",
		"manifest.json",
		"a b.jpg",
		"a.JPG",
	],
)
def test_bad_filename_is_64_and_leaves_files(tmp_path, name):
	day = make_day(tmp_path, "Cam", "2026-10-20", "a.jpg", "manifest.json")

	result = run_wrapper(tmp_path, "Cam", "2026-10-20", name)

	assert result.returncode == 64
	assert "Invalid filename." in result.stderr
	assert sorted(path.name for path in day.iterdir()) == ["a.jpg", "manifest.json"]


def test_missing_file_is_66(tmp_path):
	make_day(tmp_path, "Cam", "2026-10-20", "a.jpg")

	result = run_wrapper(tmp_path, "Cam", "2026-10-20", "b.jpg")

	assert result.returncode == 66
	assert "Image not found." in result.stderr


def test_symlink_is_refused_and_target_kept(tmp_path):
	day = make_day(tmp_path, "Cam", "2026-10-20")
	target = tmp_path / "outside.jpg"
	target.write_bytes(b"x")
	(day / "link.jpg").symlink_to(target)

	result = run_wrapper(tmp_path, "Cam", "2026-10-20", "link.jpg")

	assert result.returncode == 66
	assert (day / "link.jpg").is_symlink()
	assert target.exists()


# A symlinked day folder would let the rm reach files outside the highlights tree.
def test_symlinked_day_folder_is_refused(tmp_path):
	outside = tmp_path / "outside"
	outside.mkdir()
	(outside / "a.jpg").write_bytes(b"x")
	highlights = tmp_path / "videos" / "Cam" / "highlights"
	highlights.mkdir(parents=True)
	(highlights / "2026-10-20").symlink_to(outside)

	result = run_wrapper(tmp_path, "Cam", "2026-10-20", "a.jpg")

	assert result.returncode == 66
	assert (outside / "a.jpg").exists()


def test_a_video_path_cannot_be_reached(tmp_path):
	video = tmp_path / "videos" / "Cam" / "manual-runs" / "daily" / "a.jpg"
	video.parent.mkdir(parents=True)
	video.write_bytes(b"x")

	result = run_wrapper(tmp_path, "Cam", "2026-10-20", "a.jpg")

	assert result.returncode == 66
	assert video.exists()
