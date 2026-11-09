import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
TEMPLATE = ROOT / "config" / "siteground.env.example"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

LOGIN_NAMES = ["SITEGROUND_HOST", "SITEGROUND_USER", "SITEGROUND_PASS"]


# install.sh runs its steps as the login user with sudo; this step needs neither, so its function
# is cut out of the script and run on its own in a temporary project folder.
def run_step(project: Path) -> subprocess.CompletedProcess:
	text = INSTALL.read_text()
	function = re.search(r"^step_upload_login\(\) \{\n.*?^\}\n", text, re.S | re.M)

	assert function is not None, "install.sh has no step_upload_login"

	script = (
		"set -euo pipefail\n"
		'log() { echo "==> $*"; }\n'
		'warn() { echo "WARNING: $*" >&2; }\n'
		'fail() { echo "ERROR: $*" >&2; exit 1; }\n'
		f"{function.group(0)}\n"
		"step_upload_login\n"
	)

	return subprocess.run(
		["bash", "-c", script],
		env={"PATH": "/usr/bin:/bin", "PROJECT_ROOT": str(project)},
		capture_output=True,
		text=True,
		check=False,
	)


def make_project(tmp_path: Path, with_template: bool = True) -> Path:
	(tmp_path / "config").mkdir()

	if with_template:
		shutil.copy(TEMPLATE, tmp_path / "config" / "siteground.env.example")

	return tmp_path


def mode_of(path: Path) -> int:
	return stat.S_IMODE(path.stat().st_mode)


# A fresh host has no login file: it is made from the template, closed to everyone but the user,
# and the output says plainly that the values still have to be entered by hand.
def test_the_login_file_is_created_from_the_template(tmp_path):
	project = make_project(tmp_path)

	result = run_step(project)

	login = project / "config" / "siteground.env"

	assert result.returncode == 0
	assert login.read_text() == TEMPLATE.read_text()
	assert mode_of(login) == 0o600
	assert "fill in" in result.stderr
	assert "SITEGROUND_PASS" in result.stderr


# The file holds the real login: a re-run must never touch it.
def test_an_existing_login_file_is_left_alone(tmp_path):
	project = make_project(tmp_path)
	login = project / "config" / "siteground.env"

	login.write_text("SITEGROUND_PASS=placeholder\n")
	login.chmod(0o640)

	result = run_step(project)

	assert result.returncode == 0
	assert login.read_text() == "SITEGROUND_PASS=placeholder\n"
	assert mode_of(login) == 0o640
	assert "leaving it as it is" in result.stdout
	assert "fill in" not in result.stderr


def test_a_missing_template_fails_and_creates_nothing(tmp_path):
	project = make_project(tmp_path, with_template=False)

	result = run_step(project)

	assert result.returncode != 0
	assert "siteground.env.example" in result.stderr
	assert not (project / "config" / "siteground.env").exists()


# The template goes to GitHub, so it carries the names only and never a value.
def test_the_template_has_the_three_names_and_no_values():
	text = TEMPLATE.read_text()
	lines = [line for line in text.splitlines() if line and not line.startswith("#")]

	assert [line.split("=", 1)[0] for line in lines] == LOGIN_NAMES
	assert all(line.split("=", 1)[1] == "" for line in lines)


# The step has to run before the Apache step and after the packages exist; it is part of a full run.
def test_the_step_is_part_of_the_full_run():
	text = INSTALL.read_text()
	steps = re.search(r"^ALL_STEPS=\(\n(.*?)^\)", text, re.S | re.M)

	assert steps is not None

	names = steps.group(1).split()

	assert "upload_login" in names
	assert names.index("upload_login") < names.index("apache")
	assert names.index("upload_login") > names.index("packages")
