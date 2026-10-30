import json
import os
import stat

import pytest

import src.camera_list as camera_list_module
from src.camera_list import main, write_camera_list


@pytest.fixture
def list_path(tmp_path, monkeypatch):
	path = tmp_path / "state" / "web-jobs" / "cameras.json"
	monkeypatch.setattr(camera_list_module, "CAMERA_LIST_PATH", path)

	return path


def listing(monkeypatch, cameras, ignored=()):
	monkeypatch.setattr(camera_list_module, "get_cameras", lambda: cameras)
	monkeypatch.setattr(camera_list_module, "load_config", lambda: {"ignored_cameras": ignored})


def failing_listing(monkeypatch):
	def fail():
		raise OSError("the box is unreachable")

	monkeypatch.setattr(camera_list_module, "get_cameras", fail)
	monkeypatch.setattr(camera_list_module, "load_config", lambda: {"ignored_cameras": []})


# The web server user reads the file and walks into its folder, so both must be world-readable.
def test_write_is_readable_by_the_web_server(tmp_path):
	destination = tmp_path / "state" / "web-jobs" / "cameras.json"

	write_camera_list(destination, ["Alpha", "Beta"])

	assert json.loads(destination.read_text(encoding="utf-8")) == ["Alpha", "Beta"]
	assert stat.S_IMODE(destination.stat().st_mode) == 0o644
	assert stat.S_IMODE(destination.parent.stat().st_mode) & 0o755 == 0o755
	assert [path.name for path in destination.parent.iterdir()] == ["cameras.json"]


# mkdir's mode is cut down by the umask, and a cron job may run with 077: a folder that is created
# here must still be enterable by the web server user. A folder that already exists keeps its mode.
def test_a_new_folder_is_world_readable_whatever_the_umask(tmp_path):
	destination = tmp_path / "state" / "web-jobs" / "cameras.json"
	previous_umask = os.umask(0o077)

	try:
		write_camera_list(destination, ["Alpha"])

	finally:
		os.umask(previous_umask)

	assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o755
	assert stat.S_IMODE(destination.stat().st_mode) == 0o644


def test_an_existing_folder_keeps_its_mode(tmp_path):
	folder = tmp_path / "web-jobs"
	folder.mkdir()
	folder.chmod(0o750)

	write_camera_list(folder / "cameras.json", ["Alpha"])

	assert stat.S_IMODE(folder.stat().st_mode) == 0o750


# The page may read at any moment: it sees the old list or the new one, never half a file, and a
# write that fails leaves the old list and no temporary file behind.
def test_a_failed_write_keeps_the_old_file_and_leaves_no_temporary_file(tmp_path, monkeypatch):
	destination = tmp_path / "cameras.json"
	write_camera_list(destination, ["Old"])

	def fail(source, target):
		raise OSError("disk full")

	monkeypatch.setattr(os, "replace", fail)

	with pytest.raises(OSError, match="disk full"):
		write_camera_list(destination, ["New"])

	assert json.loads(destination.read_text(encoding="utf-8")) == ["Old"]
	assert [path.name for path in tmp_path.iterdir()] == ["cameras.json"]


def test_ignored_cameras_are_left_out(list_path, monkeypatch):
	listing(monkeypatch, ["Alpha", "Blurtest", "Gamma"], ignored=["Blurtest"])

	assert main() == 0

	assert json.loads(list_path.read_text(encoding="utf-8")) == ["Alpha", "Gamma"]


# The nightly wrapper reads the cameras it has to verify from here, one per line. Only the names go
# to stdout: logging goes to stderr, so nothing else can end up in that list.
def test_the_names_are_printed_one_per_line(list_path, monkeypatch, capsys):
	listing(monkeypatch, ["Alpha", "Blurtest", "Gamma"], ignored=["Blurtest"])

	assert main() == 0

	assert capsys.readouterr().out == "Alpha\nGamma\n"


# A listing that fails, or comes back empty, must not blank the web page until the next night.
def test_a_failed_listing_keeps_the_old_file(list_path, monkeypatch, capsys):
	write_camera_list(list_path, ["Old"])
	failing_listing(monkeypatch)

	assert main() == 1

	assert json.loads(list_path.read_text(encoding="utf-8")) == ["Old"]
	assert capsys.readouterr().out == ""


# No folder and no storage box configured is a ValueError from the frame source: the same exit 1
# and the old list, not a traceback.
def test_an_unconfigured_source_keeps_the_old_file(list_path, monkeypatch, capsys):
	write_camera_list(list_path, ["Old"])

	def unconfigured():
		raise ValueError("No frame source configured")

	monkeypatch.setattr(camera_list_module, "get_cameras", unconfigured)
	monkeypatch.setattr(camera_list_module, "load_config", lambda: {"ignored_cameras": []})

	assert main() == 1

	assert json.loads(list_path.read_text(encoding="utf-8")) == ["Old"]
	assert capsys.readouterr().out == ""


# A write that fails (a folder owned by root, a full disk) is logged and ends with exit 1, so the
# nightly wrapper reports it. The old list stays and no names are printed.
def test_a_failed_write_exits_with_one_and_keeps_the_old_file(list_path, monkeypatch, capsys):
	write_camera_list(list_path, ["Old"])
	listing(monkeypatch, ["Alpha"])

	def fail(destination, cameras):
		raise PermissionError("not allowed")

	monkeypatch.setattr(camera_list_module, "write_camera_list", fail)

	assert main() == 1

	assert json.loads(list_path.read_text(encoding="utf-8")) == ["Old"]
	assert capsys.readouterr().out == ""


def test_an_empty_listing_keeps_the_old_file(list_path, monkeypatch, capsys):
	write_camera_list(list_path, ["Old"])
	listing(monkeypatch, [])

	assert main() == 1

	assert json.loads(list_path.read_text(encoding="utf-8")) == ["Old"]
	assert capsys.readouterr().out == ""
