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
	"privacy.ignore_top_share": "0.333",
}

# Every control that carries an explanation, by element id.
EXPLAINED = [
	"privacy-privacy-blur-strength",
	"privacy-privacy-blur-padding_ratio",
	"privacy-privacy-blur-feather",
	"privacy-privacy-ignore_top_share",
	"privacy-score-SLSV",
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
def privacy_post(floats=None, cameras=BLUR_CAMERAS, score=None, boxes=None, **extra) -> dict:
	base_boxes = BASE["privacy"]["ignore_boxes"]
	post = {
		"csrf_token": TOKEN,
		"confirm_privacy": "yes",
		"loaded_mtime": "0",
		"blur_cameras": list(cameras),
		"privacy": {
			"floats": {**FLOATS, **(floats or {})},
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
	assert "<legend>Oberer Bildrand</legend>" in out

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


def test_cameras_that_already_blur_are_marked_and_the_warning_is_shown(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	live = re.findall(r'<input[^>]*data-live="1"[^>]*value="([^"]+)"', out)
	important = tag_of(out, r'<p[^>]*class="privacy-important"[^>]*>.*?</p>', re.S)

	assert sorted(live) == ["BlurTest", "Scheunenviertel", "SLSV"]
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
	# The saved boxes, then blank rows to add more without JavaScript.
	assert 'name="privacy[boxes][Scheunenviertel][1][y1]"' in out
	assert 'name="privacy[boxes][Scheunenviertel][4][x0]"' in out
	assert 'name="privacy[boxes][Scheunenviertel][5][x0]"' not in out
	assert default_boxes_of(out, "Scheunenviertel") == [[1, 2, 3, 4], [5, 6, 7, 8]]


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
		"privacy-privacy-ignore_top_share": privacy["ignore_top_share"],
	}

	for element_id, value in floats.items():
		tag = tag_of(out, rf'<input[^>]*id="{element_id}"[^>]*>')

		assert f'data-default="{value}"' in tag, element_id

	for camera in names:
		score = privacy.get("min_person_score", {}).get(camera, 0)
		tag = tag_of(out, rf'<input[^>]*id="privacy-score-{camera}"[^>]*>')

		assert f'data-default="{score}"' in tag, camera
		assert default_boxes_of(out, camera) == privacy.get("ignore_boxes", {}).get(camera, [])

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

	assert len(tags) == 4 + len(names)
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

	assert len(ranges) == 4 + len(BLUR_CAMERAS)
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
			"ignore_top_share": 0.333,
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

	# Cameras, blur values, top share, and one per blur camera.
	assert len(group_buttons) == 3 + len(BLUR_CAMERAS)
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
