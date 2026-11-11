import io
import json
import os
import stat
from typing import NamedTuple

import pytest

import src.config as config_module
import src.settings_save as settings_save
from src.settings import ALLOWED_KEYS, get_leaf, set_leaf


# An arbitrary but fixed modification time, so "the file changed since the page loaded" is exact.
FILE_TIME = 1_700_000_000


class Paths(NamedTuple):
	config: object
	settings: object
	log: object


# A copy of the real config.json next to a settings file and a log folder, like the project layout.
@pytest.fixture
def paths(tmp_path):
	config_folder = tmp_path / "config"
	logs_folder = tmp_path / "logs"
	config_folder.mkdir()
	logs_folder.mkdir()

	config_path = config_folder / "config.json"
	config_path.write_text(config_module.CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

	return Paths(config_path, config_folder / "settings.json", logs_folder / "settings.log")


def read_base(paths: Paths) -> dict:
	return json.loads(paths.config.read_text(encoding="utf-8"))


# What the form submits: every allowed leaf, at its value in config.json.
def base_submission(paths: Paths) -> dict:
	base = read_base(paths)
	submission: dict = {}

	for key in ALLOWED_KEYS:
		set_leaf(submission, key, get_leaf(base, key))

	return submission


def write_settings(paths: Paths, content: dict) -> None:
	paths.settings.write_text(json.dumps(content), encoding="utf-8")
	os.utime(paths.settings, (FILE_TIME, FILE_TIME))


def save(paths: Paths, submitted: object, expected_mtime: int = 0):
	return settings_save.save_settings(
		submitted,
		expected_mtime,
		config_path=paths.config,
		settings_path=paths.settings,
		log_path=paths.log,
	)


def stored(paths: Paths) -> dict:
	return json.loads(paths.settings.read_text(encoding="utf-8"))


def test_save_stores_only_values_that_differ_from_config_json(paths):
	base = read_base(paths)
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 30
	submission["ignored_cameras"] = [*base["ignored_cameras"], "Alpha"]

	result = save(paths, submission)

	assert result.status == "saved"
	assert result.errors == ()
	assert stored(paths) == {
		"timelapse": {"crf": 30},
		"ignored_cameras": sorted([*base["ignored_cameras"], "Alpha"]),
	}
	assert result.mtime == int(paths.settings.stat().st_mtime)


def test_a_list_in_another_order_is_not_an_override(paths):
	submission = base_submission(paths)
	submission["ignored_cameras"] = list(reversed(submission["ignored_cameras"]))

	assert save(paths, submission).status == "saved"
	assert stored(paths) == {}


def test_saving_the_base_value_again_removes_the_override(paths):
	write_settings(paths, {"timelapse": {"crf": 30}})
	submission = base_submission(paths)

	result = save(paths, submission, expected_mtime=FILE_TIME)

	assert result.status == "saved"
	assert stored(paths) == {}


def test_a_submission_replaces_the_whole_file(paths):
	write_settings(paths, {"timelapse": {"crf": 30}, "log_retention_days": 7})
	submission = base_submission(paths)
	submission["log_retention_days"] = 7

	assert save(paths, submission, expected_mtime=FILE_TIME).status == "saved"
	assert stored(paths) == {"log_retention_days": 7}


def test_invalid_values_save_nothing(paths):
	write_settings(paths, {"timelapse": {"crf": 30}})
	before = paths.settings.read_bytes()
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 99

	result = save(paths, submission, expected_mtime=FILE_TIME)

	assert result.status == "invalid"
	assert result.errors[0].startswith("timelapse.crf")
	assert paths.settings.read_bytes() == before


def test_invalid_values_do_not_create_a_file(paths):
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 99

	assert save(paths, submission).status == "invalid"
	assert not paths.settings.exists()


@pytest.mark.parametrize(
	("group", "content"),
	[("privacy", {"blur_cameras": []}), ("location", {"timezone": "UTC"})],
)
def test_keys_outside_the_allowlist_save_nothing(paths, group, content):
	write_settings(paths, {"timelapse": {"crf": 30}})
	before = paths.settings.read_bytes()
	submission = base_submission(paths)
	submission[group] = content

	result = save(paths, submission, expected_mtime=FILE_TIME)

	assert result.status == "invalid"
	assert result.errors[0].startswith(f"{group}.")
	assert paths.settings.read_bytes() == before


@pytest.mark.parametrize("key", ["ignored_cameras", "flagger.cameras"])
def test_path_like_camera_names_save_nothing(paths, key):
	submission = base_submission(paths)
	set_leaf(submission, key, ["../etc"])

	result = save(paths, submission)

	assert result.status == "invalid"
	assert not paths.settings.exists()


def test_a_stale_page_is_refused(paths):
	write_settings(paths, {"timelapse": {"crf": 30}})
	before = paths.settings.read_bytes()

	result = save(paths, base_submission(paths), expected_mtime=FILE_TIME - 5)

	assert result.status == "stale"
	assert result.mtime == FILE_TIME
	assert paths.settings.read_bytes() == before


def test_a_page_loaded_without_a_file_saves_with_time_zero(paths):
	assert save(paths, base_submission(paths), expected_mtime=0).status == "saved"


def test_a_page_loaded_without_a_file_is_stale_once_a_file_exists(paths):
	write_settings(paths, {"timelapse": {"crf": 30}})

	assert save(paths, base_submission(paths), expected_mtime=0).status == "stale"


def test_a_stale_save_creates_no_file(paths):
	assert save(paths, base_submission(paths), expected_mtime=5).status == "stale"
	assert not paths.settings.exists()


def test_saved_file_is_world_readable_and_leaves_no_temp_file(paths):
	save(paths, base_submission(paths))

	assert stat.S_IMODE(paths.settings.stat().st_mode) == 0o644
	assert sorted(entry.name for entry in paths.settings.parent.iterdir()) == [
		"config.json",
		"settings.json",
	]


def test_a_failing_rename_keeps_the_old_file(paths, monkeypatch):
	write_settings(paths, {"timelapse": {"crf": 30}})
	before = paths.settings.read_bytes()
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 31

	def fail(*arguments):
		raise OSError("disk full")

	with monkeypatch.context() as patch:
		patch.setattr(settings_save.os, "replace", fail)

		with pytest.raises(OSError):
			save(paths, submission, expected_mtime=FILE_TIME)

	assert paths.settings.read_bytes() == before
	assert sorted(entry.name for entry in paths.settings.parent.iterdir()) == [
		"config.json",
		"settings.json",
	]


def test_log_line_names_changed_keys_with_old_and_new_values(paths):
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 30

	save(paths, submission)

	lines = paths.log.read_text(encoding="utf-8").splitlines()

	assert len(lines) == 1
	assert "timelapse.crf: 28 -> 30" in lines[0]
	assert stat.S_IMODE(paths.log.stat().st_mode) == 0o600


def test_log_line_is_added_for_every_save_and_names_only_what_changed(paths):
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 30
	first = save(paths, submission)
	submission["log_retention_days"] = 7
	save(paths, submission, expected_mtime=first.mtime)

	lines = paths.log.read_text(encoding="utf-8").splitlines()

	assert len(lines) == 2
	assert "log_retention_days: 30 -> 7" in lines[1]
	assert "timelapse.crf" not in lines[1]


def test_a_log_that_cannot_be_written_does_not_fail_the_save(paths, tmp_path):
	result = settings_save.save_settings(
		base_submission(paths),
		0,
		config_path=paths.config,
		settings_path=paths.settings,
		log_path=tmp_path / "missing-folder" / "settings.log",
	)

	assert result.status == "saved"
	assert paths.settings.exists()


def run_main(monkeypatch, paths, text, expected_mtime, scope="general"):
	monkeypatch.setattr(config_module, "CONFIG_PATH", paths.config)
	monkeypatch.setattr(config_module, "SETTINGS_PATH", paths.settings)
	monkeypatch.setattr(config_module, "PRIVACY_SETTINGS_PATH", privacy_file(paths))
	monkeypatch.setattr(settings_save, "SETTINGS_LOG_PATH", paths.log)
	arguments = ["--scope", scope, "--expected-mtime", str(expected_mtime)]

	return settings_save.main(arguments, io.StringIO(text))


# The flagger refuses to start for ALL cameras when one of its cameras is ignored (ignored cameras
# are not processed). The page must never save that combination.
def flagger_camera(paths: Paths) -> str:
	return read_base(paths)["flagger"]["cameras"][0]


def test_save_refuses_a_flagger_camera_that_is_also_ignored(paths):
	camera = flagger_camera(paths)
	submission = base_submission(paths)
	submission["ignored_cameras"] = [*submission["ignored_cameras"], camera]

	result = save(paths, submission)

	assert result.status == "invalid"
	assert len(result.errors) == 1
	assert camera in result.errors[0]
	assert not paths.settings.exists()


# The message is for colleagues and names no setting key, so the page shows it as a plain message.
def test_the_flagger_message_names_the_cameras_in_words_without_a_key(paths):
	cameras = read_base(paths)["flagger"]["cameras"][:2]
	submission = base_submission(paths)
	submission["ignored_cameras"] = [*submission["ignored_cameras"], *cameras]

	message = save(paths, submission).errors[0]

	assert all(camera in message for camera in cameras)
	assert "Highlights" in message
	assert not message.startswith(("flagger.", "ignored_cameras"))


def test_save_accepts_an_ignored_camera_that_is_not_a_flagger_camera(paths):
	submission = base_submission(paths)
	submission["ignored_cameras"] = [*submission["ignored_cameras"], "Some-Other-Camera"]

	assert save(paths, submission).status == "saved"


def test_save_accepts_an_ignored_camera_that_also_left_the_flagger_list(paths):
	camera = flagger_camera(paths)
	submission = base_submission(paths)
	submission["ignored_cameras"] = [*submission["ignored_cameras"], camera]
	submission["flagger"]["cameras"] = [c for c in submission["flagger"]["cameras"] if c != camera]

	assert save(paths, submission).status == "saved"


# Not every leaf has to be sent: the check looks at what would be in force, config.json included.
def test_the_check_uses_the_flagger_list_in_force_when_the_form_does_not_send_one(paths):
	submission = {"ignored_cameras": [flagger_camera(paths)]}

	result = save(paths, submission)

	assert result.status == "invalid"
	assert not paths.settings.exists()


# Invalid input is refused before the page's age is looked at, the clash included.
def test_a_clash_is_reported_even_when_the_page_is_also_out_of_date(paths):
	write_settings(paths, {"timelapse": {"crf": 30}})
	submission = base_submission(paths)
	submission["ignored_cameras"] = [*submission["ignored_cameras"], flagger_camera(paths)]

	result = save(paths, submission, expected_mtime=1)

	assert result.status == "invalid"
	assert stored(paths) == {"timelapse": {"crf": 30}}


# A clash already in config.json (a hand edit) is refused too, with the same message.
def test_a_clash_already_in_config_json_is_refused_on_the_next_save(paths):
	camera = flagger_camera(paths)
	base = read_base(paths)
	base["ignored_cameras"] = [*base["ignored_cameras"], camera]
	paths.config.write_text(json.dumps(base), encoding="utf-8")

	result = save(paths, {"timelapse": {"crf": 30}})

	assert result.status == "invalid"
	assert camera in result.errors[0]
	assert not paths.settings.exists()


# Without a readable config.json there is nothing to compare against. Invalid input is still refused
# as invalid; a valid save fails loudly, as it always did, and writes nothing.
def test_invalid_input_is_still_refused_as_invalid_when_config_json_cannot_be_read(paths):
	paths.config.write_text("{not json", encoding="utf-8")

	result = save(paths, {"timelapse": {"crf": 99}})

	assert result.status == "invalid"
	assert result.errors[0].startswith("timelapse.crf")


def test_a_valid_save_fails_loudly_when_config_json_cannot_be_read(paths):
	paths.config.write_text("{not json", encoding="utf-8")

	with pytest.raises(ValueError, match="config.json"):
		save(paths, {"timelapse": {"crf": 30}})

	assert not paths.settings.exists()


def test_the_flagger_check_is_listed_with_other_errors_not_instead_of_them(paths):
	submission = base_submission(paths)
	submission["ignored_cameras"] = [*submission["ignored_cameras"], flagger_camera(paths)]
	submission["timelapse"]["crf"] = 99

	errors = save(paths, submission).errors

	assert len(errors) == 2
	assert any(error.startswith("timelapse.crf") for error in errors)


def test_main_saved_exits_zero_and_prints_one_json_line(monkeypatch, paths, capsys):
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 30

	code = run_main(monkeypatch, paths, json.dumps(submission), 0)
	lines = capsys.readouterr().out.splitlines()

	assert code == 0
	assert len(lines) == 1
	assert json.loads(lines[0]) == {
		"status": "saved",
		"errors": [],
		"mtime": int(paths.settings.stat().st_mtime),
	}


def test_main_invalid_values_exit_65_with_the_errors(monkeypatch, paths, capsys):
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 99

	code = run_main(monkeypatch, paths, json.dumps(submission), 0)
	reply = json.loads(capsys.readouterr().out)

	assert code == 65
	assert reply["status"] == "invalid"
	assert reply["errors"][0].startswith("timelapse.crf")


def test_main_unparsable_json_exits_65(monkeypatch, paths, capsys):
	code = run_main(monkeypatch, paths, "{not json", 0)
	reply = json.loads(capsys.readouterr().out)

	assert code == 65
	assert reply["errors"] == ["Ungültige Eingabe"]
	assert not paths.settings.exists()


@pytest.mark.parametrize("depth", [2000, 12000])
def test_main_json_nested_too_deep_exits_65(monkeypatch, paths, capsys, depth):
	code = run_main(monkeypatch, paths, '{"a":' * depth + "1" + "}" * depth, 0)
	reply = json.loads(capsys.readouterr().out)

	assert code == 65
	assert reply["errors"] == ["Ungültige Eingabe"]
	assert not paths.settings.exists()


def test_main_stale_page_exits_73(monkeypatch, paths, capsys):
	write_settings(paths, {"timelapse": {"crf": 30}})

	code = run_main(monkeypatch, paths, json.dumps(base_submission(paths)), 7)
	reply = json.loads(capsys.readouterr().out)

	assert code == 73
	assert reply["status"] == "stale"
	assert reply["mtime"] == FILE_TIME


# The privacy tab saves into its own file with its own rules: the two tabs never touch each other.
def privacy_file(paths: Paths):
	return paths.settings.parent / "settings-privacy.json"


def save_privacy(paths: Paths, names: list, expected_mtime: int = 0):
	return settings_save.save_settings(
		{"privacy": {"blur_cameras": names}},
		expected_mtime,
		scope="privacy",
		config_path=paths.config,
		settings_path=privacy_file(paths),
		log_path=paths.log,
	)


def test_a_privacy_save_writes_only_the_privacy_file(paths):
	names = [*read_base(paths)["privacy"]["blur_cameras"], "Alpha"]
	write_settings(paths, {"timelapse": {"crf": 30}})
	before = paths.settings.read_bytes()

	result = save_privacy(paths, names)

	assert result.status == "saved"
	assert json.loads(privacy_file(paths).read_text()) == {
		"privacy": {"blur_cameras": sorted(names)}
	}
	assert paths.settings.read_bytes() == before


def test_the_base_blur_list_is_not_stored_as_an_override(paths):
	result = save_privacy(paths, read_base(paths)["privacy"]["blur_cameras"])

	assert result.status == "saved"
	assert json.loads(privacy_file(paths).read_text()) == {}


def test_the_privacy_scope_refuses_general_keys(paths):
	result = settings_save.save_settings(
		{"timelapse": {"crf": 30}},
		0,
		scope="privacy",
		config_path=paths.config,
		settings_path=privacy_file(paths),
		log_path=paths.log,
	)

	assert result.status == "invalid"
	assert not privacy_file(paths).exists()


def test_a_save_in_one_scope_does_not_make_the_other_stale(paths):
	write_settings(paths, {"timelapse": {"crf": 30}})
	names = [*read_base(paths)["privacy"]["blur_cameras"], "Alpha"]

	assert save_privacy(paths, names).status == "saved"
	assert save(paths, base_submission(paths), expected_mtime=FILE_TIME).status == "saved"


def test_the_log_line_names_the_scope(paths):
	names = [*read_base(paths)["privacy"]["blur_cameras"], "Alpha"]
	submission = base_submission(paths)
	submission["timelapse"]["crf"] = 30

	save_privacy(paths, names)
	save(paths, submission)

	lines = paths.log.read_text(encoding="utf-8").splitlines()

	assert "[privacy] privacy.blur_cameras" in lines[0]
	assert "[general] timelapse.crf" in lines[1]


def test_main_saves_the_privacy_scope_to_its_own_file(monkeypatch, paths, capsys):
	names = [*read_base(paths)["privacy"]["blur_cameras"], "Alpha"]

	code = run_main(
		monkeypatch, paths, json.dumps({"privacy": {"blur_cameras": names}}), 0, scope="privacy"
	)

	assert code == 0
	assert json.loads(privacy_file(paths).read_text()) == {
		"privacy": {"blur_cameras": sorted(names)}
	}
	assert not paths.settings.exists()


def test_main_refuses_an_unknown_scope(monkeypatch, paths):
	with pytest.raises(SystemExit):
		run_main(monkeypatch, paths, "{}", 0, scope="other")


# The privacy values: decimals, per-camera maps and box lists, stored as differences like the rest.
def base_privacy_submission(paths: Paths) -> dict:
	privacy = read_base(paths)["privacy"]

	return {
		"privacy": {
			"blur_cameras": list(privacy["blur_cameras"]),
			"blur": dict(privacy["blur"]),
			"ignore_top_share_per_camera": {},
			"min_person_score": dict(privacy["min_person_score"]),
			"ignore_boxes": {
				camera: [list(box) for box in boxes]
				for camera, boxes in privacy["ignore_boxes"].items()
			},
		}
	}


def save_privacy_values(paths: Paths, submitted: dict, expected_mtime: int = 0):
	return settings_save.save_settings(
		submitted,
		expected_mtime,
		scope="privacy",
		config_path=paths.config,
		settings_path=privacy_file(paths),
		log_path=paths.log,
	)


def stored_privacy(paths: Paths) -> dict:
	return json.loads(privacy_file(paths).read_text(encoding="utf-8"))


def test_the_unchanged_privacy_values_are_not_stored(paths):
	result = save_privacy_values(paths, base_privacy_submission(paths))

	assert result.status == "saved"
	assert stored_privacy(paths) == {}


def test_a_changed_blur_value_is_stored_alone(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["blur"]["strength"] = 0.1

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {"privacy": {"blur": {"strength": 0.1}}}


def test_only_the_changed_cameras_boxes_are_stored(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["ignore_boxes"]["SLSV"] = [[10, 10, 20, 20]]

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {"privacy": {"ignore_boxes": {"SLSV": [[10, 10, 20, 20]]}}}


def test_clearing_a_cameras_boxes_is_an_override(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["ignore_boxes"]["Scheunenviertel"] = []

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {"privacy": {"ignore_boxes": {"Scheunenviertel": []}}}


def test_boxes_in_another_order_are_not_an_override(paths):
	submission = base_privacy_submission(paths)
	boxes = submission["privacy"]["ignore_boxes"]["Scheunenviertel"]
	submission["privacy"]["ignore_boxes"]["Scheunenviertel"] = list(reversed(boxes))

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {}


def test_a_new_camera_without_boxes_stores_nothing(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["ignore_boxes"]["NewCam"] = []

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {}


def test_a_per_camera_score_is_stored_and_the_base_score_is_not(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["min_person_score"]["NewCam"] = 0.3

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {"privacy": {"min_person_score": {"NewCam": 0.3}}}


# A camera's own top share is an override of the global one. Where config.json has no value for the
# camera, its default is the global value: a camera that stands at the default stores nothing, so it
# keeps following the global value if that is changed later. Only a real difference is kept.
def test_a_per_camera_top_share_equal_to_the_global_one_is_not_stored(paths):
	submission = base_privacy_submission(paths)
	global_share = read_base(paths)["privacy"]["ignore_top_share"]
	submission["privacy"]["ignore_top_share_per_camera"] = {"SLSV": global_share, "NewCam": 0.2}

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {"privacy": {"ignore_top_share_per_camera": {"NewCam": 0.2}}}


def test_a_per_camera_top_share_of_zero_is_a_real_override(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["ignore_top_share_per_camera"] = {"SLSV": 0}

	assert save_privacy_values(paths, submission).status == "saved"
	assert stored_privacy(paths) == {"privacy": {"ignore_top_share_per_camera": {"SLSV": 0}}}


def test_the_log_names_the_global_value_as_the_old_value_of_a_per_camera_top_share(paths):
	submission = base_privacy_submission(paths)
	global_share = read_base(paths)["privacy"]["ignore_top_share"]
	submission["privacy"]["ignore_top_share_per_camera"] = {"SLSV": 0.1}

	assert save_privacy_values(paths, submission).status == "saved"

	line = paths.log.read_text().splitlines()[-1]

	assert f"privacy.ignore_top_share_per_camera.SLSV: {global_share} -> 0.1" in line


@pytest.mark.parametrize(
	("path", "value"),
	[
		(("blur", "strength"), 0.9),
		(("ignore_top_share_per_camera", "SLSV"), 0.5),
		(("min_person_score", "SLSV"), 0.8),
		(("ignore_boxes", "SLSV"), [[5, 5, 5, 9]]),
	],
)
def test_invalid_privacy_values_save_nothing(paths, path, value):
	submission = base_privacy_submission(paths)
	target = submission["privacy"]

	for part in path[:-1]:
		target = target[part]

	target[path[-1]] = value

	result = save_privacy_values(paths, submission)

	assert result.status == "invalid"
	assert not privacy_file(paths).exists()


# What decides WHAT gets blurred stays with IT: these keys are refused on the page.
@pytest.mark.parametrize(
	"extra",
	[
		{"skip_labels": {"SLSV": ["vehicle"]}},
		{"detector_command": ["python", "evil.py"]},
	],
)
def test_privacy_keys_that_stay_with_it_are_refused(paths, extra):
	submission = base_privacy_submission(paths)
	submission["privacy"].update(extra)

	result = save_privacy_values(paths, submission)

	assert result.status == "invalid"
	assert not privacy_file(paths).exists()


def test_the_log_line_names_per_camera_keys_with_old_and_new_values(paths):
	submission = base_privacy_submission(paths)
	submission["privacy"]["ignore_boxes"]["SLSV"] = [[10, 10, 20, 20]]
	submission["privacy"]["min_person_score"]["SLSV"] = 0.4

	save_privacy_values(paths, submission)

	line = paths.log.read_text(encoding="utf-8").splitlines()[0]

	assert "privacy.ignore_boxes.SLSV: unset -> [[10, 10, 20, 20]]" in line
	assert "privacy.min_person_score.SLSV: 0.35 -> 0.4" in line
