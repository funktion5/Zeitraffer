import json
import re
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


# The ring is four arcs of one circle (pathLength 100: a dash length is a percent).
def test_the_ring_draws_one_arc_per_part(tmp_path):
	out = render_header(tmp_path, storage())

	for key, dash, offset in (
		("automatic", "10 90", "0"),
		("manual", "5 95", "-10"),
		("other", "25 75", "-15"),
		("free", "60 40", "-40"),
	):
		arc = re.search(rf'<circle\s+class="storage-arc storage-arc-{key}"[^>]*>', out)

		assert arc is not None, key
		assert f'stroke-dasharray="{dash}"' in arc.group(0)
		assert f'stroke-dashoffset="{offset}"' in arc.group(0)


def test_the_ring_arcs_do_not_show_float_noise(tmp_path):
	out = render_header(tmp_path, storage(percents=(0.1, 0.2, 0.0, 99.7)))

	assert 'stroke-dasharray="0.2 99.8"' in out
	assert 'stroke-dashoffset="-0.1"' in out
	assert 'stroke-dasharray="99.7 0.3"' in out
	assert 'stroke-dashoffset="-0.3"' in out


def test_an_empty_part_gets_no_arc(tmp_path):
	out = render_header(tmp_path, storage(percents=(10.0, 0.0, 30.0, 60.0)))

	assert "storage-arc-manual" not in out
	assert "storage-arc-automatic" in out


# Hovering an arc shows what it is: its own title, with the size and the share.
def test_every_arc_says_what_it_is_when_hovered(tmp_path):
	out = render_header(tmp_path, storage())

	assert "<title>Automatische Videos: 3.0 GB (10.0 %)</title>" in out
	assert "<title>Manuelle Videos: 1.0 GB (5.0 %)</title>" in out
	assert "<title>Sonstiges (System, Modelle, Logs, Highlights): 5.0 GB (25.0 %)</title>" in out
	assert "<title>Frei: 20.0 GB (60.0 %)</title>" in out


# Screen readers get the same four statements in one label: a title alone is hover-only.
def test_the_ring_has_one_label_with_all_parts(tmp_path):
	out = render_header(tmp_path, storage())

	label = re.search(r'<svg[^>]*aria-label="([^"]*)"', out)

	assert label is not None
	assert "Automatische Videos: 3.0 GB" in label.group(1)
	assert "Frei: 20.0 GB" in label.group(1)


def test_the_videos_box_shows_the_total_and_no_legend(tmp_path):
	out = render_header(tmp_path, storage())

	assert "<dt>Davon Videos</dt>" in out
	assert "4.0 GB" in out
	assert "storage-kinds" not in out
	assert "storage-swatch" not in out


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
