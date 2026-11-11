import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from web_php_test import SUDO_PATH, WEB_SRC, fake_sudo, render_page

# The two endpoints of the preview picture:
#   preview.php          GET  ?camera=<name>   the cached JPEG of a blur camera, nothing else
#   preview-refresh.php  POST camera + token   fetches a fresh picture through the wrapper, JSON

TOKEN = "test-token"
JPEG = b"\xff\xd8\xff\xc0\x00\x08\x08\x01\xe0\x02\x80\x00\xff\xd9"
CONFIG = {"privacy": {"blur_cameras": ["SLSV", "Scheunenviertel"]}}


def prepare(
	tmp_path: Path, config=CONFIG, picture: bytes | None = JPEG, camera="SLSV", info=None
) -> Path:
	(tmp_path / "config").mkdir(parents=True, exist_ok=True)
	(tmp_path / "config" / "config.json").write_text(json.dumps(config))
	folder = tmp_path / "state" / "web-jobs" / "previews"
	folder.mkdir(parents=True, exist_ok=True)

	if picture is not None:
		(folder / f"{camera}.jpg").write_bytes(picture)

		# info=False: a picture without its description; a dict changes single fields of it.
		if info is not False:
			description = {
				"image": "20261109T120000.jpg",
				"status": "blurred",
				"taken": "2026-11-09T12:00:00+01:00",
				**(info or {}),
			}
			(folder / f"{camera}.json").write_text(json.dumps(description))

	return folder


# preview.php through PHP's own web server: the headers and status codes only exist there.


@pytest.fixture
def server(tmp_path):
	shutil.copytree(WEB_SRC.parent, tmp_path / "web")

	with socket.socket() as probe:
		probe.bind(("127.0.0.1", 0))
		port = probe.getsockname()[1]

	process = subprocess.Popen(
		["php", "-S", f"127.0.0.1:{port}", "-t", str(tmp_path / "web" / "public")],
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)

	try:
		for _ in range(100):
			try:
				socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
				break

			except OSError:
				time.sleep(0.05)

		yield f"http://127.0.0.1:{port}"

	finally:
		process.terminate()
		process.wait(timeout=5)


def fetch(base: str, path: str, method: str = "GET"):
	request = urllib.request.Request(base + path, method=method)

	try:
		with urllib.request.urlopen(request, timeout=10) as response:
			return response.status, response.headers, response.read()

	except urllib.error.HTTPError as error:
		return error.code, error.headers, error.read()


def test_the_picture_is_served_as_a_jpeg(tmp_path, server):
	prepare(tmp_path)

	status, headers, body = fetch(server, "/preview.php?camera=SLSV")

	assert status == 200
	assert body == JPEG
	assert headers["Content-Type"] == "image/jpeg"
	assert headers["Content-Length"] == str(len(JPEG))


@pytest.mark.parametrize("kind", ["blurred", "clean"])
def test_a_picture_the_blur_job_judged_is_served(tmp_path, server, kind):
	prepare(tmp_path, info={"status": kind})

	status, _, body = fetch(server, "/preview.php?camera=SLSV")

	assert status == 200
	assert body == JPEG


# The page shows a picture only when its description is valid and names a judged frame, and the
# endpoint must agree. A night frame (the blur job records it without running the detector) cached
# before night frames were excluded stays on disk when a refresh finds no candidate: it must not be
# fetchable by its address, from an old tab or the browser history.
@pytest.mark.parametrize(
	"info",
	[{"status": "night"}, {"status": "mystery"}, {"status": 5}, {"taken": "yesterday"}, False],
	ids=["night", "unknown-kind", "kind-not-text", "bad-date", "no-description"],
)
def test_a_picture_the_page_would_not_show_is_not_served_either(tmp_path, server, info):
	prepare(tmp_path, info=info)

	status, _, body = fetch(server, "/preview.php?camera=SLSV")

	assert status == 404
	assert JPEG not in body


# The picture is a camera image: only this user's browser may keep it, and only after asking again.
def test_the_picture_is_not_stored_by_shared_caches_and_not_sniffed(tmp_path, server):
	prepare(tmp_path)

	_, headers, _ = fetch(server, "/preview.php?camera=SLSV")

	assert headers["X-Content-Type-Options"] == "nosniff"
	assert "private" in headers["Cache-Control"]
	assert "no-cache" in headers["Cache-Control"]


@pytest.mark.parametrize(
	("query", "expected"),
	[
		# Not a plain name: refused before any path is built.
		("camera=../SLSV", 400),
		("camera=..%2FSLSV", 400),
		("camera=SLSV%00", 400),
		("camera=a.b", 400),
		("camera=", 400),
		("camera[]=SLSV", 400),
		("", 400),
		# A plain name that does not blur, or has no picture yet.
		("camera=Other", 404),
		("camera=Scheunenviertel", 404),
	],
)
def test_a_request_that_is_not_a_blur_camera_with_a_picture_gets_no_picture(
	tmp_path, server, query, expected
):
	prepare(tmp_path)

	status, _, body = fetch(server, f"/preview.php?{query}")

	assert status == expected
	assert JPEG not in body


