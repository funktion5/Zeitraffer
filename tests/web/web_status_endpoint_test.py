import json
import os
from pathlib import Path
import subprocess
import time

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
