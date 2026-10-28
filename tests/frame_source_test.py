import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.frame_source as frame_source_module
import src.images as images_module
from src.frame_source import (
	NAME_LISTING_TIMEOUT_SECONDS,
	FrameFetchError,
	LocalFrameSource,
	SshFrameSource,
)


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


LS_DIRECTORY = "drwxr-xr-x 2 user group 4096 Oct 28 09:00 {}"
LS_FILE = "-rw-r--r-- 1 user group 1234 Oct 28 09:00 {}"
LS_SYMLINK = "lrwxrwxrwx 1 user group 9 Oct 28 09:00 {} -> elsewhere"


# Stands in for StorageBox: answers every command with a canned `ls -l` listing.
class FakeBox:
	remote = "box"
	base_directory = "cameras"

	def __init__(self, lines=(), returncode=0, stderr="", raises=None):
		self.stdout = "\n".join(["total 8", *lines])
		self.returncode = returncode
		self.stderr = stderr
		self.raises = raises
		self.commands = []

	def camera_directory(self, camera):
		return f"{self.base_directory}/{camera}"

	def run(self, command, timeout_seconds):
		self.commands.append((command, timeout_seconds))

		if self.raises is not None:
			raise self.raises

		return subprocess.CompletedProcess([command], self.returncode, self.stdout, self.stderr)


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


# Names come from a remote system and end up in local paths and the rsync file list.
@pytest.mark.parametrize("name", ["../../x.jpg", "..", "-rf.jpg", "tab\there.jpg", "a/b.jpg"])
def test_ssh_unsafe_names_from_the_box_are_refused(name):
	source = SshFrameSource(FakeBox([LS_FILE.format(name)]), Path("/cache"))

	with pytest.raises(FrameFetchError):
		source.list_names("Alpha")

	with pytest.raises(FrameFetchError):
		SshFrameSource(FakeBox([LS_DIRECTORY.format(name)]), Path("/cache")).list_cameras()

	# The same check guards the one place that builds local paths, and the camera argument.
	with pytest.raises(FrameFetchError):
		source.path_for("Alpha", name)

	with pytest.raises(FrameFetchError):
		source.path_for(name, "a.jpg")

	with pytest.raises(FrameFetchError):
		source.list_names(name)