# A picture in the cache folder of a camera that no longer blurs is not served either.
def test_a_camera_removed_from_the_blur_list_has_no_picture(tmp_path, server):
	prepare(tmp_path, config={"privacy": {"blur_cameras": ["Scheunenviertel"]}})

	assert fetch(server, "/preview.php?camera=SLSV")[0] == 404


def test_only_get_is_answered(tmp_path, server):
	prepare(tmp_path)

	for method in ("POST", "DELETE"):
		status, headers, _ = fetch(server, "/preview.php?camera=SLSV", method)

		assert status == 405
		assert headers["Allow"] == "GET"


def test_a_cache_file_that_is_no_jpeg_is_not_served(tmp_path, server):
	prepare(tmp_path, picture=b"<?php echo 1; ?>")

	status, _, body = fetch(server, "/preview.php?camera=SLSV")

	assert status == 404
	assert b"echo" not in body


def test_a_linked_cache_file_is_not_served(tmp_path, server):
	folder = prepare(tmp_path, picture=None)
	target = tmp_path / "secret.jpg"
	target.write_bytes(JPEG)
	(folder / "SLSV.jpg").symlink_to(target)

	assert fetch(server, "/preview.php?camera=SLSV")[0] == 404


# preview-refresh.php in the page harness: the session holds the token, fake sudo plays the wrapper.


def refresh(tmp_path: Path, post, sudo_exit: int = 0, sudo_out: str = "", get=None):
	swaps = {"src/preview-runner.php": (SUDO_PATH, str(fake_sudo(tmp_path)))}
	out, args = render_page(
		tmp_path, "preview-refresh.php", swaps, get or {}, post, sudo_exit, TOKEN, sudo_out
	)

	return json.loads(out), args


def post_of(camera="SLSV", token=TOKEN) -> dict:
	return {"csrf_token": token, "camera": camera}


def test_a_refresh_returns_the_new_picture(tmp_path):
	prepare(tmp_path)

	reply, args = refresh(tmp_path, post_of(), 0, '{"status": "ok"}')

	assert args[-2:] == ["/usr/local/sbin/timelapse-web-preview", "SLSV"]
	assert reply["status"] == "ok"
	assert reply["picture"]["width"] == 640
	assert reply["picture"]["height"] == 480
	# The sentences come finished from the server: the script only shows them.
	assert reply["picture"]["alt"] == "Vorschaubild der Kamera SLSV vom 09.11.2026, 12:00 Uhr"
	assert (
		reply["picture"]["caption"]
		== "Aufgenommen am 09.11.2026, 12:00 Uhr. Bildgröße: 640 × 480 Punkte."
	)
	assert "takenText" not in reply["picture"]
	assert reply["picture"]["url"].startswith("/preview.php?camera=SLSV&v=")


def test_a_refresh_reports_that_there_is_no_confirmed_frame_yet(tmp_path):
	prepare(tmp_path, picture=None)

	reply, _ = refresh(tmp_path, post_of(), 67, '{"status": "none"}')

	assert reply["status"] == "none"
	assert "picture" not in reply


def test_a_failed_refresh_shows_no_details(tmp_path):
	prepare(tmp_path)

	reply, _ = refresh(tmp_path, post_of(), 1, "")

	assert reply["status"] == "failed"
	assert "denied" not in json.dumps(reply)


# A refresh asks the Storage Box for a file: it needs the session's token, like every other action.
@pytest.mark.parametrize("token", ["wrong", "", None, ["test-token"]])
def test_a_refresh_without_the_right_token_does_nothing(tmp_path, token):
	prepare(tmp_path)

	reply, args = refresh(tmp_path, post_of(token=token))

	assert reply["status"] == "failed"
	assert args == []


def test_a_refresh_without_a_token_field_does_nothing(tmp_path):
	prepare(tmp_path)

	reply, args = refresh(tmp_path, {"camera": "SLSV"})

	assert reply["status"] == "failed"
	assert args == []


# Only a camera of the blur list, and only a plain name: the wrapper is never asked about anything
# else.
@pytest.mark.parametrize("camera", ["Other", "../SLSV", "a.b", "", ["SLSV"], None])
def test_a_refresh_for_something_that_is_not_a_blur_camera_does_nothing(tmp_path, camera):
	prepare(tmp_path)

	reply, args = refresh(tmp_path, post_of(camera=camera))

	assert reply["status"] == "unknown"
	assert args == []


def test_a_refresh_needs_post(tmp_path):
	prepare(tmp_path)

	reply, args = refresh(tmp_path, None, get={"camera": "SLSV", "csrf_token": TOKEN})

	assert reply == {"status": "failed", "message": "Nicht erlaubt."}
	assert args == []
