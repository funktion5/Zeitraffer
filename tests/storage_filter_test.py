import csv
import fcntl
import stat
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest

import src.storage_filter as storage_filter_module
from src.storage_filter import (
	StorageBox,
	acquire_run_lock,
	find_deletion_candidates,
	get_storage_box,
	hash_camera_files,
	list_camera_files,
	parse_arguments,
	parse_ls_output,
	write_report,
)

TODAY = date(2025, 1, 10)
BOX = StorageBox(remote="user@box", base_directory="")


# Run the storage box's commands locally with tmp_path as its home directory,
# so quoting and output parsing are exercised against real ls and sha256sum.
@pytest.fixture
def local_box(tmp_path, monkeypatch):
	def run_locally(self, command, timeout_seconds):
		return subprocess.run(
			["bash", "-c", command],
			cwd=tmp_path,
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			check=False,
		)

	monkeypatch.setattr(StorageBox, "run", run_locally)
	monkeypatch.setattr(storage_filter_module.images_module, "CAMERA_ROOT", tmp_path)
	(tmp_path / "Cam").mkdir()
	return tmp_path / "Cam"


def _write(camera_path: Path, name: str, content: bytes) -> Path:
	path = camera_path / name
	path.write_bytes(content)
	return path


def test_ls_output_keeps_regular_files_with_sizes():
	output = (
		"total 12\n"
		"-rw-r--r-- 1 u1 1108 157852 Aug 17 15:00 cam_250101_120000.jpg\n"
		"-rw-r--r-- 1 u1 1108      0 Aug 17  2024 cam_250101_121500.jpg\n"
		"-rw-r--r-- 1 u1 1108     42 Aug 17 15:00 name with spaces.jpg\n"
		"drwxr-xr-x 2 u1 1108   4096 Aug 17 15:00 archive\n"
		"lrwxrwxrwx 1 u1 1108     10 Aug 17 15:00 link.jpg -> other.jpg\n"
	)

	assert parse_ls_output(output) == {
		"cam_250101_120000.jpg": 157852,
		"cam_250101_121500.jpg": 0,
		"name with spaces.jpg": 42,
	}


def test_storage_box_comes_from_the_live_sshfs_mount(tmp_path):
	mounts = tmp_path / "mounts"
	mounts.write_text(
		"/dev/root / ext4 rw 0 0\nuser-sub1@box.example: /mnt/cameras fuse.sshfs ro,nosuid 0 0\n"
	)

	assert get_storage_box(mounts) == StorageBox("user-sub1@box.example", "")


def test_missing_mount_is_an_error(tmp_path):
	mounts = tmp_path / "mounts"
	mounts.write_text("/dev/root / ext4 rw 0 0\n")

	with pytest.raises(OSError, match="No SSHFS mount"):
		get_storage_box(mounts)


def test_commands_run_over_ssh_with_strict_host_checking(monkeypatch):
	calls = []

	def fake_run(command, **kwargs):
		calls.append(command)
		return subprocess.CompletedProcess(command, 0, stdout="")

	monkeypatch.setattr(storage_filter_module.subprocess, "run", fake_run)

	StorageBox("user@box", "base/").run("ls -l 'base/Cam'", timeout_seconds=5)

	assert calls[0][0] == "ssh"
	assert calls[0][-2:] == ["user@box", "ls -l 'base/Cam'"]
	assert "StrictHostKeyChecking=yes" in calls[0]
	assert StorageBox("user@box", "base/").camera_directory("Cam") == "base/Cam"


def test_listing_and_hashing_handle_awkward_names(local_box):
	name = "cam O'Neil 250101_120000.jpg"
	_write(local_box, name, b"same")

	assert list_camera_files(BOX, "Cam") == {name: 4}
	assert len(hash_camera_files(BOX, "Cam", [name])[name]) == 64


def test_missing_camera_directory_is_an_os_error(local_box):
	with pytest.raises(OSError, match="listing failed"):
		list_camera_files(BOX, "Missing")


def test_unreadable_file_fails_hashing_instead_of_looking_unique(local_box):
	_write(local_box, "cam_250101_120000.jpg", b"same")

	with pytest.raises(OSError, match="hashing failed"):
		hash_camera_files(BOX, "Cam", ["cam_250101_120000.jpg", "vanished.jpg"])


