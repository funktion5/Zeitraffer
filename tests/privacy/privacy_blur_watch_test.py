import inspect
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from privacy_fakes import run_in

import src.privacy.blur_watch as blur_watch
from src.privacy.blur_box import record_processed
from src.storage.storage_box import StorageBox

REMOTE = "user@box.example"
CAMERA = "Test-Camera"
OTHER = "Other"
TIMEZONE = "Europe/Berlin"
LOCATION = {"latitude": 52.472, "longitude": 9.333, "timezone": TIMEZONE}
NOW = datetime(2026, 6, 15, 14, 0, tzinfo=ZoneInfo(TIMEZONE))


class Box:
	"""Local folders stand in for the storage box; every command sent to it is recorded."""

	def __init__(self, tmp_path: Path, monkeypatch) -> None:
		self.root = tmp_path / "cameras"
		(self.root / CAMERA).mkdir(parents=True)
		(self.root / OTHER).mkdir()
		self.state_root = tmp_path / "state"
		self.commands: list[str] = []
		runner = run_in(self.root)

		def recording_run(storage_box, command: str, timeout_seconds: float):
			self.commands.append(command)

			return runner(storage_box, command, timeout_seconds)

		monkeypatch.setattr(StorageBox, "run", recording_run)

	def upload(self, name: str, age_seconds: float, camera: str = CAMERA) -> None:
		image = self.root / camera / name
		image.write_bytes(b"\xff\xd8image\xff\xd9")
		moment = NOW.timestamp() - age_seconds
		os.utime(image, (moment, moment))

	def stale(self) -> list[str]:
		return blur_watch.find_stale(StorageBox(REMOTE, ""), CAMERA, self.state_root, NOW)


@pytest.fixture
def box(tmp_path: Path, monkeypatch) -> Box:
	return Box(tmp_path, monkeypatch)


# The round runs every 5 minutes, so a normal image is checked within about 6.
def test_an_unchecked_image_is_stale_after_ten_minutes(box: Box) -> None:
	box.upload("20260615T134500.jpg", age_seconds=601)
	box.upload("20260615T135200.jpg", age_seconds=420)

	assert box.stale() == ["20260615T134500.jpg"]


@pytest.mark.parametrize(
	("status", "is_stale"),
	[
		("blurred", False),
		("clean", False),
		# Written by rounds before the detector ran around the clock; those lines stay valid.
		("night", False),
		# Both may still show a person: refused by the writer, or cut off mid-swap.
		("refused", True),
		("replacing", True),
	],
)
def test_only_finished_images_are_not_stale(box: Box, status: str, is_stale: bool) -> None:
	name = "20260615T120000.jpg"
	box.upload(name, age_seconds=7200)
	record_processed(box.state_root, CAMERA, {"image": name, "status": status}, NOW)

	assert box.stale() == ([name] if is_stale else [])


# The detector runs around the clock: no night exception. The watchdog writes nothing.
def test_a_night_image_without_a_status_is_stale_too(box: Box) -> None:
	box.upload("20260615T020000.jpg", age_seconds=12 * 3600)

	assert box.stale() == ["20260615T020000.jpg"]
	assert not box.state_root.exists()


def test_an_image_of_an_earlier_listed_day_still_counts(box: Box) -> None:
	box.upload("20260614T120000.jpg", age_seconds=26 * 3600)

	assert box.stale() == ["20260614T120000.jpg"]


def test_the_watchdog_only_lists_the_box(box: Box) -> None:
	box.upload("20260615T120000.jpg", age_seconds=7200)

	box.stale()

	assert box.commands
	assert all(command.startswith("ls ") for command in box.commands)


# It must keep reporting while a round is stuck or broken: no lock, no detector, no writer.
def test_the_watchdog_needs_no_lock_detector_or_writer() -> None:
	source = inspect.getsource(blur_watch)

	for name in ("acquire_run_lock", "run_detector", "BoxWriter", "record_processed"):
		assert name not in source, name


