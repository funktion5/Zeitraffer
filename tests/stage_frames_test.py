import importlib.util
import subprocess
from datetime import date
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT, load_config
from src.storage_filter import StorageBox, acquire_run_lock

# The script's file name has a hyphen, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location(
	"stage_frames", PROJECT_ROOT / "scripts" / "stage-frames.py"
)
stage_frames = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage_frames)

TARGET = date(2026, 10, 18)


class FakeBox(StorageBox):
	def __init__(self, stdout: str = "", returncode: int = 0, base_directory: str = ""):
		object.__setattr__(self, "remote", "box")
		object.__setattr__(self, "base_directory", base_directory)
		object.__setattr__(self, "_stdout", stdout)
		object.__setattr__(self, "_returncode", returncode)

	def run(self, command: str, timeout_seconds: float) -> subprocess.CompletedProcess:
		return subprocess.CompletedProcess(command, self._returncode, self._stdout, "denied")


@pytest.fixture
def config() -> dict:
	return load_config()


def select(names: list[str], config: dict) -> list[str]:
	return stage_frames.select_frame_names(names, TARGET, config)


def test_target_and_previous_day_are_staged_around_the_clock(config):
	names = [
		"Cam_20261017T230000.jpg",
		"Cam_20261018T030000.jpg",
	]

	# Both are far outside the 12:00 window; only the Daily rule can keep them.
	assert select(names, config) == names


def test_interval_window_limits_older_days(config):
	inside = "Cam_20260501T120000.jpg"
	edge = "Cam_20260501T103000.jpg"
	too_early = "Cam_20260501T102959.jpg"
	night = "Cam_20260501T030000.jpg"

	selected = select([inside, edge, too_early, night], config)

	assert inside in selected
	assert edge in selected
	assert too_early not in selected
	assert night not in selected


def test_days_outside_the_yearly_range_are_dropped(config):
	before_range = "Cam_20251018T120000.jpg"
	first_day = "Cam_20251019T120000.jpg"

	assert select([before_range, first_day], config) == [first_day]


def test_odd_and_non_jpg_names_are_ignored(config):
	names = [
		"Cam_20260501T120000.png",
		"readme.txt",
		"Cam_nodate.jpg",
		"Cam_20260501Tbad.jpg",
	]

	assert select(names, config) == []


def test_result_is_sorted(config):
	names = ["Cam_20260502T120000.jpg", "Cam_20260501T120000.jpg"]

	assert select(names, config) == sorted(names)


def test_list_box_cameras_returns_directories_only():
	listing = (
		"total 12\n"
		"drwxr-xr-x 2 u g 4096 Oct 19 12:00 Camera One\n"
		"-rw-r--r-- 1 u g   10 Oct 19 12:00 notes.txt\n"
		"drwxr-xr-x 2 u g 4096 Oct 19 12:00 SLSV\n"
	)

	assert stage_frames.list_box_cameras(FakeBox(listing)) == ["Camera One", "SLSV"]


def test_list_box_cameras_failure_is_an_oserror():
	with pytest.raises(OSError, match="listing failed"):
		stage_frames.list_box_cameras(FakeBox(returncode=255))


@pytest.mark.parametrize(
	"unsafe",
	[
		stage_frames.TEMP_ROOT,
		stage_frames.TEMP_ROOT.parent,
		Path("/"),
		stage_frames.TEMP_ROOT / ".." / "videos",
	],
)
def test_guard_rejects_destinations_outside_temp(unsafe):
	with pytest.raises(ValueError):
		stage_frames.guard_destination(unsafe)


def test_guard_accepts_a_folder_inside_temp():
	destination = stage_frames.TEMP_ROOT / "camera-staging"

	assert stage_frames.guard_destination(destination) == destination.resolve()


def test_guard_rejects_a_symlink_escaping_temp(tmp_path, monkeypatch):
	temp_root = tmp_path / "temp"
	temp_root.mkdir()
	(tmp_path / "elsewhere").mkdir()
	(temp_root / "link").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
	monkeypatch.setattr(stage_frames, "TEMP_ROOT", temp_root)

	with pytest.raises(ValueError):
		stage_frames.guard_destination(temp_root / "link")


def test_wipe_removes_a_marked_staging_folder(tmp_path):
	destination = tmp_path / "staging"
	stage_frames.create_destination(destination)
	(destination / "Cam").mkdir()
	(destination / "Cam" / "a.jpg").write_bytes(b"x")

	stage_frames.wipe_destination(destination)

	assert not destination.exists()


