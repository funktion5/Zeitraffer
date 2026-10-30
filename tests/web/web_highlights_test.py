import json
from pathlib import Path

import pytest

from web_php_test import PROJECT_ROOT_CALL, run_php, run_wrapper


# Load highlights-library.php from the patched copy, so projectRoot() points at tmp_path.
def highlights(tmp_path: Path, code: str):
	library = tmp_path / "php-src" / "highlights-library.php"
	return run_php(
		tmp_path,
		"video-library.php",
		{PROJECT_ROOT_CALL: json.dumps(str(tmp_path))},
		f"require_once {json.dumps(str(library))};\n{code}",
	)


def item(name: str, time: str = "08:14", **fields) -> dict:
	return {
		"file": name,
		"taken_at": f"2026-10-20T{time}:58+02:00",
		"group": "flying",
		"label": "airplane",
		"score": 0.8642,
		"box": [716, 579, 814, 625],
		"image_size": [1920, 1080],
		**fields,
	}


# Write a flagger report (schema 1) and, unless told otherwise, the image files it names.
def make_day(
	tmp_path: Path,
	camera: str,
	date: str,
	items: list,
	checked: int = 10,
	write_images: bool = True,
	manifest=None,
) -> Path:
	day = tmp_path / "videos" / camera / "highlights" / date
	day.mkdir(parents=True)
	if manifest is None:
		manifest = {
			"schema": 1,
			"camera": camera,
			"date": date,
			"checked": checked,
			"items": items,
		}
	(day / "manifest.json").write_text(
		manifest if isinstance(manifest, str) else json.dumps(manifest)
	)
	if write_images:
		for entry in items:
			if isinstance(entry, dict) and isinstance(entry.get("file"), str):
				name = entry["file"]
				if "/" not in name and name not in ("", ".", ".."):
					(day / name).write_bytes(b"x")
	return day


def write_config(tmp_path: Path, config) -> None:
	(tmp_path / "config").mkdir(exist_ok=True)
	(tmp_path / "config" / "config.json").write_text(
		config if isinstance(config, str) else json.dumps(config)
	)


def days(tmp_path: Path, camera: str, since=None):
	return highlights(
		tmp_path,
		# ensure_ascii=False: PHP string literals do not understand JSON's \u escapes.
		f"echo json_encode(findHighlightDays({json.dumps(camera, ensure_ascii=False)}, "
		f"{json.dumps(since)}));",
	)


def test_labels_period_and_names(tmp_path):
	result = highlights(
		tmp_path,
		"""
		$today = new DateTimeImmutable("2026-10-21");
		echo json_encode([
			array_map("translateHighlightLabel", ["bird", "airplane", "kite", "horse", "zzz"]),
			array_map("parseHighlightsPeriod", ["1", "7", "30", "all", "8", "", null, []]),
			highlightsSinceDate("1", $today),
			highlightsSinceDate("7", $today),
			highlightsSinceDate("30", $today),
			highlightsSinceDate("all", $today),
			array_map("isValidHighlightName",
				["a-1_b.2.jpg", "", ".a.jpg", "a.png", "a/b.jpg", "a b.jpg", "<x>.jpg", "a.JPG"]),
			array_map("isValidHighlightCamera",
				["SLSV", "BSV-Steinhude", "", ".", "..", "a/b", ".hidden", "a\\nb"]),
		]);
		""",
	)

	assert result == [
		["Vogel", "Flugzeug", "Drachen", "Pferd", "zzz"],
		["1", "7", "30", "all", "7", "7", "7", "7"],
		"2026-10-20",
		"2026-10-14",
		"2026-09-21",
		None,
		[True, False, False, False, False, False, False, False],
		[True, True, False, False, False, False, False, False],
	]


@pytest.mark.parametrize(
	("config", "expected"),
	[
		({"location": {"timezone": "Europe/Berlin"}}, "Europe/Berlin"),
		({"location": {"timezone": "Mars/Base"}}, "UTC"),
		({"location": "x"}, "UTC"),
		("not json", "UTC"),
	],
)
def test_today_uses_the_configured_timezone(tmp_path, config, expected):
	write_config(tmp_path, config)

	result = highlights(
		tmp_path,
		"$today = highlightsToday();"
		'echo json_encode([$today->getTimezone()->getName(), $today->format("H:i")]);',
	)

	assert result == [expected, "00:00"]


