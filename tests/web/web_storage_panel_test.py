import json
import re
from pathlib import Path

from web_php_test import PROJECT_ROOT_CALL, WEB_PUBLIC, WEB_SRC, run_php


# A disk of 1000 bytes with 400 free. The cameras' videos are inside the segments, as in real data.
def disk(videos: int) -> dict:
	return {
		"usedPercent": 60.0,
		"level": "ok",
		"segments": [
			{"key": "automatic", "bytes": videos, "percent": 0},
			{"key": "other", "bytes": 1000 - 400 - videos, "percent": 0},
			{"key": "free", "bytes": 400, "percent": 40.0},
		],
	}


# unreadable: the page found no disk figures at all ($storage is null).
def render_panel(tmp_path: Path, sizes: dict, unreadable: bool = False) -> str:
	for camera, size in sizes.items():
		video = tmp_path / "videos" / camera / "daily" / "a.mp4"
		video.parent.mkdir(parents=True, exist_ok=True)
		video.write_bytes(b"x" * size)

	(tmp_path / "videos").mkdir(exist_ok=True)
	storage = None if unreadable else disk(sum(sizes.values()))
	panel = WEB_SRC / "components" / "storage-panel.php"
	code = (
		f"$storage = json_decode({json.dumps(json.dumps(storage))}, true);"
		f" ob_start(); require {json.dumps(str(panel))}; echo json_encode(ob_get_clean());"
	)

	return run_php(
		tmp_path, "video-library.php", {PROJECT_ROOT_CALL: json.dumps(str(tmp_path))}, code
	)


def parts_list(out: str) -> str:
	start = out.index('<ul class="storage-parts">')

	return out[start : out.index("</ul>", start)]


def test_the_panel_has_a_heading_and_two_donuts_with_captions(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})

	assert "<h2" in out
	assert "Der ganze Speicher" in out
	assert "Nur die Videos" in out
	assert out.count("<svg") == 2


def test_the_list_names_every_part_with_its_size_and_no_percent(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})
	items = parts_list(out)

	for name, size in (
		("A", "300.0 B"),
		("B", "100.0 B"),
		("Sonstiges (System, Modelle, Logs)", "200.0 B"),
		("Frei", "400.0 B"),
	):
		assert f">{name}<" in items
		assert size in items

	# Two different bases (disk, videos) must never share a column: the percents are in the tips.
	assert "%" not in items


# The tooltip text names the base of its percent, so nobody reads a video share as a disk share.
def test_every_arc_has_a_tooltip_saying_what_its_percent_is_a_share_of(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})

	assert 'data-tip="A: 300.0 B (30.0 % des Speichers)"' in out
	assert 'data-tip="Frei: 400.0 B (40.0 % des Speichers)"' in out
	assert 'data-tip="A: 300.0 B (75.0 % der Videos)"' in out
	assert 'data-tip="B: 100.0 B (25.0 % der Videos)"' in out


def test_the_donut_of_the_videos_has_only_the_cameras(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})

	# Disk donut: A, B, Sonstiges, Frei. Video donut: A, B.
	assert out.count("data-tip=") == 6
	assert out.count('data-tip="Frei') == 1
	assert out.count('data-tip="Sonstiges') == 1


# Same arc maths as the header ring: pathLength 100, so a dash length is a percent.
def test_the_arcs_are_drawn_as_dashes_of_one_circle(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})

	assert 'stroke-dasharray="30 70" stroke-dashoffset="0"' in out
	assert 'stroke-dasharray="10 90" stroke-dashoffset="-30"' in out
	assert 'stroke-dasharray="75 25" stroke-dashoffset="0"' in out
	assert 'stroke-dasharray="25 75" stroke-dashoffset="-75"' in out


def test_the_cameras_have_the_same_colour_in_both_donuts(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})

	colours = re.findall(r'data-tip="A: [^"]*" style="stroke: ([^"]*)"', out)

	assert len(colours) == 2
	assert colours[0] == colours[1]


def test_the_centres_say_how_full_the_disk_is_and_how_big_the_videos_are(tmp_path):
	out = render_panel(tmp_path, {"A": 300, "B": 100})

	assert "60%" in out
	assert "belegt" in out
	assert "400.0 B" in out


def test_more_than_six_cameras_are_lumped_together_in_both_donuts(tmp_path):
	out = render_panel(tmp_path, {f"Cam{number}": 10 + number for number in range(8)})

	assert out.count('data-tip="Weitere Kameras (2)') == 2


def test_the_donuts_have_a_label_for_screen_readers(tmp_path):
	out = render_panel(tmp_path, {"A": 300})

	assert len(re.findall(r'<svg[^>]*role="img"[^>]*aria-label="[^"]+"', out)) == 2


def test_without_any_videos_the_video_donut_is_left_out(tmp_path):
	out = render_panel(tmp_path, {})

	assert "Der ganze Speicher" in out
	assert "Nur die Videos" not in out


def test_nothing_is_shown_when_the_disk_cannot_be_read(tmp_path):
	out = render_panel(tmp_path, {"A": 300}, unreadable=True)

	assert "storage-panel" not in out


# The tooltip is a script, not a title: the browser's own tooltip comes only after a delay.
def test_the_tooltip_script_shows_the_text_of_the_arc_under_the_pointer():
	script = (WEB_PUBLIC / "storage-ring.js").read_text(encoding="utf-8")

	assert ".dataset.tip" in script
	assert "pointermove" in script
	assert "pointerleave" in script
	assert "innerHTML" not in script
