import re

from src.config import PROJECT_ROOT


# Archived with the Pi mount: it guarded that the SSHFS unit mounted the camera storage read-only.
# Not collected by pytest (see archive/README.md); run it explicitly with `pytest archive/pi`.
def test_camera_mount_stays_read_only() -> None:
	unit = (PROJECT_ROOT / "archive" / "pi" / "systemd" / "cameras-sshfs.service").read_text(
		encoding="utf-8"
	)
	exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
	options = re.findall(r"-o (\S+)", exec_start)

	assert "ro" in options
	assert "rw" not in options
