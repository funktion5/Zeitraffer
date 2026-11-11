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
REBUILD_TRIGGER = REPO_ROOT / "scripts" / "web" / "timelapse-web-rebuild"
REBUILD_WORKER = REPO_ROOT / "scripts" / "web" / "timelapse-web-worker-rebuild"
JOB_ID = "a" * 32


# Prepare an isolated trigger with a harmless worker replacement. The cameras come from the list
# file the nightly run writes, as in the manual-run trigger.
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
		"TIMELAPSE_WEB_WORKER_REBUILD": str(fake_worker),
		"TIMELAPSE_TEST_INVOCATION_FILE": str(invocation_file),
	}

	return environment, status_root, invocation_file


def run_trigger(
	environment: dict, camera: str, *jobs: str, job_id: str = JOB_ID
) -> subprocess.CompletedProcess:
	return subprocess.run(
		[str(REBUILD_TRIGGER), job_id, camera, *jobs],
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


# An accepted trigger publishes "running" and hands the validated values to the worker. The order
# and uniqueness of the jobs is src.main's business (it runs them in its fixed order, once each).
def test_rebuild_trigger_starts_the_worker_with_camera_and_jobs(tmp_path):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, "Scheunenviertel", "daily", "monthly")

	wait_for_file_content(invocation_file)

	assert result.returncode == 0
	assert result.stdout.startswith("Videoauftrag gestartet (PID ")
	assert (status_root / f"{JOB_ID}.status").read_text() == "running\n"
	assert invocation_file.read_text().splitlines() == [
		JOB_ID,
		"Scheunenviertel",
		"daily",
		"monthly",
	]


# No job, an unknown job and a fifth value are refused before anything starts.
@pytest.mark.parametrize(
	"jobs",
	[
		[],
		["hourly"],
		["daily", "Daily"],
		["daily", ""],
		["daily", "weekly", "monthly", "yearly", "daily"],
	],
	ids=["no-job", "unknown-job", "wrong-case", "empty-job", "fifth-value"],
)
def test_rebuild_trigger_rejects_no_job_an_unknown_job_and_a_fifth_value(tmp_path, jobs):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, "Scheunenviertel", *jobs)

	assert result.returncode == 64
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# The name ends up in a file path and as the value of --cameras, where "-x" would be taken for an
# option. The list holds the name here, so only the pattern can refuse it.
@pytest.mark.parametrize("camera", ["../x", "", ".", "-x", "a b", "Alpha\nBeta"])
def test_rebuild_trigger_rejects_unsafe_camera_names(tmp_path, camera):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)
	(status_root / "cameras.json").write_text(json.dumps(["Alpha", camera]))

	result = run_trigger(environment, camera, "daily")

	assert result.returncode == 64
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# The list file is the only source of cameras, and a name has to equal an entry as a whole.
@pytest.mark.parametrize("camera", ["Unknown", "Scheunen", "scheunenviertel"])
def test_rebuild_trigger_rejects_an_unlisted_camera(tmp_path, camera):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, camera, "daily")

	assert result.returncode == 66
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


def test_rebuild_trigger_rejects_a_bad_job_id(tmp_path):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	result = run_trigger(environment, "Scheunenviertel", "daily", job_id="../unsafe")

	assert result.returncode == 64
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# A held run lock (another job, or the night run) leaves no status file and starts nothing.
def test_rebuild_trigger_refuses_while_the_lock_is_held(tmp_path):
	environment, status_root, invocation_file = prepare_trigger(tmp_path)

	with Path(environment["TIMELAPSE_WEB_LOCK_FILE"]).open("w") as lock:
		fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
		result = run_trigger(environment, "Scheunenviertel", "daily")

	assert result.returncode == 75
	assert result.stderr.strip() == "Another timelapse job is already running."
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# What src.main logs for every finished job (src/jobs/*.py); the worker reads these lines.
def summary_line(job_text: str, created: int, skipped: int, failed: int) -> str:
	return (
		f"2026-11-09 02:10:00,000 | INFO | {job_text} | "
		f"created={created} | skipped={skipped} | failed={failed} | run_id=20261109T021000-1\n"
	)


DAILY_LINE = summary_line("Daily timelapse job finished for 2026-11-08", 1, 0, 0)
WEEKLY_LINE = summary_line(
	"Weekly timelapse job finished for rolling window ending 2026-11-08", 0, 0, 1
)
MONTHLY_LINE = summary_line("Monthly timelapse job finished for 2026-10-10 to 2026-11-08", 2, 3, 0)
YEARLY_LINE = summary_line("Yearly timelapse job finished for 2025-11-09 to 2026-11-08", 0, 1, 0)


