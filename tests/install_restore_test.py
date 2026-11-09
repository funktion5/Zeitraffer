import re
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL = Path(__file__).resolve().parent.parent / "install.sh"

pytestmark = pytest.mark.skipif(
	shutil.which("bash") is None or shutil.which("rsync") is None,
	reason="needs bash and rsync",
)


# The step needs neither sudo nor the rest of install.sh, so its function is cut out of the script
# and run on its own: PROJECT_ROOT and BACKUP_DIR point into a temporary folder, HOME too.
def run_step(tmp_path: Path, backup: Path | str | None) -> subprocess.CompletedProcess:
	text = INSTALL.read_text()
	function = re.search(r"^step_restore\(\) \{\n.*?^\}\n", text, re.S | re.M)

	assert function is not None, "install.sh has no step_restore"

	script = (
		"set -euo pipefail\n"
		'log() { echo "==> $*"; }\n'
		'warn() { echo "WARNING: $*" >&2; }\n'
		'fail() { echo "ERROR: $*" >&2; exit 1; }\n'
		f"{function.group(0)}\n"
		"step_restore\n"
	)

	environment = {
		"PATH": "/usr/bin:/bin:/usr/local/bin",
		"HOME": str(tmp_path / "home"),
		"PROJECT_ROOT": str(tmp_path / "project"),
	}

	if backup is not None:
		environment["BACKUP_DIR"] = str(backup)

	(tmp_path / "home").mkdir(exist_ok=True)
	(tmp_path / "project").mkdir(exist_ok=True)

	return subprocess.run(
		["bash", "-c", script],
		env=environment,
		capture_output=True,
		text=True,
		check=False,
	)


def write(path: Path, content: str) -> Path:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)

	return path


def make_backup(tmp_path: Path) -> Path:
	backup = tmp_path / "backup"

	write(backup / "models" / "model.onnx", "model")
	write(backup / "state" / "privacy" / "box" / "SLSV" / "2026-11.jsonl", "backed up\n")
	write(backup / "videos" / "Camera" / "daily" / "Camera_2026-11-08.mp4", "video")
	write(backup / "crontab.txt", "0 2 * * * example\n")

	return backup


def project_files(tmp_path: Path) -> list[str]:
	project = tmp_path / "project"

	return sorted(str(path.relative_to(project)) for path in project.rglob("*") if path.is_file())


# A fresh host: the backup goes into the project, in the same folders.
def test_models_state_and_videos_are_restored(tmp_path):
	backup = make_backup(tmp_path)

	result = run_step(tmp_path, backup)

	assert result.returncode == 0
	assert project_files(tmp_path) == [
		"models/model.onnx",
		"state/privacy/box/SLSV/2026-11.jsonl",
		"videos/Camera/daily/Camera_2026-11-08.mp4",
	]
	assert (tmp_path / "project" / "models" / "model.onnx").read_text() == "model"


# The crontab is a reference; the cron lines of one host must never be installed on another.
def test_the_crontab_is_not_installed(tmp_path):
	backup = make_backup(tmp_path)

	result = run_step(tmp_path, backup)

	assert "crontab.txt" not in " ".join(project_files(tmp_path))
	assert "reference only" in result.stdout


# Without a backup folder the host is simply set up from scratch.
def test_no_backup_folder_means_nothing_to_restore(tmp_path):
	result = run_step(tmp_path, tmp_path / "missing")

	assert result.returncode == 0
	assert "nothing to restore" in result.stdout
	assert project_files(tmp_path) == []


# The default folder is ~/timelapse-backup, where backup.sh's output is copied to.
def test_the_default_folder_is_in_the_home_directory(tmp_path):
	write(tmp_path / "home" / "timelapse-backup" / "models" / "model.onnx", "model")

	result = run_step(tmp_path, None)

	assert result.returncode == 0
	assert project_files(tmp_path) == ["models/model.onnx"]


# A re-run on a host that already works must not turn back the clock: nothing that exists is
# overwritten, and nothing that only exists here is deleted.
def test_existing_files_are_never_overwritten_or_deleted(tmp_path):
	backup = make_backup(tmp_path)
	state = tmp_path / "project" / "state" / "privacy" / "box" / "SLSV"

	write(state / "2026-11.jsonl", "newer than the backup\n")
	write(state / "2026-12.jsonl", "only here\n")

	result = run_step(tmp_path, backup)

	assert result.returncode == 0
	assert (state / "2026-11.jsonl").read_text() == "newer than the backup\n"
	assert (state / "2026-12.jsonl").read_text() == "only here\n"
	assert (tmp_path / "project" / "models" / "model.onnx").exists()


def test_only_the_folders_in_the_backup_are_restored(tmp_path):
	backup = tmp_path / "backup"

	write(backup / "models" / "model.onnx", "model")

	result = run_step(tmp_path, backup)

	assert result.returncode == 0
	assert project_files(tmp_path) == ["models/model.onnx"]
	assert not (tmp_path / "project" / "state").exists()
	assert not (tmp_path / "project" / "videos").exists()


def test_an_empty_backup_folder_is_reported(tmp_path):
	backup = tmp_path / "backup"
	backup.mkdir()

	result = run_step(tmp_path, backup)

	assert result.returncode == 0
	assert "nothing restored" in result.stderr


# rsync reads `host:path` as a remote source, so a relative value is refused outright.
def test_a_relative_backup_folder_is_refused(tmp_path):
	make_backup(tmp_path)

	result = run_step(tmp_path, "somehost:backup")

	assert result.returncode != 0
	assert "absolute" in result.stderr
	assert project_files(tmp_path) == []


# The restore has to come before the permissions step, which closes the new folders for other
# users, and before the verification.
def test_the_step_runs_before_permissions_and_verify():
	text = INSTALL.read_text()
	steps = re.search(r"^ALL_STEPS=\(\n(.*?)^\)", text, re.S | re.M)

	assert steps is not None

	names = steps.group(1).split()

	assert "restore" in names
	assert names.index("restore") > names.index("venv")
	assert names.index("restore") < names.index("permissions")
	assert names.index("restore") < names.index("verify")
