import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from flagger_fakes import SequenceForward

import src.flagger.run as run
from src.flagger.run import run_cameras, scan_images, select_daily_images

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 21, 3, 0, tzinfo=BERLIN)
CONFIG = {
	"location": {"latitude": 52.45, "longitude": 9.36, "timezone": "Europe/Berlin"},
	"automatic_daylight_buffer_minutes": {str(month): 60 for month in range(1, 13)} | {"10": 75},
	"image_scan_stall_timeout_seconds": 60,
}


class FlagEverything:
	def __call__(self, blob):
		return SequenceForward([[(2440, 14, 0.9)]])(blob)


class FlagNothing:
	def __call__(self, blob):
		return SequenceForward([])(blob)


def write_image(folder: Path, name: str, size=(48, 64)) -> Path:
	folder.mkdir(parents=True, exist_ok=True)
	path = folder / name
	assert cv2.imwrite(str(path), np.zeros((*size, 3), np.uint8))
	return path


def test_scan_flags_and_counts(tmp_path):
	good = write_image(tmp_path, "cam-26-10-20_08-14-58-20.jpg")
	corrupt = tmp_path / "cam-26-10-20_09-14-58-20.jpg"
	corrupt.write_bytes(b"not a jpeg")
	unparseable = write_image(tmp_path, "weird.jpg")

	scan = scan_images([good, corrupt, unparseable], FlagEverything(), "Europe/Berlin")

	assert (len(scan.flagged), scan.checked, scan.failed) == (1, 1, 2)
	assert scan.flagged[0].path == good
	assert scan.flagged[0].taken_at.isoformat() == "2026-10-20T08:14:58+02:00"
	assert scan.flagged[0].image_size == (64, 48)
	assert scan.flagged[0].detection.label == "bird"


def test_uppercase_suffix_is_parsed_like_lowercase(tmp_path):
	upper = write_image(tmp_path, "cam-26-10-20_08-14-58-20.JPG")

	scan = scan_images([upper], FlagEverything(), "Europe/Berlin")

	assert (len(scan.flagged), scan.checked, scan.failed) == (1, 1, 0)


def test_tiny_image_is_scanned_without_error(tmp_path):
	tiny = write_image(tmp_path, "cam-26-10-20_08-14-58-20.jpg", size=(10, 10))

	scan = scan_images([tiny], FlagNothing(), "Europe/Berlin")

	assert (scan.flagged, scan.checked, scan.failed) == ([], 1, 0)


def test_select_daily_images_uses_the_daily_jobs_rules(monkeypatch):
	captured = {}

	def fake_find(**kwargs):
		captured.update(kwargs)
		return [Path("a.jpg")]

	monkeypatch.setattr(run, "find_daily_images_isolated", fake_find)

	assert select_daily_images(CONFIG, "SLSV", DAY) == [Path("a.jpg")]
	assert captured["camera"] == "SLSV" and captured["target_date"] == DAY
	assert captured["previous_date"] == date(2026, 10, 19)
	assert captured["daylight_buffer_minutes"] == 75
	assert captured["stall_timeout_seconds"] == 60
	assert captured["sunrise"] < captured["sunset"]
	assert captured["sunrise"].date() == DAY


def prepared_images(monkeypatch, images_by_camera: dict):
	def fake_select(config, camera, target_date):
		images = images_by_camera[camera]
		if isinstance(images, Exception):
			raise images
		return images

	monkeypatch.setattr(run, "select_daily_images", fake_select)


def test_a_day_without_flags_writes_an_empty_manifest(tmp_path, monkeypatch):
	images = [write_image(tmp_path / "src", f"cam-26-10-20_0{h}-14-58-20.jpg") for h in (8, 9)]
	prepared_images(monkeypatch, {"Cam": images})

	code = run_cameras(CONFIG, ["Cam"], DAY, FlagNothing(), tmp_path / "videos", "det", NOW)

	manifest_path = tmp_path / "videos" / "Cam" / "highlights" / "2026-10-20" / "manifest.json"
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	assert code == 0
	assert (manifest["items"], manifest["checked"], manifest["detector"]) == ([], 2, "det")
	assert manifest["created"] == "2026-10-21T03:00:00+02:00"


