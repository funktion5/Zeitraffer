import fcntl
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_HELPER = REPO_ROOT / "scripts" / "web" / "timelapse-web-status.sh"
PUBLISH_TRIGGER = REPO_ROOT / "scripts" / "web" / "timelapse-web-publish"
PUBLISH_WORKER = REPO_ROOT / "scripts" / "web" / "timelapse-web-worker-publish"
JOB_ID = "a" * 32


# Prepare an isolated trigger with a harmless worker replacement. The cameras come from the list
# file the nightly run writes, as in the other triggers.
def prepare_trigger(tmp_path: Path) -> tuple[dict, Path, Path]:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	invocation_file = tmp_path / "worker-arguments"
	status_root.mkdir(parents=True)
	(status_root / "cameras.json").write_text('["Alpha", "Scheunenviertel"]')

	fake_worker = tmp_path / "fake-worker"
	fake_worker.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >"$TIMELAPSE_TEST_INVOCATION_FILE"\n')
	fake_worker.chmod(0o755)

	environment = {
		**os.environ,
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_WEB_LOCK_FILE": str(tmp_path / "run.lock"),
		"TIMELAPSE_WEB_STATUS_HELPER": str(STATUS_HELPER),
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
		"TIMELAPSE_WEB_WORKER_PUBLISH": str(fake_worker),
		"TIMELAPSE_TEST_INVOCATION_FILE": str(invocation_file),
	}

	return environment, status_root, invocation_file


def run_trigger(environment: dict, *arguments: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		[str(PUBLISH_TRIGGER), *arguments],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)


# The trigger starts the worker in the background. Its shell redirect creates the file before
# printf fills it, so wait for content, with a timeout generous enough for a busy CI runner.
def wait_for_file_content(path: Path, timeout_seconds: float = 2.0) -> None:
	deadline = time.monotonic() + timeout_seconds

	while time.monotonic() < deadline:
		if path.exists() and path.read_text():
			return
		time.sleep(0.01)


def test_publish_trigger_starts_the_worker(tmp_path):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, JOB_ID, "Scheunenviertel")

	wait_for_file_content(invocation_file)

	assert result.returncode == 0
	assert result.stdout.startswith("Videoauftrag gestartet (PID ")
	assert (status_root / f"{JOB_ID}.status").read_text() == "running\n"
	assert invocation_file.read_text().splitlines() == [JOB_ID, "Scheunenviertel"]


def test_publish_trigger_rejects_a_bad_job_id(tmp_path):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, "../unsafe", "Scheunenviertel")

	assert result.returncode == 64
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# Nothing but the job ID and one camera name: no job list, no flags, no second camera.
@pytest.mark.parametrize(
	"arguments",
	[(), (JOB_ID,), (JOB_ID, "Alpha", "--run"), (JOB_ID, "Alpha", "Scheunenviertel")],
	ids=["none", "no-camera", "extra-flag", "two-cameras"],
)
def test_publish_trigger_rejects_the_wrong_number_of_arguments(tmp_path, arguments):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, *arguments)

	assert result.returncode == 64
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# The name ends up in a file path and as an argument of the delivery script, where "-x" would be
# taken for an option. The list holds the name here, so only the pattern can refuse it.
@pytest.mark.parametrize("camera", ["../x", "", ".", "-x", "a b", "Alpha\nBeta"])
def test_publish_trigger_rejects_unsafe_camera_names(tmp_path, camera):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)
	(status_root / "cameras.json").write_text(json.dumps(["Alpha", camera]))

	result = run_trigger(environment, JOB_ID, camera)

	assert result.returncode == 64
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# The list file is the only source of cameras, and a name has to equal an entry as a whole.
@pytest.mark.parametrize("camera", ["Unknown", "Scheunen", "scheunenviertel"])
def test_publish_trigger_rejects_an_unlisted_camera(tmp_path, camera):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, JOB_ID, camera)

	assert result.returncode == 66
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# A held run lock (a build, a rebuild, the night run) leaves no status file and starts nothing.
def test_publish_trigger_refuses_while_the_lock_is_held(tmp_path):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	with Path(environment["TIMELAPSE_WEB_LOCK_FILE"]).open("w") as lock:
		fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
		result = run_trigger(environment, JOB_ID, "Scheunenviertel")

	assert result.returncode == 75
	assert result.stderr.strip() == "Another timelapse job is already running."
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# What the delivery script prints at the end (scripts/copy_zeitraffer_videos_vps2siteground.sh).
def result_line(uploaded: int, skipped: int, failed: int, deleted: int) -> str:
	return (
		f"[INFO] Ergebnis: hochgeladen={uploaded} übersprungen={skipped} "
		f"fehlgeschlagen={failed} gelöscht={deleted}\n"
	)


# curl --verbose puts the FTP login into the script's output; none of it may reach the status files.
VERBOSE_LINES = "> USER someone\n> PASS hunter2\n"


