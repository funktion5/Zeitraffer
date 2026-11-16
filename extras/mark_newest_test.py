import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from privacy_fakes import FakeBox, run_in

from extras.mark_newest import mark_camera, newest_image
from src.privacy.box_writer import BoxWriter
from src.privacy.checked_mark import add_mark
from src.storage_box import StorageBox

TIMEZONE = "Europe/Berlin"


# The same image as the website's pick-up script: the newest by the time in its name, not by listing
# order, and never an empty file.
def test_the_newest_image_by_its_name_is_chosen() -> None:
	images = {
		"20261116T121000.jpg": 200_000,
		"20261116T122000.jpg": 210_000,
		"20261115T235000.jpg": 190_000,
	}

	assert newest_image(images, TIMEZONE) == "20261116T122000.jpg"


def test_yesterdays_last_image_counts_when_today_has_none() -> None:
	images = {"20261115T235000.jpg": 190_000, "20261115T234000.jpg": 180_000}

	assert newest_image(images, TIMEZONE) == "20261115T235000.jpg"


# An empty upload is skipped by the pick-up script, which then takes the one before.
def test_an_empty_newest_image_falls_back_to_the_one_before() -> None:
	images = {"20261116T122000.jpg": 0, "20261116T121000.jpg": 200_000}

	assert newest_image(images, TIMEZONE) == "20261116T121000.jpg"


def test_no_image_or_only_empty_ones_gives_none() -> None:
	assert newest_image({}, TIMEZONE) is None
	assert newest_image({"20261116T122000.jpg": 0}, TIMEZONE) is None


# Without a readable time it cannot be placed, so it is never taken for the newest.
def test_a_name_without_a_readable_time_is_never_chosen() -> None:
	images = {"cam-latest.jpg": 200_000, "20261116T121000.jpg": 200_000}

	assert newest_image(images, TIMEZONE) == "20261116T121000.jpg"


# Marking one camera, against a local folder that stands in for the storage box.

REMOTE = "user@box.example"
CAMERA = "Uferstrasse"
NOW = datetime(2026, 11, 16, 13, 0, tzinfo=ZoneInfo(TIMEZONE))
OLDER = "20261116T124000.jpg"
NEWEST = "20261116T125000.jpg"


def jpeg(name: str) -> bytes:
	return b"\xff\xd8" + name.encode() + b"\xff\xd9"


class Box:
	def __init__(self, tmp_path: Path, monkeypatch) -> None:
		self.root = tmp_path / "box"
		self.camera_dir = self.root / CAMERA
		self.camera_dir.mkdir(parents=True)
		self.work = tmp_path / "work"
		self.work.mkdir()
		self.fake = FakeBox(self.root, REMOTE)
		# The listing goes through StorageBox.run, the writes through the writer's fake runner.
		monkeypatch.setattr(StorageBox, "run", run_in(self.root))
		self.marked: dict[str, str] = {}

	def upload(self, name: str, data: bytes | None = None, age_seconds: float = 600) -> Path:
		path = self.camera_dir / name
		path.write_bytes(jpeg(name) if data is None else data)
		moment = NOW.timestamp() - age_seconds
		os.utime(path, (moment, moment))

		return path

	def mark(self) -> str:
		writer = BoxWriter(
			REMOTE,
			"",
			[CAMERA],
			TIMEZONE,
			upload_root=self.work,
			runner=self.fake,
			clock=lambda: NOW,
		)

		return mark_camera(writer, StorageBox(REMOTE, ""), CAMERA, self.marked, NOW, self.work)

	# Uploads to the box and remote cp/mv/mkdir; downloads are reads.
	def writes(self) -> list[str]:
		return [
			argv[-1]
			for argv in self.fake.calls
			if (argv[0] == "scp" and argv[-1].startswith(f"{REMOTE}:"))
			or (argv[0] == "ssh" and argv[-1].startswith(("cp ", "mv ", "mkdir ")))
		]


@pytest.fixture
def box(tmp_path: Path, monkeypatch) -> Box:
	return Box(tmp_path, monkeypatch)


def test_the_newest_image_gets_the_mark_and_nothing_else_changes(box: Box) -> None:
	older = box.upload(OLDER)
	newest = box.upload(NEWEST)

	assert box.mark() == "marked"

	assert newest.read_bytes() == add_mark(jpeg(NEWEST))
	assert older.read_bytes() == jpeg(OLDER)
	# No backup: the pixels did not change.
	assert not (box.camera_dir / "original").exists()
	assert box.marked == {CAMERA: NEWEST}
	assert not list(box.work.iterdir())


# Every 5 minutes for every camera: the image marked last time costs no download.
def test_the_image_marked_last_time_is_not_downloaded_again(box: Box) -> None:
	box.upload(NEWEST)
	box.marked[CAMERA] = NEWEST

	assert box.mark() == "unchanged"
	assert box.fake.calls == []


def test_an_upload_still_in_progress_waits_for_the_next_run(box: Box) -> None:
	newest = box.upload(NEWEST, age_seconds=5)

	assert box.mark() == "settling"
	assert newest.read_bytes() == jpeg(NEWEST)
	assert box.marked == {}


# E.g. a run cut off after the swap: nothing to write, only remember it.
def test_an_image_that_already_carries_the_mark_is_only_remembered(box: Box) -> None:
	newest = box.upload(NEWEST, add_mark(jpeg(NEWEST)))

	assert box.mark() == "unchanged"
	assert newest.read_bytes() == add_mark(jpeg(NEWEST))
	assert box.marked == {CAMERA: NEWEST}
	assert box.writes() == []


# The pick-up script skips an empty upload and takes the one before, so that one gets the mark.
def test_an_empty_newest_upload_marks_the_one_before(box: Box) -> None:
	older = box.upload(OLDER)
	box.upload(NEWEST, b"")

	assert box.mark() == "marked"
	assert older.read_bytes() == add_mark(jpeg(OLDER))
	assert box.marked == {CAMERA: OLDER}


def test_a_cut_off_upload_is_not_marked(box: Box) -> None:
	newest = box.upload(NEWEST, b"\xff\xd8half an ima")

	assert box.mark() == "incomplete"
	assert newest.read_bytes() == b"\xff\xd8half an ima"
	assert box.marked == {}
	assert box.writes() == []


def test_a_camera_without_images_has_nothing_to_mark(box: Box) -> None:
	assert box.mark() == "none"
	assert box.writes() == []


# Hidden files (an upload in progress) and the backup folder are never candidates.
def test_hidden_files_and_the_backup_folder_are_never_marked(box: Box) -> None:
	box.upload(OLDER)
	box.upload(f".{NEWEST}.tmp")
	(box.camera_dir / "original").mkdir()
	(box.camera_dir / "original" / NEWEST).write_bytes(jpeg(NEWEST))

	assert box.mark() == "marked"
	assert box.marked == {CAMERA: OLDER}
