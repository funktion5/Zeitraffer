import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

STATUS_ENDPOINT = Path(__file__).resolve().parents[2] / "web" / "public" / "job-status.php"


# Execute the status endpoint through PHP CLI with controlled request data.
def run_status_endpoint(status_root: Path, query: str) -> subprocess.CompletedProcess:
	environment = {
		**os.environ,
		"REQUEST_METHOD": "GET",
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
	}

	return subprocess.run(
		[
			"php",
			"-r",
			"parse_str($argv[1], $_GET); include $argv[2];",
			query,
			str(STATUS_ENDPOINT),
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)


# Known terminal and active states must be returned as JSON.
def test_status_endpoint_returns_known_status(tmp_path):
	job_id = "a" * 32
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	(status_root / f"{job_id}.status").write_text("completed\n")

	result = run_status_endpoint(status_root, f"id={job_id}")

	assert result.returncode == 0
	assert json.loads(result.stdout) == {"status": "completed"}


# Malformed IDs must be rejected before any path is constructed from them.
def test_status_endpoint_rejects_unsafe_job_id(tmp_path):
	result = run_status_endpoint(tmp_path, "id=../unsafe")

	assert result.returncode == 0
	assert json.loads(result.stdout) == {"error": "Invalid job ID."}


# A valid but unknown ID must not reveal filesystem paths.
def test_status_endpoint_reports_missing_status(tmp_path):
	result = run_status_endpoint(tmp_path, f"id={'b' * 32}")

	assert result.returncode == 0
	assert json.loads(result.stdout) == {"error": "Job status not found."}


# Unexpected file contents must never be forwarded to the browser.
def test_status_endpoint_rejects_unknown_stored_status(tmp_path):
	job_id = "c" * 32
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	(status_root / f"{job_id}.status").write_text("unexpected\n")

	result = run_status_endpoint(status_root, f"id={job_id}")

	assert result.returncode == 0
	assert json.loads(result.stdout) == {"error": "Invalid stored job status."}


@pytest.mark.parametrize(
	("warning", "expected"),
	[
		(
			"Monthly coverage too low: 21 of 30 days available (minimum 25)"
			" - skipping camera: SLSV",
			"Zu wenige Tage mit Bildern im Zeitfenster: 21 von 30 (mindestens 25).",
		),
		(
			"Weekly image coverage incomplete: 5 of 7 days available - skipping camera: SLSV",
			"Nur an 5 von 7 Tagen gibt es Bilder; Wöchentlich braucht alle 7.",
		),
		("Found 0 images - skipping camera.", "Für diesen Tag wurden keine Bilder gefunden."),
		(
			"No valid Yearly images available - skipping camera: SLSV",
			"Im gewählten Zeitraum gibt es keine verwendbaren Bilder.",
		),
		(
			"Blur not finished: 3 of 30 not blurred yet: a.jpg, b.jpg - skipping camera: SLSV",
			"Von 30 Bildern sind 3 noch nicht verpixelt, deshalb wurde kein Video erstellt. "
			"Bitte den Auftrag noch einmal starten.",
		),
		(
			"Blur not finished: another blur run holds the lock - skipping camera: SLSV",
			"Gerade läuft eine andere Verpixelung. Bitte später noch einmal versuchen.",
		),
		("/home/someone/secret path exploded", None),
	],
)
def test_status_endpoint_translates_known_failure_reasons_only(tmp_path, warning, expected):
	job_id = "e" * 32
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	(status_root / f"{job_id}.status").write_text("failed\n")
	(status_root / f"{job_id}.reason").write_text(warning + "\n")

	result = run_status_endpoint(status_root, f"id={job_id}")

	payload = json.loads(result.stdout)
	assert payload == (
		{"status": "failed", "reason": expected} if expected else {"status": "failed"}
	)


# A rebuild leaves one line per finished job next to the status; the page shows them under the
# final message. A job without that file answers exactly as before (the tests above).
def test_status_endpoint_includes_results_when_the_file_exists(tmp_path):
	job_id = "d" * 32
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	(status_root / f"{job_id}.status").write_text("completed\n")
	(status_root / f"{job_id}.result").write_text(
		"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen\n"
		"Jährlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen\n"
	)

	result = run_status_endpoint(status_root, f"id={job_id}")

	assert json.loads(result.stdout) == {
		"status": "completed",
		"results": [
			"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen",
			"Jährlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen",
		],
	}


# A worker that died before writing its PID must not leave the job "running" forever (the
# create button stays locked until the job ends); a fresh start without PID is still running.
@pytest.mark.parametrize(("age_seconds", "expected"), [(5, "running"), (120, "failed")])
def test_status_endpoint_fails_a_running_job_without_pid_after_a_minute(
	tmp_path, age_seconds, expected
):
	job_id = "f" * 32
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	status_file = status_root / f"{job_id}.status"
	status_file.write_text("running\n")
	written = time.time() - age_seconds
	os.utime(status_file, (written, written))

	result = run_status_endpoint(status_root, f"id={job_id}")

	assert json.loads(result.stdout) == {"status": expected}


# running-job.php tells every camera page whether ANY web job is running, so a colleague sees the
# notice without having started the job in their own tab. It reads the same status files as
# job-status.php and applies the same "is the worker still alive" check.
RUNNING_ENDPOINT = Path(__file__).resolve().parents[2] / "web" / "public" / "running-job.php"

needs_proc = pytest.mark.skipif(
	not Path("/proc/self/cmdline").exists(), reason="the worker check reads /proc"
)


def run_running_job_endpoint(status_root: Path, method: str = "GET") -> subprocess.CompletedProcess:
	environment = {
		**os.environ,
		"REQUEST_METHOD": method,
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
	}

	return subprocess.run(
		["php", "-r", "include $argv[1];", str(RUNNING_ENDPOINT)],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)


def write_job(status_root: Path, job_id: str, status: str, pid: int | None = None, age_seconds=0):
	status_root.mkdir(exist_ok=True)
	status_file = status_root / f"{job_id}.status"
	status_file.write_text(f"{status}\n")

	if pid is not None:
		(status_root / f"{job_id}.pid").write_text(f"{pid}\n")

	if age_seconds:
		written = time.time() - age_seconds
		os.utime(status_file, (written, written))


# The endpoint only trusts a PID whose command line names the worker script.
@pytest.fixture
def live_worker():
	process = subprocess.Popen(
		[sys.executable, "-c", "import time; time.sleep(60)", "timelapse-web-worker"]
	)

	yield process

	process.kill()
	process.wait()


@needs_proc
def test_running_job_endpoint_reports_a_live_worker(tmp_path, live_worker):
	status_root = tmp_path / "web-jobs"
	write_job(status_root, "a" * 32, "completed")
	write_job(status_root, "b" * 32, "running", pid=live_worker.pid)

	result = run_running_job_endpoint(status_root)

	assert json.loads(result.stdout) == {"running": True}


def test_running_job_endpoint_ignores_finished_jobs(tmp_path):
	status_root = tmp_path / "web-jobs"
	write_job(status_root, "a" * 32, "completed")
	write_job(status_root, "b" * 32, "failed")

	result = run_running_job_endpoint(status_root)

	assert json.loads(result.stdout) == {"running": False}


# A job killed outright (reboot) leaves "running" behind: it must not show a notice forever.
def test_running_job_endpoint_ignores_a_worker_that_is_gone(tmp_path):
	status_root = tmp_path / "web-jobs"
	write_job(status_root, "c" * 32, "running", pid=99999999)

	result = run_running_job_endpoint(status_root)

	assert json.loads(result.stdout) == {"running": False}


# The worker writes its PID within a second of the start; none after a minute means it never ran.
@pytest.mark.parametrize(("age_seconds", "expected"), [(5, True), (120, False)])
def test_running_job_endpoint_counts_a_fresh_start_without_pid(tmp_path, age_seconds, expected):
	status_root = tmp_path / "web-jobs"
	write_job(status_root, "d" * 32, "running", age_seconds=age_seconds)

	result = run_running_job_endpoint(status_root)

	assert json.loads(result.stdout) == {"running": expected}


def test_running_job_endpoint_without_a_status_folder(tmp_path):
	result = run_running_job_endpoint(tmp_path / "missing")

	assert json.loads(result.stdout) == {"running": False}


# Only 32-character job IDs count: the folder also holds cameras.json and other files.
def test_running_job_endpoint_ignores_other_files(tmp_path):
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	(status_root / "cameras.json").write_text("running\n")
	(status_root / "not-a-job-id.status").write_text("running\n")

	result = run_running_job_endpoint(status_root)

	assert json.loads(result.stdout) == {"running": False}


def test_running_job_endpoint_rejects_post(tmp_path):
	result = run_running_job_endpoint(tmp_path, method="POST")

	assert json.loads(result.stdout) == {"error": "Method not allowed."}
