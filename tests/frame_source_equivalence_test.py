from collections import defaultdict
from datetime import date

import pytest
from frame_source_fakes import LS_DIRECTORY, LS_FILE, FakeListingBox

import src.images as images_module
from src.frame_source import LocalFrameSource, SshFrameSource
from src.images import ImageRange

DAY = date(2026, 9, 16)
NEXT_DAY = date(2026, 9, 17)

# A 12:00 window centre for every date.
NOON = defaultdict(lambda: 12 * 60 * 60)

# One name for every filename format extract_date understands, a day either side of the days the
# functions look at, and names every function has to ignore.
NAMES = [
	"20260916T120000.jpg",
	"Reolink_00_20260916120500.jpg",
	"bsv_steinhude_202609161210.jpg",
	"promenade_2026_0916_121500_01.jpg",
	"camera_26-09-16_12-20-00-00.jpg",
	"camera_260916_122500.jpg",
	"camera_2609161230.jpg",
	"P26091612350000.jpg",
	"BSV-Steinhude-26-09-16_12-40-00-00_00001.jpg",
	# Spaces must survive the `ls -l` text, a double space included.
	"my frame 26-09-16_12-45-00-00.jpg",
	"double  space_26-09-16_12-50-00-00.jpg",
	# Upper-case extension: matched by name, but no time can be read from it.
	"UPPER_26-09-16_12-55-00-00.JPG",
	"camera_26-09-17_12-00-00-00.jpg",
	"camera_26-09-15_12-00-00-00.jpg",
	"20260916T120000.png",
	"notes.txt",
	"unknown-format.jpg",
]


# `ls -l` lists the visible regular files; the local source lists every entry. A camera folder
# never holds a hidden file, a symlink or a folder named like a jpg, so the fixture leaves those
# out: with them the two would differ, and neither result would be wrong for real camera data.
def names_sources(tmp_path):
	camera = tmp_path / "local" / "Alpha"
	camera.mkdir(parents=True)

	for name in NAMES:
		(camera / name).touch()

	(camera / "subfolder").mkdir()
	listing = [LS_FILE.format(name) for name in NAMES] + [LS_DIRECTORY.format("subfolder")]

	ssh = SshFrameSource(FakeListingBox(listing), tmp_path / "cache")

	return LocalFrameSource(tmp_path / "local"), ssh


def images_for_dates():
	found = images_module.find_images_for_dates("Alpha", [DAY, NEXT_DAY])

	return {day: [path.name for path in paths] for day, paths in found.items()}


def interval_images():
	found = images_module.find_interval_images("Alpha", DAY, NEXT_DAY, NOON)

	return [path.name for path in found]


def image_range():
	return images_module.get_image_range("Alpha")


# The spec's equivalence check: for the same folder content, both sources give the same result.
@pytest.mark.parametrize("function", [images_for_dates, interval_images, image_range])
def test_local_and_ssh_sources_give_the_same_result(monkeypatch, tmp_path, function):
	local, ssh = names_sources(tmp_path)

	monkeypatch.setattr(images_module, "get_frame_source", lambda: local)
	expected = function()
	monkeypatch.setattr(images_module, "get_frame_source", lambda: ssh)

	assert function() == expected


# Without this the comparison above could pass on two empty results.
def test_the_fixture_exercises_every_filename_format(monkeypatch, tmp_path):
	local, _ = names_sources(tmp_path)
	monkeypatch.setattr(images_module, "get_frame_source", lambda: local)

	assert len(interval_images()) >= 10
	assert image_range() == ImageRange(
		earliest_date=date(2026, 9, 15), latest_date=NEXT_DAY, unrecognized_files=1
	)


def test_local_and_ssh_sources_list_the_same_cameras(monkeypatch, tmp_path):
	root = tmp_path / "local"

	for name in ("Zebra", "Alpha", ".hidden"):
		(root / name).mkdir(parents=True)

	(root / "notes.txt").touch()
	listing = [
		LS_DIRECTORY.format("Zebra"),
		LS_DIRECTORY.format("Alpha"),
		LS_FILE.format("notes.txt"),
	]
	local = LocalFrameSource(root)
	ssh = SshFrameSource(FakeListingBox(listing), tmp_path / "cache")

	monkeypatch.setattr(images_module, "get_frame_source", lambda: local)
	expected = images_module.get_cameras()
	monkeypatch.setattr(images_module, "get_frame_source", lambda: ssh)

	assert images_module.get_cameras() == expected == ["Alpha", "Zebra"]
