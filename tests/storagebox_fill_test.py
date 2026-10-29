import os
import subprocess
import sys
from pathlib import Path

from src.config import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "nas" / "helpers" / "storagebox_fill.py"

# The window comes from config/config.json (noon, plus or minus 90 minutes by default), so the
# images that must be copied sit at exactly 12:00 and the one that must not at 03:00.
IN_WINDOW = ["cam-26-06-15_12-00-00-00.jpg", "cam-26-06-16_12-00-00-00.jpg"]
OUTSIDE_WINDOW = "cam-26-06-17_03-00-00-00.jpg"


def run_fill(tmp_path: Path) -> subprocess.CompletedProcess:
	environment = {
		key: value
		for key, value in os.environ.items()
		if key not in ("TIMELAPSE_FRAME_SOURCE", "TIMELAPSE_STORAGE_BOX")
	}
	environment["TIMELAPSE_CAMERA_ROOT"] = str(tmp_path / "cameras")
	environment["HOME"] = str(tmp_path / "home")

	return subprocess.run(
		[sys.executable, str(SCRIPT), "Cam", "2026"],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
		timeout=120,
	)


# The tool reads through the frame source, whatever it is: with a local camera root it must work
# without /mnt/cameras (it used to refuse to start anywhere else). It copies the window images into
# ~/nas-cameras, and a second run finds them already there.
def test_the_fill_copies_the_window_images_from_a_local_camera_root(tmp_path):
	folder = tmp_path / "cameras" / "Cam"
	folder.mkdir(parents=True)
	(tmp_path / "home").mkdir()

	for name in [*IN_WINDOW, OUTSIDE_WINDOW]:
		(folder / name).write_bytes(b"jpeg bytes")

	first = run_fill(tmp_path)

	copied = sorted(path.name for path in (tmp_path / "home" / "nas-cameras" / "Cam").iterdir())
	assert first.returncode == 0, first.stderr
	assert copied == IN_WINDOW
	assert "copied=2" in first.stdout

	second = run_fill(tmp_path)

	assert second.returncode == 0, second.stderr
	assert "copied=0" in second.stdout
	assert "already-local=2" in second.stdout