def test_flagged_images_are_copied_into_the_report(tmp_path, monkeypatch):
	image = write_image(tmp_path / "src", "cam-26-10-20_08-14-58-20.jpg")
	prepared_images(monkeypatch, {"Cam": [image]})

	run_cameras(CONFIG, ["Cam"], DAY, FlagEverything(), tmp_path / "videos", "det", NOW)

	folder = tmp_path / "videos" / "Cam" / "highlights" / "2026-10-20"
	assert sorted(p.name for p in folder.iterdir()) == [image.name, "manifest.json"]


def test_a_camera_without_images_writes_nothing(tmp_path, monkeypatch, caplog):
	prepared_images(monkeypatch, {"Cam": []})

	with caplog.at_level(logging.WARNING, logger="timelapse"):
		code = run_cameras(CONFIG, ["Cam"], DAY, FlagNothing(), tmp_path / "videos", "det", NOW)

	assert code == 0
	assert not (tmp_path / "videos").exists()
	assert "[Cam]" in caplog.text


def test_one_failing_camera_does_not_stop_the_others(tmp_path, monkeypatch):
	image = write_image(tmp_path / "src", "cam-26-10-20_08-14-58-20.jpg")
	prepared_images(monkeypatch, {"Broken": OSError("mount gone"), "Cam": [image]})

	code = run_cameras(
		CONFIG, ["Broken", "Cam"], DAY, FlagNothing(), tmp_path / "videos", "det", NOW
	)

	assert code == 1
	assert (tmp_path / "videos" / "Cam" / "highlights" / "2026-10-20" / "manifest.json").is_file()
	assert not (tmp_path / "videos" / "Broken").exists()


def test_a_scan_timeout_counts_as_a_failed_camera(tmp_path, monkeypatch):
	prepared_images(monkeypatch, {"Cam": TimeoutError("stalled")})

	assert run_cameras(CONFIG, ["Cam"], DAY, FlagNothing(), tmp_path / "videos", "d", NOW) == 1


def test_summary_line_per_camera(tmp_path, monkeypatch, caplog):
	images = [
		write_image(tmp_path / "src", "cam-26-10-20_08-14-58-20.jpg"),
		write_image(tmp_path / "src", "cam-26-10-20_09-14-58-20.jpg"),
	]

	class FlagFirstForwardCall:
		def __init__(self):
			self.calls_seen = 0

		def __call__(self, blob):
			self.calls_seen += 1
			# Five forward calls per image (whole frame, four tiles): only the first image hits.
			calls = [[(2440, 14, 0.9)]] if self.calls_seen == 1 else []
			return SequenceForward(calls)(blob)

	prepared_images(monkeypatch, {"Strandallee": images})

	with caplog.at_level(logging.INFO, logger="timelapse"):
		run_cameras(
			CONFIG, ["Strandallee"], DAY, FlagFirstForwardCall(), tmp_path / "videos", "d", NOW
		)

	assert "[Strandallee] checked=2 flagged=1 failed=0" in caplog.text


def test_a_camera_whose_images_all_fail_keeps_its_old_report(tmp_path, monkeypatch):
	good = write_image(tmp_path / "src", "cam-26-10-20_08-14-58-20.jpg")
	prepared_images(monkeypatch, {"Cam": [good]})
	run_cameras(CONFIG, ["Cam"], DAY, FlagEverything(), tmp_path / "videos", "d", NOW)
	folder = tmp_path / "videos" / "Cam" / "highlights" / "2026-10-20"
	before = sorted(p.name for p in folder.iterdir())
	broken = tmp_path / "src" / "cam-26-10-20_09-14-58-20.jpg"
	broken.write_bytes(b"unreadable over a flaky mount")
	prepared_images(monkeypatch, {"Cam": [broken]})

	code = run_cameras(CONFIG, ["Cam"], DAY, FlagEverything(), tmp_path / "videos", "d", NOW)

	assert code == 1
	assert sorted(p.name for p in folder.iterdir()) == before


def test_a_truncated_jpeg_is_skipped_as_failed(tmp_path):
	ok, encoded = cv2.imencode(".jpg", np.full((48, 64, 3), 200, np.uint8))
	truncated = tmp_path / "cam-26-10-20_08-14-58-20.jpg"
	# A cut-off upload: no FF D9 end marker, the lower part would decode grey.
	truncated.write_bytes(encoded.tobytes()[:-40])

	scan = scan_images([truncated], FlagEverything(), "Europe/Berlin")

	assert (scan.flagged, scan.checked, scan.failed) == ([], 0, 1)
