import json
import os
import re
import subprocess
from pathlib import Path

from web_php_test import WEB_SRC

WEB_PUBLIC = WEB_SRC.parent / "public"
PAGES = ("index.php", "camera.php", "highlights.php", "settings.php", "verpixelung.php")

FRESH_NIGHT = {
	"night": {
		"date": "2026-11-18",
		"run": "20261118-020005",
		"started": "2026-11-18T02:00:05+01:00",
		"finished": "2026-11-18T02:55:12.123456+01:00",
	},
	"messages": [],
}
FRESH_WATCH = {"checked": "2026-11-18T06:55:00+01:00", "stale": {"SLSV": 0}, "error": None}


def write_state(root: Path, warnings=FRESH_NIGHT, watch=FRESH_WATCH) -> None:
	root.mkdir(parents=True, exist_ok=True)

	for name, content in (("warnings.json", warnings), ("blur-watch.json", watch)):
		path = root / name

		if content is None:
			path.unlink(missing_ok=True)
			continue

		text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
		path.write_text(text, encoding="utf-8")


def run_driver(tmp_path: Path, code: str) -> str:
	driver = tmp_path / "banner-driver.php"
	driver.write_text(
		"<?php\n"
		f"require_once {json.dumps(str(WEB_SRC / 'video-library.php'))};\n"
		f"require_once {json.dumps(str(WEB_SRC / 'warnings.php'))};\n" + code
	)
	environment = {**os.environ, "TIMELAPSE_WEB_STATUS_ROOT": str(tmp_path / "web-jobs")}
	result = subprocess.run(
		["php", "-d", "display_errors=1", "-d", "error_reporting=-1", str(driver)],
		capture_output=True,
		text=True,
		check=False,
		env=environment,
	)

	assert result.returncode == 0, result.stdout + result.stderr
	for problem in ("Warning:", "Notice:", "Deprecated:", "Fatal error"):
		assert problem not in result.stdout, result.stdout

	return result.stdout


def banner(tmp_path: Path, now: str, storage: dict | None = None) -> dict:
	code = (
		f"$now = DateTimeImmutable::createFromFormat(DATE_ATOM, {json.dumps(now)});\n"
		f"$storage = json_decode({json.dumps(json.dumps(storage))}, true);\n"
		"echo json_encode(bannerMessages($now, $storage));\n"
	)

	return json.loads(run_driver(tmp_path, code))


def texts(result: dict) -> list[tuple]:
	return [(message["camera"], message["text"]) for message in result["messages"]]


def render(tmp_path: Path, now: str) -> str:
	code = (
		f"$bannerNow = DateTimeImmutable::createFromFormat(DATE_ATOM, {json.dumps(now)});\n"
		"$storage = null;\n"
		f"require {json.dumps(str(WEB_SRC / 'components' / 'warning-banner.php'))};\n"
	)

	return run_driver(tmp_path, code)


MORNING = "2026-11-18T07:00:00+01:00"


def test_nothing_to_report(tmp_path):
	write_state(tmp_path / "web-jobs")

	result = banner(tmp_path, MORNING)

	assert result["messages"] == []
	assert result["lastRun"] == "18.11.2026, 02:00–02:55 Uhr"

	page = render(tmp_path, MORNING)
	assert "Nichts zu melden." in page
	assert "Letzter Nachtlauf: 18.11.2026, 02:00–02:55 Uhr" in page
	assert 'data-state="ok"' in page


def test_night_messages_are_shown(tmp_path):
	night = dict(FRESH_NIGHT)
	night["messages"] = [
		{"camera": "Strandterrassen", "text": "856 Bildnamen nicht lesbar", "hint": "Handbuch"},
		{"camera": None, "text": "Upload auf die Website lief nicht", "hint": "Cron-Zeile prüfen"},
	]
	write_state(tmp_path / "web-jobs", warnings=night)

	assert texts(banner(tmp_path, MORNING)) == [
		("Strandterrassen", "856 Bildnamen nicht lesbar"),
		(None, "Upload auf die Website lief nicht"),
	]

	page = render(tmp_path, MORNING)
	assert "2 Meldungen" in page
	assert 'data-state="warn"' in page
	assert "Strandterrassen" in page
	assert "Cron-Zeile prüfen" in page