@pytest.fixture
def config(box: Box, monkeypatch) -> dict:
	config = {
		"location": LOCATION,
		# No detector_command: the watchdog never needs one.
		"privacy": {"blur_cameras": [CAMERA, OTHER]},
	}
	monkeypatch.setattr(blur_watch, "load_config", lambda: config)
	monkeypatch.setattr(blur_watch, "get_storage_box", lambda: StorageBox(REMOTE, ""))
	monkeypatch.setattr(blur_watch, "STATE_ROOT", box.state_root)
	# Every main() run writes the status file; never into the real state folder.
	monkeypatch.setattr(
		blur_watch, "STATUS_PATH", box.state_root.parent / "web-jobs" / "blur-watch.json"
	)

	return config


def test_main_warns_per_camera_and_still_exits_zero(box: Box, config, caplog) -> None:
	names = [f"20260615T12{minute:02d}00.jpg" for minute in range(12)]

	for name in names:
		box.upload(name, age_seconds=7200)

	assert blur_watch.main(now=NOW) == 0

	warnings = [record.getMessage() for record in caplog.records if record.levelname == "WARNING"]
	assert warnings == [
		f"[{CAMERA}] 12 images unblurred for more than 10 minutes: "
		f"{', '.join(names[:10])} and 2 more"
	]
	assert "Stale check: 2 cameras, 12 stale images" in caplog.text


# One line per quiet run shows that the watchdog itself is alive.
def test_main_logs_one_line_when_nothing_is_stale(box: Box, config, caplog) -> None:
	assert blur_watch.main(now=NOW) == 0

	assert "Stale check: 2 cameras, nothing stale" in caplog.text
	assert not [record for record in caplog.records if record.levelname == "WARNING"]


def test_a_failed_listing_is_an_error_and_the_next_camera_is_still_checked(
	box: Box, config, caplog, monkeypatch
) -> None:
	box.upload("20260615T120000.jpg", age_seconds=7200, camera=OTHER)
	real_listing = blur_watch.list_images_for_dates

	def listing(storage_box, camera, days):
		if camera == CAMERA:
			raise OSError("Storage box listing failed")

		return real_listing(storage_box, camera, days)

	monkeypatch.setattr(blur_watch, "list_images_for_dates", listing)

	assert blur_watch.main(now=NOW) == 1

	assert f"[{CAMERA}] Stale check failed: Storage box listing failed" in caplog.text
	assert f"[{OTHER}] 1 images unblurred for more than 10 minutes" in caplog.text


def test_main_without_a_storage_box_is_an_error(config, caplog, monkeypatch) -> None:
	def no_box():
		raise OSError("TIMELAPSE_STORAGE_BOX is not set")

	monkeypatch.setattr(blur_watch, "get_storage_box", no_box)

	assert blur_watch.main(now=NOW) == 1
	assert "No storage box: TIMELAPSE_STORAGE_BOX is not set" in caplog.text


# The web UI's banner reads this file: the check time shows the watchdog is alive.
@pytest.fixture
def status_path(tmp_path: Path, monkeypatch) -> Path:
	path = tmp_path / "web-jobs" / "blur-watch.json"
	monkeypatch.setattr(blur_watch, "STATUS_PATH", path)

	return path


def read_status(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


def test_status_file_lists_stale_counts(box: Box, config, status_path: Path) -> None:
	box.upload("20260615T120000.jpg", age_seconds=7200)
	box.upload("20260615T121500.jpg", age_seconds=7200)

	assert blur_watch.main(now=NOW) == 0

	assert read_status(status_path) == {
		"checked": NOW.isoformat(),
		"stale": {CAMERA: 2, OTHER: 0},
		"error": None,
	}


def test_status_file_records_an_unreachable_box(config, status_path: Path, monkeypatch) -> None:
	def no_box():
		raise OSError("no box")

	monkeypatch.setattr(blur_watch, "get_storage_box", no_box)

	assert blur_watch.main(now=NOW) == 1

	status = read_status(status_path)
	assert status["checked"] == NOW.isoformat()
	assert status["stale"] == {}
	assert "no box" in status["error"]


def test_status_file_records_a_failed_camera_check(
	box: Box, config, status_path: Path, monkeypatch
) -> None:
	def listing(storage_box, camera, days):
		raise OSError("Storage box listing failed")

	monkeypatch.setattr(blur_watch, "list_images_for_dates", listing)

	assert blur_watch.main(now=NOW) == 1

	status = read_status(status_path)
	assert status["stale"] == {}
	assert f"[{CAMERA}] Storage box listing failed" in status["error"]
