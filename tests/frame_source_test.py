import itertools
import json
import logging
import multiprocessing
import os
import signal
import stat
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from frame_source_fakes import LS_DIRECTORY, LS_FILE, LS_SYMLINK, FakeBox

import src.frame_source as frame_source_module
import src.images as images_module
from src.frame_source import (
	FETCH_RETRY_WAIT_SECONDS,
	FRAME_CACHE_ENV,
	FRAME_CACHE_MARKER,
	HEARTBEAT_SECONDS,
	NAME_LISTING_TIMEOUT_SECONDS,
	RSYNC_IDLE_TIMEOUT_SECONDS,
	FrameFetchError,
	LocalFrameSource,
	SshFrameSource,
	create_frame_cache,
	release_leftovers,
)
from src.storage_filter import StorageBox


def test_frame_fetch_error_is_an_oserror():
	# The jobs already treat OSError as an operational failure of one camera.
	assert issubclass(FrameFetchError, OSError)


def test_local_list_cameras_returns_sorted_visible_directories(tmp_path):
	for name in ("Zebra", "Alpha", ".hidden"):
		(tmp_path / name).mkdir()
	(tmp_path / "notes.txt").write_text("not a camera")

	assert LocalFrameSource(tmp_path).list_cameras() == ["Alpha", "Zebra"]


def test_local_list_names_returns_every_entry_name(tmp_path):
	camera = tmp_path / "Alpha"
	camera.mkdir()
	for name in ("a_20260101T1000.jpg", "b.JPG", "c.txt"):
		(camera / name).write_bytes(b"x")

	names = LocalFrameSource(tmp_path).list_names("Alpha")

	assert sorted(names) == ["a_20260101T1000.jpg", "b.JPG", "c.txt"]


# The isolated workers tick a progress callback per name and kill a scan that goes quiet for the
# stall timeout. A slow mount must keep yielding names while the folder is read, not hand over the
# whole listing at the end.
def test_local_list_names_streams_entries_while_the_folder_is_read(monkeypatch, tmp_path):
	events = []

	class SlowEntries:
		def __enter__(self):
			return self

		def __exit__(self, *exc_info):
			return False

		def __iter__(self):
			for name in ("a.jpg", "b.jpg"):
				events.append(f"read {name}")
				yield SimpleNamespace(name=name)

	monkeypatch.setattr(frame_source_module.os, "scandir", lambda path: SlowEntries())

	for name in LocalFrameSource(tmp_path).list_names("Alpha"):
		events.append(f"got {name}")

	assert events == ["read a.jpg", "got a.jpg", "read b.jpg", "got b.jpg"]


def test_local_path_for_joins_root_camera_and_name(tmp_path):
	source = LocalFrameSource(tmp_path)

	assert source.path_for("Alpha", "a.jpg") == tmp_path / "Alpha" / "a.jpg"


def test_local_localize_and_release_change_nothing(tmp_path):
	camera = tmp_path / "Alpha"
	camera.mkdir()
	frame = camera / "a.jpg"
	frame.write_bytes(b"x")
	source = LocalFrameSource(tmp_path)
	calls = []

	source.localize("Alpha", [frame], lambda: calls.append(1))
	source.release("Alpha")

	assert frame.read_bytes() == b"x"
	assert sorted(path.name for path in tmp_path.rglob("*")) == ["Alpha", "a.jpg"]
	# Local files need no fetch, so there is nothing to report progress on.
	assert calls == []


def test_get_frame_source_follows_a_patched_camera_root(monkeypatch, tmp_path):
	first = tmp_path / "first"
	second = tmp_path / "second"
	first.mkdir()
	second.mkdir()

	monkeypatch.setattr(images_module, "CAMERA_ROOT", first)
	assert images_module.get_frame_source() == LocalFrameSource(first)

	monkeypatch.setattr(images_module, "CAMERA_ROOT", second)
	assert images_module.get_frame_source() == LocalFrameSource(second)
	assert isinstance(images_module.get_frame_source().root, Path)


