import json
import os
import pwd

import pytest
from web_php_test import PROJECT_ROOT_CALL, run_php, run_wrapper

SAVED = '{"status": "saved", "errors": [], "mtime": 456}'
VALUES = {"timelapse": {"crf": 30}, "ignored_cameras": ["Alpha", "Beta"]}
VALUES_PHP = '["timelapse" => ["crf" => 30], "ignored_cameras" => ["Alpha", "Beta"]]'
FAILED_MESSAGE = "Die Einstellungen konnten nicht gespeichert werden."


def save(
	tmp_path,
	exit_code: int,
	out: str = "",
	values_php: str = VALUES_PHP,
	mtime: int = 123,
	scope: str | None = None,
):
	scope_php = "" if scope is None else f', "{scope}"'

	return run_wrapper(
		tmp_path,
		"settings-runner.php",
		f"saveSettings({values_php}, {mtime}{scope_php})",
		exit_code,
		out,
	)


# The wrapper gets the page's modification time and the values as ONE argument, nothing else: the
# browser's request never reaches a command line in any other form.
def test_save_settings_calls_the_wrapper_with_the_mtime_and_the_json(tmp_path):
	result, args = save(tmp_path, 0, SAVED)

	assert args[:3] == ["-n", "-u", pwd.getpwuid(os.getuid()).pw_name]
	assert args[3:] == [
		"/usr/local/sbin/timelapse-web-settings",
		"general",
		"123",
		json.dumps(VALUES, separators=(",", ":")),
	]
	assert result == {"status": "saved", "errors": [], "mtime": 456}


def test_save_settings_reports_invalid_values_with_the_writers_messages(tmp_path):
	out = json.dumps(
		{
			"status": "invalid",
			"errors": ["timelapse.crf: muss eine ganze Zahl von 18 bis 35 sein"],
			"mtime": 123,
		}
	)

	result, _ = save(tmp_path, 65, out)

	assert result == {
		"status": "invalid",
		"errors": ["timelapse.crf: muss eine ganze Zahl von 18 bis 35 sein"],
		"mtime": 123,
	}


# Only strings are passed on: the page prints them, and nothing else may reach it from a reply.
def test_save_settings_keeps_only_string_errors(tmp_path):
	out = json.dumps({"status": "invalid", "errors": [1, "ok", None, ["x"]], "mtime": 123})

	result, _ = save(tmp_path, 65, out)

	assert result["errors"] == ["ok"]


def test_save_settings_gives_invalid_a_message_when_the_writer_sent_none(tmp_path):
	result, _ = save(tmp_path, 65, '{"status": "invalid", "errors": [], "mtime": 123}')

	assert result["status"] == "invalid"
	assert result["errors"] == ["Die Eingaben sind ungültig."]


def test_save_settings_reports_a_page_that_is_out_of_date(tmp_path):
	result, _ = save(tmp_path, 73, '{"status": "stale", "errors": [], "mtime": 789}')

	assert result == {"status": "stale", "errors": [], "mtime": 789}


def test_save_settings_falls_back_to_the_loaded_mtime_when_the_reply_has_none(tmp_path):
	result, _ = save(tmp_path, 73, '{"status": "stale", "errors": []}', mtime=321)

	assert result["status"] == "stale"
	assert result["mtime"] == 321


# Wrapper stderr is logged server-side only, never returned to the browser.
@pytest.mark.parametrize("exit_code", [1, 64, 69, 75, 126, 127])
def test_save_settings_hides_wrapper_failures(tmp_path, exit_code):
	result, _ = save(tmp_path, exit_code, "")

	assert result["status"] == "failed"
	assert result["errors"] == [FAILED_MESSAGE]
	assert "denied" not in json.dumps(result)


# An exit code and a reply that do not belong together are not trusted.
@pytest.mark.parametrize(
	("exit_code", "out"),
	[
		(0, ""),
		(0, "not json"),
		(0, "[1]"),
		(0, '{"status": "invalid", "errors": ["x"], "mtime": 1}'),
		(65, '{"status": "saved", "errors": [], "mtime": 1}'),
		(73, '{"status": "saved", "errors": [], "mtime": 1}'),
		(65, "not json"),
		(73, ""),
	],
)
def test_save_settings_fails_on_a_reply_that_does_not_match_the_exit_code(tmp_path, exit_code, out):
	result, _ = save(tmp_path, exit_code, out)

	assert result["status"] == "failed"
	assert result["errors"] == [FAILED_MESSAGE]


def test_save_settings_refuses_values_that_cannot_be_encoded(tmp_path):
	result, args = save(tmp_path, 0, SAVED, values_php='["a" => "\\xB1"]')

	assert result["status"] == "failed"
	assert args == []


def test_save_settings_refuses_without_a_run_user(tmp_path):
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")

	result, args = save(tmp_path, 0, SAVED)

	assert result["status"] == "failed"
	assert args == []


def test_save_settings_passes_the_privacy_scope_to_the_wrapper(tmp_path):
	result, args = save(tmp_path, 0, SAVED, scope="privacy")

	assert args[3:5] == ["/usr/local/sbin/timelapse-web-settings", "privacy"]
	assert args[5] == "123"
	assert result["status"] == "saved"


# The scope names a file on the host: only the two known names ever reach the wrapper.
@pytest.mark.parametrize("scope", ["other", "", "General", "privacy ", "../x"])
def test_save_settings_refuses_an_unknown_scope(tmp_path, scope):
	result, args = save(tmp_path, 0, SAVED, scope=scope)

	assert result["status"] == "failed"
	assert args == []
