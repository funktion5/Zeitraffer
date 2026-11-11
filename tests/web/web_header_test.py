import json
import re
import subprocess
from pathlib import Path

from web_php_test import WEB_SRC


def storage(level: str = "ok", percents=(10.0, 5.0, 2.0, 23.0, 60.0)) -> dict:
	keys = ("automatic", "manual", "highlights", "other", "free")
	byte_sizes = (3 * 1024**3, 1024**3, 512 * 1024**2, 5 * 1024**3, 20 * 1024**3)

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


# The ring is five arcs of one circle (pathLength 100: a dash length is a percent).
def test_the_ring_draws_one_arc_per_part(tmp_path):
	out = render_header(tmp_path, storage())

	for key, dash, offset in (
		("automatic", "10 90", "0"),
		("manual", "5 95", "-10"),
		("highlights", "2 98", "-15"),
		("other", "23 77", "-17"),
		("free", "60 40", "-40"),
	):
		arc = re.search(rf'<circle\s+class="storage-arc storage-arc-{key}"[^>]*>', out)

		assert arc is not None, key
		assert f'stroke-dasharray="{dash}"' in arc.group(0)
		assert f'stroke-dashoffset="{offset}"' in arc.group(0)


def test_the_ring_arcs_do_not_show_float_noise(tmp_path):
	out = render_header(tmp_path, storage(percents=(0.1, 0.2, 0.0, 0.0, 99.7)))

	assert 'stroke-dasharray="0.2 99.8"' in out
	assert 'stroke-dashoffset="-0.1"' in out
	assert 'stroke-dasharray="99.7 0.3"' in out
	assert 'stroke-dashoffset="-0.3"' in out


def test_an_empty_part_gets_no_arc(tmp_path):
	out = render_header(tmp_path, storage(percents=(10.0, 0.0, 0.0, 30.0, 60.0)))

	assert "storage-arc-manual" not in out
	assert "storage-arc-automatic" in out


# Hovering an arc shows what it is: a tooltip box with the size and the share, which the CSS shows
# at once. A native title tooltip would come back with the browser's delay, so there is none.
def test_every_arc_has_a_tooltip_box_saying_what_it_is(tmp_path):
	out = render_header(tmp_path, storage())

	for key, text in (
		("automatic", "Automatische Videos: 3.0 GB (10.0 %)"),
		("manual", "Manuelle Videos: 1.0 GB (5.0 %)"),
		("highlights", "Highlight-Bilder: 512.0 MB (2.0 %)"),
		("other", "Sonstiges (System, Modelle, Logs): 5.0 GB (23.0 %)"),
		("free", "Frei: 20.0 GB (60.0 %)"),
	):
		assert (
			f'<span class="storage-tip storage-tip-{key}" aria-hidden="true">{text}</span>' in out
		)

	assert "<title>" not in out


def test_an_empty_part_gets_no_tooltip_box(tmp_path):
	out = render_header(tmp_path, storage(percents=(10.0, 0.0, 0.0, 30.0, 60.0)))

	assert "storage-tip-manual" not in out


# The tooltip of an arc is shown by hovering THAT arc and no other: one rule per arc.
def test_the_style_shows_a_tooltip_only_for_the_hovered_arc(tmp_path):
	css = (WEB_SRC.parent / "public" / "style.css").read_text(encoding="utf-8")

	for key in ("automatic", "manual", "highlights", "other", "free"):
		assert f".storage-chart:has(.storage-arc-{key}:hover) .storage-tip-{key}" in css

	# No delay: shown by display, not by a transition or animation.
	tip_rule = css[css.index(".storage-tip {") : css.index("}", css.index(".storage-tip {"))]
	assert "transition" not in tip_rule
	assert "animation" not in tip_rule


# Screen readers get the same statements in one label: a title alone is hover-only.
def test_the_ring_has_one_label_with_all_parts(tmp_path):
	out = render_header(tmp_path, storage())

	label = re.search(r'<svg[^>]*aria-label="([^"]*)"', out)

	assert label is not None
	assert "Automatische Videos: 3.0 GB" in label.group(1)
	assert "Frei: 20.0 GB" in label.group(1)


# The tooltip boxes are spans too: a bare ".storage-chart span" rule would move them like the label.
def test_the_percentage_label_has_its_own_class_apart_from_the_tooltips(tmp_path):
	out = render_header(tmp_path, storage())
	css = (WEB_SRC.parent / "public" / "style.css").read_text(encoding="utf-8")

	assert '<span class="storage-percent">' in out
	assert ".storage-chart span" not in css


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
