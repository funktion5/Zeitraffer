import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "web" / "timelapse-web-preview"

# A stand-in for the project's Python: it records its arguments and its working folder, then answers
# the way the preview script does.
FAKE_PYTHON = r"""#!/bin/bash
printf "%s\n" "$@" >"$TIMELAPSE_TEST_ARGS_FILE"
pwd -P >"$TIMELAPSE_TEST_ARGS_FILE.cwd"
echo "$FAKE_OUTPUT"
exit "${FAKE_EXIT:-0}"
"""

# A stand-in for coreutils' timeout (a Mac has none): it records the limit it was given, then runs
# the command without one. FAKE_TIMEOUT_EXIT plays a command that was cut off (124).
FAKE_TIMEOUT = r"""#!/bin/bash
printf "%s\n" "$1" >"$TIMELAPSE_TEST_TIMEOUT_FILE"
if [[ -n "${FAKE_TIMEOUT_EXIT:-}" ]]; then
	exit "$FAKE_TIMEOUT_EXIT"
fi
shift
exec "$@"
"""


def prepare(tmp_path: Path, exit_code: int = 0, output: str = '{"status": "ok"}') -> dict:
	project_root = tmp_path / "project"
	project_root.mkdir()

	fake_python = tmp_path / "fake-python"
	fake_python.write_text(FAKE_PYTHON)
	fake_python.chmod(0o755)

	bin_dir = tmp_path / "bin"
	bin_dir.mkdir()
	fake_timeout = bin_dir / "timeout"
	fake_timeout.write_text(FAKE_TIMEOUT)
	fake_timeout.chmod(0o755)

	return {
		**os.environ,
		"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_WEB_PYTHON": str(fake_python),
		"TIMELAPSE_TEST_ARGS_FILE": str(tmp_path / "args"),
		"TIMELAPSE_TEST_TIMEOUT_FILE": str(tmp_path / "timeout"),
		"FAKE_OUTPUT": output,
		"FAKE_EXIT": str(exit_code),
	}


def run_wrapper(environment: dict, *arguments: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		[str(WRAPPER), *arguments],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)


# The camera name reaches the script as one argument after the module name: nothing from the web
# request is ever spliced into a command line.
def test_wrapper_hands_the_camera_to_the_preview_script(tmp_path):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, "Strand-Terrassen_2")

	assert result.returncode == 0
	assert result.stdout.strip() == '{"status": "ok"}'
	assert (tmp_path / "args").read_text().splitlines() == [
		"-m",
		"src.privacy.preview",
		"Strand-Terrassen_2",
	]


# A click answers in seconds or not at all: a box that does not answer must not hold a web request
# (and an Apache worker) for minutes.
def test_wrapper_limits_the_run_time(tmp_path):
	environment = prepare(tmp_path)

	run_wrapper(environment, "SLSV")

	assert (tmp_path / "timeout").read_text().strip() == "90"


def test_wrapper_hands_on_a_run_that_was_cut_off(tmp_path):
	environment = {**prepare(tmp_path), "FAKE_TIMEOUT_EXIT": "124"}

	result = run_wrapper(environment, "SLSV")

	assert result.returncode == 124
	assert not (tmp_path / "args").exists()


def test_wrapper_runs_the_script_from_the_project_root(tmp_path):
	environment = prepare(tmp_path)

	run_wrapper(environment, "SLSV")

	recorded = Path((tmp_path / "args.cwd").read_text().strip())

	assert recorded.resolve() == (tmp_path / "project").resolve()


@pytest.mark.parametrize(
	"arguments",
	[
		[],
		["SLSV", "extra"],
		[""],
		["../SLSV"],
		["a/b"],
		["/etc"],
		["-SLSV"],
		[".SLSV"],
		["SLS V"],
		["SLSV;id"],
		["$(id)"],
		["SLSV\n"],
		# A dot cannot carry per-camera settings, so such a camera has no preview either.
		["a.b"],
	],
)
def test_wrapper_rejects_bad_arguments(tmp_path, arguments):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, *arguments)

	assert result.returncode == 64
	assert not (tmp_path / "args").exists()


@pytest.mark.parametrize(
	("exit_code", "output"),
	[
		(66, '{"status": "unknown_camera"}'),
		(67, '{"status": "none"}'),
		(1, '{"status": "failed"}'),
	],
)
def test_wrapper_returns_the_scripts_exit_code_and_output(tmp_path, exit_code, output):
	environment = prepare(tmp_path, exit_code=exit_code, output=output)

	result = run_wrapper(environment, "SLSV")

	assert result.returncode == exit_code
	assert result.stdout.strip() == output


def test_wrapper_reports_a_missing_python(tmp_path):
	environment = prepare(tmp_path)
	environment["TIMELAPSE_WEB_PYTHON"] = str(tmp_path / "no-such-python")

	result = run_wrapper(environment, "SLSV")

	assert result.returncode == 69
	assert not (tmp_path / "args").exists()