def test_wipe_refuses_a_folder_without_marker(tmp_path):
	# Looks like the pipeline's own working frames: temp/<camera>/<date>/frame_000001.jpg
	destination = tmp_path / "Cam"
	(destination / "2026-10-18").mkdir(parents=True)
	(destination / "2026-10-18" / "frame_000001.jpg").write_bytes(b"x")

	with pytest.raises(ValueError, match="marker"):
		stage_frames.wipe_destination(destination)

	assert (destination / "2026-10-18" / "frame_000001.jpg").exists()


def test_wipe_removes_an_empty_folder_and_ignores_a_missing_one(tmp_path):
	empty = tmp_path / "empty"
	empty.mkdir()

	stage_frames.wipe_destination(empty)
	stage_frames.wipe_destination(tmp_path / "missing")

	assert not empty.exists()


def test_main_exits_fatal_when_the_run_lock_is_held(tmp_path, monkeypatch):
	temp_root = tmp_path / "temp"
	temp_root.mkdir()
	monkeypatch.setattr(stage_frames, "TEMP_ROOT", temp_root)
	destination = temp_root / "staging"
	monkeypatch.setattr(
		stage_frames.sys,
		"argv",
		["stage-frames.py", "--clean-only", "--destination", str(destination)],
	)
	stage_frames.create_destination(destination)

	lock_path = tmp_path / "state" / "zeitraffer-run.lock"
	monkeypatch.setattr(
		stage_frames,
		"acquire_run_lock",
		lambda: acquire_run_lock(lock_path),
	)

	with acquire_run_lock(lock_path):
		assert stage_frames.main() == stage_frames.EXIT_FATAL

		# The held lock must also have stopped the wipe, not just the exit code.
		assert destination.exists()

	assert stage_frames.main() == stage_frames.EXIT_OK
	assert not destination.exists()


def test_no_lock_flag_skips_the_run_lock(tmp_path, monkeypatch):
	temp_root = tmp_path / "temp"
	temp_root.mkdir()
	monkeypatch.setattr(stage_frames, "TEMP_ROOT", temp_root)
	monkeypatch.setattr(
		stage_frames.sys,
		"argv",
		[
			"stage-frames.py",
			"--clean-only",
			"--no-lock",
			"--destination",
			str(temp_root / "staging"),
		],
	)

	def locked():
		raise AssertionError("the lock must not be taken with --no-lock")

	monkeypatch.setattr(stage_frames, "acquire_run_lock", locked)

	assert stage_frames.main() == stage_frames.EXIT_OK


def test_copy_camera_sends_names_nul_separated_to_rsync(tmp_path, monkeypatch):
	calls = []

	def fake_run(command, **kwargs):
		calls.append((command, kwargs))
		return subprocess.CompletedProcess(command, 0, b"", b"")

	monkeypatch.setattr(stage_frames.subprocess, "run", fake_run)

	stage_frames.copy_camera(FakeBox(), "Cam", ["a.jpg", "b c.jpg"], tmp_path)

	command, kwargs = calls[0]
	assert command[0] == "rsync"
	assert "--from0" in command
	assert "--files-from=-" in command
	assert "box:Cam/" in command
	assert kwargs["input"] == b"a.jpg\0b c.jpg\0"
	assert (tmp_path / "Cam").is_dir()


def test_failed_rsync_raises_and_keeps_the_partial_copy_for_the_retry(tmp_path, monkeypatch):
	def fake_run(command, **kwargs):
		(tmp_path / "Cam" / "a.jpg").write_bytes(b"x")
		return subprocess.CompletedProcess(command, 23, b"", b"boom")

	monkeypatch.setattr(stage_frames.subprocess, "run", fake_run)

	with pytest.raises(OSError, match="boom"):
		stage_frames.copy_camera(FakeBox(), "Cam", ["a.jpg", "b.jpg"], tmp_path)

	assert (tmp_path / "Cam" / "a.jpg").exists()


def test_copy_camera_removes_leftovers_that_are_not_in_the_selection(tmp_path, monkeypatch):
	(tmp_path / "Cam").mkdir()
	(tmp_path / "Cam" / "wanted.jpg").write_bytes(b"x")
	(tmp_path / "Cam" / "gone-from-box.jpg").write_bytes(b"x")
	(tmp_path / "Cam" / ".wanted.jpg.AbC123").write_bytes(b"x")

	monkeypatch.setattr(
		stage_frames.subprocess,
		"run",
		lambda command, **kwargs: subprocess.CompletedProcess(command, 0, b"", b""),
	)

	stage_frames.copy_camera(FakeBox(), "Cam", ["wanted.jpg"], tmp_path)

	assert sorted(path.name for path in (tmp_path / "Cam").iterdir()) == ["wanted.jpg"]


