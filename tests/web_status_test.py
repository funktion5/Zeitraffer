import fcntl
import os
import shlex
from pathlib import Path
import subprocess
import time

import pytest


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
	window: tuple[str, str] | None = None,
	expected_video_suffix: str | None = None,
	python_stderr: str = "",
) -> subprocess.CompletedProcess:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	project_root.mkdir()
	video_suffix = f"_{daylight_buffer_minutes}min" if daylight_buffer_minutes else ""

	# Tests state the expected name literally so the worker can't agree with itself.
	if expected_video_suffix is not None:
		video_suffix = expected_video_suffix

	python_arguments_file = tmp_path / "python-arguments"
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
	fake_python_lines = [
		"#!/bin/bash",
		f'printf "%s\\n" "$@" >"{python_arguments_file}"',
	]

	if publish_video:
		fake_python_lines.extend(
			[
				f'mkdir -p "{video_path.parent}"',
				f'temporary_video="{video_path.parent}/.replacement.mp4"',
				'printf "new video" >"$temporary_video"',
				f'mv -f "$temporary_video" "{video_path}"',
			]
		)

	if python_stderr:
		fake_python_lines.append(f"printf '%s' {shlex.quote(python_stderr)} >&2")

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

	if window is not None:
		command.extend(window)

	result = subprocess.run(
		command,
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	result.status_file = status_root / f"{job_id}.status"
	result.video_path = video_path
	result.python_arguments_file = python_arguments_file
	result.reason_file = status_root / f"{job_id}.reason"
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


SKIP_LOG = (
	"2026-10-26 10:00:00,000 | WARNING | Monthly coverage partial: 26 of 30 days\n"
	"2026-10-26 10:00:01,000 | WARNING | Monthly coverage too low: 21 of 30 days available"
	" (minimum 25) - skipping camera: Scheunenviertel\n"
	"2026-10-26 10:00:02,000 | WARNING | Available image range: 2023-03-03 - 2024-12-02\n"
	"2026-10-26 10:00:03,000 | INFO | Monthly timelapse job finished\n"
)


# The last "skipping" warning is why no video came out (diagnostics that follow it, like the
# image range after a skipped Daily, are not); job-status.php translates it.
def test_web_worker_keeps_the_last_warning_as_failure_reason(tmp_path):
	result = run_web_worker(tmp_path, python_exit_code=0, python_stderr=SKIP_LOG)

	assert result.status_file.read_text() == "failed\n"
	assert result.reason_file.read_text() == (
		"Monthly coverage too low: 21 of 30 days available (minimum 25)"
		" - skipping camera: Scheunenviertel\n"
	)
	assert result.reason_file.stat().st_mode & 0o777 == 0o644


# Without a temp file the run still happens; it just cannot name a failure reason.
def test_web_worker_runs_even_when_mktemp_fails(tmp_path, monkeypatch):
	monkeypatch.setenv("TMPDIR", str(tmp_path / "missing"))

	result = run_web_worker(tmp_path, python_exit_code=0, publish_video=True)

	assert result.status_file.read_text() == "completed\n"


def test_web_worker_leaves_no_reason_on_success(tmp_path):
	result = run_web_worker(
		tmp_path, python_exit_code=0, publish_video=True, python_stderr=SKIP_LOG
	)

	assert result.status_file.read_text() == "completed\n"
	assert not result.reason_file.exists()


# Prepare an isolated trigger with a harmless worker replacement.
def prepare_web_trigger(tmp_path: Path) -> tuple[dict, Path, Path]:
	project_root = tmp_path / "project"
	status_root = project_root / "state" / "web-jobs"
	invocation_file = tmp_path / "worker-arguments"
	# The cameras come from the list file the nightly run writes, not from a folder.
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
		"TIMELAPSE_WEB_WORKER": str(fake_worker),
		"TIMELAPSE_TEST_INVOCATION_FILE": str(invocation_file),
	}

	return environment, status_root, invocation_file


# The trigger starts the worker in the background. Its shell redirect creates the file before
# printf fills it, so wait for content, with a timeout generous enough for a busy Pi or CI runner.
def wait_for_file_content(path: Path, timeout_seconds: float = 2.0) -> None:
	deadline = time.monotonic() + timeout_seconds

	while time.monotonic() < deadline:
		if path.exists() and path.read_text():
			return
		time.sleep(0.01)


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

	wait_for_file_content(invocation_file)

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
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


def run_trigger(environment: dict, camera: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		[str(WEB_TRIGGER), "a" * 32, "daily", "2026-09-22", camera, "60"],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)


# The list file is the only source of cameras: a folder of that name does not make a camera.
def test_web_trigger_rejects_a_camera_that_is_not_in_the_list(tmp_path):
	environment, status_root, invocation_file = prepare_web_trigger(tmp_path)
	(tmp_path / "cameras" / "Folderonly").mkdir(parents=True)
	environment["TIMELAPSE_CAMERA_ROOT"] = str(tmp_path / "cameras")

	result = run_trigger(environment, "Folderonly")

	assert result.returncode == 66
	assert result.stderr.strip() == "Camera not found: Folderonly"
	assert [path.name for path in status_root.iterdir()] == ["cameras.json"]
	assert not invocation_file.exists()