def test_ssh_list_cameras_returns_directories_only():
	box = FakeBox(
		[
			LS_DIRECTORY.format("Zebra"),
			LS_DIRECTORY.format("Alpha"),
			LS_FILE.format("notes.txt"),
		]
	)

	assert SshFrameSource(box, Path("/cache")).list_cameras() == ["Alpha", "Zebra"]
	assert box.commands == [("ls -l cameras", NAME_LISTING_TIMEOUT_SECONDS)]


def test_ssh_list_names_returns_regular_files():
	box = FakeBox(
		[
			LS_FILE.format("a_20260101T1000.jpg"),
			LS_DIRECTORY.format("subfolder"),
			LS_SYMLINK.format("link.jpg"),
			LS_FILE.format("b.JPG"),
		]
	)

	names = SshFrameSource(box, Path("/cache")).list_names("Alpha")

	assert sorted(names) == ["a_20260101T1000.jpg", "b.JPG"]
	assert box.commands == [("ls -l cameras/Alpha", NAME_LISTING_TIMEOUT_SECONDS)]


def test_ssh_list_names_keeps_names_with_spaces():
	box = FakeBox([LS_FILE.format("my frame 01.jpg")])

	assert list(SshFrameSource(box, Path("/cache")).list_names("Alpha")) == ["my frame 01.jpg"]


def test_ssh_listing_failure_is_an_oserror():
	box = FakeBox(returncode=2, stderr="Permission denied\n")

	with pytest.raises(OSError, match="Permission denied"):
		SshFrameSource(box, Path("/cache")).list_names("Alpha")


def test_ssh_listing_timeout_is_a_timeouterror():
	box = FakeBox(raises=subprocess.TimeoutExpired("ssh", NAME_LISTING_TIMEOUT_SECONDS))

	with pytest.raises(TimeoutError):
		SshFrameSource(box, Path("/cache")).list_names("Alpha")

	with pytest.raises(TimeoutError):
		SshFrameSource(box, Path("/cache")).list_cameras()


def test_ssh_path_for_points_into_the_cache():
	source = SshFrameSource(FakeBox(), Path("/cache"))

	assert source.path_for("Alpha", "a.jpg") == Path("/cache/Alpha/a.jpg")


# The listing is the stall timeout's neighbour: one ssh command sends no progress ticks, so its own
# timeout has to fire first or the worker is killed as "stalled" and the real error is hidden.
def test_ssh_listing_timeout_is_below_the_configured_stall_timeout():
	config_path = Path(__file__).parent.parent / "config" / "config.json"
	stall_timeout = json.loads(config_path.read_text())["image_scan_stall_timeout_seconds"]

	assert NAME_LISTING_TIMEOUT_SECONDS < stall_timeout


UNSAFE_NAMES = ["../../x.jpg", "..", "-rf.jpg", "tab\there.jpg", "a/b.jpg"]
# Spaces and shell characters are fine in a file name (names travel in a file list) but not in a
# camera name, which goes into rsync's remote path: older rsync versions pass that to the box's
# shell.
UNSAFE_CAMERAS = [*UNSAFE_NAMES, "a b", "a;b", "$HOME", "a`b`", "a'b", "Caf\u00e9"]


# Names come from a remote system. One odd entry must not take a whole camera, or every camera,
# down (the local source simply counts such a file), so a listing skips it and reports it.
@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_ssh_listing_skips_unsafe_file_names_and_keeps_the_rest(name):
	box = FakeBox([LS_FILE.format(name), LS_FILE.format("ok.jpg")])

	assert SshFrameSource(box, Path("/cache")).list_names("Alpha") == ["ok.jpg"]


@pytest.mark.parametrize("name", UNSAFE_CAMERAS)
def test_ssh_camera_listing_skips_unsafe_camera_names(name):
	box = FakeBox([LS_DIRECTORY.format(name), LS_DIRECTORY.format("Alpha")])

	assert SshFrameSource(box, Path("/cache")).list_cameras() == ["Alpha"]


