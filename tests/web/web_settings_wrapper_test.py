import os
import subprocess
from pathlib import Path

import pytest


WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "web" / "timelapse-web-settings"
SETTINGS_JSON = '{"timelapse": {"crf": 30}}'

# A stand-in for the project's Python: it records its arguments, its working folder and its stdin,
# then answers the way the writer does.
FAKE_PYTHON = r"""#!/bin/bash
printf "%s\n" "$@" >"$TIMELAPSE_TEST_ARGS_FILE"
pwd -P >"$TIMELAPSE_TEST_ARGS_FILE.cwd"
cat >"$TIMELAPSE_TEST_STDIN_FILE"
echo "$FAKE_OUTPUT"
exit "${FAKE_EXIT:-0}"
"""


def prepare(tmp_path: Path, exit_code: int = 0, output: str = '{"status": "saved"}') -> dict:
	project_root = tmp_path / "project"
	project_root.mkdir()

	fake_python = tmp_path / "fake-python"
	fake_python.write_text(FAKE_PYTHON)
	fake_python.chmod(0o755)

	return {
		**os.environ,
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_WEB_PYTHON": str(fake_python),
		"TIMELAPSE_TEST_ARGS_FILE": str(tmp_path / "args"),
		"TIMELAPSE_TEST_STDIN_FILE": str(tmp_path / "stdin"),
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


# The values reach the writer on stdin and the time as an option: nothing from the web request is
# ever spliced into a command line.
def test_wrapper_passes_the_json_on_stdin_and_the_mtime_as_an_option(tmp_path):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, "123", SETTINGS_JSON)

	assert result.returncode == 0
	assert result.stdout.strip() == '{"status": "saved"}'
	assert (tmp_path / "args").read_text().splitlines() == [
		"-m",
		"src.settings_save",
		"--expected-mtime",
		"123",
	]
	assert (tmp_path / "stdin").read_text().strip() == SETTINGS_JSON


def test_wrapper_runs_the_writer_from_the_project_root(tmp_path):
	environment = prepare(tmp_path)

	run_wrapper(environment, "0", SETTINGS_JSON)

	recorded = Path((tmp_path / "args.cwd").read_text().strip())

	assert recorded.resolve() == (tmp_path / "project").resolve()


@pytest.mark.parametrize(
	"arguments",
	[
		[],
		["123"],
		["123", SETTINGS_JSON, "extra"],
		["abc", SETTINGS_JSON],
		["-1", SETTINGS_JSON],
		["12 3", SETTINGS_JSON],
		["1.5", SETTINGS_JSON],
		["", SETTINGS_JSON],
		["1234567890123", SETTINGS_JSON],
		["123", "x" * 9000],
		# 4097 two-byte characters are 8194 bytes: the limit counts bytes, not characters.
		["123", "ä" * 4097],
	],
)
def test_wrapper_rejects_bad_arguments(tmp_path, arguments):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, *arguments)

	assert result.returncode == 64
	assert not (tmp_path / "args").exists()


def test_wrapper_accepts_json_exactly_at_the_size_limit(tmp_path):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, "123", "x" * 8192)

	assert result.returncode == 0
	assert (tmp_path / "args").exists()


@pytest.mark.parametrize(
	("exit_code", "output"),
	[
		(65, '{"status": "invalid", "errors": ["timelapse.crf: nicht in Ordnung"]}'),
		(73, '{"status": "stale"}'),
	],
)
def test_wrapper_returns_the_writers_exit_code_and_output(tmp_path, exit_code, output):
	environment = prepare(tmp_path, exit_code=exit_code, output=output)

	result = run_wrapper(environment, "123", SETTINGS_JSON)

	assert result.returncode == exit_code
	assert result.stdout.strip() == output


def test_wrapper_reports_a_missing_python(tmp_path):
	environment = prepare(tmp_path)
	environment["TIMELAPSE_WEB_PYTHON"] = str(tmp_path / "no-such-python")

	result = run_wrapper(environment, "123", SETTINGS_JSON)

	assert result.returncode == 69
	assert not (tmp_path / "args").exists()
