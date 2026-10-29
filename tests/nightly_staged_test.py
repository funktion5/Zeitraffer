import fcntl
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-nightly-staged"

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock(1)")

# Stands in for .venv/bin/python3: answers `-m src.camera_list` and `-m src.main` from files under
# <project>/fake, and records every call in fake/events.
FAKE_PYTHON = r"""#!/bin/bash
R="$TIMELAPSE_PROJECT_ROOT"
if [[ "$1" == "-m" && "$2" == "src.camera_list" ]]; then
	echo "camera_list" >> "$R/fake/events"
	rc="$(cat "$R/fake/list_rc" 2>/dev/null || echo 0)"
	if [[ "$rc" == 0 ]]; then
		mkdir -p "$R/state/web-jobs"
		cp "$R/fake/cameras" "$R/state/web-jobs/cameras.txt"
		cat "$R/fake/cameras"
	fi
	exit "$rc"
elif [[ "$1" == "-m" && "$2" == "src.main" ]]; then
	[[ -n "${FAKE_READ_STDIN:-}" ]] && cat > /dev/null
	echo "main preset=$TIMELAPSE_X264_PRESET source=${TIMELAPSE_FRAME_SOURCE-unset}" \
		"root=${TIMELAPSE_CAMERA_ROOT-unset}" >> "$R/fake/events"
	if [[ -d "$R/fake/videos" ]]; then
		mkdir -p "$R/videos"
		cp -R "$R/fake/videos/." "$R/videos/"
	fi
	if [[ -n "${FAKE_MAIN_SLEEP:-}" ]]; then
		sleep "$FAKE_MAIN_SLEEP" &
		sleeper=$!
		trap 'echo "main got TERM" >> "$R/fake/events"; kill "$sleeper" 2>/dev/null; exit 1' TERM
		echo "started" >> "$R/fake/events"
		wait "$sleeper"
	fi
	if [[ -f "$R/fake/main_out" ]]; then
		cat "$R/fake/main_out"
	else
		tail=" | created=1 | skipped=0 | failed=0 | run_id=x"
		for job in Daily Weekly Monthly Yearly; do
			echo "x | INFO | $job timelapse job finished for x$tail"
		done
	fi
	exit "$(cat "$R/fake/main_rc" 2>/dev/null || echo 0)"
fi
"""

# The video's "duration" is simply the file's content.
FAKE_FFPROBE = '#!/bin/bash\ncat "${@: -1}"\n'


def summary(job: str, failed: int = 0) -> str:
	return (
		f"x | INFO | {job} timelapse job finished for x | "
		f"created=1 | skipped=0 | failed={failed} | run_id=x"
	)


def failure(job: str, camera: str) -> str:
	return f"x | ERROR | Failed to process {job} for camera: {camera}"


class Project:
	def __init__(self, root: Path):
		self.root = root
		self.fake = root / "fake"
		self.home = root / "home"
		self.python = root / "fake-python"

		(self.fake / "videos").mkdir(parents=True)
		(self.home / "bin").mkdir(parents=True)
		self._script(self.python, FAKE_PYTHON)
		self._script(self.home / "bin" / "ffprobe", FAKE_FFPROBE)

		self.set_cameras("Alpha", "Bravo Cam")

		for camera in ("Alpha", "Bravo Cam"):
			self.video(camera, "daily/video.mp4", "88.2")

	@staticmethod
	def _script(path: Path, content: str) -> None:
		path.write_text(content)
		path.chmod(0o755)

	def set_cameras(self, *cameras: str) -> None:
		(self.fake / "cameras").write_text("".join(f"{camera}\n" for camera in cameras))

	def video(self, camera: str, relative: str, content: str) -> None:
		path = self.fake / "videos" / camera / relative
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(content)

	def main_rc(self, code: int) -> None:
		(self.fake / "main_rc").write_text(str(code))

	def main_lines(self, *lines: str) -> None:
		(self.fake / "main_out").write_text("\n".join(lines) + "\n")

	def environment(self, **extra_env: str) -> dict:
		inherited = dict(os.environ)

		for name in ("TIMELAPSE_X264_PRESET", "TIMELAPSE_CAMERA_ROOT", "TIMELAPSE_FRAME_SOURCE"):
			inherited.pop(name, None)

		return {
			**inherited,
			"HOME": str(self.home),
			"TIMELAPSE_PROJECT_ROOT": str(self.root),
			"TIMELAPSE_NIGHTLY_PYTHON": str(self.python),
			**extra_env,
		}

	def run(self, **extra_env: str) -> subprocess.CompletedProcess:
		return subprocess.run(
			["bash", str(WRAPPER)],
			capture_output=True,
			text=True,
			env=self.environment(**extra_env),
			check=False,
			timeout=120,
		)

	def start(self, **extra_env: str) -> subprocess.Popen:
		return subprocess.Popen(
			["bash", str(WRAPPER)],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
			env=self.environment(**extra_env),
		)

	def events(self) -> list[str]:
		path = self.fake / "events"

		return path.read_text().splitlines() if path.exists() else []

	def report(self) -> str:
		return next((self.root / "logs" / "nightly").glob("*/report.txt")).read_text()


@pytest.fixture
def project(tmp_path: Path) -> Project:
	return Project(tmp_path)


def commands(events: list[str]) -> list[str]:
	return [event.split(" preset=")[0] for event in events]