def test_days_are_newest_first_and_items_keep_manifest_order(tmp_path):
	make_day(tmp_path, "Cam", "2026-10-19", [item("old.jpg")])
	make_day(tmp_path, "Cam", "2026-10-20", [item("b.jpg", score=0.9), item("a.jpg", score=0.4)])

	result = days(tmp_path, "Cam")

	assert [day["date"] for day in result] == ["2026-10-20", "2026-10-19"]
	assert [entry["file"] for entry in result[0]["items"]] == ["b.jpg", "a.jpg"]


def test_period_limits_the_days(tmp_path):
	make_day(tmp_path, "Cam", "2026-10-13", [item("a.jpg")])
	make_day(tmp_path, "Cam", "2026-10-14", [item("b.jpg")])
	make_day(tmp_path, "Cam", "2026-10-20", [item("c.jpg")])

	result = days(tmp_path, "Cam", "2026-10-14")

	assert [day["date"] for day in result] == ["2026-10-20", "2026-10-14"]


def test_item_fields_and_url(tmp_path):
	make_day(
		tmp_path,
		"Cam Ä",
		"2026-10-20",
		[item("strandallee-26-10-20_08-14-58-20.jpg", score=1)],
		checked=143,
	)

	result = days(tmp_path, "Cam Ä")

	assert result == [
		{
			"date": "2026-10-20",
			"checked": 143,
			"items": [
				{
					"file": "strandallee-26-10-20_08-14-58-20.jpg",
					"url": "/videos/Cam%20%C3%84/highlights/2026-10-20/"
					"strandallee-26-10-20_08-14-58-20.jpg",
					"time": "08:14",
					"label": "airplane",
					"score": 1.0,
					"box": [716, 579, 814, 625],
					"imageSize": [1920, 1080],
				}
			],
		}
	]


# A broken report must cost only its own day, never the page.
@pytest.mark.parametrize(
	"manifest",
	[
		"not json",
		"[]",
		{"schema": 2, "checked": 1, "items": []},
		{"schema": 1, "checked": 1, "items": "x"},
		{"schema": 1, "checked": "1", "items": []},
		{"schema": 1, "checked": -1, "items": []},
		{"schema": 1, "items": []},
	],
)
def test_corrupt_or_wrong_schema_manifest_is_skipped(tmp_path, manifest):
	make_day(tmp_path, "Cam", "2026-10-19", [item("a.jpg")])
	make_day(tmp_path, "Cam", "2026-10-20", [], manifest=manifest)

	result = days(tmp_path, "Cam")

	assert [day["date"] for day in result] == ["2026-10-19"]


@pytest.mark.parametrize(
	"bad",
	[
		{"score": "0.8"},
		{"score": 1.5},
		{"box": [1, 2, 3]},
		{"box": [1, 2, 3, "4"]},
		{"image_size": [0, 1080]},
		{"image_size": [1920]},
		{"taken_at": "yesterday"},
		{"taken_at": 5},
		{"label": ["bird"]},
		{"label": ""},
		{"group": "person"},
		{"file": 3},
	],
)
def test_items_with_wrong_fields_are_dropped(tmp_path, bad):
	make_day(tmp_path, "Cam", "2026-10-20", [item("good.jpg"), item("bad.jpg", **bad)])

	result = days(tmp_path, "Cam")

	assert [entry["file"] for entry in result[0]["items"]] == ["good.jpg"]


def test_item_missing_a_field_is_dropped(tmp_path):
	broken = item("bad.jpg")
	del broken["box"]
	make_day(tmp_path, "Cam", "2026-10-20", [item("good.jpg"), broken, "not an object"])

	result = days(tmp_path, "Cam")

	assert [entry["file"] for entry in result[0]["items"]] == ["good.jpg"]


def test_item_whose_image_is_missing_or_a_symlink_is_dropped(tmp_path):
	day = make_day(
		tmp_path,
		"Cam",
		"2026-10-20",
		[item("kept.jpg"), item("gone.jpg"), item("link.jpg"), item("dir.jpg")],
		checked=7,
	)
	(day / "gone.jpg").unlink()
	(day / "link.jpg").unlink()
	(day / "link.jpg").symlink_to(day / "kept.jpg")
	(day / "dir.jpg").unlink()
	(day / "dir.jpg").mkdir()

	result = days(tmp_path, "Cam")

	assert [entry["file"] for entry in result[0]["items"]] == ["kept.jpg"]