# Asking for a path to such a name is a bug or an attack, and raises.
@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_ssh_path_for_refuses_unsafe_file_names(name):
	with pytest.raises(FrameFetchError):
		SshFrameSource(FakeBox(), Path("/cache")).path_for("Alpha", name)


@pytest.mark.parametrize("camera", UNSAFE_CAMERAS)
def test_ssh_refuses_unsafe_camera_names_everywhere(camera):
	source = SshFrameSource(FakeBox(), Path("/cache"))

	with pytest.raises(FrameFetchError):
		source.list_names(camera)

	with pytest.raises(FrameFetchError):
		source.path_for(camera, "a.jpg")

	with pytest.raises(FrameFetchError):
		source.localize(camera, [Path("/cache/x/a.jpg")])


# The ssh source with a box from the environment, a cache root inside tmp_path and no cache root
# chosen yet (the monkeypatch round trip makes the test restore "unset" afterwards).
@pytest.fixture
def ssh_env(monkeypatch, tmp_path):
	monkeypatch.setenv("TIMELAPSE_FRAME_SOURCE", "ssh")
	monkeypatch.setenv("TIMELAPSE_STORAGE_BOX", "box:cameras")
	monkeypatch.setenv(FRAME_CACHE_ENV, "placeholder")
	monkeypatch.delenv(FRAME_CACHE_ENV)
	monkeypatch.setattr(images_module, "PROJECT_ROOT", tmp_path)

	return tmp_path


@pytest.mark.parametrize("value", [None, "", "local"])
def test_unset_or_local_gives_the_local_source(monkeypatch, value):
	if value is None:
		monkeypatch.delenv("TIMELAPSE_FRAME_SOURCE", raising=False)
	else:
		monkeypatch.setenv("TIMELAPSE_FRAME_SOURCE", value)

	assert images_module.get_frame_source() == LocalFrameSource(images_module.CAMERA_ROOT)


def test_ssh_gives_an_ssh_source_with_the_box_from_the_environment(ssh_env):
	source = images_module.get_frame_source()

	assert isinstance(source, SshFrameSource)
	assert source.box == StorageBox(remote="box", base_directory="cameras")
	assert source.cache_root.parent == ssh_env / "temp" / "frame-cache"
	assert source.temp_root == ssh_env / "temp"


def test_unknown_value_is_rejected(monkeypatch):
	monkeypatch.setenv("TIMELAPSE_FRAME_SOURCE", "nfs")

	with pytest.raises(ValueError, match="'local' or 'ssh'"):
		images_module.get_frame_source()


# Choosing the folder must not touch the disk: a run that only lists leaves nothing behind.
def test_cache_root_is_chosen_once_and_exported_without_creating_it(ssh_env):
	first = images_module.get_frame_source().cache_root
	second = images_module.get_frame_source().cache_root

	assert first == second
	assert os.environ[FRAME_CACHE_ENV] == str(first)
	assert not first.exists()


def test_cache_root_is_created_once_with_a_marker(tmp_path):
	root = tmp_path / "frame-cache" / "run-1"

	create_frame_cache(root)
	create_frame_cache(root)

	assert (root / FRAME_CACHE_MARKER).is_file()
	assert sorted(path.name for path in root.iterdir()) == [FRAME_CACHE_MARKER]


# Fetched frames are unblurred and show people: only the login user may read them.
def test_cache_root_is_owner_only(tmp_path):
	root = tmp_path / "frame-cache" / "run-1"
	old_umask = os.umask(0o002)

	try:
		create_frame_cache(root)
		assert stat.S_IMODE(root.stat().st_mode) == 0o700

		# A folder that already exists with looser rights is tightened too.
		root.chmod(0o777)
		create_frame_cache(root)
		assert stat.S_IMODE(root.stat().st_mode) == 0o700

	finally:
		os.umask(old_umask)


# macOS (and future Python defaults) start workers with "spawn", which shares no module variables.
def test_spawned_child_process_sees_the_same_cache_root(ssh_env):
	root = images_module.get_frame_source().cache_root

	with multiprocessing.get_context("spawn").Pool(1) as pool:
		assert pool.apply(os.getenv, (FRAME_CACHE_ENV,)) == str(root)