# One run covers every camera: the list is written first, then the pipeline runs once, and nothing
# stages frames any more.
def test_one_run_covers_all_cameras_and_the_list_is_written_first(project):
	result = project.run()

	assert result.returncode == 0
	assert commands(project.events()) == ["camera_list", "main"]
	assert (project.root / "state" / "web-jobs" / "cameras.txt").is_file()
	assert "Cameras: 2, failed: 0" in project.report()
	assert "ok: 1 videos verified" in project.report()


def test_pipeline_reads_over_ssh_with_the_default_preset_and_no_camera_root(project):
	project.run()

	main_event = next(event for event in project.events() if event.startswith("main"))

	assert "preset=ultrafast" in main_event
	assert "source=ssh" in main_event
	assert "root=unset" in main_event


def test_the_preset_can_be_overridden(project):
	project.run(TIMELAPSE_X264_PRESET="fast")

	assert all("preset=fast" in event for event in project.events() if event.startswith("main"))


def test_an_unknown_preset_is_refused_before_anything_runs(project):
	result = project.run(TIMELAPSE_X264_PRESET="ultrafst")

	assert result.returncode == 64
	assert project.events() == []


# The old list would be stale, so a camera list that cannot be written ends the night.
def test_a_failed_camera_list_is_fatal(project):
	(project.fake / "list_rc").write_text("1")

	result = project.run()

	assert result.returncode == 2
	assert project.events() == ["camera_list"]


def test_no_cameras_is_fatal(project):
	project.set_cameras()

	result = project.run()

	assert result.returncode == 2
	assert "lists no cameras" in project.report()
	assert "main" not in " ".join(commands(project.events()))


# A camera error is caught by the jobs and only logged, so the log line names the camera.
def test_a_logged_camera_failure_fails_that_camera_and_only_that_one(project):
	project.main_lines(
		summary("Daily"),
		failure("Weekly", "Bravo Cam"),
		summary("Weekly", failed=1),
		summary("Monthly"),
		summary("Yearly"),
	)

	result = project.run()
	report = project.report()

	assert result.returncode == 1
	assert "Failed: Bravo Cam" in report
	assert "Alpha" not in report.split("Failed:")[1]
	assert "Cameras: 2, failed: 1" in report


# A frame cache that could not be removed is counted as failed by the job and names its camera too.
def test_a_frame_cache_that_could_not_be_removed_fails_that_camera(project):
	project.main_lines(
		summary("Daily"),
		"x | ERROR | Could not remove fetched frames for camera: Alpha",
		summary("Weekly", failed=1),
		summary("Monthly"),
		summary("Yearly"),
	)

	result = project.run()

	assert result.returncode == 1
	assert "Failed: Alpha" in project.report()


# A failure the log does not attribute to a camera must still end the night with exit 1.
def test_a_job_failure_without_a_named_camera_fails_the_run(project):
	project.main_lines(
		summary("Daily"),
		summary("Weekly", failed=1),
		summary("Monthly"),
		summary("Yearly"),
	)

	result = project.run()

	assert result.returncode == 1
	assert "FAILED (run)" in project.report()


def test_missing_summary_lines_fail_the_run(project):
	project.main_lines(summary("Daily"), summary("Weekly"), summary("Monthly"))

	result = project.run()

	assert result.returncode == 1
	assert "expected 4 job summary lines, found 3" in project.report()


def test_a_nonzero_pipeline_exit_fails_the_run(project):
	project.main_rc(1)

	result = project.run()

	assert result.returncode == 1
	assert "src.main exited with 1" in project.report()


def test_an_empty_video_fails_that_camera(project):
	project.video("Alpha", "daily/video.mp4", "0")

	result = project.run()

	assert result.returncode == 1
	assert "empty or unreadable video" in project.report()
	assert "Failed: Alpha" in project.report()


# A killed FFmpeg leaves its hidden temporary file behind; the exit code of src.main is still 0.
def test_a_leftover_partial_file_fails_that_camera(project):
	project.video("Alpha", "monthly/.Alpha_2026-10-19.tmp.mp4", "5")

	result = project.run()

	assert result.returncode == 1
	assert "partial file left behind" in project.report()


def test_a_held_run_lock_stops_the_run(project):
	lock_path = project.root / "state" / "zeitraffer-run.lock"
	lock_path.parent.mkdir()

	with lock_path.open("a") as lock_file:
		fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

		result = project.run()

	assert result.returncode == 75
	assert project.events() == []


# The pipeline must not read the terminal (or, from cron, nothing at all): a program that tries to
# read its input would otherwise hang the night.
def test_a_pipeline_that_reads_its_input_does_not_hang(project):
	result = project.run(FAKE_READ_STDIN="1")

	assert result.returncode == 0
	assert "main" in " ".join(commands(project.events()))


# A stop signal sent to the wrapper alone has to reach the pipeline, which releases its frames
# before it exits, and the report says why the run ended.
def test_stopping_the_wrapper_stops_the_run(project):
	process = project.start(FAKE_MAIN_SLEEP="30")
	deadline = time.monotonic() + 10

	while "started" not in project.events() and time.monotonic() < deadline:
		time.sleep(0.05)

	process.send_signal(signal.SIGTERM)
	process.wait(timeout=20)

	assert process.returncode == 143
	assert "main got TERM" in project.events()
	assert "STOPPED" in project.report()
