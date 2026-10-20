import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "timelapse-nightly-staged"

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock(1)")

# Stands in for .venv/bin/python3: answers the three stage-frames calls and src.main from files
# under <project>/fake, and records every call in fake/events.
FAKE_PYTHON = r"""#!/bin/bash
R="$TIMELAPSE_PROJECT_ROOT"
if [[ "$1" == "scripts/stage-frames.py" ]]; then
	shift
	case "$1" in
		--list-cameras)
			cat "$R/fake/cameras"
			exit "$(cat "$R/fake/list_rc" 2>/dev/null || echo 0)"
			;;
		--clean-only)
			echo "clean" >> "$R/fake/events"
			exit 0
			;;
		--no-lock)
			echo "stage $3" >> "$R/fake/events"
			rc="$(cat "$R/fake/stage_rc/$3" 2>/dev/null || echo 0)"
			[[ "$rc" == 0 ]] && echo "$3" > "$R/fake/current"
			exit "$rc"
			;;
	esac
elif [[ "$1" == "-m" ]]; then
	[[ -n "${FAKE_READ_STDIN:-}" ]] && cat > /dev/null
	camera="$(cat "$R/fake/current")"
	line="main $camera preset=$TIMELAPSE_X264_PRESET"
	echo "$line root=$TIMELAPSE_CAMERA_ROOT" >> "$R/fake/events"
	if [[ -d "$R/fake/videos/$camera" ]]; then
		mkdir -p "$R/videos/$camera"
		cp -R "$R/fake/videos/$camera/." "$R/videos/$camera/"
	fi
	if [[ -f "$R/fake/main_out/$camera" ]]; then
		cat "$R/fake/main_out/$camera"
	else
		tail=" | created=1 | skipped=0 | failed=0 | run_id=x"
		for job in Daily Weekly Monthly Yearly; do
			echo "x | INFO | $job timelapse job finished for x$tail"
		done
	fi
	exit "$(cat "$R/fake/main_rc/$camera" 2>/dev/null || echo 0)"
fi
"""

# The video's "duration" is simply the file's content.
FAKE_FFPROBE = '#!/bin/bash\ncat "${@: -1}"\n'

SUMMARY = (
	"x | INFO | {job} timelapse job finished for x"
	" | created=1 | skipped=0 | failed=0 | run_id=x"
)


