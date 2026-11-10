import html
import json
import os
import re
from pathlib import Path

import pytest

import src.config as config_module
from web_php_test import SUDO_PATH, fake_sudo, render_page

TOKEN = "test-token"
FILE_TIME = 1_700_000_000
SAVED = '{"status": "saved", "errors": [], "mtime": 456}'
WRAPPER = "/usr/local/sbin/timelapse-web-settings"
CAMERAS = ("Alpha", "Scheunenviertel", "SLSV")
BLUR_CAMERAS = ("BlurTest", "Scheunenviertel", "SLSV")
BLANK = {"x0": "", "y0": "", "x1": "", "y1": ""}

BASE = {
	"location": {"latitude": 52.472, "longitude": 9.333, "timezone": "Europe/Berlin"},
	"ignored_cameras": ["BlurTest"],
	"privacy": {
		"blur_cameras": ["BlurTest", "Scheunenviertel", "SLSV"],
		"blur": {"strength": 0.08, "padding_ratio": 0.05, "feather": 0.5},
		"ignore_top_share": 0.333,
		"min_person_score": {"SLSV": 0.35},
		"ignore_boxes": {
			"BlurTest": [[703, 557, 742, 643]],
			"Scheunenviertel": [[1, 2, 3, 4], [5, 6, 7, 8]],
		},
	},
}

FLOATS = {
	"privacy.blur.strength": "0.08",
	"privacy.blur.padding_ratio": "0.05",
	"privacy.blur.feather": "0.5",
}

# What the page sends for each blur camera's own top share when nothing was changed: the global
# value (the writer then stores nothing).
TOPS ={"BlurTest": "0.333", "Scheunenviertel": "0.333", "SLSV": "0.333"}

# Every control that carries an explanation, by element id.
EXPLAINED = [
	"privacy-privacy-blur-strength",
	"privacy-privacy-blur-padding_ratio",
	"privacy-privacy-blur-feather",
	"privacy-score-SLSV",
	"privacy-top-SLSV",
]


def prepare(tmp_path: Path, config=None, privacy=None, cameras=CAMERAS) -> None:
	(tmp_path / "config").mkdir(parents=True, exist_ok=True)
	(tmp_path / "config" / "config.json").write_text(json.dumps(config or BASE))

	if privacy is not None:
		path = tmp_path / "config" / "settings-privacy.json"
		path.write_text(json.dumps(privacy))
		os.utime(path, (FILE_TIME, FILE_TIME))

	list_path = tmp_path / "state" / "web-jobs" / "cameras.json"
	list_path.parent.mkdir(parents=True, exist_ok=True)
	list_path.write_text(json.dumps(list(cameras)))


def render(tmp_path: Path, post=None, sudo_exit: int = 0, sudo_out: str = ""):
	swaps = {"src/settings-runner.php": (SUDO_PATH, str(fake_sudo(tmp_path)))}

	return render_page(tmp_path, "verpixelung.php", swaps, {}, post, sudo_exit, TOKEN, sudo_out)


def box_rows(boxes: list) -> dict:
	names = ("x0", "y0", "x1", "y1")
	rows = {}

	for index, box in enumerate(boxes):
		rows[str(index)] = {name: str(value) for name, value in zip(names, box)}

	rows[str(len(boxes))] = dict(BLANK)

	return rows


# A complete, valid POST (what the browser sends after the confirm dialog), with changes on top.
def privacy_post(
	floats=None, cameras=BLUR_CAMERAS, score=None, boxes=None, top=None, **extra
) -> dict:
	base_boxes = BASE["privacy"]["ignore_boxes"]
	post = {
		"csrf_token": TOKEN,
		"confirm_privacy": "yes",
		"loaded_mtime": "0",
		"blur_cameras": list(cameras),
		"privacy": {
			"floats": {**FLOATS, **(floats or {})},
			"top": {**TOPS, **(top or {})},
			"score": {"BlurTest": "0", "Scheunenviertel": "0", "SLSV": "0.35", **(score or {})},
			"boxes": {
				"BlurTest": box_rows(base_boxes["BlurTest"]),
				"Scheunenviertel": box_rows(base_boxes["Scheunenviertel"]),
				"SLSV": box_rows([]),
				**(boxes or {}),
			},
		},
	}
	post.update(extra)

	return post


def sent_values(args: list) -> dict:
	return json.loads(args[-1])


def tag_of(out: str, pattern: str, flags: int = 0) -> str:
	match = re.search(pattern, out, flags)

	assert match is not None, pattern

	return match.group(0)


def script_with(out: str, marker: str) -> str:
	scripts = re.findall(r"<script[^>]*>(.*?)</script>", out, re.S)
	matching = [script for script in scripts if marker in script]

	assert len(matching) == 1, marker

	return matching[0]


def camera_boxes(out: str) -> dict:
	boxes = {}

	for tag in re.findall(r'<input[^>]*name="blur_cameras\[\]"[^>]*>', out):
		value = re.search(r'value="([^"]+)"', tag).group(1)
		standard = re.search(r'data-default-checked="([01])"', tag).group(1)
		boxes[value] = (standard, re.search(r"\schecked\b", tag) is not None)

	return boxes


def default_boxes_of(out: str, camera: str) -> list:
	container = tag_of(out, rf'<div[^>]*id="privacy-boxes-{camera}"[^>]*>')
	raw = re.search(r'data-default-boxes="([^"]*)"', container).group(1)

	return json.loads(html.unescape(raw))