def test_a_transient_failure_is_retried_and_the_partial_copy_survives(
	tmp_path, monkeypatch, config
):
	waits = []
	attempts = []

	def fake_listing(box, camera):
		return {"Cam_20261018T120000.jpg": 1, "Cam_20261018T120100.jpg": 1}

	def fake_copy(box, camera, names, destination):
		attempts.append(sorted(path.name for path in (destination / camera).glob("*.jpg")))
		(destination / camera).mkdir(parents=True, exist_ok=True)
		(destination / camera / names[0]).write_bytes(b"x")

		if len(attempts) == 1:
			raise OSError("connection lost")

	monkeypatch.setattr(stage_frames, "list_camera_files", fake_listing)
	monkeypatch.setattr(stage_frames, "copy_camera", fake_copy)
	monkeypatch.setattr(stage_frames.time, "sleep", waits.append)

	count = stage_frames.stage_camera(FakeBox(), "Cam", TARGET, config, tmp_path)

	assert count == 2
	assert waits == [30]
	assert attempts == [[], ["Cam_20261018T120000.jpg"]]


def test_last_failed_attempt_removes_folder_and_reports_camera(tmp_path, monkeypatch, config):
	waits = []

	def fake_listing(box, camera):
		return {"Cam_20261018T120000.jpg": 1}

	def fake_copy(box, camera, names, destination):
		(destination / camera).mkdir(parents=True, exist_ok=True)
		(destination / camera / names[0]).write_bytes(b"x")
		raise TimeoutError("stalled")

	monkeypatch.setattr(stage_frames, "list_camera_files", fake_listing)
	monkeypatch.setattr(stage_frames, "copy_camera", fake_copy)
	monkeypatch.setattr(stage_frames.time, "sleep", waits.append)

	failed = stage_frames.stage(FakeBox(), ["Cam"], TARGET, config, tmp_path)

	assert failed == ["Cam"]
	assert waits == [30, 120]
	assert not (tmp_path / "Cam").exists()


def test_a_code_or_config_error_is_not_retried(tmp_path, monkeypatch, config):
	calls = []

	def fake_listing(box, camera):
		calls.append(camera)
		raise ValueError("bad config")

	monkeypatch.setattr(stage_frames, "list_camera_files", fake_listing)
	monkeypatch.setattr(stage_frames.time, "sleep", lambda seconds: pytest.fail("must not wait"))

	with pytest.raises(ValueError):
		stage_frames.stage_camera(FakeBox(), "Cam", TARGET, config, tmp_path)

	assert calls == ["Cam"]


def test_an_unexpected_error_exits_fatal_not_as_some_cameras_failed(tmp_path, monkeypatch):
	temp_root = tmp_path / "temp"
	temp_root.mkdir()
	monkeypatch.setattr(stage_frames, "TEMP_ROOT", temp_root)
	monkeypatch.setattr(
		stage_frames.sys,
		"argv",
		["stage-frames.py", "--no-lock", "--destination", str(temp_root / "staging")],
	)
	monkeypatch.setattr(stage_frames, "run", lambda arguments, destination: {}["missing"])

	assert stage_frames.main() == stage_frames.EXIT_FATAL


def test_camera_without_frames_gets_an_empty_folder_and_no_rsync(tmp_path, monkeypatch):
	def fail(*args, **kwargs):
		raise AssertionError("rsync must not run without names")

	monkeypatch.setattr(stage_frames.subprocess, "run", fail)

	stage_frames.copy_camera(FakeBox(), "Cam", [], tmp_path)

	assert list((tmp_path / "Cam").iterdir()) == []


def test_stage_reports_failed_cameras_and_keeps_the_others(tmp_path, monkeypatch, config):
	def fake_listing(box, camera):
		if camera == "Broken":
			raise OSError("listing failed")

		return {"Cam_20261018T120000.jpg": 1}

	def fake_copy(box, camera, names, destination):
		(destination / camera).mkdir(parents=True)
		(destination / camera / names[0]).write_bytes(b"x")

	monkeypatch.setattr(stage_frames, "list_camera_files", fake_listing)
	monkeypatch.setattr(stage_frames, "copy_camera", fake_copy)
	monkeypatch.setattr(stage_frames.time, "sleep", lambda seconds: None)

	failed = stage_frames.stage(FakeBox(), ["Good", "Broken", "../evil"], TARGET, config, tmp_path)

	assert failed == ["Broken", "../evil"]
	assert (tmp_path / "Good" / "Cam_20261018T120000.jpg").exists()
	assert not (tmp_path / "Broken").exists()
