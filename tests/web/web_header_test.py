import json
import subprocess
from pathlib import Path

from web_php_test import WEB_SRC


def storage(level: str = "ok", percents=(10.0, 5.0, 25.0, 60.0)) -> dict:
	keys = ("automatic", "manual", "other", "free")
	byte_sizes = (3 * 1024**3, 1024**3, 5 * 1024**3, 20 * 1024**3)

	return {
		"total": "38.0 GB",
		"used": "9.0 GB",
		"available": "29.0 GB",
		"usedPercent": 40.0,
		"level": level,
		"videos": "4.0 GB",
		"segments": [
			{"key": key, "bytes": size, "percent": percent}
			for key, size, percent in zip(keys, byte_sizes, percents, strict=True)
		],
	}


# The header component as a page includes it: the page has loaded the library and set $storage.
def render_header(tmp_path: Path, data: dict | None) -> str:
	driver = tmp_path / "header-driver.php"
	driver.write_text(
		"<?php\n"
		f"require_once {json.dumps(str(WEB_SRC / 'video-library.php'))};\n"
		f"$storage = json_decode({json.dumps(json.dumps(data))}, true);\n"
		f"require {json.dumps(str(WEB_SRC / 'components' / 'header.php'))};\n"
	)
	result = subprocess.run(
		["php", "-d", "display_errors=1", "-d", "error_reporting=-1", str(driver)],
		capture_output=True,
		text=True,
		check=False,
	)

	assert result.returncode == 0, result.stdout + result.stderr
	for problem in ("Warning:", "Notice:", "Deprecated:", "Fatal error"):
		assert problem not in result.stdout, result.stdout

	return result.stdout


# The ring is one conic-gradient; the page hands it the END of each part as a custom property.
def test_the_ring_gets_the_end_of_each_part(tmp_path):
	out = render_header(tmp_path, storage())

	assert "--storage-automatic: 10%" in out
	assert "--storage-manual: 15%" in out
	assert "--storage-other: 40%" in out


def test_the_ring_ends_do_not_show_float_noise(tmp_path):
	out = render_header(tmp_path, storage(percents=(0.1, 0.2, 0.0, 99.7)))

	assert "--storage-manual: 0.3%" in out


def test_the_videos_box_names_both_kinds_with_their_sizes(tmp_path):
	out = render_header(tmp_path, storage())

	assert "<dt>Davon Videos</dt>" in out
	assert "4.0 GB" in out
	assert "Automatisch" in out
	assert "3.0 GB" in out
	assert "Manuell" in out
	assert "1.0 GB" in out


def test_the_old_boxes_are_still_there(tmp_path):
	out = render_header(tmp_path, storage())

	for label, value in (("Gesamt", "38.0 GB"), ("Belegt", "9.0 GB"), ("Verfügbar", "29.0 GB")):
		assert f"<dt>{label}</dt>" in out
		assert value in out


def test_no_warning_while_there_is_room(tmp_path):
	out = render_header(tmp_path, storage("ok"))

	assert 'data-level="ok"' in out
	assert "storage-warning" not in out


# Colour alone is not enough: from the warning level on the header says it in words.
def test_the_warning_level_says_it_in_words(tmp_path):
	out = render_header(tmp_path, storage("warn"))

	assert 'data-level="warn"' in out
	assert "Speicher wird knapp" in out


def test_the_critical_level_says_it_in_words(tmp_path):
	out = render_header(tmp_path, storage("critical"))

	assert 'data-level="critical"' in out
	assert "Speicher fast voll" in out


def test_an_unknown_level_falls_back_to_ok(tmp_path):
	out = render_header(tmp_path, storage('"><script>x</script>'))

	assert "<script>x" not in out
	assert 'data-level="ok"' in out


def test_nothing_is_shown_when_the_disk_cannot_be_read(tmp_path):
	out = render_header(tmp_path, None)

	assert "storage-overview" not in out