def test_hostile_names_in_the_manifest_are_dropped(tmp_path):
	day = make_day(
		tmp_path,
		"Cam",
		"2026-10-20",
		[item("../x.jpg"), item("a/b.jpg"), item(".h.jpg"), item("<s>.jpg"), item("ok.jpg")],
	)
	(day / ".h.jpg").write_bytes(b"x")
	(tmp_path / "videos" / "Cam" / "highlights" / "x.jpg").write_bytes(b"x")

	result = days(tmp_path, "Cam")

	assert [entry["file"] for entry in result[0]["items"]] == ["ok.jpg"]


def test_day_without_remaining_items_keeps_its_checked_count(tmp_path):
	day = make_day(tmp_path, "Cam", "2026-10-20", [item("a.jpg")], checked=50)
	(day / "a.jpg").unlink()

	result = days(tmp_path, "Cam")

	assert result == [{"date": "2026-10-20", "checked": 50, "items": []}]


def test_non_date_folders_and_symlinked_days_are_ignored(tmp_path):
	make_day(tmp_path, "Cam", "2026-10-20", [item("a.jpg")])
	make_day(tmp_path, "Cam", ".2026-10-21.tmp", [item("a.jpg")])
	make_day(tmp_path, "Cam", "2026-02-30", [item("a.jpg")])
	make_day(tmp_path, "Cam", "notes", [item("a.jpg")])
	highlights_dir = tmp_path / "videos" / "Cam" / "highlights"
	(highlights_dir / "2026-10-19").symlink_to(highlights_dir / "2026-10-20")

	result = days(tmp_path, "Cam")

	assert [day["date"] for day in result] == ["2026-10-20"]


@pytest.mark.parametrize("camera", ["Nope", "", "..", "../videos", "Cam/highlights"])
def test_unknown_or_invalid_camera_gives_no_days(tmp_path, camera):
	make_day(tmp_path, "Cam", "2026-10-20", [item("a.jpg")])

	assert days(tmp_path, camera) == []


def test_cameras_are_the_union_of_config_and_folders(tmp_path):
	write_config(tmp_path, {"flagger": {"cameras": ["b", "A", 3, "../x", "A"]}})
	make_day(tmp_path, "C", "2026-10-20", [])
	(tmp_path / "videos" / "D").mkdir()

	result = highlights(
		tmp_path, "echo json_encode([getFlaggerCameras(), listHighlightCameras()]);"
	)

	assert result == [["b", "A"], ["A", "b", "C"]]


@pytest.mark.parametrize(
	"config",
	["not json", {"flagger": "x"}, {"flagger": {"cameras": "A"}}, {}],
)
def test_malformed_config_means_folders_only(tmp_path, config):
	write_config(tmp_path, config)
	make_day(tmp_path, "C", "2026-10-20", [])

	result = highlights(
		tmp_path, "echo json_encode([getFlaggerCameras(), listHighlightCameras()]);"
	)

	assert result == [[], ["C"]]


def test_delete_calls_the_wrapper_with_exactly_three_arguments(tmp_path):
	result, args = run_wrapper(
		tmp_path,
		"highlight-delete.php",
		'deleteHighlightImage("Cam", "2026-10-20", "a.jpg")',
		0,
	)

	assert result == {"deleted": True, "message": "Bild erfolgreich gelöscht."}
	assert args[:2] == ["-n", "-u"]
	assert args[3:] == [
		"/usr/local/sbin/timelapse-web-delete-highlight",
		"Cam",
		"2026-10-20",
		"a.jpg",
	]


def test_delete_reports_the_wrapper_message(tmp_path):
	result, _ = run_wrapper(
		tmp_path,
		"highlight-delete.php",
		'deleteHighlightImage("Cam", "2026-10-20", "a.jpg")',
		0,
		out="Gelöscht.",
	)

	assert result == {"deleted": True, "message": "Gelöscht."}


def test_wrapper_failure_gives_the_generic_message_without_details(tmp_path):
	result, _ = run_wrapper(
		tmp_path,
		"highlight-delete.php",
		'deleteHighlightImage("Cam", "2026-10-20", "a.jpg")',
		66,
	)

	assert result == {"deleted": False, "message": "Das Bild konnte nicht gelöscht werden."}


def test_missing_run_user_refuses_without_calling_sudo(tmp_path):
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")
	result, args = run_wrapper(
		tmp_path,
		"highlight-delete.php",
		'deleteHighlightImage("Cam", "2026-10-20", "a.jpg")',
		0,
	)

	assert result["deleted"] is False
	assert args == []
