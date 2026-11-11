import json
import os
import re
from pathlib import Path

import pytest

from web_php_test import SUDO_PATH, fake_sudo, render_page

TOKEN = "test-token"
FILE_TIME = 1_700_000_000
SAVED = '{"status": "saved", "errors": [], "mtime": 456}'

BASE = {
	"location": {"latitude": 52.472, "longitude": 9.333, "timezone": "Europe/Berlin"},
	"daylight_buffer_minutes": 90,
	"automatic_daylight_buffer_minutes": {str(month): 60 for month in range(1, 13)},
	"interval_window": {"target_time": "12:00", "tolerance_minutes": 90},
	"min_coverage_days": {"monthly": 25, "yearly": 300},
	"log_retention_days": 30,
	"ignored_cameras": ["Reolink"],
	"timelapse": {
		"daily_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
		"crf": 28,
	},
	"privacy": {"blur_cameras": ["Alpha"]},
	"flagger": {"cameras": ["Alpha"], "retention_days": 30},
}

# Every one-value field of the form, at its config.json value.
SCALARS = {
	"timelapse.crf": "28",
	"timelapse.daily_framerate": "10",
	"timelapse.monthly_framerate": "20",
	"timelapse.yearly_framerate": "20",
	"flagger.retention_days": "30",
	"daylight_buffer_minutes": "90",
	"interval_window.target_time": "12:00",
	"interval_window.tolerance_minutes": "90",
	"min_coverage_days.monthly": "25",
	"min_coverage_days.yearly": "300",
	"log_retention_days": "30",
	**{f"automatic_daylight_buffer_minutes.{month}": "60" for month in range(1, 13)},
}


def prepare(tmp_path: Path, config=None, settings=None, cameras=("Alpha", "Beta")) -> None:
	(tmp_path / "config").mkdir(parents=True, exist_ok=True)
	(tmp_path / "config" / "config.json").write_text(json.dumps(config or BASE))

	if settings is not None:
		path = tmp_path / "config" / "settings.json"
		path.write_text(json.dumps(settings))
		os.utime(path, (FILE_TIME, FILE_TIME))

	list_path = tmp_path / "state" / "web-jobs" / "cameras.json"
	list_path.parent.mkdir(parents=True, exist_ok=True)
	list_path.write_text(json.dumps(list(cameras)))


def render(tmp_path: Path, post=None, sudo_exit: int = 0, sudo_out: str = ""):
	swaps = {"src/settings-runner.php": (SUDO_PATH, str(fake_sudo(tmp_path)))}

	return render_page(tmp_path, "settings.php", swaps, {}, post, sudo_exit, TOKEN, sudo_out)


# A complete, valid POST (what the browser sends), with changes on top.
def form_post(scalars=None, processed=("Alpha", "Beta"), flagger=("Alpha",), **extra) -> dict:
	post = {
		"csrf_token": TOKEN,
		"confirm": "yes",
		"loaded_mtime": "0",
		"settings": {**SCALARS, **(scalars or {})},
		"process_cameras": list(processed),
		"flagger_cameras": list(flagger),
	}
	post.update(extra)

	return post


def sent_values(args: list) -> dict:
	return json.loads(args[-1])


def test_the_page_shows_the_groups_the_fields_and_the_current_values(tmp_path):
	prepare(tmp_path, settings={"timelapse": {"crf": 30}})

	out, _ = render(tmp_path)

	assert "<h1>Einstellungen</h1>" in out
	for legend in ("Videoqualität", "Kameras", "Highlights (Flagger)", "Protokolle"):
		assert f"<legend>{legend}</legend>" in out
	assert 'name="settings[timelapse.crf]"' in out
	assert 'value="30"' in out
	# The config.json value stays visible as the default.
	assert "Standard: 28" in out
	assert 'name="settings[automatic_daylight_buffer_minutes.11]"' in out
	assert 'name="settings[interval_window.target_time]"' in out


