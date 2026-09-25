import fcntl
import os
from pathlib import Path
import subprocess
import time


STATUS_HELPER = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-web-status.sh"
WEB_WORKER = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-web-worker"
WEB_TRIGGER = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-web-trigger"


# Run one status helper command against an isolated status directory.
def run_status_helper(status_root: Path, command: str) -> subprocess.CompletedProcess:
	environment = {
		**os.environ,
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
	}

	return subprocess.run(
		[
			"bash",
			"-c",
			f'source "$1"; {command}',
			"bash",
			str(STATUS_HELPER),
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)


# A valid status must be written to the expected job-specific file.
def test_write_job_status_creates_status_file(tmp_path):
	job_id = "a" * 32
	status_root = tmp_path / "web-jobs"

	result = run_status_helper(
		status_root,
		f'write_job_status "{job_id}" "running"',
	)

	assert result.returncode == 0
	assert (status_root / f"{job_id}.status").read_text() == "running\n"


# Rewriting a job status must replace the previous complete value.
def test_write_job_status_replaces_existing_status(tmp_path):
	job_id = "b" * 32
	status_root = tmp_path / "web-jobs"

	first_result = run_status_helper(
		status_root,
		f'write_job_status "{job_id}" "running"',
	)
	second_result = run_status_helper(
		status_root,
		f'write_job_status "{job_id}" "completed"',
	)

	assert first_result.returncode == 0
	assert second_result.returncode == 0
	assert (status_root / f"{job_id}.status").read_text() == "completed\n"
	assert list(status_root.glob(f".{job_id}.*")) == []


# Invalid IDs must be rejected without creating a status directory.
def test_write_job_status_rejects_invalid_job_id(tmp_path):
	status_root = tmp_path / "web-jobs"

	result = run_status_helper(
		status_root,
		'write_job_status "../unsafe" "running"',
	)

	assert result.returncode == 64
	assert result.stderr.strip() == "Invalid job ID."
	assert not status_root.exists()


# Unknown state names must not be persisted.
def test_write_job_status_rejects_invalid_status(tmp_path):
	job_id = "c" * 32
	status_root = tmp_path / "web-jobs"

	result = run_status_helper(
		status_root,
		f'write_job_status "{job_id}" "unknown"',
	)

	assert result.returncode == 64
	assert result.stderr.strip() == "Invalid job status: unknown"
	assert not status_root.exists()


# Run the isolated worker with a controlled replacement for the Python CLI.
def run_web_worker(
	tmp_path: Path,
	python_exit_code: int,
	publish_video: bool = False,
	existing_video: bool = False,
	job: str = "daily",
	daylight_buffer_minutes: str | None = "60",
) -> subprocess.CompletedProcess:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	project_root.mkdir()
	video_suffix = f"_{daylight_buffer_minutes}min" if daylight_buffer_minutes else ""
	video_path = (
		project_root
		/ "videos"
		/ "Scheunenviertel"
		/ "manual-runs"
		/ job
		/ f"Scheunenviertel_2026-09-22{video_suffix}.mp4"
	)

	if existing_video:
		video_path.parent.mkdir(parents=True)
		video_path.write_text("existing video")

	fake_python = tmp_path / "fake-python"
	fake_python_lines = ["#!/bin/bash"]

	if publish_video:
		fake_python_lines.extend(
			[
				f'mkdir -p "{video_path.parent}"',
				f'temporary_video="{video_path.parent}/.replacement.mp4"',
				'printf "new video" >"$temporary_video"',
				f'mv -f "$temporary_video" "{video_path}"',
			]
		)

	fake_python_lines.append(f"exit {python_exit_code}")
	fake_python.write_text("\n".join(fake_python_lines) + "\n")
	fake_python.chmod(0o755)

	job_id = "d" * 32
	initial_result = run_status_helper(
		status_root,
		f'write_job_status "{job_id}" "running"',
	)
	assert initial_result.returncode == 0

	environment = {
		**os.environ,
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_WEB_PYTHON": str(fake_python),
		"TIMELAPSE_WEB_STATUS_HELPER": str(STATUS_HELPER),
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
	}

	command = [
		str(WEB_WORKER),
		job_id,
		job,
		"2026-09-22",
		"Scheunenviertel",
	]

	if daylight_buffer_minutes:
		command.append(daylight_buffer_minutes)

	result = subprocess.run(
		command,
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	result.status_file = status_root / f"{job_id}.status"
	result.video_path = video_path
	return result


# A successful Python process that publishes a video must complete.
def test_web_worker_writes_completed_status(tmp_path):
	result = run_web_worker(
		tmp_path,
		python_exit_code=0,
		publish_video=True,
	)

	assert result.returncode == 0
	assert result.status_file.read_text() == "completed\n"
	assert result.video_path.read_text() == "new video"


# A successful Python process without a new video must publish failure.
def test_web_worker_rejects_success_without_new_video(tmp_path):
	result = run_web_worker(tmp_path, python_exit_code=0)

	assert result.returncode == 1
	assert result.status_file.read_text() == "failed\n"
	assert result.stderr.strip() == "The video job finished without publishing a new video."


# An unchanged previous video must not be mistaken for a new result.
def test_web_worker_rejects_unchanged_existing_video(tmp_path):
	result = run_web_worker(
		tmp_path,
		python_exit_code=0,
		existing_video=True,
	)

	assert result.returncode == 1
	assert result.status_file.read_text() == "failed\n"
	assert result.video_path.read_text() == "existing video"


# Atomically replacing an existing video must publish completion.
def test_web_worker_accepts_replaced_existing_video(tmp_path):
	result = run_web_worker(
		tmp_path,
		python_exit_code=0,
		publish_video=True,
		existing_video=True,
	)

	assert result.returncode == 0
	assert result.status_file.read_text() == "completed\n"
	assert result.video_path.read_text() == "new video"


# A failed Python process must preserve its exit code and publish failure.
def test_web_worker_writes_failed_status(tmp_path):
	result = run_web_worker(tmp_path, python_exit_code=23)

	assert result.returncode == 23
	assert result.status_file.read_text() == "failed\n"


# Prepare an isolated trigger with a harmless worker replacement.
def prepare_web_trigger(tmp_path: Path) -> tuple[dict, Path, Path]:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	camera_root = tmp_path / "cameras"
	invocation_file = tmp_path / "worker-arguments"
	project_root.mkdir()
	(camera_root / "Scheunenviertel").mkdir(parents=True)

	fake_worker = tmp_path / "fake-worker"
	fake_worker.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >"$TIMELAPSE_TEST_INVOCATION_FILE"\n')
	fake_worker.chmod(0o755)

	environment = {
		**os.environ,
		"TIMELAPSE_PROJECT_ROOT": str(project_root),
		"TIMELAPSE_CAMERA_ROOT": str(camera_root),
		"TIMELAPSE_WEB_LOCK_FILE": str(tmp_path / "run.lock"),
		"TIMELAPSE_WEB_STATUS_HELPER": str(STATUS_HELPER),
		"TIMELAPSE_WEB_STATUS_ROOT": str(status_root),
		"TIMELAPSE_WEB_WORKER": str(fake_worker),
		"TIMELAPSE_TEST_INVOCATION_FILE": str(invocation_file),
	}

	return environment, status_root, invocation_file


# An accepted trigger must publish running and pass validated values to the worker.
def test_web_trigger_writes_running_and_launches_worker(tmp_path):
	environment, status_root, invocation_file = prepare_web_trigger(tmp_path)
	job_id = "e" * 32

	result = subprocess.run(
		[
			str(WEB_TRIGGER),
			job_id,
			"weekly",
			"2026-09-22",
			"Scheunenviertel",
			"60",
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	for _ in range(20):
		if invocation_file.exists():
			break
		time.sleep(0.01)

	assert result.returncode == 0
	assert (status_root / f"{job_id}.status").read_text() == "running\n"
	assert invocation_file.read_text().splitlines() == [
		job_id,
		"weekly",
		"2026-09-22",
		"Scheunenviertel",
		"60",
	]


# A busy trigger must not create status or launch the worker.
def test_web_trigger_rejects_busy_lock(tmp_path):
	environment, status_root, invocation_file = prepare_web_trigger(tmp_path)
	job_id = "f" * 32
	lock_file = Path(environment["TIMELAPSE_WEB_LOCK_FILE"])

	with lock_file.open("w") as lock:
		fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
		result = subprocess.run(
			[
				str(WEB_TRIGGER),
				job_id,
				"daily",
				"2026-09-22",
				"Scheunenviertel",
				"60",
			],
			capture_output=True,
			text=True,
			env=environment,
			check=False,
		)

	assert result.returncode == 75
	assert result.stderr.strip() == "Another timelapse job is already running."
	assert not status_root.exists()
	assert not invocation_file.exists()


# Monthly/Yearly must accept the 4-argument form and never receive a buffer.
def test_web_trigger_accepts_monthly_without_buffer(tmp_path):
	environment, status_root, invocation_file = prepare_web_trigger(tmp_path)
	job_id = "1" * 32

	result = subprocess.run(
		[
			str(WEB_TRIGGER),
			job_id,
			"monthly",
			"2026-09-22",
			"Scheunenviertel",
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	for _ in range(20):
		if invocation_file.exists():
			break
		time.sleep(0.01)

	assert result.returncode == 0
	assert invocation_file.read_text().splitlines() == [
		job_id,
		"monthly",
		"2026-09-22",
		"Scheunenviertel",
	]


# A buffer supplied alongside Monthly/Yearly must be rejected outright.
def test_web_trigger_rejects_buffer_with_monthly(tmp_path):
	environment, _, invocation_file = prepare_web_trigger(tmp_path)
	job_id = "2" * 32

	result = subprocess.run(
		[
			str(WEB_TRIGGER),
			job_id,
			"monthly",
			"2026-09-22",
			"Scheunenviertel",
			"60",
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	assert result.returncode == 64
	assert result.stderr.strip() == "Monthly/Yearly do not use a daylight buffer."
	assert not invocation_file.exists()


# Daily/Weekly must reject a request missing the required buffer.
def test_web_trigger_rejects_daily_without_buffer(tmp_path):
	environment, _, invocation_file = prepare_web_trigger(tmp_path)
	job_id = "3" * 32

	result = subprocess.run(
		[
			str(WEB_TRIGGER),
			job_id,
			"daily",
			"2026-09-22",
			"Scheunenviertel",
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	assert result.returncode == 64
	assert result.stderr.strip() == "Invalid daylight buffer:"
	assert not invocation_file.exists()


# A Monthly worker run must publish a video with no buffer suffix at all.
def test_web_worker_monthly_video_has_no_buffer_suffix(tmp_path):
	result = run_web_worker(
		tmp_path,
		python_exit_code=0,
		publish_video=True,
		job="monthly",
		daylight_buffer_minutes=None,
	)

	assert result.returncode == 0
	assert result.status_file.read_text() == "completed\n"
	assert result.video_path.name == "Scheunenviertel_2026-09-22.mp4"
