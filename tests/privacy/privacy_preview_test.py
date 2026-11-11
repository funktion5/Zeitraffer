import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import src.frame_source as frame_source
import src.privacy.preview as preview
from src.frame_source import LocalFrameSource
from src.privacy.preview import (
	EXIT_FAILED,
	EXIT_NO_FRAME,
	EXIT_OK,
	EXIT_UNKNOWN_CAMERA,
	MAX_CANDIDATES,
	build_preview,
	rank_candidates,
)

# The preview picture of the Verpixelung page: ONE frame of a blur camera that the box blur job has
# judged (blurred or clean), fetched with the frame source and cached for the web server.
#   rank_candidates(processed, timezone) -> best frame first
#   build_preview(camera, config, state_root, preview_root, now) -> info dict, or None

CAMERA = "Blur-Camera"
TIMEZONE = "Europe/Berlin"
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=ZoneInfo(TIMEZONE))
CONFIG = {"location": {"timezone": TIMEZONE}, "privacy": {"blur_cameras": [CAMERA]}}


# A JPEG as small as the checks need it: start marker, one size segment, end marker. The payload
# makes two frames differ.
def make_jpeg(width: int = 640, height: int = 480, payload: bytes = b"") -> bytes:
	frame_header = struct.pack(">BHHB", 8, height, width, 0)
	segment = b"\xff\xc0" + struct.pack(">H", len(frame_header) + 2) + frame_header

	return b"\xff\xd8" + segment + payload + b"\xff\xd9"