def test_every_field_has_a_label_and_every_group_a_legend(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	inputs = re.findall(r'<input\s+type="(?:number|time)"\s+id="([^"]+)"', out)

	assert len(inputs) == len(SCALARS)
	for input_id in inputs:
		assert f'<label for="{input_id}">' in out
	assert out.count("<fieldset") == out.count("<legend>") == 6


# The noon picture is a daylight picture: the page offers 10:00 to 14:00 and at most 120 minutes of
# tolerance (src/settings.py refuses the rest; these limits only shape the inputs).
def test_the_target_time_is_limited_to_daylight(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	field = tag_of(out, r'<input\s+type="time"\s+id="setting-interval_window-target_time"[^>]*>')

	assert 'min="10:00"' in field
	assert 'max="14:00"' in field
	# No step on the real field: a Standard off the 15 minute grid must still be savable.
	assert "step=" not in field
	assert "Standard: 12:00" in out


# The flagger refuses to start with less than a week of retention.
def test_the_flagger_retention_starts_at_its_own_minimum(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	field = tag_of(out, r'<input\s+type="number"\s+id="setting-flagger-retention_days"[^>]*>')

	assert 'min="7"' in field
	assert 'max="365"' in field


# The jobs raise for more days than their window has (30; 365 in a year without a 29 February).
def test_the_coverage_fields_stop_at_the_shortest_window(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	monthly = tag_of(out, r'<input\s+type="number"\s+id="setting-min_coverage_days-monthly"[^>]*>')
	yearly = tag_of(out, r'<input\s+type="number"\s+id="setting-min_coverage_days-yearly"[^>]*>')

	assert 'min="1"' in monthly
	assert 'max="30"' in monthly
	assert 'min="1"' in yearly
	assert 'max="365"' in yearly


def test_the_tolerance_runs_from_one_to_120_minutes(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	field = tag_of(
		out, r'<input\s+type="number"\s+id="setting-interval_window-tolerance_minutes"[^>]*>'
	)

	assert 'min="1"' in field
	assert 'max="120"' in field


# The slider only helps the mouse (the time field is the real control), so it starts hidden and the
# script shows it. It counts minutes since midnight: 10:00 = 600, 14:00 = 840.
def test_the_target_time_has_a_helper_slider_in_minutes(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	slider = tag_of(
		out,
		r'<input\s+type="range"[^>]*data-slider-for="setting-interval_window-target_time"[^>]*>',
	)

	assert 'min="600"' in slider
	assert 'max="840"' in slider
	assert 'step="15"' in slider
	# The attribute itself, not the "hidden" inside aria-hidden.
	assert re.search(r"\shidden(\s|>)", slider) is not None
	assert 'aria-hidden="true"' in slider
	assert 'tabindex="-1"' in slider
	# Only the time field is a form field: the slider must not send a second value.
	assert "name=" not in slider
	assert out.count('type="range"') == 1


def test_the_page_script_keeps_the_slider_and_the_time_field_in_step(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	scripts = [
		script
		for script in re.findall(r"<script[^>]*>(.*?)</script>", out, re.S)
		if "data-default-group" in script
	]

	assert len(scripts) == 1
	assert 'querySelectorAll("[data-slider-for]")' in scripts[0]
	# A restored Standard moves no slider by itself: the script has to announce the change.
	assert 'dispatchEvent(new Event("input"))' in scripts[0]


def test_the_saved_time_is_handed_back_and_shown(tmp_path):
	prepare(tmp_path, settings={})

	out, _ = render(tmp_path)

	assert f'name="loaded_mtime" value="{FILE_TIME}"' in out
	assert "Zuletzt gespeichert: 14.11.2023, 23:13" in out


def test_without_a_settings_file_the_time_is_zero(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	assert 'name="loaded_mtime" value="0"' in out
	assert "Noch nicht auf dieser Seite gespeichert." in out


# Ticked = processed. The ignored camera is not in the list file, but it must be shown, unticked.
def test_the_cameras_are_the_listed_ones_plus_the_ignored_ones(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	boxes = re.findall(r'name="process_cameras\[\]"\s+value="([^"]+)"(\s+checked)?', out)

	assert [(name, flag.strip()) for name, flag in boxes] == [
		("Alpha", "checked"),
		("Beta", "checked"),
		("Reolink", ""),
	]
	assert 'name="flagger_cameras[]"' in out


def standard_of(out: str, legend: str) -> str:
	fieldset = re.search(rf"<legend>{legend}</legend>.*?</fieldset>", out, re.S)

	assert fieldset is not None, legend

	pattern = r'<span class="settings-default">Standard: ([^<]*)</span>'

	return re.search(pattern, fieldset.group(0)).group(1)


# A list of cameras says its Standard in words, so nobody has to compare ticks with a file: all of
# them, "all but" the few that are off, the few that are on, or none.
def test_each_camera_list_says_what_its_standard_is(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	# Known: Alpha, Beta and the ignored Reolink. Two of three are on, so the off one is named.
	assert standard_of(out, "Kameras") == "alle außer Reolink"
	# One of three is on: the camera that is on is named.
	assert standard_of(out, r"Highlights \(Flagger\)") == "Alpha"


def test_the_standard_of_a_camera_list_can_be_all_or_none(tmp_path):
	config = {**BASE, "ignored_cameras": [], "flagger": {"cameras": [], "retention_days": 30}}
	prepare(tmp_path, config=config)

	out, _ = render(tmp_path)

	assert standard_of(out, "Kameras") == "alle Kameras"
	assert standard_of(out, r"Highlights \(Flagger\)") == "keine"


# The Standard is what config.json holds: a saved change leaves it as it was.
def test_the_standard_of_a_camera_list_ignores_what_is_saved(tmp_path):
	# Beta is switched off on the page; Reolink stays ignored, so all three cameras are still shown.
	prepare(tmp_path, settings={"ignored_cameras": ["Reolink", "Beta"]})

	out, _ = render(tmp_path)
	boxes = re.findall(r'name="process_cameras\[\]"\s+value="([^"]+)"(\s+checked)?', out)

	assert [(name, flag.strip()) for name, flag in boxes] == [
		("Alpha", "checked"),
		("Beta", ""),
		("Reolink", ""),
	]
	assert standard_of(out, "Kameras") == "alle außer Reolink"


def test_a_camera_name_that_is_not_a_plain_name_is_never_shown(tmp_path):
	config = {**BASE, "ignored_cameras": ["<b>x</b>", "../etc"]}
	prepare(tmp_path, config=config)

	out, _ = render(tmp_path)

	assert "<b>x</b>" not in out
	assert "../etc" not in out


def test_a_valid_save_sends_the_values_to_the_wrapper_and_redirects(tmp_path):
	prepare(tmp_path)

	out, args = render(
		tmp_path,
		form_post(scalars={"timelapse.crf": "30"}, processed=("Alpha",), flagger=("Alpha", "Beta")),
		sudo_out=SAVED,
	)
	values = sent_values(args)

	assert args[3:6] == ["/usr/local/sbin/timelapse-web-settings", "general", "0"]
	assert values["timelapse"]["crf"] == 30
	assert values["ignored_cameras"] == ["Beta", "Reolink"]
	assert values["flagger"]["cameras"] == ["Alpha", "Beta"]
	assert values["interval_window"]["target_time"] == "12:00"
	assert values["automatic_daylight_buffer_minutes"]["11"] == 60
	# Post/Redirect/Get: nothing is rendered for the POST itself.
	assert "<h1>" not in out


def test_the_saved_message_shows_once_after_the_redirect(tmp_path):
	prepare(tmp_path)
	render(tmp_path, form_post(), sudo_out=SAVED)

	out, _ = render(tmp_path)

	assert "Gespeichert. Die Einstellungen gelten ab dem nächsten Auftrag." in out

	out, _ = render(tmp_path)

	assert "Gespeichert." not in out


def test_the_page_time_goes_to_the_wrapper(tmp_path):
	prepare(tmp_path, settings={})

	_, args = render(tmp_path, form_post(loaded_mtime=str(FILE_TIME)), sudo_out=SAVED)

	assert args[5] == str(FILE_TIME)


# Text that is not a whole number goes on as text: the writer's message names the problem.
def test_text_in_a_number_field_is_forwarded_as_text(tmp_path):
	prepare(tmp_path)

	_, args = render(tmp_path, form_post(scalars={"timelapse.crf": "abc"}), sudo_out=SAVED)

	assert sent_values(args)["timelapse"]["crf"] == "abc"


def test_post_without_a_valid_csrf_token_saves_nothing(tmp_path):
	prepare(tmp_path)

	for token in ("wrong", None):
		post = form_post()
		post["csrf_token"] = token
		out, args = render(tmp_path, post)

		assert "Die Anfrage ist ungültig (Sicherheitstoken)." in out
		assert args == []


@pytest.mark.parametrize("confirm", ["on", "true", "1", "YES", ["yes"], None])
def test_only_the_exact_string_yes_confirms(tmp_path, confirm):
	prepare(tmp_path)
	post = form_post()
	post["confirm"] = confirm

	out, args = render(tmp_path, post)

	assert "Bitte das Speichern mit der Schaltfläche bestätigen." in out
	assert args == []


@pytest.mark.parametrize("mtime", ["", "abc", "-1", "1.5", "1234567890123", ["1"], None])
def test_a_bad_page_time_saves_nothing(tmp_path, mtime):
	prepare(tmp_path)

	out, args = render(tmp_path, form_post(loaded_mtime=mtime))

	assert "Die Anfrage ist ungültig (Seitenstand)." in out
	assert args == []


def test_a_save_with_every_camera_unticked_is_refused(tmp_path):
	prepare(tmp_path)

	out, args = render(tmp_path, form_post(processed=()))

	assert "Mindestens eine Kamera muss angehakt bleiben." in out
	assert args == []


def test_a_ticked_camera_outside_the_known_set_is_refused(tmp_path):
	prepare(tmp_path)

	for field in ("process_cameras", "flagger_cameras"):
		post = form_post()
		post[field] = ["Alpha", "Gamma"]
		out, args = render(tmp_path, post)

		assert "Die ausgewählte Kamera ist ungültig." in out
		assert args == []


def test_a_camera_list_that_is_not_a_list_is_refused(tmp_path):
	prepare(tmp_path)
	post = form_post()
	post["process_cameras"] = "Alpha"

	out, args = render(tmp_path, post)

	assert "Die ausgewählte Kamera ist ungültig." in out
	assert args == []


@pytest.mark.parametrize("settings", [None, "text", ["x"]])
def test_a_form_without_its_fields_is_refused(tmp_path, settings):
	prepare(tmp_path)
	post = form_post()
	post["settings"] = settings

	out, args = render(tmp_path, post)

	assert "Das Formular war unvollständig. Bitte die Seite neu laden." in out
	assert args == []


def test_a_missing_field_is_refused(tmp_path):
	prepare(tmp_path)
	post = form_post()
	del post["settings"]["timelapse.crf"]

	out, args = render(tmp_path, post)

	assert "Das Formular war unvollständig." in out
	assert args == []


# Only the form's fixed field list is read: whatever else a crafted request carries goes nowhere.
def test_unknown_posted_fields_are_never_forwarded(tmp_path):
	prepare(tmp_path)
	post = form_post(
		privacy={"blur_cameras": []},
		location={"timezone": "UTC"},
		ignored_cameras=["Alpha"],
	)
	post["settings"]["privacy.blur_cameras"] = "[]"
	post["settings"]["location.timezone"] = "UTC"

	_, args = render(tmp_path, post, sudo_out=SAVED)
	values = sent_values(args)

	assert set(values) == {
		"timelapse",
		"flagger",
		"daylight_buffer_minutes",
		"interval_window",
		"min_coverage_days",
		"log_retention_days",
		"automatic_daylight_buffer_minutes",
		"ignored_cameras",
	}
	assert "privacy" not in args[-1]
	assert "location" not in args[-1]
	assert values["ignored_cameras"] == ["Reolink"]


def test_invalid_values_are_shown_next_to_their_field_with_what_was_typed(tmp_path):
	prepare(tmp_path)
	out_json = json.dumps(
		{
			"status": "invalid",
			"errors": ["timelapse.crf: muss eine ganze Zahl von 18 bis 35 sein"],
			"mtime": 0,
		}
	)

	out, _ = render(
		tmp_path, form_post(scalars={"timelapse.crf": "99"}), sudo_exit=65, sudo_out=out_json
	)

	assert 'id="settings-problems"' in out
	assert 'href="#setting-timelapse-crf"' in out
	assert 'id="setting-timelapse-crf-error"' in out
	assert "muss eine ganze Zahl von 18 bis 35 sein" in out
	assert 'aria-invalid="true"' in out
	assert 'aria-describedby="setting-timelapse-crf-hint setting-timelapse-crf-error"' in out
	# The typed value is still in the field, not the saved one.
	assert 'value="99"' in out


# A message about two lists together (a flagger camera that is ignored) belongs to no single field:
# it stands in the summary as plain words, with the ticks the colleague set still in place.
def test_a_message_that_names_no_field_stands_in_the_summary_only(tmp_path):
	prepare(tmp_path)
	message = (
		"Unter „Kameras“ abgewählt, unter „Highlights“ aber noch angehakt: Alpha. "
		"Bitte auch dort abwählen."
	)
	reply = json.dumps({"status": "invalid", "errors": [message], "mtime": 0})

	out, _ = render(
		tmp_path, form_post(processed=("Beta",), flagger=("Alpha",)), sudo_exit=65, sudo_out=reply
	)

	assert 'id="settings-problems"' in out
	assert message in out
	assert 'class="field-error"' not in out
	# What was ticked stays ticked, so the colleague only has to change the one box.
	assert camera_boxes(out, "flagger_cameras")["Alpha"][1] is True
	assert camera_boxes(out, "process_cameras")["Alpha"][1] is False


def test_a_page_that_is_out_of_date_is_refused_and_stays_so(tmp_path):
	prepare(tmp_path, settings={})
	stale = '{"status": "stale", "errors": [], "mtime": 999}'

	out, _ = render(tmp_path, form_post(loaded_mtime="5"), sudo_exit=73, sudo_out=stale)

	assert "Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden." in out
	# The old time is handed back, so a second try without reloading is refused again.
	assert 'name="loaded_mtime" value="5"' in out


def test_a_failed_save_shows_a_generic_message_without_wrapper_details(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path, form_post(), sudo_exit=1)

	assert "Die Einstellungen konnten nicht gespeichert werden." in out
	assert "denied" not in out


def test_messages_and_values_are_escaped(tmp_path):
	prepare(tmp_path)
	out_json = json.dumps(
		{"status": "invalid", "errors": ["<script>alert(1)</script>"], "mtime": 0}
	)

	out, _ = render(
		tmp_path,
		form_post(scalars={"timelapse.crf": '"><script>x</script>'}),
		sudo_exit=65,
		sudo_out=out_json,
	)

	assert "<script>alert(1)</script>" not in out
	assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
	assert '"><script>x</script>' not in out


def test_the_header_has_the_settings_link_with_a_hidden_gear_and_marks_its_page(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)

	link = re.search(r'<a[^>]*class="settings-link"[^>]*>.*?</a>', out, re.S)

	assert link is not None
	assert 'href="/settings.php"' in link.group(0)
	assert 'aria-current="page"' in link.group(0)
	assert "Einstellungen" in link.group(0)
	assert re.search(r'<svg[^>]*aria-hidden="true"', link.group(0)) is not None
	# The other links stay where they were.
	assert '<a href="/">Kameras</a>' in out
	assert '<a href="/highlights.php">Highlights</a>' in out


# The two settings pages are tabs of one area: each marks its own tab.
def test_the_settings_page_has_the_tab_strip_with_its_own_tab_marked(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	strip = re.search(r'<nav[^>]*class="settings-tabs"[^>]*>.*?</nav>', out, re.S)

	assert strip is not None
	links = re.findall(r'href="(/[a-z]+\.php)"', strip.group(0))
	current = re.findall(r'<a[^>]*aria-current="page"[^>]*>', strip.group(0))

	assert links == ["/settings.php", "/verpixelung.php"]

	assert len(current) == 1
	assert 'href="/settings.php"' in current[0]


def tag_of(out: str, pattern: str) -> str:
	match = re.search(pattern, out)

	assert match is not None, pattern

	return match.group(0)


# name -> (the Standard tick, ticked now) for one list of camera boxes.
def camera_boxes(out: str, name: str) -> dict:
	boxes = {}

	for tag in re.findall(rf'<input[^>]*name="{name}\[\]"[^>]*>', out):
		value = re.search(r'value="([^"]+)"', tag).group(1)
		standard = re.search(r'data-default-checked="([01])"', tag).group(1)
		boxes[value] = (standard, re.search(r"\schecked\b", tag) is not None)

	return boxes


# The restore buttons fill the fields with the config.json value, whatever is saved.
def test_every_field_carries_its_standard_for_the_restore_buttons(tmp_path):
	prepare(tmp_path, settings={"timelapse": {"crf": 30}, "log_retention_days": 14})

	out, _ = render(tmp_path)

	for key, standard in SCALARS.items():
		field_id = "setting-" + key.replace(".", "-")
		tag = tag_of(out, rf'<input[^>]*id="{field_id}"[^>]*>')

		assert f'data-default="{standard}"' in tag, key


def test_a_field_without_a_standard_has_nothing_to_restore(tmp_path):
	config = {key: value for key, value in BASE.items() if key != "log_retention_days"}
	prepare(tmp_path, config=config)

	out, _ = render(tmp_path)

	assert "data-default" not in tag_of(out, r'<input[^>]*id="setting-log_retention_days"[^>]*>')


def test_the_camera_boxes_carry_the_standard_ticks(tmp_path):
	prepare(tmp_path, settings={"ignored_cameras": ["Beta"], "flagger": {"cameras": ["Beta"]}})

	out, _ = render(tmp_path)

	# The Standard is config.json (Reolink ignored, Alpha flagged); then what is saved.
	assert camera_boxes(out, "process_cameras") == {"Alpha": ("1", True), "Beta": ("1", False)}
	assert camera_boxes(out, "flagger_cameras") == {"Alpha": ("1", False), "Beta": ("0", True)}


def test_each_group_and_the_bar_have_a_restore_button_that_starts_hidden(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	group_buttons = re.findall(r"<button[^>]*data-default-group[^>]*>", out)

	assert len(group_buttons) == 6
	for tag in group_buttons:
		assert 'type="button"' in tag
		assert re.search(r"\shidden[\s>]", tag) is not None
	assert 'aria-label="Videoqualität: auf Standard zurücksetzen"' in out

	all_button = tag_of(out, r"<button[^>]*data-default-all[^>]*>")

	assert 'type="button"' in all_button
	assert re.search(r"\shidden[\s>]", all_button) is not None
	assert re.search(r'<p[^>]*id="settings-default-note"[^>]*role="status"', out) is not None


# Restoring only fills the fields: the one Save button stores them, the script never submits.
def test_the_restore_script_fills_fields_and_never_submits(tmp_path):
	prepare(tmp_path)

	out, _ = render(tmp_path)
	scripts = [
		script
		for script in re.findall(r"<script[^>]*>(.*?)</script>", out, re.S)
		if "data-default-group" in script
	]

	assert len(scripts) == 1
	assert 'querySelectorAll("[data-default]")' in scripts[0]
	assert 'querySelectorAll("[data-default-checked]")' in scripts[0]
	assert re.search(r"\bvar\b", scripts[0]) is None
	assert ".submit(" not in scripts[0]
	assert "requestSubmit" not in scripts[0]
