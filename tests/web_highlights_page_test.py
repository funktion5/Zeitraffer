import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web_highlights_test import item, make_day, write_config
from web_php_test import SUDO_PATH, fake_sudo

WEB = Path(__file__).resolve().parent.parent / "web"
TOKEN = "test-token"


# The config in these tests has no timezone, so the page counts days in UTC like this does.
def days_ago(count: int) -> str:
	return (datetime.now(timezone.utc).date() - timedelta(days=count)).isoformat()


# Render web/public/highlights.php from a copy in tmp_path: the copy's projectRoot() is
# tmp_path itself, and the session already holds TOKEN. Returns stdout and the sudo arguments.
def render(tmp_path: Path, get=None, post=None, sudo_exit: int = 0):
	site = tmp_path / "web"
	if not site.exists():
		shutil.copytree(WEB, site)
		delete = site / "src" / "highlight-delete.php"
		text = delete.read_text()
		assert SUDO_PATH in text
		delete.write_text(text.replace(SUDO_PATH, str(fake_sudo(tmp_path))))
	(tmp_path / "videos").mkdir(exist_ok=True)
	sessions = tmp_path / "sessions"
	sessions.mkdir(exist_ok=True)
	args_file = tmp_path / "sudo-args.txt"
	args_file.unlink(missing_ok=True)

	driver = tmp_path / "page-driver.php"
	driver.write_text(
		"<?php\n"
		'session_id("highlightstest");\n'
		"session_start();\n"
		f"$_SESSION['csrf_token'] = {json.dumps(TOKEN)};\n"
		"session_write_close();\n"
		f"$_SERVER['REQUEST_METHOD'] = {json.dumps('POST' if post is not None else 'GET')};\n"
		f"$_GET = json_decode({json.dumps(json.dumps(get or {}))}, true);\n"
		f"$_POST = json_decode({json.dumps(json.dumps(post or {}))}, true);\n"
		f"require {json.dumps(str(site / 'public' / 'highlights.php'))};\n"
	)
	result = subprocess.run(
		[
			"php",
			"-d",
			"display_errors=1",
			"-d",
			"error_reporting=-1",
			"-d",
			f"session.save_path={sessions}",
			str(driver),
		],
		capture_output=True,
		text=True,
		env={
			**os.environ,
			"FAKE_SUDO_ARGS": str(args_file),
			"FAKE_SUDO_EXIT": str(sudo_exit),
			"FAKE_SUDO_OUT": "",
			"FAKE_SUDO_ERR": "denied",
		},
		check=False,
	)
	assert result.returncode == 0, result.stdout + result.stderr
	for problem in ("Warning:", "Notice:", "Deprecated:", "Fatal error"):
		assert problem not in result.stdout, result.stdout
	args = args_file.read_text().splitlines() if args_file.exists() else []
	return result.stdout, args


def delete_post(camera: str, date: str, file: str, token: str = TOKEN) -> dict:
	return {
		"action": "delete-highlight",
		"csrf_token": token,
		"camera": camera,
		"date": date,
		"file": file,
		"days": "7",
		"filter_camera": "",
	}


def test_page_shows_cameras_days_and_images(tmp_path):
	write_config(tmp_path, {"flagger": {"cameras": ["Strandallee"]}})
	date = days_ago(1)
	make_day(tmp_path, "Strandallee", date, [item("a.jpg", score=0.8642)], checked=143)

	out, _ = render(tmp_path)

	assert "<h1>Highlights</h1>" in out
	assert "Strandallee" in out
	german = ".".join(reversed(date.split("-")))
	assert german in out
	assert "143 Bilder geprüft" in out
	assert "verpixelt" not in out
	assert 'alt="Strandallee, 08:14 Uhr, Flugzeug?"' in out
	assert "86 %" in out
	assert f'href="/videos/Strandallee/highlights/{date}/a.jpg"' in out
	# The image itself links to the full size, which the viewer dialog shows.
	assert 'class="highlights-open"' in out
	assert f'data-caption="Strandallee · {german} · 08:14 Uhr · Flugzeug? · 86 %"' in out
	assert 'id="highlights-viewer"' in out
	assert "download" in out
	assert f'value="{TOKEN}"' in out
	assert 'width="1920"' in out and 'height="1080"' in out


def test_default_period_is_seven_days(tmp_path):
	make_day(tmp_path, "A", days_ago(3), [item("recent.jpg")])
	make_day(tmp_path, "A", days_ago(10), [item("old.jpg")])

	default, _ = render(tmp_path)
	everything, _ = render(tmp_path, get={"days": "all"})
	bogus, _ = render(tmp_path, get={"days": "8"})

	assert "recent.jpg" in default and "old.jpg" not in default
	assert "recent.jpg" in everything and "old.jpg" in everything
	assert "recent.jpg" in bogus and "old.jpg" not in bogus