def sha256(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


class Box:
	def __init__(self, root: Path):
		self.state_root = root / "state"
		self.frames = root / "frames"
		self.previews = root / "previews"

	# The frame on the "box" and its line in the blur state (one file per month).
	def add(self, name: str, status: str, data: bytes | None = None, **extra) -> bytes:
		data = make_jpeg(payload=name.encode()) if data is None else data
		path = self.frames / CAMERA / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(data)

		entry = {"image": name, "status": status, **extra}
		page = self.state_root / CAMERA / "2026-11.jsonl"
		page.parent.mkdir(parents=True, exist_ok=True)

		with page.open("a", encoding="utf-8") as file:
			file.write(json.dumps(entry) + "\n")

		return data

	def build(self):
		return build_preview(CAMERA, CONFIG, self.state_root, self.previews, NOW)


@pytest.fixture
def box(tmp_path, monkeypatch) -> Box:
	box = Box(tmp_path)

	monkeypatch.setattr(preview, "get_frame_source", lambda: LocalFrameSource(box.frames))

	return box


def processed_of(*pairs: tuple[str, str]) -> dict:
	return {name: {"image": name, "status": status} for name, status in pairs}


def names_of(candidates) -> list[str]:
	return [candidate.name for candidate in candidates]


# Blurred first, then clean. A night frame is never a candidate: the job records it without
# running the detector.
def test_a_blurred_frame_beats_a_clean_one_and_a_night_frame_is_never_a_candidate():
	ranked = rank_candidates(
		processed_of(
			("20261109T120000.jpg", "night"),
			("20261109T120100.jpg", "clean"),
			("20261109T120200.jpg", "blurred"),
		),
		TIMEZONE,
	)

	assert names_of(ranked) == ["20261109T120200.jpg", "20261109T120100.jpg"]


# Within a kind the newest day wins, and on that day the frame nearest midday.
def test_the_newest_day_wins_and_on_that_day_the_frame_nearest_midday():
	ranked = rank_candidates(
		processed_of(
			("20261108T120000.jpg", "blurred"),
			("20261109T080000.jpg", "blurred"),
			("20261109T114500.jpg", "blurred"),
			("20261109T150000.jpg", "blurred"),
		),
		TIMEZONE,
	)

	assert names_of(ranked) == [
		"20261109T114500.jpg",
		"20261109T150000.jpg",
		"20261109T080000.jpg",
		"20261108T120000.jpg",
	]


# Anything the job has not finished may still show a person, so it is never a candidate. A name
# without a readable time cannot be placed on a day.
def test_only_confirmed_frames_with_a_readable_time_are_candidates():
	ranked = rank_candidates(
		processed_of(
			("20261109T100000.jpg", "refused"),
			("20261109T100100.jpg", "replacing"),
			("20261109T100200.jpg", "mystery"),
			("no-time-in-this-name.jpg", "blurred"),
			("20261109T100300.jpg", "clean"),
			("20261109T100400.jpg", "night"),
		),
		TIMEZONE,
	)

	assert names_of(ranked) == ["20261109T100300.jpg"]


# The description has no size: the web side reads it from the picture itself.
def test_a_preview_is_written_with_its_description(box):
	data = box.add("20261109T120000.jpg", "blurred")
	info = box.build()

	assert info == {
		"image": "20261109T120000.jpg",
		"status": "blurred",
		"taken": "2026-11-09T12:00:00+01:00",
	}
	assert (box.previews / f"{CAMERA}.jpg").read_bytes() == data
	assert json.loads((box.previews / f"{CAMERA}.json").read_text()) == info


# The web server user reads the cache: a file of the run user alone (mkstemp makes 0600) would
# show a broken image.
def test_the_cache_is_readable_for_the_web_server_user(box):
	box.add("20261109T120000.jpg", "clean")
	box.build()

	assert (box.previews / f"{CAMERA}.jpg").stat().st_mode & 0o777 == 0o644
	assert (box.previews / f"{CAMERA}.json").stat().st_mode & 0o777 == 0o644
	assert box.previews.stat().st_mode & 0o777 == 0o755


def test_a_new_preview_replaces_the_old_one_and_leaves_no_temporary_file(box):
	box.add("20261108T120000.jpg", "blurred")
	box.build()
	newer = box.add("20261109T120000.jpg", "blurred")
	info = box.build()

	assert info["image"] == "20261109T120000.jpg"
	assert (box.previews / f"{CAMERA}.jpg").read_bytes() == newer
	assert sorted(path.name for path in box.previews.iterdir()) == [
		f"{CAMERA}.jpg",
		f"{CAMERA}.json",
	]


# Nothing confirmed means no picture; an older preview stays as it is.
def test_without_a_confirmed_frame_there_is_no_preview_and_the_old_one_stays(box):
	box.add("20261109T120000.jpg", "refused")
	box.previews.mkdir()
	(box.previews / f"{CAMERA}.jpg").write_bytes(b"old")

	assert box.build() is None
	assert (box.previews / f"{CAMERA}.jpg").read_bytes() == b"old"


def test_a_camera_without_any_state_has_no_preview(box):
	assert box.build() is None
	assert not box.previews.exists()


# A night frame was never run through the detector: showing it would show an unchecked raw frame.
def test_a_night_frame_is_never_shown_and_there_is_then_no_preview(box):
	box.add("20261109T230000.jpg", "night")

	assert box.build() is None
	assert not box.previews.exists()


def test_an_older_judged_frame_is_taken_instead_of_a_newer_night_frame(box):
	box.add("20261108T120000.jpg", "clean")
	box.add("20261109T230000.jpg", "night")

	info = box.build()

	assert info["image"] == "20261108T120000.jpg"
	assert info["status"] == "clean"


# The state names the bytes it judged. A frame on the box that is something else (rewritten since)
# was never checked, so it must not reach the web UI; the next candidate is taken instead.
def test_a_frame_that_is_not_the_judged_one_is_skipped(box):
	box.add("20261109T120000.jpg", "blurred", blurred_sha256=sha256(b"something else"))
	good = make_jpeg(payload=b"good")
	box.add("20261109T130000.jpg", "blurred", good, blurred_sha256=sha256(good))

	info = box.build()

	assert info["image"] == "20261109T130000.jpg"
	assert (box.previews / f"{CAMERA}.jpg").read_bytes() == good


# A clean frame was judged as the original bytes; a blurred one as the blurred copy.
def test_each_kind_is_checked_against_its_own_recorded_hash(box):
	clean = make_jpeg(payload=b"clean")
	box.add("20261109T110000.jpg", "clean", clean, original_sha256=sha256(clean))
	# Nearer to midday, but not the bytes the job judged.
	box.add("20261109T120000.jpg", "clean", original_sha256=sha256(b"x"))

	assert box.build()["image"] == "20261109T110000.jpg"

	# The original's hash is recorded for a blurred frame too, but it is not the bytes on the box.
	blurred = make_jpeg(payload=b"blurred")
	box.add(
		"20261109T123000.jpg",
		"blurred",
		blurred,
		original_sha256=sha256(b"the original"),
		blurred_sha256=sha256(blurred),
	)

	assert box.build()["image"] == "20261109T123000.jpg"


def test_a_cut_off_frame_is_skipped(box):
	box.add("20261109T120000.jpg", "blurred", make_jpeg()[:-2])
	box.add("20261109T130000.jpg", "blurred")

	assert box.build()["image"] == "20261109T130000.jpg"


def test_a_frame_missing_on_the_box_is_skipped(box):
	box.add("20261109T120000.jpg", "blurred")
	(box.frames / CAMERA / "20261109T120000.jpg").unlink()
	box.add("20261109T130000.jpg", "blurred")

	assert box.build()["image"] == "20261109T130000.jpg"


# A box that answers slowly must not be asked about the whole backlog.
def test_only_a_few_candidates_are_tried(box):
	for hour in range(MAX_CANDIDATES + 2):
		box.add(f"20261109T{10 + hour:02d}0000.jpg", "blurred", b"broken")

	# Usable, but too far down the list to be asked for.
	box.add("20261109T230000.jpg", "blurred")

	assert box.build() is None
	assert not (box.previews / f"{CAMERA}.jpg").exists()


# The fetched copy is dropped after the build, whether or not a picture came out of it.
@pytest.mark.parametrize("data", [None, b"broken"])
def test_the_fetched_copies_are_released_after_a_build(box, monkeypatch, data):
	released = []

	class Spy(LocalFrameSource):
		def release(self, camera: str) -> None:
			released.append(camera)

	monkeypatch.setattr(preview, "get_frame_source", lambda: Spy(box.frames))
	box.add("20261109T120000.jpg", "blurred", data)
	box.build()

	assert released == [CAMERA]


# The command line: one JSON line on stdout and an exit code the wrapper hands on to PHP.


@pytest.fixture
def cli(box, monkeypatch, capsys):
	monkeypatch.setattr(preview, "load_config", lambda: CONFIG)
	monkeypatch.setattr(preview, "BLUR_STATE_ROOT", box.state_root)
	monkeypatch.setattr(preview, "PREVIEW_ROOT", box.previews)
	# The state is read by month, so the clock is fixed to the month the test writes.
	monkeypatch.setattr(preview, "current_time", lambda timezone: NOW)
	# main() lowers the retry waits for its own process; the test restores the old value afterwards.
	retries = frame_source.FETCH_RETRY_WAIT_SECONDS
	monkeypatch.setattr(frame_source, "FETCH_RETRY_WAIT_SECONDS", retries)

	def run(*arguments: str) -> tuple[int, dict]:
		code = preview.main(list(arguments))

		return code, json.loads(capsys.readouterr().out)

	return run


def test_the_command_line_reports_the_preview(box, cli):
	box.add("20261109T120000.jpg", "blurred")

	code, reply = cli(CAMERA)

	assert code == EXIT_OK
	assert reply["status"] == "ok"
	assert reply["image"] == "20261109T120000.jpg"


def test_the_command_line_reports_no_frame(box, cli):
	code, reply = cli(CAMERA)

	assert code == EXIT_NO_FRAME
	assert reply == {"status": "none"}


# Only a camera of the blur list has a preview: the name may come from a web request.
@pytest.mark.parametrize("camera", ["Other", "../etc", "", CAMERA.lower()])
def test_the_command_line_refuses_a_camera_that_does_not_blur(box, cli, camera):
	code, reply = cli(camera)

	assert code == EXIT_UNKNOWN_CAMERA
	assert reply == {"status": "unknown_camera"}
	assert not box.previews.exists()


# A setup error (no frame source configured) is a ValueError: it ends in the same quiet failure,
# with the reason in the log, not in a traceback the page cannot read.
@pytest.mark.parametrize(
	"error",
	[OSError("secret path /root/x"), ValueError("No frame source")],
)
def test_the_command_line_reports_a_failure_without_details(box, cli, monkeypatch, error):
	def broken(*arguments, **keywords):
		raise error

	monkeypatch.setattr(preview, "build_preview", broken)

	code, reply = cli(CAMERA)

	assert code == EXIT_FAILED
	assert reply == {"status": "failed"}


# A click must answer in seconds, so a fetch that fails is not retried with the long waits of a job.
def test_the_command_line_does_not_retry_a_failing_fetch(box, cli, monkeypatch):
	seen = []

	def spy(*arguments, **keywords):
		seen.append(frame_source.FETCH_RETRY_WAIT_SECONDS)

		return None

	monkeypatch.setattr(preview, "build_preview", spy)
	cli(CAMERA)

	assert seen == [()]