# No usable list means no camera can be started, the same as the web page shows. A string instead
# of a list is one of the cases: "Scheunen" would be found inside it by a plain substring test.
@pytest.mark.parametrize(
	"list_content",
	[None, "{not json", '"Scheunenviertel"', '{"first": "Scheunenviertel"}'],
)
def test_web_trigger_accepts_no_camera_without_a_usable_list(tmp_path, list_content):
	environment, status_root, invocation_file = prepare_web_trigger(tmp_path)
	list_path = status_root / "cameras.json"
	list_path.unlink()

	if list_content is not None:
		list_path.write_text(list_content)

	result = run_trigger(environment, "Scheunenviertel")

	assert result.returncode == 66
	assert not invocation_file.exists()


# The name arrives from the web layer. It must equal a list entry as a whole, and nothing in it may
# be taken for code, a pattern or a second entry.
@pytest.mark.parametrize(
	"camera",
	[
		"Scheunen",
		"scheunenviertel",
		"Scheunenviertel ",
		'x"] or True or ["',
		"Alpha\nScheunenviertel",
		"*",
	],
)
def test_web_trigger_compares_the_camera_as_a_whole_name(tmp_path, camera):
	environment, _, invocation_file = prepare_web_trigger(tmp_path)

	result = run_trigger(environment, camera)

	assert result.returncode == 66
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

	wait_for_file_content(invocation_file)

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


# Monthly/Yearly may pass a window time plus tolerance through to the worker.
@pytest.mark.parametrize("window_time", ["sunset", "18:30"])
def test_web_trigger_accepts_monthly_with_window(tmp_path, window_time):
	environment, _, invocation_file = prepare_web_trigger(tmp_path)
	job_id = "4" * 32

	result = subprocess.run(
		[
			str(WEB_TRIGGER),
			job_id,
			"yearly",
			"2026-09-22",
			"Scheunenviertel",
			window_time,
			"60",
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	wait_for_file_content(invocation_file)

	assert result.returncode == 0
	assert invocation_file.read_text().splitlines() == [
		job_id,
		"yearly",
		"2026-09-22",
		"Scheunenviertel",
		window_time,
		"60",
	]


@pytest.mark.parametrize(
	("job", "window_time", "tolerance", "message"),
	[
		("monthly", "24:00", "60", "Invalid window time: 24:00"),
		("monthly", "9:30", "60", "Invalid window time: 9:30"),
		("monthly", "sunrise", "60", "Invalid window time: sunrise"),
		("monthly", "$(id)", "60", "Invalid window time: $(id)"),
		("yearly", "sunset", "0", "Invalid window tolerance: 0"),
		("yearly", "sunset", "1000", "Invalid window tolerance: 1000"),
		("yearly", "sunset", "-5", "Invalid window tolerance: -5"),
		("daily", "sunset", "60", "Invalid daylight buffer:"),
	],
)
def test_web_trigger_rejects_invalid_window(tmp_path, job, window_time, tolerance, message):
	environment, _, invocation_file = prepare_web_trigger(tmp_path)

	result = subprocess.run(
		[
			str(WEB_TRIGGER),
			"5" * 32,
			job,
			"2026-09-22",
			"Scheunenviertel",
			window_time,
			tolerance,
		],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
	)

	assert result.returncode == 64
	assert result.stderr.strip() == message
	assert not invocation_file.exists()


# The worker must call the CLI with the window and expect the suffixed filename.
@pytest.mark.parametrize(
	("window", "expected_suffix"),
	[
		(("sunset", "60"), "_sunset-60min"),
		(("18:30", "45"), "_1830-45min"),
	],
)
def test_web_worker_passes_window_and_expects_suffixed_video(tmp_path, window, expected_suffix):
	result = run_web_worker(
		tmp_path,
		python_exit_code=0,
		publish_video=True,
		job="monthly",
		daylight_buffer_minutes=None,
		window=window,
		expected_video_suffix=expected_suffix,
	)

	assert result.returncode == 0
	assert result.status_file.read_text() == "completed\n"
	assert result.video_path.name == f"Scheunenviertel_2026-09-22{expected_suffix}.mp4"
	assert result.python_arguments_file.read_text().splitlines() == [
		"-m",
		"src.main",
		"--jobs",
		"monthly",
		"--target-date",
		"2026-09-22",
		"--cameras",
		"Scheunenviertel",
		"--window-time",
		window[0],
		"--window-tolerance-minutes",
		window[1],
	]


# A default-window video must not count as success for a sunset request.
def test_web_worker_rejects_default_video_for_window_request(tmp_path):
	result = run_web_worker(
		tmp_path,
		python_exit_code=0,
		publish_video=True,
		job="monthly",
		daylight_buffer_minutes=None,
		window=("sunset", "60"),
		expected_video_suffix="",
	)

	assert result.returncode == 1
	assert result.status_file.read_text() == "failed\n"
