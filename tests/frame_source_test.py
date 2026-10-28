from pathlib import Path

import src.images as images_module
from src.frame_source import FrameFetchError, LocalFrameSource


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
