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


# The scope, the values and the time reach the writer as options and on stdin: nothing from the web
# request is ever spliced into a command line.
def test_wrapper_passes_the_scope_and_time_as_options_and_the_json_on_stdin(tmp_path):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, "general", "123", SETTINGS_JSON)

	assert result.returncode == 0
	assert result.stdout.strip() == '{"status": "saved"}'
	assert (tmp_path / "args").read_text().splitlines() == [
		"-m",
		"src.settings_save",
		"--scope",
		"general",
		"--expected-mtime",
		"123",
	]
	assert (tmp_path / "stdin").read_text().strip() == SETTINGS_JSON


@pytest.mark.parametrize("scope", ["general", "privacy"])
def test_wrapper_accepts_each_known_scope(tmp_path, scope):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, scope, "5", SETTINGS_JSON)

	assert result.returncode == 0
	assert (tmp_path / "args").read_text().splitlines()[2:4] == ["--scope", scope]


def test_wrapper_runs_the_writer_from_the_project_root(tmp_path):
	environment = prepare(tmp_path)

	run_wrapper(environment, "general", "0", SETTINGS_JSON)

	recorded = Path((tmp_path / "args.cwd").read_text().strip())

	assert recorded.resolve() == (tmp_path / "project").resolve()


@pytest.mark.parametrize(
	"arguments",
	[
		[],
		["general"],
		["general", "123"],
		["general", "123", SETTINGS_JSON, "extra"],
		["general", "abc", SETTINGS_JSON],
		["general", "-1", SETTINGS_JSON],
		["general", "12 3", SETTINGS_JSON],
		["general", "1.5", SETTINGS_JSON],
		["general", "", SETTINGS_JSON],
		["general", "1234567890123", SETTINGS_JSON],
		["general", "123", "x" * 9000],
		# 4097 two-byte characters are 8194 bytes: the limit counts bytes, not characters.
		["general", "123", "ä" * 4097],
		# The scope is checked against a fixed list, never passed on as it came.
		["other", "123", SETTINGS_JSON],
		["", "123", SETTINGS_JSON],
		["General", "123", SETTINGS_JSON],
		["general ", "123", SETTINGS_JSON],
		["--scope", "123", SETTINGS_JSON],
		["../x", "123", SETTINGS_JSON],
		["123", "general", SETTINGS_JSON],
	],
)
def test_wrapper_rejects_bad_arguments(tmp_path, arguments):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, *arguments)

	assert result.returncode == 64
	assert not (tmp_path / "args").exists()


def test_wrapper_accepts_json_exactly_at_the_size_limit(tmp_path):
	environment = prepare(tmp_path)

	result = run_wrapper(environment, "general", "123", "x" * 8192)

	assert result.returncode == 0
	assert (tmp_path / "args").exists()


# The privacy form carries many ignore boxes, so its scope may be larger; the general one is small.
def test_the_privacy_scope_has_a_larger_size_limit(tmp_path):
	environment = prepare(tmp_path)

	at_limit = run_wrapper(environment, "privacy", "123", "x" * 65536)

	assert at_limit.returncode == 0

	over = run_wrapper(environment, "privacy", "123", "x" * 65537)

	assert over.returncode == 64


def test_the_general_scope_still_refuses_what_only_privacy_may_send(tmp_path):
	environment = prepare(tmp_path)

	assert run_wrapper(environment, "general", "123", "x" * 8193).returncode == 64


@pytest.mark.parametrize(
	("exit_code", "output"),
	[
		(65, '{"status": "invalid", "errors": ["timelapse.crf: nicht in Ordnung"]}'),
		(73, '{"status": "stale"}'),
	],
)
def test_wrapper_returns_the_writers_exit_code_and_output(tmp_path, exit_code, output):
	environment = prepare(tmp_path, exit_code=exit_code, output=output)

	result = run_wrapper(environment, "general", "123", SETTINGS_JSON)

	assert result.returncode == exit_code
	assert result.stdout.strip() == output


def test_wrapper_reports_a_missing_python(tmp_path):
	environment = prepare(tmp_path)
	environment["TIMELAPSE_WEB_PYTHON"] = str(tmp_path / "no-such-python")

	result = run_wrapper(environment, "general", "123", SETTINGS_JSON)

	assert result.returncode == 69
	assert not (tmp_path / "args").exists()