# Run the isolated worker with a controlled replacement for the Python CLI.
def run_rebuild_worker(
	tmp_path: Path,
	python_exit_code: int = 0,
	python_stderr: str = "",
	jobs: tuple[str, ...] = ("daily", "monthly"),
	extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	project_root.mkdir()

	python_arguments_file = tmp_path / "python-arguments"
	python_environment_file = tmp_path / "python-environment"
	fake_python = tmp_path / "fake-python"
	fake_python_lines = [
		"#!/bin/bash",
		f'printf "%s\\n" "$@" >"{python_arguments_file}"',
		# What src.main would see of the frame source settings ("unset" when missing).
		f'echo "${{TIMELAPSE_FRAME_SOURCE-unset}}" >"{python_environment_file}"',
		f'echo "${{TIMELAPSE_STORAGE_BOX-unset}}" >>"{python_environment_file}"',
	]

	if python_stderr:
		fake_python_lines.append(f"printf '%s' {shlex.quote(python_stderr)} >&2")

	fake_python_lines.append(f"exit {python_exit_code}")
	fake_python.write_text("\n".join(fake_python_lines) + "\n")
	fake_python.chmod(0o755)

	# The developer's own frame source settings must not leak into the worker under test.
	inherited = {
		key: value
		for key, value in os.environ.items()
		if key not in ("TIMELAPSE_FRAME_SOURCE", "TIMELAPSE_STORAGE_BOX")
	}
	environment = {
		**inherited,
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_WEB_PYTHON": str(fake_python),
		"TIMELAPSE_WEB_STATUS_HELPER": str(STATUS_HELPER),
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
		**(extra_environment or {}),
	}

	result = subprocess.run(
		[str(REBUILD_WORKER), JOB_ID, "Scheunenviertel", *jobs],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	result.status_file = status_root / f"{JOB_ID}.status"
	result.result_file = status_root / f"{JOB_ID}.result"
	result.reason_file = status_root / f"{JOB_ID}.reason"
	result.python_arguments_file = python_arguments_file
	result.python_environment_file = python_environment_file
	return result


# An automatic job for one camera: no --target-date, or src.main would treat it as a manual run
# and write to manual-runs/ instead of the real folders.
def test_rebuild_worker_runs_main_for_one_camera_without_a_target_date(tmp_path):
	result = run_rebuild_worker(tmp_path)

	assert result.python_arguments_file.read_text().splitlines() == [
		"-m",
		"src.main",
		"--jobs",
		"daily",
		"monthly",
		"--cameras",
		"Scheunenviertel",
	]


# The worker runs as the login user through sudo, which clears the environment, and this host has
# no mount: the job has to be told to read over ssh, and from which box.
def test_rebuild_worker_reads_frames_over_ssh_from_the_default_box(tmp_path):
	result = run_rebuild_worker(tmp_path)

	assert result.python_environment_file.read_text().splitlines() == ["ssh", "storagebox"]


def test_rebuild_worker_passes_a_configured_box_and_always_reads_over_ssh(tmp_path):
	result = run_rebuild_worker(
		tmp_path,
		extra_environment={
			"TIMELAPSE_FRAME_SOURCE": "local",
			"TIMELAPSE_STORAGE_BOX": "boxalias:/base",
		},
	)

	assert result.python_environment_file.read_text().splitlines() == ["ssh", "boxalias:/base"]


# One German line per finished job, in the order the jobs ran, with the labels the page uses
# (translateJobLabel in web/src/video-library.php). A skipped job is a result, not an error.
def test_rebuild_worker_writes_one_german_result_line_per_job(tmp_path):
	result = run_rebuild_worker(
		tmp_path,
		python_stderr=DAILY_LINE + WEEKLY_LINE + MONTHLY_LINE + YEARLY_LINE,
		jobs=("daily", "weekly", "monthly", "yearly"),
	)

	assert result.returncode == 0
	assert result.status_file.read_text() == "completed\n"
	assert result.result_file.read_text().splitlines() == [
		"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen",
		"Wöchentlich: 0 erstellt, 0 übersprungen, 1 fehlgeschlagen",
		"Monatlich: 2 erstellt, 3 übersprungen, 0 fehlgeschlagen",
		"Jährlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen",
	]
	assert result.result_file.stat().st_mode & 0o777 == 0o644


# Other log lines (warnings, per-camera messages) are not results.
def test_rebuild_worker_ignores_log_lines_that_are_not_job_summaries(tmp_path):
	noise = (
		"2026-11-09 02:09:00,000 | INFO | Finished processing camera: Scheunenviertel\n"
		"2026-11-09 02:09:30,000 | WARNING | Blur gate: left out 2 of 90 unconfirmed images\n"
	)

	result = run_rebuild_worker(tmp_path, python_stderr=noise + DAILY_LINE + noise)

	assert result.result_file.read_text().splitlines() == [
		"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen",
	]


# A failed run keeps the exit code and says why through the existing reason mechanism (the last
# "skipping" warning), and the jobs that did finish still show their result.
def test_rebuild_worker_marks_failed_when_main_exits_nonzero(tmp_path):
	warning = (
		"2026-11-09 02:09:30,000 | WARNING | Monthly coverage too low: 21 of 30 days available"
		" (minimum 25) - skipping camera: Scheunenviertel\n"
	)

	result = run_rebuild_worker(tmp_path, python_exit_code=3, python_stderr=DAILY_LINE + warning)

	assert result.returncode == 3
	assert result.status_file.read_text() == "failed\n"
	assert result.reason_file.read_text() == (
		"Monthly coverage too low: 21 of 30 days available (minimum 25)"
		" - skipping camera: Scheunenviertel\n"
	)
	assert result.result_file.read_text().splitlines() == [
		"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen",
	]


# No summary line at all (src.main died early) leaves no result file rather than an empty one.
def test_rebuild_worker_writes_no_result_file_without_summary_lines(tmp_path):
	result = run_rebuild_worker(tmp_path, python_exit_code=1, python_stderr="Traceback\n")

	assert result.status_file.read_text() == "failed\n"
	assert not result.result_file.exists()


# The jobs arrive from the trigger, but the worker is its own entry point: it checks them again.
@pytest.mark.parametrize(
	"jobs", [(), ("hourly",), ("daily", "weekly", "monthly", "yearly", "daily")]
)
def test_rebuild_worker_rejects_bad_jobs_without_running_main(tmp_path, jobs):
	result = run_rebuild_worker(tmp_path, jobs=jobs)

	assert result.returncode == 64
	assert not result.python_arguments_file.exists()
	assert not result.status_file.exists()