def test_missing_file_is_not_green(tmp_path):
	write_state(tmp_path / "web-jobs", warnings=None)

	assert texts(banner(tmp_path, MORNING)) == [(None, "Nachtlauf fehlt")]


def test_broken_json_is_not_green(tmp_path):
	for broken in ('{"night": {"date": "2026-11-18"', '{"night": 5, "messages": "x"}', "[]"):
		write_state(tmp_path / "web-jobs", warnings=broken)

		assert texts(banner(tmp_path, MORNING)) == [(None, "Nachtlauf fehlt")], broken


# Between 02:00 and 06:00 the night may still be running: yesterday's file still counts.
def test_before_six_yesterday_still_counts(tmp_path):
	write_state(tmp_path / "web-jobs", watch=dict(FRESH_WATCH, checked="2026-11-19T05:28:00+01:00"))

	assert banner(tmp_path, "2026-11-19T05:30:00+01:00")["messages"] == []


def test_after_six_yesterday_is_missing(tmp_path):
	write_state(tmp_path / "web-jobs", watch=dict(FRESH_WATCH, checked="2026-11-19T05:58:00+01:00"))

	result = banner(tmp_path, "2026-11-19T06:00:00+01:00")

	assert texts(result) == [(None, "Nachtlauf fehlt")]
	assert result["lastRun"] == "18.11.2026, 02:00–02:55 Uhr"


def test_stale_watchdog_file(tmp_path):
	write_state(tmp_path / "web-jobs", watch=dict(FRESH_WATCH, checked="2026-11-18T06:40:00+01:00"))

	assert texts(banner(tmp_path, MORNING)) == [(None, "Verpixelungs-Wächter läuft nicht")]


def test_missing_watchdog_file(tmp_path):
	write_state(tmp_path / "web-jobs", watch=None)

	assert texts(banner(tmp_path, MORNING)) == [(None, "Verpixelungs-Wächter läuft nicht")]


def test_watchdog_error(tmp_path):
	write_state(tmp_path / "web-jobs", watch=dict(FRESH_WATCH, error="No storage box: x"))

	assert texts(banner(tmp_path, MORNING)) == [(None, "Verpixelungs-Wächter: No storage box: x")]


def test_stale_images_per_camera(tmp_path):
	write_state(tmp_path / "web-jobs", watch=dict(FRESH_WATCH, stale={"SLSV": 3, "Other": 0}))

	assert texts(banner(tmp_path, MORNING)) == [
		("SLSV", "3 Bilder seit über 10 Minuten unverpixelt")
	]

	write_state(tmp_path / "web-jobs", watch=dict(FRESH_WATCH, stale={"SLSV": 1}))

	assert texts(banner(tmp_path, MORNING)) == [("SLSV", "1 Bild seit über 10 Minuten unverpixelt")]


def test_disk_level_warn_and_critical(tmp_path):
	write_state(tmp_path / "web-jobs")

	assert texts(banner(tmp_path, MORNING, {"level": "warn"})) == [(None, "Speicher wird knapp")]
	assert texts(banner(tmp_path, MORNING, {"level": "critical"})) == [(None, "Speicher fast voll")]
	assert texts(banner(tmp_path, MORNING, {"level": "ok"})) == []


def test_camera_names_are_escaped(tmp_path):
	night = dict(FRESH_NIGHT)
	night["messages"] = [{"camera": "<b>Cam & Co</b>", "text": "<i>x</i>", "hint": "<u>y</u>"}]
	write_state(tmp_path / "web-jobs", warnings=night)

	page = render(tmp_path, MORNING)

	assert "<b>" not in page and "<i>" not in page and "<u>" not in page
	assert "&lt;b&gt;Cam &amp; Co&lt;/b&gt;" in page


# Every page requires the header, and the header brings the banner.
def test_every_page_shows_the_banner():
	header = (WEB_SRC / "components" / "header.php").read_text(encoding="utf-8")

	assert re.search(r"require[^;]*warning-banner\.php", header)
	for page in PAGES:
		assert "components/header.php" in (WEB_PUBLIC / page).read_text(encoding="utf-8"), page
