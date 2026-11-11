import json
import os
import pwd
from pathlib import Path

import pytest

from web_php_test import PROJECT_ROOT_CALL, SUDO_PATH, fake_sudo, run_php

# web/src/preview-runner.php: the PHP side of the preview picture. It starts the root-owned wrapper
# (refreshPreview) and reads what the wrapper's script cached (readPreviewInfo, previewPicturePath).
# The cache folder is state/web-jobs/previews/ under the project root.

OK_REPLY = '{"status": "ok"}'
NONE_REPLY = '{"status": "none"}'
UNKNOWN_REPLY = '{"status": "unknown_camera"}'
FAILED_MESSAGE = "Das Bild konnte nicht geholt werden. Bitte später noch einmal versuchen."
JPEG = b"\xff\xd8\xff\xc0\x00\x08\x08\x01\xe0\x02\x80\x00\xff\xd9"
# The same picture at 800 x 600, and pictures PHP cannot give a plausible size.
JPEG_800X600 = b"\xff\xd8\xff\xc0\x00\x08\x08\x02\x58\x03\x20\x00\xff\xd9"
JPEG_WIDTH_0 = b"\xff\xd8\xff\xc0\x00\x08\x08\x01\xe0\x00\x00\x00\xff\xd9"
JPEG_WIDTH_20001 = b"\xff\xd8\xff\xc0\x00\x08\x08\x01\xe0\x4e\x21\x00\xff\xd9"


def cache(tmp_path: Path, camera: str = "SLSV", info=None, picture: bytes | None = JPEG) -> Path:
	folder = tmp_path / "state" / "web-jobs" / "previews"
	folder.mkdir(parents=True, exist_ok=True)

	if picture is not None:
		(folder / f"{camera}.jpg").write_bytes(picture)

	if info is not False:
		data = {
			"image": "20261109T120000.jpg",
			"status": "blurred",
			"taken": "2026-11-09T12:00:00+01:00",
			**(info or {}),
		}
		(folder / f"{camera}.json").write_text(json.dumps(data))

	return folder


# run_php swaps the project folder in the copy of the file once, so one test makes ONE php() call;
# several checks go into one piece of PHP that answers with a list.
def php(tmp_path: Path, code: str):
	swaps = {PROJECT_ROOT_CALL: json.dumps(str(tmp_path))}

	return run_php(tmp_path, "preview-runner.php", swaps, code)


def php_string(value: object) -> str:
	return json.dumps(value)


def refresh(tmp_path: Path, exit_code: int, out: str = "", camera: str = "SLSV"):
	args_file = tmp_path / "sudo-args.txt"
	result = run_php(
		tmp_path,
		"preview-runner.php",
		{PROJECT_ROOT_CALL: json.dumps(str(tmp_path)), SUDO_PATH: str(fake_sudo(tmp_path))},
		f"echo json_encode(refreshPreview({php_string(camera)}));",
		env={
			"FAKE_SUDO_ARGS": str(args_file),
			"FAKE_SUDO_EXIT": str(exit_code),
			"FAKE_SUDO_OUT": out,
			"FAKE_SUDO_ERR": "denied",
		},
	)
	args = args_file.read_text().splitlines() if args_file.exists() else []

	return result, args


# The wrapper gets the camera as its one argument: nothing else from the request reaches sudo.
def test_refresh_calls_the_wrapper_with_the_camera_only(tmp_path):
	cache(tmp_path)

	result, args = refresh(tmp_path, 0, OK_REPLY)

	assert args[:3] == ["-n", "-u", pwd.getpwuid(os.getuid()).pw_name]
	assert args[3:] == ["/usr/local/sbin/timelapse-web-preview", "SLSV"]
	assert result["status"] == "ok"


# The picture shown comes from the cache the script wrote, not from the script's reply: the page
# trusts only what it can read itself (which also proves the web server user can read it).
def test_refresh_reports_the_cached_picture_when_the_script_succeeded(tmp_path):
	cache(tmp_path)

	result, _ = refresh(tmp_path, 0, OK_REPLY)

	assert result["status"] == "ok"
	assert (result["info"]["width"], result["info"]["height"]) == (640, 480)
	assert result["info"]["takenText"] == "09.11.2026, 12:00"
	assert isinstance(result["info"]["version"], int)


def test_refresh_fails_when_the_script_said_ok_but_no_picture_is_readable(tmp_path):
	result, _ = refresh(tmp_path, 0, OK_REPLY)

	assert result["status"] == "failed"
	assert result["message"] == FAILED_MESSAGE


def test_refresh_reports_that_there_is_no_confirmed_frame_yet(tmp_path):
	result, _ = refresh(tmp_path, 67, NONE_REPLY)

	assert result["status"] == "none"
	assert "noch kein" in result["message"]


def test_refresh_reports_a_camera_that_does_not_blur(tmp_path):
	result, _ = refresh(tmp_path, 66, UNKNOWN_REPLY)

	assert result["status"] == "unknown"


def test_refresh_says_when_the_box_did_not_answer_in_time(tmp_path):
	result, _ = refresh(tmp_path, 124, "")

	assert result["status"] == "failed"
	assert "nicht rechtzeitig" in result["message"]


# Wrapper stderr is logged server-side only, never returned to the browser.
@pytest.mark.parametrize("exit_code", [1, 64, 69, 75, 126, 127])
def test_refresh_hides_wrapper_failures(tmp_path, exit_code):
	result, _ = refresh(tmp_path, exit_code, "")

	assert result["status"] == "failed"
	assert result["message"] == FAILED_MESSAGE
	assert "denied" not in json.dumps(result)


