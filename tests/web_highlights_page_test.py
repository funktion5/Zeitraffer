import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web_highlights_test import item, make_day, write_config
from web_php_test import SUDO_PATH, fake_sudo, render_page

TOKEN = "test-token"


# The config in these tests has no timezone, so the page counts days in UTC like this does.
def days_ago(count: int) -> str:
	return (datetime.now(timezone.utc).date() - timedelta(days=count)).isoformat()


# highlights.php with sudo faked.
def render(tmp_path: Path, get=None, post=None, sudo_exit: int = 0):
	swaps = {"src/highlight-delete.php": (SUDO_PATH, str(fake_sudo(tmp_path)))}
	return render_page(tmp_path, "highlights.php", swaps, get or {}, post, sudo_exit, TOKEN)


def delete_post(camera: str, date: str, file: str, token: str = TOKEN) -> dict:
	return {
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
	# The viewer has its own delete button and marker toggle.
	assert 'id="highlights-viewer-delete"' in out
	assert 'id="highlights-viewer-show-boxes"' in out
	# The shared confirm dialog from components/confirm-delete.php.
	assert '<h2 id="confirm-delete-title">Bild löschen</h2>' in out
	assert 'data-delete-name="a.jpg"' in out
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


def test_json_delete_answers_with_the_outcome_instead_of_a_redirect(tmp_path):
	date = days_ago(1)
	make_day(tmp_path, "A", date, [item("a.jpg")])

	out, args = render(tmp_path, post={**delete_post("A", date, "a.jpg"), "response": "json"})

	assert json.loads(out) == {"deleted": True, "message": "Bild erfolgreich gelöscht."}
	assert args[3:] == ["/usr/local/sbin/timelapse-web-delete-highlight", "A", date, "a.jpg"]


def test_json_delete_reports_a_refusal_without_calling_the_wrapper(tmp_path):
	date = days_ago(1)
	make_day(tmp_path, "A", date, [item("a.jpg")])

	post = {**delete_post("A", date, "a.jpg", token="wrong"), "response": "json"}
	out, args = render(tmp_path, post=post)

	assert json.loads(out) == {
		"deleted": False,
		"message": "Die Anfrage ist ungültig (Sicherheitstoken).",
	}
	assert args == []
