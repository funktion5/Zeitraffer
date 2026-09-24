import json
import os
from pathlib import Path
import subprocess


STATUS_ENDPOINT = Path(__file__).resolve().parent.parent / "web" / "public" / "job-status.php"


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
