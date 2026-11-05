import fcntl
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
	Path(__file__).resolve().parent.parent / "scripts" / "copy_zeitraffer_videos_vps2siteground.sh"
)

# The FTP login is not in the script: it comes from the environment or from a file that git
# ignores (siteground.env). The tests set their own values in the environment, point
# SITEGROUND_CONFIG at a file that does not exist unless a test needs one, and send every curl call
# to the fake below, so a real login file on the machine is never read.
pytestmark = pytest.mark.skipif(
	not SCRIPT.exists(),
	reason="the delivery script is not in this checkout",
)

# A fake FTP server in a folder: it understands exactly the curl calls the script makes.
FAKE_CURL = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
root = Path(os.environ["FAKE_FTP_ROOT"])

with open(os.environ["FAKE_CURL_LOG"], "a") as log:
	log.write(json.dumps(args) + "\n")

VALUE_OPTIONS = {
	"--user",
	"--upload-file",
	"--quote",
	"--connect-timeout",
	"--speed-limit",
	"--speed-time",
}
options = {}
quotes = []
flags = set()
index = 0

while index < len(args) - 1:
	argument = args[index]

	if argument in VALUE_OPTIONS:
		if argument == "--quote":
			quotes.append(args[index + 1])
		else:
			options[argument] = args[index + 1]

		index += 2
	else:
		flags.add(argument)
		index += 1

url = args[-1]
path = url.split("/", 3)[3] if url.count("/") >= 3 else ""

if options.get("--user") != os.environ["FAKE_LOGIN"]:
	sys.exit(67)

if "--upload-file" in options:
	if os.environ.get("FAKE_FAIL_UPLOAD") and os.environ["FAKE_FAIL_UPLOAD"] in path:
		sys.exit(55)

	target = root / path

	if not target.parent.exists():
		if "--ftp-create-dirs" not in flags:
			sys.exit(9)

		target.parent.mkdir(parents=True)

	target.write_bytes(Path(options["--upload-file"]).read_bytes())
elif "--head" in flags:
	target = root / path

	if not target.is_file():
		sys.exit(19)

	sys.stdout.write(f"Content-Length: {target.stat().st_size}\r\n\r\n")
elif "--list-only" in flags:
	folder = root / path

	if not folder.is_dir():
		sys.exit(78)

	for entry in sorted(folder.iterdir()):
		print(entry.name)
elif quotes:
	renamed_from = None

	for command in quotes:
		verb, _, argument = command.partition(" ")

		if verb == "RNFR":
			renamed_from = argument
		elif verb == "RNTO":
			(root / renamed_from).replace(root / argument)
		elif verb == "DELE":
			if not (root / argument).is_file():
				sys.exit(21)

			(root / argument).unlink()
		else:
			sys.exit(21)
else:
	sys.exit(2)
