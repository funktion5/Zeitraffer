import json
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


# Starts a session the way a page does and reports the cookie rules PHP then applies.
def session_rules(tmp_path: Path, server: dict) -> dict:
	driver = tmp_path / "driver.php"
	driver.write_text(
		"<?php\n"
		f"$_SERVER = array_merge($_SERVER, json_decode({json.dumps(json.dumps(server))}, true));\n"
		f"require {json.dumps(str(WEB / 'src' / 'session.php'))};\n"
		"startSession();\n"
		"echo json_encode(session_get_cookie_params()"
		' + ["strict" => ini_get("session.use_strict_mode")]);\n'
	)
	result = subprocess.run(
		[
			"php",
			"-d",
			"display_errors=1",
			"-d",
			"error_reporting=-1",
			"-d",
			f"session.save_path={tmp_path}",
			str(driver),
		],
		capture_output=True,
		text=True,
		check=False,
	)
	assert result.returncode == 0, result.stdout + result.stderr
	return json.loads(result.stdout)


def test_the_session_cookie_is_hidden_from_scripts_and_other_sites(tmp_path):
	rules = session_rules(tmp_path, {})

	assert rules["httponly"] is True
	assert rules["samesite"] == "Lax"
	assert rules["strict"] == "1"
	# Plain HTTP: a Secure cookie would never come back.
	assert rules["secure"] is False


def test_the_session_cookie_is_secure_once_the_site_runs_on_https(tmp_path):
	assert session_rules(tmp_path, {"HTTPS": "on"})["secure"] is True


# The rules only hold if no page starts its session some other way.
def test_every_page_with_a_session_starts_it_through_the_helper():
	pages = [
		page
		for page in (WEB / "public").glob("*.php")
		if "$_SESSION" in page.read_text(encoding="utf-8")
	]

	assert len(pages) >= 5

	for page in pages:
		text = page.read_text(encoding="utf-8")

		assert "startSession();" in text, page.name
		assert "session_start(" not in text, page.name