def test_timeouts_become_timeout_errors(monkeypatch):
	def hanging_run(self, command, timeout_seconds):
		raise subprocess.TimeoutExpired(command, timeout_seconds)

	monkeypatch.setattr(StorageBox, "run", hanging_run)

	with pytest.raises(TimeoutError, match="listing timed out"):
		list_camera_files(BOX, "Cam")

	with pytest.raises(TimeoutError, match="hashing timed out"):
		hash_camera_files(BOX, "Cam", ["a.jpg"])


def test_empty_images_are_reported(local_box):
	empty = _write(local_box, "cam_250101_120000.jpg", b"")
	_write(local_box, "cam_250101_121500.jpg", b"frame")

	assert find_deletion_candidates(BOX, "Cam", TODAY) == [(empty, "empty")]


def test_later_same_day_duplicates_are_reported(local_box):
	_write(local_box, "cam_250101_090000.jpg", b"same")
	later = _write(local_box, "cam_250101_120000.jpg", b"same")
	latest = _write(local_box, "cam_250101_150000.jpg", b"same")
	_write(local_box, "cam_250101_160000.jpg", b"diff")

	assert find_deletion_candidates(BOX, "Cam", TODAY) == [
		(later, "duplicate"),
		(latest, "duplicate"),
	]


def test_duplicates_are_found_across_batch_boundaries(local_box, monkeypatch):
	# Tiny batches and several parallel calls: results must not depend on order.
	monkeypatch.setattr(storage_filter_module, "HASH_BATCH_SIZE", 2)
	_write(local_box, "cam_250101_090000.jpg", b"same")
	_write(local_box, "cam_250101_100000.jpg", b"diff")
	_write(local_box, "cam_250101_110000.jpg", b"ffid")
	copy = _write(local_box, "cam_250101_120000.jpg", b"same")
	other_copy = _write(local_box, "cam_250101_130000.jpg", b"diff")

	assert find_deletion_candidates(BOX, "Cam", TODAY) == [
		(copy, "duplicate"),
		(other_copy, "duplicate"),
	]


def test_failed_batch_cancels_the_queued_batches(monkeypatch):
	monkeypatch.setattr(storage_filter_module, "HASH_BATCH_SIZE", 1)
	monkeypatch.setattr(storage_filter_module, "PARALLEL_HASH_CALLS", 1)
	calls = []

	def failing_hash(storage_box, camera, names):
		calls.append(names)

		if len(calls) == 1:
			raise OSError("batch failed")

		# The worker may already have picked up the next batch; keep it busy so
		# the cancel reaches every batch still queued behind it.
		time.sleep(0.2)
		return {name: "hash" for name in names}

	monkeypatch.setattr(storage_filter_module, "hash_camera_files", failing_hash)
	names = [f"{index}.jpg" for index in range(10)]

	with pytest.raises(OSError, match="batch failed"):
		storage_filter_module.hash_in_batches(BOX, "Cam", names)

	# At most the failed batch plus the one already running, never all ten.
	assert len(calls) <= 2


def test_identical_images_on_different_days_are_kept(local_box):
	_write(local_box, "cam_250101_120000.jpg", b"same")
	_write(local_box, "cam_250102_120000.jpg", b"same")

	assert find_deletion_candidates(BOX, "Cam", TODAY) == []


def test_today_unknown_names_and_non_jpg_files_are_skipped(local_box):
	# Today's frames may still be uploading and briefly have 0 bytes.
	_write(local_box, "cam_250110_120000.jpg", b"")
	_write(local_box, "unknown-name.jpg", b"")
	_write(local_box, "notes.txt", b"")

	assert find_deletion_candidates(BOX, "Cam", TODAY) == []


def test_progress_is_logged_before_and_during_the_duplicate_check(local_box, monkeypatch, caplog):
	monkeypatch.setattr(storage_filter_module, "HASH_BATCH_SIZE", 2)
	# Log after every batch so the interval does not depend on test speed.
	monkeypatch.setattr(storage_filter_module, "PROGRESS_LOG_INTERVAL_SECONDS", 0)
	_write(local_box, "cam_250101_120000.jpg", b"")
	_write(local_box, "cam_250102_090000.jpg", b"same")
	_write(local_box, "cam_250102_120000.jpg", b"same")
	_write(local_box, "cam_250103_090000.jpg", b"diff")
	_write(local_box, "cam_250103_120000.jpg", b"ffid")

	with caplog.at_level("INFO", logger="timelapse"):
		find_deletion_candidates(BOX, "Cam", TODAY)

	messages = [record.getMessage() for record in caplog.records]
	assert any("listed=5 | empty=1 | checking 4 files for duplicates" in m for m in messages)
	assert any("checked 4/4 files for duplicates" in m for m in messages)


