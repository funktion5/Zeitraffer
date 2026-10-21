import json
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import src.flagger.report as report
from src.flagger.groups import Detection
from src.flagger.report import FlaggedImage, build_manifest, write_report

BERLIN = ZoneInfo("Europe/Berlin")
CREATED = datetime(2026, 10, 21, 3, 12, 44, tzinfo=BERLIN)
DAY = date(2026, 10, 20)
JPEG = b"\xff\xd8x\xff\xd9"


def image(tmp_path: Path, name: str, content: bytes = JPEG) -> Path:
	source = tmp_path / "source"
	source.mkdir(exist_ok=True)
	path = source / name
	path.write_bytes(content)
	return path


def flagged(path: Path, score: float = 0.865, hour: int = 8) -> FlaggedImage:
	return FlaggedImage(
		path=path,
		detection=Detection(4, score, (716.4, 579.0, 813.6, 625.2)),
		taken_at=datetime(2026, 10, 20, hour, 14, 58, tzinfo=BERLIN),
		image_size=(1920, 1080),
	)


def manifest_for(items: list[FlaggedImage], checked: int = 143) -> dict:
	return build_manifest("Strandallee", DAY, CREATED, "yolox-abcd1234-ort-t2", checked, items)


def test_manifest_matches_the_contract(tmp_path):
	item = flagged(image(tmp_path, "strandallee-26-10-20_08-14-58-20.jpg"), score=0.86512)

	assert manifest_for([item]) == {
		"schema": 1,
		"camera": "Strandallee",
		"date": "2026-10-20",
		"created": "2026-10-21T03:12:44+02:00",
		"detector": "yolox-abcd1234-ort-t2",
		"checked": 143,
		"items": [
			{
				"file": "strandallee-26-10-20_08-14-58-20.jpg",
				"taken_at": "2026-10-20T08:14:58+02:00",
				"group": "flying",
				"label": "airplane",
				"score": 0.8651,
				"box": [716, 579, 814, 625],
				"image_size": [1920, 1080],
			}
		],
	}


def test_items_are_ordered_by_score_highest_first(tmp_path):
	low = flagged(image(tmp_path, "a.jpg"), score=0.4)
	high = flagged(image(tmp_path, "b.jpg"), score=0.9)
	middle = flagged(image(tmp_path, "c.jpg"), score=0.6)

	files = [item["file"] for item in manifest_for([low, high, middle])["items"]]

	assert files == ["b.jpg", "c.jpg", "a.jpg"]


def test_uppercase_suffix_is_lowercased_in_the_manifest_and_the_copy(tmp_path):
	item = flagged(image(tmp_path, "B_26-10-20_09-14-58-20.JPG"))
	manifest = manifest_for([item])

	folder = write_report(tmp_path / "videos", "Strandallee", DAY, manifest, [item])

	assert manifest["items"][0]["file"] == "B_26-10-20_09-14-58-20.jpg"
	assert sorted(p.name for p in folder.iterdir()) == [
		"B_26-10-20_09-14-58-20.jpg",
		"manifest.json",
	]


def test_report_folder_holds_clean_copies_and_a_manifest(tmp_path):
	item = flagged(image(tmp_path, "a.jpg"))
	manifest = manifest_for([item])

	folder = write_report(tmp_path / "videos", "Strandallee", DAY, manifest, [item])

	assert folder == tmp_path / "videos" / "Strandallee" / "highlights" / "2026-10-20"
	assert (folder / "a.jpg").read_bytes() == JPEG
	assert json.loads((folder / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_empty_report_still_writes_a_manifest(tmp_path):
	manifest = manifest_for([], checked=97)

	folder = write_report(tmp_path / "videos", "Strandallee", DAY, manifest, [])

	assert [p.name for p in folder.iterdir()] == ["manifest.json"]
	saved = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
	assert (saved["items"], saved["checked"]) == ([], 97)


def test_rerun_replaces_the_day_and_leaves_other_days_alone(tmp_path):
	video_root = tmp_path / "videos"
	first = flagged(image(tmp_path, "a.jpg"))
	second = flagged(image(tmp_path, "b.jpg"))
	write_report(video_root, "Strandallee", DAY, manifest_for([first]), [first])
	other_day = write_report(video_root, "Strandallee", date(2026, 10, 19), manifest_for([]), [])

	folder = write_report(video_root, "Strandallee", DAY, manifest_for([second]), [second])

	assert sorted(p.name for p in folder.iterdir()) == ["b.jpg", "manifest.json"]
	assert (other_day / "manifest.json").is_file()
	assert sorted(p.name for p in folder.parent.iterdir()) == ["2026-10-19", "2026-10-20"]


def test_failure_while_copying_keeps_the_previous_report_and_leaves_no_temp(tmp_path, monkeypatch):
	video_root = tmp_path / "videos"
	old = flagged(image(tmp_path, "old.jpg"))
	folder = write_report(video_root, "Strandallee", DAY, manifest_for([old]), [old])
	before = {p.name: p.read_bytes() for p in folder.iterdir()}

	real_copy = shutil.copy2
	calls = []

	def failing_copy(source, target, *args, **kwargs):
		calls.append(source)
		if len(calls) == 2:
			raise OSError("disk full")
		return real_copy(source, target, *args, **kwargs)

	monkeypatch.setattr(report.shutil, "copy2", failing_copy)
	new = [flagged(image(tmp_path, "a.jpg")), flagged(image(tmp_path, "b.jpg"))]

	with pytest.raises(OSError, match="disk full"):
		write_report(video_root, "Strandallee", DAY, manifest_for(new), new)

	assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
	assert [p.name for p in folder.parent.iterdir()] == ["2026-10-20"]


def test_leftover_temp_folder_from_a_crash_is_replaced(tmp_path):
	highlights = tmp_path / "videos" / "Strandallee" / "highlights"
	(highlights / ".2026-10-20.tmp").mkdir(parents=True)
	(highlights / ".2026-10-20.tmp" / "stale.jpg").write_bytes(JPEG)
	item = flagged(image(tmp_path, "a.jpg"))

	folder = write_report(tmp_path / "videos", "Strandallee", DAY, manifest_for([item]), [item])

	assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "manifest.json"]
	assert [p.name for p in highlights.iterdir()] == ["2026-10-20"]