def test_camera_filter_and_unknown_camera(tmp_path):
	make_day(tmp_path, "A", days_ago(1), [item("from-a.jpg")])
	make_day(tmp_path, "B", days_ago(1), [item("from-b.jpg")])

	only_b, _ = render(tmp_path, get={"camera": "B"})
	unknown, _ = render(tmp_path, get={"camera": "Nope"})
	weird, _ = render(tmp_path, get={"camera": ["B"]})

	assert "from-b.jpg" in only_b and "from-a.jpg" not in only_b
	assert "Für diese Kamera gibt es keine Highlights." in unknown
	assert "from-a.jpg" not in unknown and "from-b.jpg" not in unknown
	assert "from-a.jpg" in weird and "from-b.jpg" in weird


# A quiet camera must not look like a skipped one, and the other way round.
def test_configured_camera_without_items_is_listed(tmp_path):
	write_config(tmp_path, {"flagger": {"cameras": ["Quiet", "Skipped"]}})
	make_day(tmp_path, "Quiet", days_ago(1), [], checked=99)

	out, _ = render(tmp_path)

	assert "Quiet" in out and "geprüft, nichts gefunden (99 Bilder geprüft)" in out
	assert "Skipped" in out and "Kein Bericht im Zeitraum." in out


def test_no_highlights_at_all_shows_the_empty_message(tmp_path):
	out, _ = render(tmp_path)

	assert "Noch keine Highlights vorhanden." in out


def test_hostile_label_and_names_are_escaped_or_dropped(tmp_path):
	date = days_ago(1)
	day = make_day(
		tmp_path,
		"A<b>",
		date,
		[item("ok.jpg", label="<script>alert(1)</script>"), item("../evil.jpg")],
	)
	(day.parent / "evil.jpg").write_bytes(b"x")

	out, _ = render(tmp_path)

	assert "<script>alert(1)</script>" not in out
	assert "&lt;script&gt;alert(1)&lt;/script&gt;?" in out
	assert "A&lt;b&gt;" in out and "A<b>" not in out
	assert "evil.jpg" not in out


def test_post_with_bad_token_deletes_nothing(tmp_path):
	date = days_ago(1)
	make_day(tmp_path, "A", date, [item("a.jpg")])

	out, args = render(tmp_path, post=delete_post("A", date, "a.jpg", token="wrong"))

	assert "Die Anfrage ist ungültig" in out
	assert args == []


def test_post_with_valid_token_calls_the_wrapper_once(tmp_path):
	date = days_ago(1)
	make_day(tmp_path, "A", date, [item("a.jpg")])

	out, args = render(tmp_path, post=delete_post("A", date, "a.jpg"))

	# Success redirects; the CLI drops the Location header, so the page body stays empty.
	assert out.strip() == ""
	assert args[3:] == ["/usr/local/sbin/timelapse-web-delete-highlight", "A", date, "a.jpg"]


def test_failed_delete_shows_the_generic_message(tmp_path):
	date = days_ago(1)
	make_day(tmp_path, "A", date, [item("a.jpg")])

	out, args = render(tmp_path, post=delete_post("A", date, "a.jpg"), sudo_exit=66)

	assert "Das Bild konnte nicht gelöscht werden." in out
	assert "denied" not in out
	assert len(args) == 7


def test_post_for_an_image_not_in_the_listing_is_refused(tmp_path):
	date = days_ago(1)
	day = make_day(tmp_path, "A", date, [item("a.jpg")])
	(day / "unlisted.jpg").write_bytes(b"x")

	for file in ("unlisted.jpg", "manifest.json", "../a.jpg"):
		out, args = render(tmp_path, post=delete_post("A", date, file))

		assert "Das ausgewählte Bild wurde nicht gefunden." in out
		assert args == []

	out, args = render(tmp_path, post=delete_post("A", days_ago(2), "a.jpg"))

	assert "Das ausgewählte Bild wurde nicht gefunden." in out
	assert args == []


def test_post_with_unknown_camera_is_refused(tmp_path):
	date = days_ago(1)
	make_day(tmp_path, "A", date, [item("a.jpg")])

	for camera in ("Nope", "../A", ["A"]):
		post = delete_post("A", date, "a.jpg")
		post["camera"] = camera
		out, args = render(tmp_path, post=post)

		assert "Die ausgewählte Kamera ist ungültig." in out
		assert args == []


def test_navigation_link_exists_in_the_header(tmp_path):
	out, _ = render(tmp_path)

	assert '<a href="/">Kameras</a>' in out
	assert '<a href="/highlights.php">Highlights</a>' in out