def test_report_is_excel_friendly_and_closed_to_other(tmp_path):
	report_path = tmp_path / "reports" / "storage-filter" / "Cam_2025-01-10_120000.csv"
	candidates = [
		(Path("/cams/Cam/a.jpg"), "empty"),
		(Path("/cams/Cam/b.jpg"), "duplicate"),
	]

	write_report("Cam", candidates, report_path)

	assert report_path.read_bytes().startswith(b"\xef\xbb\xbf")

	with report_path.open(encoding="utf-8-sig", newline="") as report_file:
		rows = list(csv.reader(report_file, delimiter=";"))

	assert rows == [
		["camera", "path", "reason"],
		["Cam", "/cams/Cam/a.jpg", "empty"],
		["Cam", "/cams/Cam/b.jpg", "duplicate"],
	]
	assert not list(report_path.parent.glob(".*.tmp"))

	for directory in (report_path.parent, report_path.parent.parent):
		assert not directory.stat().st_mode & stat.S_IRWXO


def test_lock_held_by_another_run_is_refused(tmp_path):
	lock_path = tmp_path / "zeitraffer-run.lock"

	with lock_path.open("a") as other_run:
		fcntl.flock(other_run, fcntl.LOCK_EX | fcntl.LOCK_NB)

		with pytest.raises(RuntimeError, match="holds the lock"):
			with acquire_run_lock(lock_path):
				pass

	with acquire_run_lock(lock_path):
		pass


def test_camera_selection_is_required_and_exclusive():
	with pytest.raises(SystemExit):
		parse_arguments([])

	with pytest.raises(SystemExit):
		parse_arguments(["--cameras", "Cam", "--all-cameras"])

	assert parse_arguments(["--cameras", "A", "B"]).cameras == ["A", "B"]


# main() must never prune the real logs/ directory or contact the storage box.
@pytest.fixture
def isolated_main(monkeypatch):
	monkeypatch.setattr(storage_filter_module, "cleanup_old_logs", lambda retention_days: None)
	monkeypatch.setattr(storage_filter_module, "get_cameras", lambda: ["Cam"])
	monkeypatch.setattr(storage_filter_module, "get_storage_box", lambda: BOX)


@pytest.mark.usefixtures("isolated_main")
def test_main_rejects_unknown_cameras():
	with pytest.raises(ValueError, match="Missing"):
		storage_filter_module.main(["--cameras", "Missing"])


@pytest.mark.usefixtures("isolated_main")
def test_main_writes_one_report_per_camera(tmp_path, local_box, monkeypatch):
	_write(local_box, "cam_250101_120000.jpg", b"")
	lock_path = tmp_path / "state" / "zeitraffer-run.lock"
	monkeypatch.setattr(storage_filter_module, "REPORT_ROOT", tmp_path / "reports" / "sf")
	monkeypatch.setattr(
		storage_filter_module,
		"acquire_run_lock",
		lambda: acquire_run_lock(lock_path),
	)

	assert storage_filter_module.main(["--cameras", "Cam"]) == 0

	reports = list((tmp_path / "reports" / "sf").glob("Cam_*.csv"))
	assert len(reports) == 1
	assert ";empty" in reports[0].read_text(encoding="utf-8-sig")


@pytest.mark.usefixtures("isolated_main")
def test_main_continues_after_a_failing_camera(tmp_path, local_box, monkeypatch):
	monkeypatch.setattr(storage_filter_module, "get_cameras", lambda: ["Cam", "Gone"])
	monkeypatch.setattr(storage_filter_module, "REPORT_ROOT", tmp_path / "reports" / "sf")
	monkeypatch.setattr(
		storage_filter_module,
		"acquire_run_lock",
		lambda: acquire_run_lock(tmp_path / "state" / "zeitraffer-run.lock"),
	)

	assert storage_filter_module.main(["--cameras", "Gone", "Cam"]) == 1
	assert len(list((tmp_path / "reports" / "sf").glob("Cam_*.csv"))) == 1