# A root chosen inside a worker never reaches the parent, whose cleanup would then find nothing and
# leave unblurred frames on disk. So the parent has to choose it before the worker is started.
def start_images_scan():
	day = date(2026, 9, 16)
	noon = datetime(2026, 9, 16, 12)
	images_module.find_images_isolated("Alpha", day, noon, noon, 0, 1)


def start_daily_scan():
	day = date(2026, 9, 16)
	noon = datetime(2026, 9, 16, 12)
	images_module.find_daily_images_isolated("Alpha", day, noon, noon, day, 0, 1)


def start_interval_scan():
	day = date(2026, 9, 16)
	images_module.find_interval_images_isolated("Alpha", day, day, 1, {}, 90)


@pytest.mark.parametrize("start_scan", [start_images_scan, start_daily_scan, start_interval_scan])
def test_a_worker_that_is_the_first_caller_does_not_create_its_own_root(
	ssh_env, monkeypatch, start_scan
):
	seen = []

	def fake_run_isolated_worker(**kwargs):
		seen.append(os.environ.get(FRAME_CACHE_ENV))
		return []

	monkeypatch.setattr(images_module, "run_isolated_worker", fake_run_isolated_worker)

	start_scan()

	assert seen[0] is not None


# Stands in for subprocess.Popen: records every rsync start, answers with the given exit codes (the
# last one repeats) and on success creates the requested files, as a real transfer would. With
# slow_rounds the process keeps "running" for that many heartbeat intervals first; with interrupt
# the wait is cut short by SystemExit, which is what the worker's SIGTERM handler raises.
class FakeRsync:
	def __init__(self, *exit_codes, stderr=b"", slow_rounds=0, interrupt=False):
		self.exit_codes = exit_codes or (0,)
		self.stderr = stderr
		self.slow_rounds = slow_rounds
		self.interrupt = interrupt
		self.calls = []
		self.inputs = []
		self.processes = []
		self.killed = 0

	def __call__(self, command, **kwargs):
		self.calls.append((command, kwargs))
		exit_code = self.exit_codes[min(len(self.calls), len(self.exit_codes)) - 1]
		# A pid no system has, so a missing patch of os.killpg could never hit a real process group.
		process = FakeProcess(self, command, exit_code, 9_000_000 + len(self.calls))
		self.processes.append(process)

		return process

	# Stands in for os.killpg: rsync was started as a session leader, so its group is its pid.
	def killpg(self, group_id, signal_number):
		assert signal_number == signal.SIGKILL

		for process in self.processes:
			if process.pid == group_id:
				process.kill()

	# The names sent to rsync on standard input in call number `index`.
	def names(self, index):
		return self.inputs[index].decode().split("\0")[:-1]


class FakeProcess:
	def __init__(self, rsync, command, exit_code, pid):
		self.rsync = rsync
		self.pid = pid
		self.command = command
		self.exit_code = exit_code
		self.input = None
		self.rounds = 0
		self.returncode = None

	def communicate(self, input=None, timeout=None):
		if input is not None:
			self.input = input
			self.rsync.inputs.append(input)

		if self.rsync.interrupt:
			raise SystemExit(1)

		if timeout is not None and self.rounds < self.rsync.slow_rounds:
			self.rounds += 1
			raise subprocess.TimeoutExpired(self.command, timeout)

		self.returncode = self.exit_code

		if self.exit_code == 0 and self.input is not None:
			for name in self.input.decode().split("\0")[:-1]:
				(Path(self.command[-1]) / name).write_bytes(b"frame")

		return None, self.rsync.stderr

	def kill(self):
		self.rsync.killed += 1
		self.returncode = -9

	def poll(self):
		return self.returncode

	def wait(self):
		return self.returncode