class Project:
	def __init__(self, root: Path):
		self.root = root
		self.fake = root / "fake"
		self.home = root / "home"
		self.python = root / "fake-python"

		for folder in ("stage_rc", "main_out", "main_rc", "videos"):
			(self.fake / folder).mkdir(parents=True)

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

	def stage_rc(self, camera: str, code: int) -> None:
		(self.fake / "stage_rc" / camera).write_text(str(code))

	def main_rc(self, camera: str, code: int) -> None:
		(self.fake / "main_rc" / camera).write_text(str(code))

	def main_output(self, camera: str, jobs: list[str]) -> None:
		lines = [SUMMARY.format(job=job) for job in jobs]
		(self.fake / "main_out" / camera).write_text("\n".join(lines) + "\n")

	def run(self, **extra_env: str) -> subprocess.CompletedProcess:
		inherited = dict(os.environ)
		inherited.pop("TIMELAPSE_X264_PRESET", None)

		environment = {
			**inherited,
			"HOME": str(self.home),
			"TIMELAPSE_PROJECT_ROOT": str(self.root),
			"TIMELAPSE_NIGHTLY_PYTHON": str(self.python),
			**extra_env,
		}

		return subprocess.run(
			["bash", str(WRAPPER)],
			capture_output=True,
			text=True,
			env=environment,
			check=False,
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


def test_every_camera_is_staged_run_verified_and_cleaned_in_turn(project):
	result = project.run()

	assert result.returncode == 0
	assert commands(project.events()) == [
		"stage Alpha",
		"main Alpha",
		"clean",
		"stage Bravo Cam",
		"main Bravo Cam",
		"clean",
		"clean",
	]
	assert "Cameras: 2, failed: 0" in project.report()


def test_pipeline_gets_the_staging_root_and_the_default_preset(project):
	project.run()

	main_event = next(event for event in project.events() if event.startswith("main Alpha"))

	assert "preset=ultrafast" in main_event
	assert f"root={project.root}/temp/camera-staging" in main_event


def test_the_preset_can_be_overridden(project):
	project.run(TIMELAPSE_X264_PRESET="fast")

	assert all("preset=fast" in event for event in project.events() if event.startswith("main"))


def test_an_unknown_preset_is_refused_before_anything_runs(project):
	result = project.run(TIMELAPSE_X264_PRESET="ultrafst")

	assert result.returncode == 64
	assert project.events() == []


def test_a_staging_failure_skips_that_camera_and_continues(project):
	project.stage_rc("Alpha", 1)

	result = project.run()

	assert result.returncode == 1
	assert commands(project.events()) == [
		"stage Alpha",
		"clean",
		"stage Bravo Cam",
		"main Bravo Cam",
		"clean",
		"clean",
	]
	assert "Alpha (staging)" in project.report()


def test_a_fatal_staging_error_aborts_the_remaining_cameras(project):
	project.stage_rc("Alpha", 2)

	result = project.run()

	assert result.returncode == 2
	assert "stage Bravo Cam" not in project.events()
	assert "ABORTED" in project.report()


def test_a_job_summary_with_failures_fails_the_camera(project):
	project.main_output("Bravo Cam", ["Daily", "Weekly", "Monthly", "Yearly"])
	output = project.fake / "main_out" / "Bravo Cam"
	output.write_text(
		output.read_text().replace(
			"created=1 | skipped=0 | failed=0", "created=0 | skipped=0 | failed=1", 1
		)
	)

	result = project.run()

	assert result.returncode == 1
	assert "Failed: Bravo Cam" in project.report()


def test_missing_summary_lines_fail_the_camera(project):
	project.main_output("Alpha", ["Daily", "Weekly", "Monthly"])

	result = project.run()

	assert result.returncode == 1
	assert "expected 4 job summary lines, found 3" in project.report()


def test_a_nonzero_pipeline_exit_fails_the_camera(project):
	project.main_rc("Alpha", 1)

	result = project.run()

	assert result.returncode == 1
	assert "src.main exited with 1" in project.report()


def test_an_empty_video_fails_the_camera(project):
	project.video("Alpha", "daily/video.mp4", "0")

	result = project.run()

	assert result.returncode == 1
	assert "empty or unreadable video" in project.report()


# A killed FFmpeg leaves its hidden temporary file behind; the exit code of src.main is still 0.
def test_a_leftover_partial_file_fails_the_camera(project):
	project.video("Alpha", "monthly/.Alpha_2026-10-19.tmp.mp4", "5")

	result = project.run()

	assert result.returncode == 1
	assert "partial file left behind" in project.report()


def test_a_failed_camera_listing_is_fatal_and_still_cleans(project):
	(project.fake / "list_rc").write_text("1")

	result = project.run()

	assert result.returncode == 2
	assert project.events() == ["clean"]


def test_no_cameras_is_fatal(project):
	project.set_cameras()

	result = project.run()

	assert result.returncode == 2
	assert "lists no cameras" in project.report()


def test_a_held_run_lock_stops_the_run(project):
	lock_path = project.root / "state" / "zeitraffer-run.lock"
	lock_path.parent.mkdir()

	with lock_path.open("a") as lock_file:
		fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

		result = project.run()

	assert result.returncode == 75
	assert project.events() == []


# FFmpeg inside the pipeline reads stdin; it must not eat the list of cameras still to do.
def test_a_pipeline_that_reads_stdin_does_not_swallow_the_camera_list(project):
	result = project.run(FAKE_READ_STDIN="1")

	assert result.returncode == 0
	assert "main Bravo Cam" in " ".join(project.events())