"""

PASSWORD = "fake-secret-password"


def make_files(root: Path, files: dict[str, int]) -> None:
	for relative, size in files.items():
		path = root / relative
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(b"x" * size)


# videos: files on the VPS (path under videos/ -> size); server: files already on the fake FTP
# server. The delivery list is every video unless list_lines says otherwise. The script is
# called per camera folder, like its template; the tests use the folder "Cam".
def run_delivery(
	tmp_path: Path,
	videos: dict[str, int],
	server: dict[str, int] | None = None,
	args: tuple[str, ...] = ("Cam", "--run"),
	list_lines: list[str] | None = None,
	env: dict[str, str] | None = None,
):
	bin_dir = tmp_path / "bin"
	bin_dir.mkdir()
	curl = bin_dir / "curl"
	curl.write_text(FAKE_CURL)
	curl.chmod(curl.stat().st_mode | stat.S_IXUSR)

	ftp_root = tmp_path / "ftp"
	ftp_root.mkdir()
	make_files(tmp_path / "videos", videos)
	make_files(ftp_root, server or {})

	lines = list(videos) if list_lines is None else list_lines
	list_file = tmp_path / "list.txt"
	list_file.write_text("".join(f"{line}\n" for line in lines))

	environment = {
		**os.environ,
		"PATH": f"{bin_dir}:{os.environ['PATH']}",
		"VIDEO_ROOT": str(tmp_path / "videos"),
		"LOCK_FILE": str(tmp_path / "delivery.lock"),
		"SITEGROUND_CONFIG": str(tmp_path / "no-login-file.env"),
		"SITEGROUND_HOST": "ftp.example.test",
		"SITEGROUND_USER": "fake-user",
		"SITEGROUND_PASS": PASSWORD,
		"FAKE_LOGIN": f"fake-user:{PASSWORD}",
		"FAKE_FTP_ROOT": str(ftp_root),
		"FAKE_CURL_LOG": str(tmp_path / "curl.log"),
		**(env or {}),
	}
	result = subprocess.run(
		["bash", str(SCRIPT), *args, "--list-file", str(list_file)],
		env=environment,
		capture_output=True,
		text=True,
		timeout=60,
	)

	return result, ftp_root, tmp_path / "curl.log"


def ftp_files(ftp_root: Path) -> dict[str, int]:
	return {
		str(path.relative_to(ftp_root)): path.stat().st_size
		for path in ftp_root.rglob("*")
		if path.is_file()
	}


def curl_calls(log: Path) -> list[list[str]]:
	if not log.exists():
		return []

	return [json.loads(line) for line in log.read_text().splitlines()]


# Without --run nothing is sent, nothing is deleted, and the server is not even asked.
def test_a_dry_run_changes_nothing_and_makes_no_connection(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"

	result, ftp_root, log = run_delivery(tmp_path, {video: 12}, args=("Cam",))

	assert result.returncode == 0
	assert video in result.stdout
	assert ftp_files(ftp_root) == {}
	assert curl_calls(log) == []


# A half-sent video must never have its final name, and a missing folder is created.
def test_a_file_is_sent_under_a_temporary_name_and_then_renamed(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"

	result, ftp_root, log = run_delivery(tmp_path, {video: 12})

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {video: 12}

	calls = curl_calls(log)
	upload = next(call for call in calls if "--upload-file" in call)

	assert upload[-1] == "ftp://ftp.example.test/Cam/daily/.Cam_2026-11-03.mp4.part"
	assert "--ftp-create-dirs" in upload
	assert sum(1 for call in calls if f"RNTO {video}" in call) == 1
	assert "hochgeladen=1 übersprungen=0 fehlgeschlagen=0 gelöscht=0" in result.stdout


# The login goes to curl but never into the output.
def test_the_password_never_appears_in_the_output(tmp_path):
	result, _, _ = run_delivery(tmp_path, {"Cam/daily/Cam_2026-11-03.mp4": 12})

	assert PASSWORD not in result.stdout + result.stderr


def test_a_file_that_is_already_there_with_the_same_size_is_not_sent_again(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"

	result, ftp_root, log = run_delivery(tmp_path, {video: 12}, server={video: 12})

	assert result.returncode == 0
	assert not any("--upload-file" in call for call in curl_calls(log))
	assert "hochgeladen=0 übersprungen=1 fehlgeschlagen=0 gelöscht=0" in result.stdout
	assert ftp_files(ftp_root) == {video: 12}


def test_a_file_with_a_different_size_on_the_server_is_sent_again(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"

	result, ftp_root, _ = run_delivery(tmp_path, {video: 12}, server={video: 5})

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {video: 12}
	assert "hochgeladen=1" in result.stdout


# The newest two videos of a folder stay; other names in the folder are not touched.
def test_cleanup_keeps_the_newest_two_videos_and_leaves_other_files_alone(tmp_path):
	new = "Cam/weekly/Cam_2026-11-04.mp4"
	server = {f"Cam/weekly/Cam_2026-11-0{day}.mp4": 3 for day in (1, 2, 3)}
	server["Cam/weekly/.Cam_2026-11-00.mp4.part"] = 1
	server["Cam/weekly/notes.txt"] = 1

	result, ftp_root, _ = run_delivery(tmp_path, {new: 7}, server=server)

	assert result.returncode == 0
	assert sorted(ftp_files(ftp_root)) == [
		"Cam/weekly/.Cam_2026-11-00.mp4.part",
		"Cam/weekly/Cam_2026-11-03.mp4",
		"Cam/weekly/Cam_2026-11-04.mp4",
		"Cam/weekly/notes.txt",
	]
	assert "gelöscht=2" in result.stdout


# A failed upload keeps that folder's old videos, other folders are still cleaned, and the run
# ends with an error.
def test_a_failed_upload_blocks_the_cleanup_of_its_folder_only(tmp_path):
	daily = "Cam/daily/Cam_2026-11-04.mp4"
	weekly = "Cam/weekly/Cam_2026-11-04.mp4"
	server = {}

	for period in ("daily", "weekly"):
		for day in (1, 2, 3):
			server[f"Cam/{period}/Cam_2026-11-0{day}.mp4"] = 3

	result, ftp_root, _ = run_delivery(
		tmp_path,
		{daily: 5, weekly: 5},
		server=server,
		env={"FAKE_FAIL_UPLOAD": "Cam/daily/"},
	)

	files = ftp_files(ftp_root)

	assert result.returncode == 1
	assert all(f"Cam/daily/Cam_2026-11-0{day}.mp4" in files for day in (1, 2, 3))
	assert "Cam/weekly/Cam_2026-11-01.mp4" not in files
	assert weekly in files
	assert "fehlgeschlagen=1" in result.stdout


# An empty list means something upstream broke: never treat it as "delete everything".
def test_an_empty_list_sends_nothing_deletes_nothing_and_fails(tmp_path):
	server = {"Cam/daily/Cam_2026-11-01.mp4": 3}

	result, ftp_root, log = run_delivery(tmp_path, {}, server=server, list_lines=[])

	assert result.returncode != 0
	assert "leer" in result.stderr
	assert ftp_files(ftp_root) == server
	assert curl_calls(log) == []


# Only paths of the form <camera>/<period>/<name>.mp4 are ever sent.
def test_unsafe_list_entries_are_refused_and_counted_as_failed(tmp_path):
	good = "Cam/daily/Cam_2026-11-03.mp4"
	unsafe = [
		"../outside.mp4",
		"/abs/Cam/daily/x.mp4",
		"Cam/other/x.mp4",
		"Cam/daily/not-a-video.txt",
		"Cam/daily/../../x.mp4",
	]

	result, ftp_root, _ = run_delivery(tmp_path, {good: 4}, list_lines=[*unsafe, good])

	assert ftp_files(ftp_root) == {good: 4}
	assert result.returncode == 1
	assert "hochgeladen=1" in result.stdout
	# Entries of other folders are ignored; the three that start with "Cam/" are refused.
	assert "fehlgeschlagen=3" in result.stdout


# The script works on one camera folder per call: other cameras on the list are left alone.
def test_only_the_named_camera_is_sent(tmp_path):
	mine = "Cam/daily/Cam_2026-11-03.mp4"
	other = "Other/daily/Other_2026-11-03.mp4"

	result, ftp_root, _ = run_delivery(tmp_path, {mine: 4, other: 4})

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {mine: 4}


# A camera that is not on the list (for example one in ignored_cameras) sends nothing.
def test_a_camera_without_entries_on_the_list_fails_without_sending(tmp_path):
	result, ftp_root, log = run_delivery(
		tmp_path,
		{"Other/daily/Other_2026-11-03.mp4": 4},
	)

	assert result.returncode != 0
	assert "leer" in result.stderr
	assert ftp_files(ftp_root) == {}
	assert curl_calls(log) == []


# The camera name goes into paths and patterns, so only plain names and known options are accepted.
@pytest.mark.parametrize(
	"args",
	[("../Cam", "--run"), ("Cam/daily", "--run"), ("a b", "--run"), ("--bogus",)],
)
def test_an_unsafe_camera_name_or_unknown_option_is_refused(tmp_path, args):
	result, ftp_root, log = run_delivery(tmp_path, {"Cam/daily/Cam_2026-11-03.mp4": 4}, args=args)

	assert result.returncode == 2
	assert ftp_files(ftp_root) == {}
	assert curl_calls(log) == []


# Without a camera name the script goes through every camera on the list, one call per camera.
def test_without_a_camera_name_every_camera_on_the_list_is_sent(tmp_path):
	cam = "Cam/daily/Cam_2026-11-03.mp4"
	other = "Other/weekly/Other_2026-11-03.mp4"

	result, ftp_root, _ = run_delivery(tmp_path, {cam: 4, other: 5}, args=("--run",))

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {cam: 4, other: 5}


# One camera failing must not stop the others, but the whole run still ends with an error.
def test_a_failing_camera_does_not_stop_the_others_but_fails_the_run(tmp_path):
	cam = "Cam/daily/Cam_2026-11-03.mp4"
	other = "Other/weekly/Other_2026-11-03.mp4"

	result, ftp_root, _ = run_delivery(
		tmp_path,
		{cam: 4, other: 5},
		args=("--run",),
		env={"FAKE_FAIL_UPLOAD": "Cam/"},
	)

	assert result.returncode == 1
	assert ftp_files(ftp_root) == {other: 5}


def test_a_dry_run_without_a_camera_name_changes_nothing(tmp_path):
	videos = {"Cam/daily/Cam_2026-11-03.mp4": 4, "Other/weekly/Other_2026-11-03.mp4": 5}

	result, ftp_root, log = run_delivery(tmp_path, videos, args=())

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {}
	assert curl_calls(log) == []


# Two runs at once must not both write.
def test_a_second_run_is_refused_while_another_holds_the_lock(tmp_path):
	lock_path = tmp_path / "delivery.lock"

	with lock_path.open("w") as lock:
		fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

		result, ftp_root, _ = run_delivery(tmp_path, {"Cam/daily/Cam_2026-11-03.mp4": 4})

	assert result.returncode != 0
	assert "läuft bereits" in result.stderr
	assert ftp_files(ftp_root) == {}


# The login lives in a file that git ignores, so the script itself can be pushed. Every test above
# gives the login through the environment, which has priority; the tests below use the file.
NO_LOGIN_IN_ENV = {"SITEGROUND_HOST": "", "SITEGROUND_USER": "", "SITEGROUND_PASS": ""}


def login_text(password: str = PASSWORD, user: str = "fake-user") -> str:
	return "\n".join(
		[
			"# SiteGround FTP",
			"",
			"UNRELATED=ignored",
			"SITEGROUND_HOST=ftp.example.test",
			f"SITEGROUND_USER={user}",
			f"SITEGROUND_PASS={password}",
			"",
		]
	)


def write_login_file(tmp_path: Path, text: str) -> dict[str, str]:
	login_file = tmp_path / "siteground.env"
	login_file.write_text(text)

	return {"SITEGROUND_CONFIG": str(login_file)}


def test_the_login_is_read_from_the_config_file_when_the_environment_has_none(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"
	env = {**NO_LOGIN_IN_ENV, **write_login_file(tmp_path, login_text())}

	result, ftp_root, _ = run_delivery(tmp_path, {video: 12}, env=env)

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {video: 12}
	assert "SITEGROUND_HOST: ftp.example.test" in result.stdout
	assert PASSWORD not in result.stdout + result.stderr


# The environment has priority, as the script says: a test or a one-off run can override the file.
def test_the_environment_beats_the_config_file(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"
	wrong_file = write_login_file(tmp_path, login_text("wrong-password", "wrong-user"))

	result, ftp_root, _ = run_delivery(tmp_path, {video: 12}, env=wrong_file)

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {video: 12}


# The file fills in only what the environment leaves empty.
def test_the_config_file_fills_only_the_values_the_environment_leaves_empty(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"
	file_login = write_login_file(tmp_path, login_text("wrong-password"))
	env = {**file_login, "SITEGROUND_HOST": "", "SITEGROUND_USER": ""}

	result, ftp_root, _ = run_delivery(tmp_path, {video: 12}, env=env)

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {video: 12}


# Everything after the first "=" is the value: no quotes and no escaping, so "$", quotes, "#" and
# "=" inside a password need no care.
def test_the_password_in_the_config_file_is_taken_literally(tmp_path):
	video = "Cam/daily/Cam_2026-11-03.mp4"
	password = "p$HOME \"q\" 'r' a=b #c"
	env = {
		**NO_LOGIN_IN_ENV,
		**write_login_file(tmp_path, login_text(password)),
		"FAKE_LOGIN": f"fake-user:{password}",
	}

	result, ftp_root, _ = run_delivery(tmp_path, {video: 12}, env=env)

	assert result.returncode == 0
	assert ftp_files(ftp_root) == {video: 12}


# Without a camera the script calls itself once per camera; every call reads the file again.
def test_every_camera_run_reads_the_config_file(tmp_path):
	videos = {"Cam/daily/Cam_2026-11-03.mp4": 12, "Other/daily/Other_2026-11-03.mp4": 7}
	env = {**NO_LOGIN_IN_ENV, **write_login_file(tmp_path, login_text())}

	result, ftp_root, _ = run_delivery(tmp_path, videos, args=("--run",), env=env)

	assert result.returncode == 0
	assert ftp_files(ftp_root) == videos
	assert "Alle Kameras erfolgreich abgeschlossen." in result.stdout


def test_a_real_run_without_any_login_stops_before_a_connection(tmp_path):
	result, ftp_root, log = run_delivery(
		tmp_path, {"Cam/daily/Cam_2026-11-03.mp4": 12}, env=NO_LOGIN_IN_ENV
	)

	assert result.returncode == 2
	assert "müssen ausgefüllt sein" in result.stderr
	assert ftp_files(ftp_root) == {}
	assert curl_calls(log) == []