# Run the isolated worker with a fake delivery script in place of the real one.
def run_publish_worker(
	tmp_path: Path,
	script_exit_code: int = 0,
	script_output: str = "",
	camera: str = "Scheunenviertel",
	extra_arguments: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	# A test may have made the folder already (to put an earlier log into it).
	project_root.mkdir(exist_ok=True)

	script_arguments_file = tmp_path / "script-arguments"
	fake_script = tmp_path / "fake-delivery.sh"
	fake_script_lines = [
		"#!/bin/bash",
		f'printf "%s\\n" "$@" >"{script_arguments_file}"',
	]

	if script_output:
		fake_script_lines.append(f"printf '%s' {shlex.quote(script_output)}")

	fake_script_lines.append(f"exit {script_exit_code}")
	fake_script.write_text("\n".join(fake_script_lines) + "\n")

	environment = {
		**os.environ,
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_WEB_STATUS_HELPER": str(STATUS_HELPER),
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
		"TIMELAPSE_WEB_PUBLISH_SCRIPT": str(fake_script),
	}

	result = subprocess.run(
		[str(PUBLISH_WORKER), JOB_ID, camera, *extra_arguments],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	result.status_root = status_root
	result.status_file = status_root / f"{JOB_ID}.status"
	result.result_file = status_root / f"{JOB_ID}.result"
	result.script_arguments_file = script_arguments_file
	result.delivery_log = project_root / "logs" / "siteground-delivery.log"
	return result


# One camera, a real run (not the dry run): the script's own default is a dry run.
def test_publish_worker_runs_the_script_for_one_camera_with_run(tmp_path):
	result = run_publish_worker(tmp_path, script_output=result_line(0, 1, 0, 0))

	assert result.script_arguments_file.read_text().splitlines() == ["Scheunenviertel", "--run"]


# One German line from the script's result line, and nothing else of its output reaches the files
# the browser can read.
def test_publish_worker_writes_the_result_line_and_completes(tmp_path):
	result = run_publish_worker(
		tmp_path, script_output=VERBOSE_LINES + result_line(1, 2, 0, 1) + "[INFO] fertig\n"
	)

	assert result.returncode == 0
	assert result.status_file.read_text() == "completed\n"
	assert result.result_file.read_text() == (
		"Hochgeladen: 1, übersprungen: 2, fehlgeschlagen: 0, gelöscht: 1\n"
	)
	assert result.result_file.stat().st_mode & 0o777 == 0o644

	for path in result.status_root.iterdir():
		assert "hunter2" not in path.read_text()


# The script exits 1 when a file failed, and still prints its result: the line stays visible.
def test_publish_worker_fails_when_a_file_failed(tmp_path):
	result = run_publish_worker(tmp_path, script_exit_code=1, script_output=result_line(2, 0, 1, 0))

	assert result.returncode == 1
	assert result.status_file.read_text() == "failed\n"
	assert result.result_file.read_text() == (
		"Hochgeladen: 2, übersprungen: 0, fehlgeschlagen: 1, gelöscht: 0\n"
	)


# A failure count above 0 is a failure even when the exit code says 0.
def test_publish_worker_fails_on_a_failure_count_despite_exit_zero(tmp_path):
	result = run_publish_worker(tmp_path, script_output=result_line(2, 0, 1, 0))

	assert result.status_file.read_text() == "failed\n"


# The script aborts without a result line for an empty list, a missing login or a lock held by
# another upload of the same camera: that is a failure, not a success with nothing to report.
@pytest.mark.parametrize("exit_code", [0, 1, 3])
def test_publish_worker_fails_without_a_result_line(tmp_path, exit_code):
	result = run_publish_worker(
		tmp_path,
		script_exit_code=exit_code,
		script_output="[ERROR] Die Liste ist leer: Es wird nichts gesendet und nichts gelöscht.\n",
	)

	assert result.returncode != 0
	assert result.status_file.read_text() == "failed\n"
	assert not result.result_file.exists()


# The full output goes to the file the night upload writes to, after what is already there.
def test_publish_worker_appends_to_the_delivery_log(tmp_path):
	log = tmp_path / "project" / "logs" / "siteground-delivery.log"
	log.parent.mkdir(parents=True)
	log.write_text("earlier night run\n")
	output = VERBOSE_LINES + result_line(1, 0, 0, 0)

	result = run_publish_worker(tmp_path, script_output=output)

	assert result.delivery_log.read_text() == "earlier night run\n" + output


# A log the worker creates is private: the verbose output holds the FTP login.
def test_publish_worker_creates_a_private_delivery_log(tmp_path):
	output = VERBOSE_LINES + result_line(1, 0, 0, 0)

	result = run_publish_worker(tmp_path, script_output=output)

	assert result.delivery_log.read_text() == output
	assert result.delivery_log.stat().st_mode & 0o077 == 0


# The worker is its own entry point: it checks its arguments again before it touches the script.
@pytest.mark.parametrize(
	("camera", "extra_arguments"),
	[("../x", ()), ("", ()), ("-x", ()), ("Alpha", ("--run",))],
	ids=["path", "empty", "option", "extra-argument"],
)
def test_publish_worker_rejects_bad_arguments_without_running_the_script(
	tmp_path, camera, extra_arguments
):
	result = run_publish_worker(tmp_path, camera=camera, extra_arguments=extra_arguments)

	assert result.returncode == 64
	assert not result.script_arguments_file.exists()
	assert not result.status_file.exists()