def test_the_page_has_its_groups_and_the_tab_strip(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	assert "<h1>Einstellungen</h1>" in out
	assert "<legend>Welche Kameras werden verpixelt?</legend>" in out
	assert "<legend>Wie wird verpixelt?</legend>" in out
	# The top strip is a per-camera setting now: no group of its own, no field for all cameras.
	assert "<legend>Oberer Bildrand</legend>" not in out
	assert "privacy.ignore_top_share]" not in out

	strip = tag_of(out, r'<nav[^>]*class="settings-tabs"[^>]*>.*?</nav>', re.S)
	current = re.findall(r'<a[^>]*aria-current="page"[^>]*>', strip)

	assert re.findall(r'href="(/[a-z]+\.php)"', strip) == ["/settings.php", "/verpixelung.php"]
	assert len(current) == 1
	assert 'href="/verpixelung.php"' in current[0]
	# The gear link of the header marks the settings area as the current one, too.
	assert 'class="settings-link"' in out


def test_the_camera_list_shows_listed_ignored_and_blur_cameras(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	# The first value is the Standard from config.json, the second whether it is ticked now.
	assert camera_boxes(out) == {
		"Alpha": ("0", False),
		"BlurTest": ("1", True),
		"Scheunenviertel": ("1", True),
		"SLSV": ("1", True),
	}


# The lists say their Standard in words too: the cameras that blur, and the number of boxes of each
# camera. It is what config.json holds, whatever is saved on top.
def camera_list_standard(out: str) -> str:
	match = re.search(r'id="privacy-blur-cameras".*?Standard: ([^<]*)</span>', out, re.S)

	assert match is not None

	return match.group(1)


def box_standard(out: str, camera: str) -> str:
	block = tag_of(out, rf'<fieldset[^>]*data-camera="{camera}"[^>]*>.*?</fieldset>', re.S)

	return re.search(r"privacy-boxes-field.*?Standard: ([^<]*)</span>", block, re.S).group(1)


def test_the_camera_list_and_the_box_lists_say_their_standard(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	# Known: Alpha and the three that blur; one is off, so it is named.
	assert camera_list_standard(out) == "alle außer Alpha"
	assert box_standard(out, "BlurTest") == "1 Rahmen"
	assert box_standard(out, "Scheunenviertel") == "2 Rahmen"
	assert box_standard(out, "SLSV") == "kein Rahmen"


def test_these_standards_stay_the_config_json_ones_when_something_is_saved(tmp_path):
	# SLSV stays on the blur list, so its block is there; only its boxes and the list itself change.
	saved = {"blur_cameras": ["Alpha", "SLSV"], "ignore_boxes": {"SLSV": [[1, 1, 2, 2]]}}
	prepare(tmp_path, privacy={"privacy": saved})

	out, _ = render(tmp_path)

	assert "Alpha" in re.findall(r'name="blur_cameras\[\]"\s+value="([^"]+)"\s+checked', out)
	assert 'name="privacy[boxes][SLSV][0][x0]"' in out
	assert camera_list_standard(out) == "alle außer Alpha"
	assert box_standard(out, "SLSV") == "kein Rahmen"


def test_cameras_that_already_blur_are_marked_and_the_warning_is_shown(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	live = re.findall(r'<input[^>]*data-live="1"[^>]*value="([^"]+)"', out)
	important = tag_of(out, r'<p[^>]*class="privacy-important"[^>]*>.*?</p>', re.S)

	# sorted() orders by character code ("SL" before "Sc"), so sort the expectation the same way.
	assert sorted(live) == sorted(["BlurTest", "Scheunenviertel", "SLSV"])
	assert "Wichtig" in important
	assert "schon läuft" in important


def test_the_current_values_are_shown_with_their_standard(tmp_path):
	overrides = {"privacy": {"blur": {"strength": 0.2}, "min_person_score": {"SLSV": 0.4}}}
	prepare(tmp_path, privacy=overrides)

	out, _ = render(tmp_path)
	strength = tag_of(out, r'<input[^>]*id="privacy-privacy-blur-strength"[^>]*>')
	score = tag_of(out, r'<input[^>]*id="privacy-score-SLSV"[^>]*>')

	assert 'value="0.2"' in strength
	assert 'data-default="0.08"' in strength
	assert 'value="0.4"' in score
	assert 'data-default="0.35"' in score
	assert "Standard: 0.08" in out


def test_every_blur_camera_has_its_score_and_its_boxes(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	pattern = r'<fieldset[^>]*class="[^"]*privacy-camera[^"]*"[^>]*data-camera="([^"]+)"'

	assert re.findall(pattern, out) == ["BlurTest", "Scheunenviertel", "SLSV"]

	first = tag_of(out, r'<input[^>]*name="privacy\[boxes\]\[BlurTest\]\[0\]\[x0\]"[^>]*>')

	assert 'value="703"' in first
	# Exactly the saved boxes: no empty rows stand by.
	assert 'name="privacy[boxes][Scheunenviertel][1][y1]"' in out
	assert 'name="privacy[boxes][Scheunenviertel][2][x0]"' not in out
	assert default_boxes_of(out, "Scheunenviertel") == [[1, 2, 3, 4], [5, 6, 7, 8]]


def box_rows_of(out: str, camera: str) -> list:
	pattern = rf'<div[^>]*id="privacy-boxes-{camera}"[^>]*>.*?(?=</div>\s*<template)'
	container = tag_of(out, pattern, re.S)

	return re.findall(r'<div class="privacy-box-row">', container)


# New boxes come from "Rahmen hinzufügen" or from the picture, so no empty row is rendered.
def test_no_empty_rows_are_offered(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	assert len(box_rows_of(out, "Scheunenviertel")) == 2
	assert len(box_rows_of(out, "BlurTest")) == 1
	assert box_rows_of(out, "SLSV") == []

	# A row the script adds takes the next free index, after the saved ones.
	container = tag_of(out, r'<div[^>]*id="privacy-boxes-Scheunenviertel"[^>]*>')

	assert 'data-next-index="2"' in container
	assert 'data-next-index="0"' in tag_of(out, r'<div[^>]*id="privacy-boxes-SLSV"[^>]*>')


# Without a row the page says so, instead of leaving an empty space under the heading.
def test_a_camera_without_boxes_says_so(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	notes = {
		camera: tag_of(
			tag_of(out, rf'<fieldset[^>]*data-camera="{camera}"[^>]*>.*?</fieldset>', re.S),
			r'<p[^>]*class="privacy-boxes-empty"[^>]*>',
		)
		for camera in ("BlurTest", "Scheunenviertel", "SLSV")
	}

	assert not re.search(r"\shidden[\s>]", notes["SLSV"])
	assert re.search(r"\shidden[\s>]", notes["BlurTest"])
	assert re.search(r"\shidden[\s>]", notes["Scheunenviertel"])


def test_restoring_defaults_does_not_add_empty_rows_back(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	script = script_with(out, "data-default-group")

	assert "for (let blank" not in script
	# The note under the heading follows the rows, so it shows again after the last one is removed.
	assert "privacy-boxes-empty" in script


# The Standard is the live setting: render against the REAL config and compare with the file.
def test_the_standard_shown_is_what_config_json_holds(tmp_path):
	real = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	privacy = real["privacy"]
	names = privacy["blur_cameras"]
	prepare(tmp_path, config=real, cameras=tuple(names))

	out, _ = render(tmp_path)
	floats = {
		"privacy-privacy-blur-strength": privacy["blur"]["strength"],
		"privacy-privacy-blur-padding_ratio": privacy["blur"]["padding_ratio"],
		"privacy-privacy-blur-feather": privacy["blur"]["feather"],
	}

	for element_id, value in floats.items():
		tag = tag_of(out, rf'<input[^>]*id="{element_id}"[^>]*>')

		assert f'data-default="{value}"' in tag, element_id

	for camera in names:
		score = privacy.get("min_person_score", {}).get(camera, 0)
		tag = tag_of(out, rf'<input[^>]*id="privacy-score-{camera}"[^>]*>')

		assert f'data-default="{score}"' in tag, camera
		assert default_boxes_of(out, camera) == privacy.get("ignore_boxes", {}).get(camera, [])

		# A camera's own top share, else the global one that config.json gives every camera.
		own = privacy.get("ignore_top_share_per_camera", {})
		top = own.get(camera, privacy["ignore_top_share"])
		tag = tag_of(out, rf'<input[^>]*id="privacy-top-{camera}"[^>]*>')

		assert f'data-default="{top}"' in tag, camera

	standard = {name for name, (tick, _) in camera_boxes(out).items() if tick == "1"}

	assert standard == set(names)


# A value the browser's own validation refuses cannot be saved, so every Standard of the REAL config
# must be valid for its field: inside min and max, and with no step that rejects it.
def test_every_standard_of_the_real_config_is_valid_for_its_field(tmp_path):
	real = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
	names = real["privacy"]["blur_cameras"]
	prepare(tmp_path, config=real, cameras=tuple(names))

	out, _ = render(tmp_path)
	tags = re.findall(r'<input[^>]*type="number"[^>]*data-default="[^"]*"[^>]*>', out)

	# Three blur values for all cameras, then a score and a top share for each camera.
	assert len(tags) == 3 + 2 * len(names)
	for tag in tags:
		value = float(re.search(r'value="([^"]*)"', tag).group(1))
		low = float(re.search(r'min="([^"]*)"', tag).group(1))
		high = float(re.search(r'max="([^"]*)"', tag).group(1))

		assert low <= value <= high, tag
		assert 'step="any"' in tag, tag


def test_the_explanations_use_simple_words_and_cover_every_control(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	for element_id in EXPLAINED:
		assert f'id="{element_id}-help"' in out, element_id
		assert f'aria-describedby="{element_id}-help' in out, element_id

	assert 'id="privacy-boxes-SLSV-help"' in out
	assert "Mosaik" in out
	assert "Wo ein Rahmen liegt" in out


def test_the_sliders_are_hidden_from_assistive_technology_and_the_number_field_is_real(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	ranges = re.findall(r'<input[^>]*type="range"[^>]*>', out)

	assert len(ranges) == 3 + 2 * len(BLUR_CAMERAS)
	for tag in ranges:
		assert 'aria-hidden="true"' in tag
		assert 'tabindex="-1"' in tag
		assert re.search(r"\shidden[\s>]", tag) is not None
		assert "name=" not in tag

	number = tag_of(out, r'<input[^>]*id="privacy-privacy-blur-strength"[^>]*>')
	slider = tag_of(out, r'<input[^>]*data-slider-for="privacy-privacy-blur-strength"[^>]*>')

	assert 'type="number"' in number
	assert 'name="privacy[floats][privacy.blur.strength]"' in number
	assert 'min="0.05"' in number
	assert 'max="0.5"' in number
	# Only the slider has a step. A number field with a step would refuse a Standard such as 0.333
	# (the top share), and the browser would then block the save.
	assert 'step="any"' in number
	assert 'step="0.01"' in slider


def test_a_valid_save_sends_the_privacy_values_to_the_wrapper_and_redirects(tmp_path):
	prepare(tmp_path)
	post = privacy_post(floats={"privacy.blur.strength": "0.1"})

	out, args = render(tmp_path, post, sudo_out=SAVED)

	assert args[3:6] == [WRAPPER, "privacy", "0"]
	assert sent_values(args) == {
		"privacy": {
			"blur_cameras": ["BlurTest", "Scheunenviertel", "SLSV"],
			"blur": {"strength": 0.1, "padding_ratio": 0.05, "feather": 0.5},
			"ignore_top_share_per_camera": {
				"BlurTest": 0.333,
				"Scheunenviertel": 0.333,
				"SLSV": 0.333,
			},
			"min_person_score": {"BlurTest": 0, "Scheunenviertel": 0, "SLSV": 0.35},
			"ignore_boxes": {
				"BlurTest": [[703, 557, 742, 643]],
				"Scheunenviertel": [[1, 2, 3, 4], [5, 6, 7, 8]],
				"SLSV": [],
			},
		}
	}
	# Post/Redirect/Get: nothing is rendered for the POST itself.
	assert "<h1>" not in out


def test_the_saved_message_shows_once_after_the_redirect(tmp_path):
	prepare(tmp_path)
	render(tmp_path, privacy_post(), sudo_out=SAVED)

	out, _ = render(tmp_path)

	assert "Gespeichert. Die Verpixelungs-Einstellungen gelten ab dem nächsten Auftrag." in out

	out, _ = render(tmp_path)

	assert "Gespeichert." not in out


def test_boxes_are_read_from_their_rows_and_blank_rows_are_ignored(tmp_path):
	prepare(tmp_path)
	row = {"x0": "10", "y0": "20", "x1": "30", "y1": "40"}
	post = privacy_post(boxes={"SLSV": {"0": row, "1": dict(BLANK)}})

	_, args = render(tmp_path, post, sudo_out=SAVED)

	assert sent_values(args)["privacy"]["ignore_boxes"]["SLSV"] == [[10, 20, 30, 40]]


# A half-filled row is not guessed at: it goes on as text and the writer names the problem.
def test_a_half_filled_box_row_is_forwarded_as_text_for_the_writer_to_refuse(tmp_path):
	prepare(tmp_path)
	row = {"x0": "10", "y0": "20", "x1": "", "y1": "40"}
	post = privacy_post(boxes={"SLSV": {"0": row}})

	_, args = render(tmp_path, post, sudo_out=SAVED)

	assert sent_values(args)["privacy"]["ignore_boxes"]["SLSV"] == [[10, 20, "", 40]]


def test_numbers_accept_a_decimal_comma_and_text_goes_on_as_text(tmp_path):
	prepare(tmp_path)
	floats = {"privacy.blur.strength": "0,12", "privacy.blur.feather": "abc"}

	_, args = render(tmp_path, privacy_post(floats=floats), sudo_out=SAVED)
	blur = sent_values(args)["privacy"]["blur"]

	assert blur["strength"] == 0.12
	assert blur["feather"] == "abc"


# A camera's own top share: the red strip on its picture. One field per blur camera, in its block.


def top_field(out: str, camera: str) -> str:
	return tag_of(out, rf'<input[^>]*id="privacy-top-{camera}"[^>]*>')


def test_every_blur_camera_has_its_own_top_share_field_in_its_block(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	for camera in ("BlurTest", "Scheunenviertel", "SLSV"):
		field = top_field(out, camera)
		slider = tag_of(out, rf'<input[^>]*data-slider-for="privacy-top-{camera}"[^>]*>')
		block = tag_of(out, rf'<fieldset[^>]*data-camera="{camera}"[^>]*>.*?</fieldset>', re.S)

		assert f'name="privacy[top][{camera}]"' in field
		# No value of its own: the field shows the global one, which is also its Standard.
		assert 'value="0.333"' in field
		assert 'data-default="0.333"' in field
		assert 'max="0.49"' in field
		# A number field with a step would refuse the Standard 0.333 and block the save.
		assert 'step="any"' in field
		assert 'max="0.49"' in slider
		assert f'id="privacy-top-{camera}"' in block


def test_a_saved_top_share_is_shown_and_the_standard_stays_the_global_one(tmp_path):
	prepare(tmp_path, privacy={"privacy": {"ignore_top_share_per_camera": {"SLSV": 0.1}}})

	out, _ = render(tmp_path)

	assert 'value="0.1"' in top_field(out, "SLSV")
	assert 'data-default="0.333"' in top_field(out, "SLSV")
	assert 'value="0.333"' in top_field(out, "Scheunenviertel")


# IT may give one camera its own value in config.json: that is the camera's Standard.
def test_a_top_share_in_config_json_is_the_standard_of_that_camera(tmp_path):
	privacy = {**BASE["privacy"], "ignore_top_share_per_camera": {"SLSV": 0.2}}
	prepare(tmp_path, config={**BASE, "privacy": privacy})

	out, _ = render(tmp_path)

	assert 'value="0.2"' in top_field(out, "SLSV")
	assert 'data-default="0.2"' in top_field(out, "SLSV")
	assert 'data-default="0.333"' in top_field(out, "BlurTest")


def test_each_cameras_top_share_is_sent_as_its_own_value(tmp_path):
	prepare(tmp_path)

	_, args = render(tmp_path, privacy_post(top={"SLSV": "0,1", "BlurTest": "0"}), sudo_out=SAVED)
	sent = sent_values(args)["privacy"]

	assert sent["ignore_top_share_per_camera"] == {
		"BlurTest": 0,
		"Scheunenviertel": 0.333,
		"SLSV": 0.1,
	}
	# The global value is not the page's to send any more: it stays with config.json.
	assert "ignore_top_share" not in sent


def test_a_top_share_that_is_not_a_number_goes_on_as_text(tmp_path):
	prepare(tmp_path)

	_, args = render(tmp_path, privacy_post(top={"SLSV": "abc"}), sudo_out=SAVED)

	assert sent_values(args)["privacy"]["ignore_top_share_per_camera"]["SLSV"] == "abc"


@pytest.mark.parametrize("camera", ["Gamma", "a.b", "../x"])
def test_a_top_share_for_an_unknown_or_dotted_camera_is_refused(tmp_path, camera):
	prepare(tmp_path)

	out, args = render(tmp_path, privacy_post(top={camera: "0.1"}))

	assert "Die ausgewählte Kamera ist ungültig." in out
	assert args == []


def test_a_top_share_that_is_not_text_is_refused(tmp_path):
	prepare(tmp_path)

	out, args = render(tmp_path, privacy_post(top={"SLSV": ["0.1"]}))

	assert "Das Formular war unvollständig." in out
	assert args == []


def test_the_writers_message_for_a_top_share_points_at_that_cameras_field(tmp_path):
	prepare(tmp_path)
	errors = ["privacy.ignore_top_share_per_camera.SLSV: muss eine Zahl von 0 bis unter 0.5 sein"]
	reply = json.dumps({"status": "invalid", "errors": errors, "mtime": 0})

	out, _ = render(tmp_path, privacy_post(top={"SLSV": "0.7"}), sudo_exit=65, sudo_out=reply)

	assert 'href="#privacy-top-SLSV"' in out
	assert "Kamera SLSV: Oberer Bildrand" in out
	assert 'id="privacy-top-SLSV-error"' in out
	# What was typed stays in the field.
	assert 'value="0.7"' in top_field(out, "SLSV")


def test_post_without_a_valid_csrf_token_saves_nothing(tmp_path):
	prepare(tmp_path)

	for token in ("wrong", None):
		post = privacy_post()
		post["csrf_token"] = token
		out, args = render(tmp_path, post)

		assert "Die Anfrage ist ungültig (Sicherheitstoken)." in out
		assert args == []


# The confirm dialog is privacy protection: the server only accepts the exact confirmation.
@pytest.mark.parametrize("confirm", ["on", "true", "1", "YES", ["yes"], None, ""])
def test_only_the_exact_string_yes_confirms(tmp_path, confirm):
	prepare(tmp_path)
	post = privacy_post()
	post["confirm_privacy"] = confirm

	out, args = render(tmp_path, post)

	assert "Bitte die Änderungen bestätigen." in out
	assert args == []


@pytest.mark.parametrize("mtime", ["", "abc", "-1", "1.5", "1234567890123", ["1"], None])
def test_a_bad_page_time_saves_nothing(tmp_path, mtime):
	prepare(tmp_path)

	out, args = render(tmp_path, privacy_post(loaded_mtime=mtime))

	assert "Die Anfrage ist ungültig (Seitenstand)." in out
	assert args == []


def test_the_page_time_goes_to_the_wrapper(tmp_path):
	prepare(tmp_path, privacy={})

	_, args = render(tmp_path, privacy_post(loaded_mtime=str(FILE_TIME)), sudo_out=SAVED)

	assert args[5] == str(FILE_TIME)


def test_a_camera_outside_the_known_set_is_refused(tmp_path):
	prepare(tmp_path)

	out, args = render(tmp_path, privacy_post(cameras=(*BLUR_CAMERAS, "Gamma")))

	assert "Die ausgewählte Kamera ist ungültig." in out
	assert args == []


@pytest.mark.parametrize("camera", ["Gamma", "a.b", "../x"])
def test_per_camera_values_for_an_unknown_or_dotted_camera_are_refused(tmp_path, camera):
	prepare(tmp_path)

	out, args = render(tmp_path, privacy_post(score={camera: "0.3"}))

	assert "Die ausgewählte Kamera ist ungültig." in out
	assert args == []


@pytest.mark.parametrize("value", ["Alpha", {"a": "Gamma"}])
def test_a_camera_list_that_is_not_a_list_of_known_cameras_is_refused(tmp_path, value):
	prepare(tmp_path)
	post = privacy_post()
	post["blur_cameras"] = value

	out, args = render(tmp_path, post)

	assert "Die ausgewählte Kamera ist ungültig." in out
	assert args == []


# Taking every camera off the blur job is allowed ("people know what they do"): the dialog warns.
def test_every_camera_can_be_taken_off_the_blur_list(tmp_path):
	prepare(tmp_path)

	_, args = render(tmp_path, privacy_post(cameras=()), sudo_out=SAVED)

	assert sent_values(args)["privacy"]["blur_cameras"] == []


@pytest.mark.parametrize("fields", [None, "text", ["x"]])
def test_a_form_without_its_fields_is_refused(tmp_path, fields):
	prepare(tmp_path)
	post = privacy_post()
	post["privacy"] = fields

	out, args = render(tmp_path, post)

	assert "Das Formular war unvollständig. Bitte die Seite neu laden." in out
	assert args == []


def test_a_missing_number_field_is_refused(tmp_path):
	prepare(tmp_path)
	post = privacy_post()
	del post["privacy"]["floats"]["privacy.blur.feather"]

	out, args = render(tmp_path, post)

	assert "Das Formular war unvollständig." in out
	assert args == []


# Only the form's fixed fields are read: what stays with IT never reaches the wrapper.
def test_unknown_posted_fields_are_never_forwarded(tmp_path):
	prepare(tmp_path)
	post = privacy_post(skip_labels={"SLSV": ["vehicle"]}, detector_command=["x"])
	post["privacy"]["skip_labels"] = {"SLSV": ["vehicle"]}
	post["privacy"]["floats"]["privacy.detector"] = "1"

	_, args = render(tmp_path, post, sudo_out=SAVED)

	assert "skip_labels" not in args[-1]
	assert "detector" not in args[-1]


def test_invalid_values_are_shown_next_to_their_controls_with_what_was_typed(tmp_path):
	prepare(tmp_path)
	errors = [
		"privacy.blur.strength: muss eine Zahl von 0.05 bis 0.5 sein",
		"privacy.ignore_boxes.SLSV: muss eine Liste von höchstens 50 Rahmen sein",
	]
	reply = json.dumps({"status": "invalid", "errors": errors, "mtime": 0})
	post = privacy_post(floats={"privacy.blur.strength": "9"})

	out, _ = render(tmp_path, post, sudo_exit=65, sudo_out=reply)

	assert 'id="settings-problems"' in out
	assert 'href="#privacy-privacy-blur-strength"' in out
	assert 'id="privacy-privacy-blur-strength-error"' in out
	assert 'id="privacy-boxes-SLSV-error"' in out
	assert 'aria-invalid="true"' in out
	assert 'value="9"' in out


def test_a_page_that_is_out_of_date_is_refused_and_stays_so(tmp_path):
	prepare(tmp_path, privacy={})
	stale = '{"status": "stale", "errors": [], "mtime": 999}'

	out, _ = render(tmp_path, privacy_post(loaded_mtime="5"), sudo_exit=73, sudo_out=stale)

	assert "Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden." in out
	assert 'name="loaded_mtime" value="5"' in out


def test_a_failed_save_shows_a_generic_message_without_wrapper_details(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path, privacy_post(), sudo_exit=1)

	assert "Die Einstellungen konnten nicht gespeichert werden." in out
	assert "denied" not in out


def test_messages_and_values_are_escaped(tmp_path):
	prepare(tmp_path)
	errors = ["<script>alert(1)</script>"]
	reply = json.dumps({"status": "invalid", "errors": errors, "mtime": 0})
	post = privacy_post(floats={"privacy.blur.strength": '"><script>x</script>'})

	out, _ = render(tmp_path, post, sudo_exit=65, sudo_out=reply)

	assert "<script>alert(1)</script>" not in out
	assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
	assert '"><script>x</script>' not in out


# Restore: one button per section and one for everything, all inside this page's form only.
def test_the_restore_buttons_exist_per_section_and_for_everything(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	group_buttons = re.findall(r"<button[^>]*data-default-group[^>]*>", out)

	# The camera list, the blur values, and one per blur camera (its block holds its top share too).
	assert len(group_buttons) == 2 + len(BLUR_CAMERAS)
	for tag in group_buttons:
		assert 'type="button"' in tag
		assert re.search(r"\shidden[\s>]", tag) is not None

	all_button = tag_of(out, r"<button[^>]*data-default-all[^>]*>")

	assert re.search(r"\shidden[\s>]", all_button) is not None
	assert re.search(r'<p[^>]*id="settings-default-note"[^>]*role="status"', out) is not None


def test_every_button_resets_inside_its_own_page_only(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	script = script_with(out, "data-default-group")

	assert 'document.querySelector(".settings-form")' in script
	# Everything is looked up below the form or a fieldset, never on the whole document.
	assert "document.querySelectorAll" not in script
	assert re.search(r"\bvar\b", script) is None


def test_the_confirm_dialog_and_its_no_javascript_tick_box_exist(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	script = script_with(out, "privacy-confirm")
	dialog = tag_of(out, r'<dialog[^>]*id="privacy-confirm"[^>]*>.*?</dialog>', re.S)
	noscript = tag_of(out, r"<noscript>.*?</noscript>", re.S)

	assert 'aria-labelledby="privacy-confirm-title"' in dialog
	assert 'id="privacy-confirm-important"' in dialog
	assert "data-confirm-yes" in dialog
	assert "data-confirm-cancel" in dialog
	assert 'name="confirm_privacy"' in noscript
	assert 'value="yes"' in noscript
	assert "showModal()" in script
	assert "confirm_privacy" in script
	# The save button is a plain submit: the dialog is the script's job.
	assert 'name="confirm"' not in out


# The preview picture in each camera's block (the cache is written by the wrapper's script).

JPEG = b"\xff\xd8\xff\xc0\x00\x08\x08\x01\xe0\x02\x80\x00\xff\xd9"


def cache_preview(tmp_path: Path, camera: str, picture: bool = True, **info) -> None:
	folder = tmp_path / "state" / "web-jobs" / "previews"
	folder.mkdir(parents=True, exist_ok=True)

	if picture:
		(folder / f"{camera}.jpg").write_bytes(JPEG)

	data = {
		"image": "20261109T120000.jpg",
		"status": "blurred",
		"width": 640,
		"height": 480,
		"taken": "2026-11-09T12:00:00+01:00",
		**info,
	}
	(folder / f"{camera}.json").write_text(json.dumps(data))


def preview_block(out: str, camera: str) -> str:
	fieldset = tag_of(out, rf'<fieldset[^>]*data-camera="{camera}"[^>]*>.*?</fieldset>', re.S)

	return tag_of(fieldset, r'<section[^>]*class="privacy-preview"[^>]*>.*?</section>', re.S)


def test_a_cached_preview_is_shown_in_its_camera_block(tmp_path):
	prepare(tmp_path)
	cache_preview(tmp_path, "SLSV")

	out, _ = render(tmp_path)
	block = preview_block(out, "SLSV")
	image = tag_of(block, r"<img[^>]*>")

	assert re.search(r'src="/preview\.php\?camera=SLSV&amp;v=\d+"', image)
	# The size is in the markup, so the page does not jump when the picture arrives.
	assert 'width="640"' in image
	assert 'height="480"' in image
	assert "SLSV" in re.search(r'alt="([^"]*)"', image).group(1)
	assert "09.11.2026, 12:00" in re.search(r'alt="([^"]*)"', image).group(1)
	assert "09.11.2026, 12:00 Uhr" in block
	assert "640 × 480" in block


def test_a_camera_without_a_preview_says_so_and_shows_no_picture(tmp_path):
	prepare(tmp_path)
	cache_preview(tmp_path, "SLSV")

	out, _ = render(tmp_path)
	block = preview_block(out, "Scheunenviertel")

	assert "<img" not in block
	assert "noch kein Bild" in block


# A description without its picture (or the other way round) would be a broken image: not shown.
def test_a_damaged_cache_shows_no_picture(tmp_path):
	prepare(tmp_path)
	cache_preview(tmp_path, "SLSV", picture=False)

	out, _ = render(tmp_path)

	assert "<img" not in preview_block(out, "SLSV")


# The only picture of the page is the preview; nothing else in it may load an image.
def test_only_blur_cameras_with_a_cache_load_a_picture(tmp_path):
	prepare(tmp_path)
	cache_preview(tmp_path, "SLSV")
	cache_preview(tmp_path, "Alpha")

	out, _ = render(tmp_path)
	version = int((tmp_path / "state" / "web-jobs" / "previews" / "SLSV.jpg").stat().st_mtime)

	assert re.findall(r'<img[^>]*src="([^"]*)"', out) == [
		f"/preview.php?camera=SLSV&amp;v={version}"
	]


# The refresh button belongs to the picture, not to the form: it sends nothing and saves nothing.
def test_the_refresh_button_is_script_only_and_carries_no_field(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	for camera in ("BlurTest", "Scheunenviertel", "SLSV"):
		block = preview_block(out, camera)
		button = tag_of(block, r"<button[^>]*data-preview-refresh[^>]*>")

		assert 'type="button"' in button
		assert re.search(r"\shidden[\s>]", button)
		assert re.search(r"\sname=", block) is None
		assert f'data-preview-camera="{camera}"' in block


def test_the_script_asks_for_a_new_picture_with_the_forms_token(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	script = script_with(out, "data-default-group")

	assert "/preview-refresh.php" in script
	assert "data-preview-refresh" in script
	assert "csrf_token" in script
	# What the server answers is shown as text, never as markup.
	assert "textContent" in script
	assert "innerHTML =" not in script
	assert 'role="status"' in preview_block(out, "SLSV")


# The drawing editor on the picture. Its drag logic is script (the project has no browser test
# runner, so it is clicked for real in a browser); these tests pin what the server puts in place.

STYLE = Path(__file__).resolve().parents[2] / "web" / "public" / "style.css"


# The script turns a rectangle on the picture into box numbers by one scale factor: it needs the
# picture's own size, and a frame (the stage) to lay its layer over.
def test_the_picture_sits_in_a_stage_that_carries_its_size(tmp_path):
	prepare(tmp_path)
	cache_preview(tmp_path, "SLSV")

	out, _ = render(tmp_path)
	block = preview_block(out, "SLSV")
	section = tag_of(block, r"<section[^>]*>")

	assert 'data-preview-width="640"' in section
	assert 'data-preview-height="480"' in section
	assert re.search(r'<div class="privacy-preview-stage">\s*<img', block)


def test_a_camera_without_a_picture_has_no_stage_and_no_size(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	block = preview_block(out, "SLSV")

	assert "privacy-preview-stage" not in block
	assert "data-preview-width" not in block


# Drawing needs a pointer and a script: the button is hidden until the script shows it, and it is a
# toggle, so the layer only catches the pointer while it is on (a finger can still scroll past).
def test_the_draw_button_is_a_script_only_toggle(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	for camera in ("BlurTest", "Scheunenviertel", "SLSV"):
		button = tag_of(preview_block(out, camera), r"<button[^>]*data-preview-draw[^>]*>")

		assert 'type="button"' in button
		assert 'aria-pressed="false"' in button
		assert re.search(r"\shidden[\s>]", button)
		# One toggle for drawing and moving: the name says both are on.
		assert "Rahmen bearbeiten" in tag_of(
			preview_block(out, camera), r"<button[^>]*data-preview-draw[^>]*>.*?</button>", re.S
		)


def test_the_drawing_help_is_hidden_until_the_script_runs_and_names_every_symbol(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	block = preview_block(out, "SLSV")
	help_tag = tag_of(block, r"<div[^>]*data-draw-help[^>]*>.*?</div>", re.S)

	assert re.search(r"\shidden[\s>]", help_tag.split(">", 1)[0] + ">")
	# What is drawn on the picture is explained in words: the rectangles, the strip, the way out.
	assert "Rahmen bearbeiten" in help_tag
	# Moving a box by hand is explained too, next to drawing one.
	assert "schiebst" in help_tag
	# The strip's edge can be dragged, and the strip belongs to this camera alone.
	assert "Kante" in help_tag
	assert "nur für diese Kamera" in help_tag
	assert "alle Kameras" not in help_tag
	assert "Streifen" in help_tag
	assert "Entfernen" in help_tag


# A rectangle on the picture is matched to its row by number, so every row shows one.
def test_every_box_row_shows_its_number(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	rows = re.findall(r'<div class="privacy-box-row">.*?</div>', out, re.S)
	pattern = r'<span class="privacy-box-number"[^>]*>(.*?)</span>'
	numbers = [re.search(pattern, row) for row in rows]

	assert rows
	assert all(number is not None for number in numbers)
	assert all('aria-hidden="true"' in number.group(0) for number in numbers)
	# The template the script clones carries the placeholder it fills in.
	assert "__NUMBER__" in tag_of(out, r"<template data-box-template>.*?</template>", re.S)


def test_the_script_draws_with_pointer_events_and_keeps_the_layer_out_of_the_accessibility_tree(
	tmp_path,
):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	script = script_with(out, "data-default-group")

	for event in ("pointerdown", "pointermove", "pointerup", "pointercancel", "setPointerCapture"):
		assert event in script, event

	# The layer is decoration for the mouse: the rows are the real, keyboard-operable control.
	assert 'setAttribute("aria-hidden", "true")' in script
	assert "is-drawing" in script
	# A box on the picture knows which row it is, so a drag on it can change that row.
	assert "dataset.row" in script
	# The strip's handle writes THIS camera's top-share field (and its slider), nothing global.
	assert "privacy-top-handle" in script
	assert "setTopShare" in script
	assert "ignore_top_share" not in script
	# The dialog names the camera of a changed number: one label stands in every camera's block.
	assert 'closest(".privacy-camera")' in script
	assert "innerHTML =" not in script
	assert re.search(r"\bvar\b", script) is None


# The generic "main section" panel would take about a fifth of a phone's width from the picture.
def test_the_picture_block_gives_up_its_panel_on_a_phone():
	css = STYLE.read_text(encoding="utf-8")
	narrow = tag_of(css, r"@media \(max-width: 40rem\)\s*\{\s*\.privacy-preview\s*\{[^}]*\}", re.S)

	assert "padding: 0" in narrow
	assert "border: 0" in narrow


# "Entfernen" is a deletion, so it is red like the app's other delete buttons (the text still says
# what it does: colour is not the only sign), and it stands level with the inputs of its row.
def test_the_remove_button_is_red_and_level_with_its_inputs():
	css = STYLE.read_text(encoding="utf-8")
	rule = tag_of(css, r"\.privacy-box-row \.privacy-box-remove\s*\{[^}]*\}", re.S)
	hover = tag_of(css, r"\.privacy-box-row \.privacy-box-remove:hover\s*\{[^}]*\}", re.S)

	assert "border-color: var(--color-danger)" in rule
	assert "color: var(--color-danger)" in rule
	assert "rgb(223 113 113" in hover
	# The generic small button is pinned to the top of a flex row: here it must sit on the bottom
	# line with the inputs, or it looks shifted up next to them.
	assert "align-self: flex-end" in rule


# The row's inputs, its button and its number share one height, so they line up in one row.
def test_the_row_items_share_one_height():
	css = STYLE.read_text(encoding="utf-8")
	heights = re.findall(
		r"(\.privacy-box-row input|\.privacy-box-row \.privacy-box-remove|\.privacy-box-number)"
		r"\s*\{[^}]*?(?<![\w-])height:\s*([^;]+);",
		css,
		re.S,
	)

	assert {selector for selector, _ in heights} == {
		".privacy-box-row input",
		".privacy-box-row .privacy-box-remove",
		".privacy-box-number",
	}
	assert len({value for _, value in heights}) == 1
	assert "align-self: flex-end" in tag_of(css, r"\.privacy-box-number\s*\{[^}]*\}", re.S)


# Without the toggle the layer must let everything through, or the picture would block scrolling
# on a phone; only while drawing may it take the touch away from the page.
def test_the_layer_only_catches_the_pointer_while_drawing():
	css = STYLE.read_text(encoding="utf-8")
	layer = tag_of(css, r"\.privacy-preview-layer\s*\{[^}]*\}", re.S)
	drawing = tag_of(css, r"\.privacy-preview-layer\.is-drawing\s*\{[^}]*\}", re.S)

	assert "pointer-events: none" in layer
	assert "touch-action" not in layer
	assert "pointer-events: auto" in drawing
	assert "touch-action: none" in drawing


# The strip's handle exists on the picture only while editing is on; its pointer says "up and down".
def test_the_strip_handle_shows_only_while_editing():
	css = STYLE.read_text(encoding="utf-8")
	pattern = r"\.privacy-preview-layer\.is-drawing \.privacy-top-handle\s*\{[^}]*\}"
	idle = tag_of(css, r"\.privacy-top-handle\s*\{[^}]*\}", re.S)
	editing = tag_of(css, pattern, re.S)

	assert "display: none" in idle
	assert "display: block" in editing
	assert "cursor: ns-resize" in editing


# A box can be grabbed only while editing is on, and the pointer says so.
def test_a_box_shows_the_move_cursor_only_while_editing():
	css = STYLE.read_text(encoding="utf-8")
	pattern = r"\.privacy-preview-layer\.is-drawing \.privacy-box-shape\s*\{[^}]*\}"
	grabbable = tag_of(css, pattern, re.S)

	assert "cursor: move" in grabbable
	# The rectangle being drawn is not a handle: it keeps the crosshair.
	assert "cursor: crosshair" in tag_of(css, r"\.privacy-box-shape\.is-draft\s*\{[^}]*\}", re.S)