def fetcher(monkeypatch, tmp_path, *exit_codes, stderr=b"", slow_rounds=0, interrupt=False):
	rsync = FakeRsync(*exit_codes, stderr=stderr, slow_rounds=slow_rounds, interrupt=interrupt)
	sleeps = []
	monkeypatch.setattr(frame_source_module.subprocess, "Popen", rsync)
	monkeypatch.setattr(frame_source_module.os, "killpg", rsync.killpg)
	monkeypatch.setattr(frame_source_module.time, "sleep", sleeps.append)

	# temp_root is tmp_path, so the cache folder counts as inside it for the guarded cleanup.
	return SshFrameSource(FakeBox(), tmp_path / "cache", tmp_path), rsync, sleeps


def frames(source, *names):
	return [source.path_for("Alpha", name) for name in names]


def test_fetch_runs_rsync_with_nul_separated_names(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	source.localize("Alpha", frames(source, "b.jpg", "a.jpg"))

	command = rsync.calls[0][0]
	assert command[0] == "rsync"
	assert "--from0" in command
	assert "--files-from=-" in command
	assert f"--timeout={RSYNC_IDLE_TIMEOUT_SECONDS}" in command
	assert "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes" in command
	assert rsync.inputs[0] == b"a.jpg\0b.jpg\0"
	# Its own process group, so one signal reaches rsync and the processes it starts.
	assert rsync.calls[0][1]["start_new_session"] is True
	assert all(path.is_file() for path in frames(source, "a.jpg", "b.jpg"))
	assert (tmp_path / "cache" / FRAME_CACHE_MARKER).is_file()


# Direction: the box is the source and the cache folder the destination, never the reverse. This is
# what lets frame_source.py start rsync under the structural guard in privacy_box_writer_test.
def test_fetch_rsync_pulls_from_the_box_into_the_cache(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	source.localize("Alpha", frames(source, "a.jpg"))

	command = rsync.calls[0][0]
	assert command[-2] == "box:cameras/Alpha/"
	assert command[-1] == f"{tmp_path / 'cache' / 'Alpha'}/"
	assert not command[-1].startswith("box:")


# The blur cache recognises a frame by the size and modification time of its local copy, and copy2
# keeps the time of the fetched file. Without -t every fetched frame would look new and each
# earlier detection would be lost.
def test_fetch_keeps_the_modification_time_of_the_box(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	source.localize("Alpha", frames(source, "a.jpg"))

	assert "-t" in rsync.calls[0][0]


def test_fetch_keeps_names_with_spaces_intact(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	source.localize("Alpha", frames(source, "my frame 01.jpg"))

	assert rsync.inputs[0] == b"my frame 01.jpg\0"
	assert frames(source, "my frame 01.jpg")[0].is_file()


# Everything the job needs goes through one rsync, however many frames that is.
def test_all_frames_are_fetched_with_one_rsync(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)
	names = [f"{index:05d}.jpg" for index in range(1200)]

	source.localize("Alpha", frames(source, *names))

	assert len(rsync.calls) == 1
	assert rsync.names(0) == names


# The worker running this is killed after 60 s without a progress tick, and a running rsync sends
# none. So the wait for it wakes up every heartbeat and ticks, and a process that is still moving
# bytes is never killed.
def test_the_wait_for_rsync_ticks_so_the_worker_is_not_killed_as_stalled(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path, slow_rounds=3)
	ticks = []

	source.localize("Alpha", frames(source, "a.jpg"), lambda: ticks.append(1))

	assert len(rsync.calls) == 1
	assert len(ticks) == 3
	assert rsync.killed == 0
	assert frames(source, "a.jpg")[0].is_file()


def test_failed_fetch_is_retried_with_the_configured_waits(monkeypatch, tmp_path):
	source, rsync, sleeps = fetcher(monkeypatch, tmp_path, 255, 255, 0)
	ticks = []

	source.localize("Alpha", frames(source, "a.jpg"), lambda: ticks.append(1))

	assert len(rsync.calls) == 3
	assert sum(sleeps) == sum(FETCH_RETRY_WAIT_SECONDS)
	assert frames(source, "a.jpg")[0].is_file()
	# The waits are sliced and tick: a wait longer than the stall timeout would otherwise get the
	# worker killed as "stalled" before the retry happens.
	assert max(sleeps) <= HEARTBEAT_SECONDS
	assert len(ticks) == len(sleeps)


def test_exhausted_retries_remove_the_camera_folder_and_raise(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path, 255, stderr=b"connection refused")
	earlier = source.path_for("Alpha", "earlier.jpg")
	earlier.parent.mkdir(parents=True)
	earlier.write_bytes(b"frame")

	with pytest.raises(FrameFetchError, match="exit 255.*connection refused"):
		source.localize("Alpha", frames(source, "a.jpg"))

	assert len(rsync.calls) == len(FETCH_RETRY_WAIT_SECONDS) + 1
	# A half-fetched camera must never be handed on.
	assert not (tmp_path / "cache" / "Alpha").exists()


# A frame listed on the box can vanish before rsync runs: the camera fails, it is never built from
# fewer frames.
def test_rsync_vanished_files_exit_code_23_fails_the_camera(monkeypatch, tmp_path):
	source, _, _ = fetcher(monkeypatch, tmp_path, 23, stderr=b"some files vanished")

	with pytest.raises(FrameFetchError, match="exit 23"):
		source.localize("Alpha", frames(source, "a.jpg", "b.jpg"))

	assert not (tmp_path / "cache" / "Alpha").exists()


# rsync's own idle timeout normally ends a hung transfer; this is the outer limit for a process
# that trickles forever. The fake clock jumps one heartbeat per reading.
def test_an_rsync_that_never_finishes_is_killed_and_fails_the_camera(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path, 255, slow_rounds=10**9)
	clock = itertools.count(0, HEARTBEAT_SECONDS)
	monkeypatch.setattr(frame_source_module.time, "monotonic", lambda: next(clock))

	with pytest.raises(FrameFetchError, match="did not finish"):
		source.localize("Alpha", frames(source, "a.jpg"))

	assert rsync.killed == len(FETCH_RETRY_WAIT_SECONDS) + 1
	assert not (tmp_path / "cache" / "Alpha").exists()


def test_rsync_that_cannot_start_fails_the_camera(monkeypatch, tmp_path):
	source, _, _ = fetcher(monkeypatch, tmp_path)

	def missing_rsync(command, **kwargs):
		raise FileNotFoundError("rsync")

	monkeypatch.setattr(frame_source_module.subprocess, "Popen", missing_rsync)

	with pytest.raises(FrameFetchError, match="could not start"):
		source.localize("Alpha", frames(source, "a.jpg"))


# Manual Weekly runs one worker, and so one localize, per day: a later call must keep what an
# earlier one fetched, and fetch only what is missing.
def test_a_later_call_keeps_the_files_of_an_earlier_call(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	source.localize("Alpha", frames(source, "a.jpg", "b.jpg"))
	source.localize("Alpha", frames(source, "b.jpg", "c.jpg"))

	assert all(path.is_file() for path in frames(source, "a.jpg", "b.jpg", "c.jpg"))
	assert rsync.names(1) == ["c.jpg"]


def test_nothing_missing_runs_no_rsync_and_creates_nothing(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	source.localize("Alpha", [])

	assert rsync.calls == []
	assert not (tmp_path / "cache").exists()


def test_localize_refuses_unsafe_names_before_any_rsync(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path)

	with pytest.raises(FrameFetchError):
		source.localize("Alpha", [Path("/cache/Alpha/-rf.jpg")])

	assert rsync.calls == []


# A source whose cache folder sits inside tmp_path/temp, holds the marker and one frame per camera.
def source_with_frames(tmp_path, *cameras):
	root = tmp_path / "temp" / "frame-cache" / "run-1"
	create_frame_cache(root)

	for camera in cameras:
		(root / camera).mkdir()
		(root / camera / "a.jpg").write_bytes(b"frame")

	return SshFrameSource(FakeBox(), root, tmp_path / "temp")


def test_release_removes_only_the_named_camera_folder(tmp_path):
	source = source_with_frames(tmp_path, "Alpha", "Beta")

	source.release("Alpha")

	assert not (source.cache_root / "Alpha").exists()
	assert (source.cache_root / "Beta" / "a.jpg").is_file()
	assert (source.cache_root / FRAME_CACHE_MARKER).is_file()


def test_release_refuses_a_cache_root_without_the_marker(tmp_path):
	source = source_with_frames(tmp_path, "Alpha")
	(source.cache_root / FRAME_CACHE_MARKER).unlink()

	with pytest.raises(ValueError, match="marker"):
		source.release("Alpha")

	assert (source.cache_root / "Alpha" / "a.jpg").is_file()


# Strictly inside temp/: a folder elsewhere, temp/ itself and a symlink that leads out all count
# as outside, and nothing in them is touched.
def test_release_refuses_a_root_outside_temp(tmp_path):
	outside = tmp_path / "elsewhere" / "run-1"
	create_frame_cache(outside)
	(outside / "Alpha").mkdir()
	(outside / "Alpha" / "a.jpg").write_bytes(b"frame")
	temp = tmp_path / "temp"
	create_frame_cache(temp)
	link = temp / "frame-cache-link"
	link.symlink_to(outside)

	for root in (outside, temp, link):
		source = SshFrameSource(FakeBox(), root, temp)

		with pytest.raises(ValueError, match="inside"):
			source.release("Alpha")

	assert (outside / "Alpha" / "a.jpg").is_file()
	assert (temp / FRAME_CACHE_MARKER).is_file()


@pytest.mark.parametrize("camera", ["../Beta", "a/b", ".", "..", ""])
def test_release_refuses_unsafe_camera_names(tmp_path, camera):
	source = source_with_frames(tmp_path, "Alpha", "Beta")

	with pytest.raises(ValueError, match="camera name"):
		source.release(camera)

	assert (source.cache_root / "Alpha" / "a.jpg").is_file()
	assert (source.cache_root / "Beta" / "a.jpg").is_file()


# A job that failed before it fetched anything, or a second release, must not raise.
def test_release_ignores_a_missing_folder(tmp_path):
	temp = tmp_path / "temp"
	never_created = SshFrameSource(FakeBox(), temp / "frame-cache" / "run-9", temp)

	never_created.release("Alpha")

	source = source_with_frames(tmp_path, "Alpha")
	source.release("Gamma")
	source.release("Alpha")
	source.release("Alpha")

	assert not (source.cache_root / "Alpha").exists()


# The worker is stopped with SIGTERM, which image_worker turns into SystemExit: rsync must not be
# left running to write into the cache after it has been cleaned up. Not retried either.
def test_rsync_is_killed_when_the_worker_is_told_to_stop(monkeypatch, tmp_path):
	source, rsync, _ = fetcher(monkeypatch, tmp_path, interrupt=True)

	with pytest.raises(SystemExit):
		source.localize("Alpha", frames(source, "a.jpg"))

	assert rsync.killed == 1
	assert len(rsync.calls) == 1


# A process id that belonged to a process that has ended.
def dead_pid():
	process = subprocess.Popen([sys.executable, "-c", "pass"])
	process.wait()

	return process.pid


# Folders under temp/frame-cache the way runs leave them: one of a run that is over, one of a run
# that is still going (this process), and three that are none of our business.
def leftover_cache(tmp_path):
	parent = tmp_path / "temp" / "frame-cache"
	folders = {
		"over": f"{dead_pid()}-aaaaaaaa",
		"running": f"{os.getpid()}-bbbbbbbb",
		"no-marker": f"{dead_pid()}-cccccccc",
		"odd-name": "marked-but-odd",
		"foreign": "foreign",
	}

	for key, name in folders.items():
		folder = parent / name
		folder.mkdir(parents=True)
		(folder / "a.jpg").write_bytes(b"frame")

		if key in ("over", "running", "odd-name"):
			(folder / FRAME_CACHE_MARKER).touch()

	return {key: parent / name for key, name in folders.items()}


# Another job may be running (a flagger or backfill that starts while the nightly run works, before
# it holds the run lock), so only the folders of runs that are over are removed.
def test_release_leftovers_removes_only_folders_of_runs_that_are_over(tmp_path):
	folders = leftover_cache(tmp_path)

	release_leftovers(tmp_path / "temp")

	assert not folders["over"].exists()
	assert (folders["running"] / "a.jpg").is_file()
	assert (folders["no-marker"] / "a.jpg").is_file()
	assert (folders["odd-name"] / "a.jpg").is_file()
	assert (folders["foreign"] / "a.jpg").is_file()


# A finished run leaves its run folder with only the marker, so the next run finding that is the
# normal case and must not warn. Frames left in it are a real leftover and keep the warning.
def test_the_empty_folder_of_a_finished_run_is_removed_without_a_warning(tmp_path, caplog):
	folder = tmp_path / "temp" / "frame-cache" / f"{dead_pid()}-aaaaaaaa"
	create_frame_cache(folder)

	with caplog.at_level(logging.INFO, logger="timelapse"):
		release_leftovers(tmp_path / "temp")

	assert not folder.exists()
	assert [record.levelno for record in caplog.records] == [logging.INFO]


def test_a_leftover_with_frames_is_removed_with_a_warning(tmp_path, caplog):
	folders = leftover_cache(tmp_path)

	with caplog.at_level(logging.INFO, logger="timelapse"):
		release_leftovers(tmp_path / "temp")

	assert not folders["over"].exists()
	assert [record.levelno for record in caplog.records] == [logging.WARNING]
	assert "left behind by an earlier run" in caplog.text


def test_release_leftovers_does_not_follow_a_symlinked_cache_folder(tmp_path):
	outside = tmp_path / "elsewhere" / "frame-cache"
	leftover = outside / f"{dead_pid()}-aaaaaaaa"
	leftover.mkdir(parents=True)
	(leftover / FRAME_CACHE_MARKER).touch()
	temp = tmp_path / "temp"
	temp.mkdir()
	(temp / "frame-cache").symlink_to(outside)

	release_leftovers(temp)

	assert leftover.is_dir()


def test_release_leftovers_without_a_cache_folder_does_nothing(tmp_path):
	release_leftovers(tmp_path / "temp")

	assert not (tmp_path / "temp").exists()


# A run that starts clears what an earlier run left behind (a crash, a hard kill). It does so once:
# later calls in the same run reuse the exported root and must never clear anything again.
def test_choosing_a_new_cache_root_clears_leftovers_once(ssh_env):
	folders = leftover_cache(ssh_env)

	images_module.get_frame_source()

	assert not folders["over"].exists()
	assert folders["running"].is_dir()

	again = folders["over"].parent / f"{dead_pid()}-dddddddd"
	again.mkdir()
	(again / FRAME_CACHE_MARKER).touch()
	images_module.get_frame_source()

	assert again.is_dir()


# TIMELAPSE_FRAME_CACHE is an environment variable: a stray export in a shell or crontab must not
# make a run reuse an old folder, or point its cleanup and chmod at an arbitrary directory. Only a
# folder like <project>/temp/frame-cache/<pid>-<random> is accepted.
def test_a_cache_root_from_the_environment_must_be_a_run_folder(ssh_env, monkeypatch):
	parent = ssh_env / "temp" / "frame-cache"
	elsewhere = ssh_env / "other" / "frame-cache" / "12-aaaaaaaa"
	rejected = [
		ssh_env,
		parent,
		parent / "not-a-run",
		parent / "12-xyz",
		parent / "12-aaaaaaaa" / "x",
	]

	for value in [*rejected, elsewhere]:
		monkeypatch.setenv(FRAME_CACHE_ENV, str(value))

		with pytest.raises(ValueError, match=FRAME_CACHE_ENV):
			images_module.get_frame_source()

	monkeypatch.setenv(FRAME_CACHE_ENV, str(parent / "12-aaaaaaaa"))

	assert images_module.get_frame_source().cache_root == parent / "12-aaaaaaaa"