# An exit code and a reply that do not belong together are not trusted.
@pytest.mark.parametrize(
	("exit_code", "out"),
	[
		(0, ""),
		(0, "not json"),
		(0, "[1]"),
		(0, NONE_REPLY),
		(67, OK_REPLY),
		(67, ""),
		(66, NONE_REPLY),
	],
)
def test_refresh_fails_on_a_reply_that_does_not_match_the_exit_code(tmp_path, exit_code, out):
	cache(tmp_path)

	result, _ = refresh(tmp_path, exit_code, out)

	assert result["status"] == "failed"


# The name may come straight from a request: only a plain name reaches sudo.
@pytest.mark.parametrize("camera", ["", "../x", "a b", "a.b", "-x", "a/b", "a;id", "x\n"])
def test_refresh_never_passes_an_unsafe_name_on(tmp_path, camera):
	result, args = refresh(tmp_path, 0, OK_REPLY, camera=camera)

	assert result["status"] == "unknown"
	assert args == []


def test_refresh_refuses_without_a_run_user(tmp_path):
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")

	result, args = refresh(tmp_path, 0, OK_REPLY)

	assert result["status"] == "failed"
	assert args == []


def test_the_cached_info_is_read_and_validated(tmp_path):
	cache(tmp_path)

	info = php(tmp_path, 'echo json_encode(readPreviewInfo("SLSV"));')

	assert info["width"] == 640
	assert info["height"] == 480
	assert info["kind"] == "blurred"
	assert info["taken"] == "2026-11-09T12:00:00+01:00"
	assert info["takenText"] == "09.11.2026, 12:00"


# The size is the picture's own. A description with a size of its own (one from before the script
# stopped writing it, or a wrong one) cannot make the page lie about the picture.
def test_the_size_is_read_from_the_picture_not_from_the_description(tmp_path):
	cache(tmp_path, picture=JPEG_800X600, info={"width": 1, "height": 1})

	info = php(tmp_path, 'echo json_encode(readPreviewInfo("SLSV"));')

	assert (info["width"], info["height"]) == (800, 600)


def test_there_is_no_info_without_a_cache(tmp_path):
	assert php(tmp_path, 'echo json_encode(readPreviewInfo("SLSV"));') is None


# The picture and its description belong together: either one missing or broken means no preview.
@pytest.mark.parametrize(
	"damage",
	[
		{"picture": None},
		{"info": False},
		{"picture": b""},
		{"picture": b"GIF89a not a jpeg"},
		# The size is read from the picture itself: one without a plausible size is no preview.
		{"picture": b"\xff\xd8not really\xff\xd9"},
		{"picture": JPEG_WIDTH_0},
		{"picture": JPEG_WIDTH_20001},
		{"picture": b"\xff\xd8\xff\xc0\x00"},
		{"picture": b"\xff\xd8\xff\xe0"},
		# PHP complains about this one (a notice): the page must show no preview and no error text.
		{"picture": b"\xff\xd8\x8e\xff"},
		{"info": {"status": "mystery"}},
		# A night frame was never judged by the detector: never shown.
		{"info": {"status": "night"}},
		{"info": {"taken": "yesterday"}},
		{"info": {"taken": 5}},
	],
)
def test_a_damaged_cache_gives_no_info(tmp_path, damage):
	cache(tmp_path, **damage)

	assert php(tmp_path, 'echo json_encode(readPreviewInfo("SLSV"));') is None


def test_info_that_is_not_json_gives_no_info(tmp_path):
	folder = cache(tmp_path)
	(folder / "SLSV.json").write_text("{not json")

	assert php(tmp_path, 'echo json_encode(readPreviewInfo("SLSV"));') is None


# A link in the cache folder could point anywhere the web server user can read.
def test_a_linked_picture_is_not_served(tmp_path):
	folder = cache(tmp_path, picture=None)
	target = tmp_path / "elsewhere.jpg"
	target.write_bytes(JPEG)
	(folder / "SLSV.jpg").symlink_to(target)

	assert php(tmp_path, 'echo json_encode(previewPicturePath("SLSV"));') is None


@pytest.mark.parametrize("camera", ["", "../SLSV", "a.b", "-x", "a b"])
def test_an_unsafe_name_has_no_picture_and_no_info(tmp_path, camera):
	cache(tmp_path)
	name = php_string(camera)

	result = php(
		tmp_path,
		f"echo json_encode([previewPicturePath({name}), readPreviewInfo({name})]);",
	)

	assert result == [None, None]


def test_the_picture_path_is_inside_the_cache_folder(tmp_path):
	folder = cache(tmp_path)

	path = php(tmp_path, 'echo json_encode(previewPicturePath("SLSV"));')

	assert path == str(folder / "SLSV.jpg")


# The page asks the browser for the picture by an address that changes with the picture, so an
# old one is never shown from the browser's cache.
def test_the_picture_address_carries_the_camera_and_a_version(tmp_path):
	url = php(tmp_path, 'echo json_encode(previewUrl("SLSV", 17));')

	assert url == "/preview.php?camera=SLSV&v=17"


def test_only_a_camera_of_the_blur_list_is_a_blur_camera(tmp_path):
	config = php_string(json.dumps({"privacy": {"blur_cameras": ["SLSV", 5, None]}}))

	result = php(
		tmp_path,
		f"$config = json_decode({config}, true);"
		"echo json_encode(["
		"isBlurCamera($config, 'SLSV'),"
		"isBlurCamera($config, 'Other'),"
		"isBlurCamera($config, '5'),"
		"isBlurCamera([], 'SLSV'),"
		"isBlurCamera(['privacy' => 'x'], 'SLSV'),"
		"]);",
	)

	assert result == [True, False, False, False, False]
