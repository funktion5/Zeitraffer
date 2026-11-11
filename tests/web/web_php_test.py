import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess

import pytest


WEB_SRC = Path(__file__).resolve().parents[2] / "web" / "src"
WEB_PUBLIC = WEB_SRC.parent / "public"
# The PHP derives the project folder from its own location; tests swap that call for a temp dir.
PROJECT_ROOT_CALL = "dirname(__DIR__, 2)"
SUDO_PATH = "/usr/bin/sudo"


# The text of script files of web/public, joined: what a page's scripts do together.
def read_scripts(*names: str) -> str:
	return "\n".join((WEB_PUBLIC / name).read_text(encoding="utf-8") for name in names)


# The helpers hardcode absolute paths and /usr/bin/sudo. Instead of touching the PHP source, run a
# copy in tmp_path with those literals swapped; the assert guards against silent no-op swaps.
def run_php(tmp_path: Path, source: str, replacements: dict, code: str, env=None):
	src_dir = tmp_path / "php-src"
	if not src_dir.exists():
		shutil.copytree(WEB_SRC, src_dir, ignore=shutil.ignore_patterns("components"))
	target = src_dir / source
	text = target.read_text()
	for old, new in replacements.items():
		assert old in text, f"{old!r} not found in {source}"
		text = text.replace(old, new)
	target.write_text(text)

	driver = tmp_path / "driver.php"
	driver.write_text(f"<?php\nrequire_once {json.dumps(str(target))};\n{code}\n")
	result = subprocess.run(
		["php", "-d", "display_errors=1", "-d", "error_reporting=-1", str(driver)],
		capture_output=True,
		text=True,
		env={**os.environ, **(env or {})},
		check=False,
	)
	assert result.returncode == 0, result.stdout + result.stderr
	return json.loads(result.stdout)


def library(tmp_path: Path, code: str, **roots):
	replacements = {}
	for old, new in roots.items():
		replacements[old] = str(new)
	return run_php(tmp_path, "video-library.php", replacements, code)


def videos_library(tmp_path: Path, code: str):
	videos = tmp_path / "videos"
	videos.mkdir(exist_ok=True)
	return run_php(
		tmp_path,
		"video-library.php",
		{PROJECT_ROOT_CALL: json.dumps(str(tmp_path))},
		code,
	)


def make_videos(tmp_path: Path, camera: str, job: str, names: list) -> Path:
	job_dir = tmp_path / "videos" / camera / "manual-runs" / job
	job_dir.mkdir(parents=True, exist_ok=True)
	for name in names:
		(job_dir / name).write_bytes(b"x")
	return job_dir


def test_translate_job_label_maps_known_jobs_and_passes_unknown(tmp_path):
	result = library(
		tmp_path,
		'echo json_encode(array_map("translateJobLabel",'
		' ["daily","weekly","monthly","yearly","x"]));',
	)

	assert result == ["Täglich", "Wöchentlich", "Monatlich", "Jährlich", "x"]


# Metadata is only trusted for exactly the documented filename shapes.
@pytest.mark.parametrize(
	("filename", "expected"),
	[
		("cam_2026-03-05.mp4", ["2026-03-05", None, None]),
		("cam_2026-03-05_45min.mp4", ["2026-03-05", 45, None]),
		("cam_2026-03-05_1830-60min.mp4", ["2026-03-05", None, "18:30 ±60 Min."]),
		("cam_2026-03-05_sunset-30min.mp4", ["2026-03-05", None, "Sonnenuntergang ±30 Min."]),
		("cam_2026-02-30.mp4", [None, None, None]),
		("cam_2026-03-05_2561-60min.mp4", [None, None, None]),
		("cam_2026-03-05.mov", [None, None, None]),
		("other_2026-03-05.mp4", [None, None, None]),
	],
)
def test_extract_manual_video_metadata(tmp_path, filename, expected):
	result = library(
		tmp_path,
		f'$m = extractManualVideoMetadata("cam", {json.dumps(filename)});'
		'echo json_encode([$m["date"], $m["bufferMinutes"], $m["window"]]);',
	)

	assert result == expected


# A camera name with regex metacharacters must be matched literally, not as a pattern.
def test_extract_manual_video_metadata_quotes_camera_name(tmp_path):
	result = library(
		tmp_path,
		"echo json_encode(["
		'extractManualVideoMetadata("a.c", "abc_2026-03-05.mp4")["date"],'
		'extractManualVideoMetadata("a.c", "a.c_2026-03-05.mp4")["date"]]);',
	)

	assert result == [None, "2026-03-05"]


def test_format_helpers(tmp_path):
	result = library(
		tmp_path,
		"echo json_encode([formatBytes(512), formatBytes(1536), formatBytes(5 * 1024 ** 3),"
		' formatGermanDate("2026-03-05"), formatGermanDate("garbage"),'
		' isValidIsoDate("2024-02-29"), isValidIsoDate("2026-02-29"),'
		' isValidIsoDate("2026-3-5")]);',
	)

	assert result == ["512.0 B", "1.5 KB", "5.0 GB", "05.03.2026", "garbage", True, False, False]


def test_find_manual_videos_lists_only_regular_mp4_files(tmp_path):
	job_dir = make_videos(tmp_path, "cam", "daily", ["cam_2026-03-05.mp4", "notes.txt", "a.MP4"])
	(tmp_path / "real.mp4").write_bytes(b"x")
	(job_dir / "link.mp4").symlink_to(tmp_path / "real.mp4")
	(job_dir / "subdir.mp4").mkdir()

	result = videos_library(tmp_path, 'echo json_encode(findVideos("cam", "manual-runs"));')

	assert sorted(v["filename"] for v in result["daily"]) == ["a.MP4", "cam_2026-03-05.mp4"]


# Newest first by date; files without parseable metadata sort by raw filename and keep working.
def test_find_manual_videos_sorts_newest_first_and_exposes_metadata(tmp_path):
	make_videos(
		tmp_path,
		"cam",
		"monthly",
		[
			"cam_2026-01-31.mp4",
			"cam_2026-03-31_1200-90min.mp4",
			"cam_2026-02-28.mp4",
		],
	)

	result = videos_library(tmp_path, 'echo json_encode(findVideos("cam", "manual-runs"));')

	monthly = result["monthly"]
	assert [v["date"] for v in monthly] == ["2026-03-31", "2026-02-28", "2026-01-31"]
	assert monthly[0]["window"] == "12:00 ±90 Min."
	assert monthly[0]["url"] == "/videos/cam/manual-runs/monthly/cam_2026-03-31_1200-90min.mp4"


# Filenames end up in URLs, so they must be percent-encoded.
def test_find_manual_videos_url_encodes_names(tmp_path):
	make_videos(tmp_path, "cam", "daily", ["my video#1.mp4"])

	result = videos_library(tmp_path, 'echo json_encode(findVideos("cam", "manual-runs"));')

	assert result["daily"][0]["url"] == "/videos/cam/manual-runs/daily/my%20video%231.mp4"
	assert result["daily"][0]["date"] is None


# Only the four known job directories are scanned; anything else is ignored.
def test_find_manual_videos_ignores_unknown_job_directories(tmp_path):
	make_videos(tmp_path, "cam", "hourly", ["cam_2026-03-05.mp4"])
	make_videos(tmp_path, "cam", "yearly", ["cam_2026-12-31.mp4"])

	result = videos_library(tmp_path, 'echo json_encode(findVideos("cam", "manual-runs"));')

	assert list(result) == ["yearly"]


def test_find_manual_videos_without_manual_runs_returns_empty_list(tmp_path):
	result = videos_library(tmp_path, 'echo json_encode(findVideos("missing", "manual-runs"));')

	assert result == []


# Encodes write to `.<name>.tmp.mp4` first; a half-written file must not be offered for
# playback or deletion in the UI.
def test_find_manual_videos_hides_in_progress_tmp_files(tmp_path):
	make_videos(tmp_path, "cam", "daily", ["cam_2026-03-05.mp4", ".cam_2026-03-06.tmp.mp4"])

	result = videos_library(tmp_path, 'echo json_encode(findVideos("cam", "manual-runs"));')

	assert [v["filename"] for v in result["daily"]] == ["cam_2026-03-05.mp4"]


# Automatic videos live in videos/<camera>/<job>/; manual-runs and highlights are not jobs.
def test_find_videos_reads_automatic_videos_from_the_camera_folder(tmp_path):
	make_videos(tmp_path, "cam", "daily", ["cam_2026-10-22_60min.mp4"])
	weekly = tmp_path / "videos" / "cam" / "weekly"
	weekly.mkdir(parents=True)
	(weekly / "cam_2026-10-25.mp4").write_bytes(b"x")
	(tmp_path / "videos" / "cam" / "highlights" / "2026-10-25").mkdir(parents=True)

	result = videos_library(tmp_path, 'echo json_encode(findVideos("cam", ""));')

	assert list(result) == ["weekly"]
	assert result["weekly"][0]["date"] == "2026-10-25"
	assert result["weekly"][0]["url"] == "/videos/cam/weekly/cam_2026-10-25.mp4"


# Config: only string camera names count; broken or missing config must never raise.
@pytest.mark.parametrize(
	("config", "expected"),
	[
		('{"ignored_cameras": ["A", 3, null, "B"]}', ["A", "B"]),
		('{"ignored_cameras": "A"}', []),
		("{not json", []),
		(None, []),
	],
)
def test_get_ignored_cameras(tmp_path, config, expected):
	config_path = tmp_path / "config" / "config.json"
	config_path.parent.mkdir()
	if config is not None:
		config_path.write_text(config)

	result = library(
		tmp_path,
		"echo json_encode(getIgnoredCameras());",
		**{PROJECT_ROOT_CALL: json.dumps(str(tmp_path))},
	)

	assert result == expected


# privacy.blur_cameras: only string names count; a broken or missing config must never raise.
@pytest.mark.parametrize(
	("config", "expected"),
	[
		('{"privacy": {"blur_cameras": ["A", 3, null, "B"]}}', ["A", "B"]),
		('{"privacy": {"blur_cameras": "A"}}', []),
		('{"privacy": "A"}', []),
		('{"ignored_cameras": ["A"]}', []),
		("{not json", []),
		(None, []),
	],
)
def test_get_blur_cameras(tmp_path, config, expected):
	config_path = tmp_path / "config" / "config.json"
	config_path.parent.mkdir()
	if config is not None:
		config_path.write_text(config)

	result = library(
		tmp_path,
		"echo json_encode(getBlurCameras());",
		**{PROJECT_ROOT_CALL: json.dumps(str(tmp_path))},
	)

	assert result == expected


# The camera names come from state/web-jobs/cameras.json (python3 -m src.camera_list), because the
# web server user has no ssh key and the storage is not mounted on this host.
def available_cameras(tmp_path: Path, list_content: str | None):
	list_path = tmp_path / "state" / "web-jobs" / "cameras.json"
	list_path.parent.mkdir(parents=True)

	if list_content is not None:
		list_path.write_text(list_content)

	return library(
		tmp_path,
		"echo json_encode(findAvailableCameras());",
		**{PROJECT_ROOT_CALL: json.dumps(str(tmp_path))},
	)


def test_find_available_cameras_reads_the_list_filters_and_sorts(tmp_path):
	# Ignored cameras are dropped here too, so a camera added to ignored_cameras disappears
	# without waiting for the next nightly rewrite of the list.
	config_path = tmp_path / "config" / "config.json"
	config_path.parent.mkdir()
	config_path.write_text('{"ignored_cameras": ["Ignored"]}')

	result = available_cameras(tmp_path, '["cam10", "cam2", "Alpha", "Ignored"]')

	assert result == ["Alpha", "cam2", "cam10"]


@pytest.mark.parametrize(
	"list_content",
	[
		None,
		"{not json",
		'"Alpha"',
		'{"first": 1}',
	],
)
def test_find_available_cameras_gives_nothing_without_a_usable_list(tmp_path, list_content):
	assert available_cameras(tmp_path, list_content) == []


# The names end up in file paths (videos/<camera>/...), so only the plain names the Python side
# also accepts get through, even if the file were edited.
def test_find_available_cameras_drops_unsafe_names(tmp_path):
	unsafe = ["../etc", ".hidden", "a/b", "", "-dash", "with space", "Alpha\n", 7, None, ["Nested"]]
	names = ["Alpha", *unsafe, "Bravo_1.x-2"]

	result = available_cameras(tmp_path, json.dumps(names))

	assert result == ["Alpha", "Bravo_1.x-2"]


def run_privileged(tmp_path: Path, argv: list):
	return run_php(
		tmp_path,
		"process-runner.php",
		{},
		f"echo json_encode(runPrivilegedCommand({json.dumps(argv)}));",
	)


def test_run_privileged_command_captures_stdout_trimmed(tmp_path):
	result = run_privileged(tmp_path, ["/bin/echo", "hello"])

	assert result == {"exitCode": 0, "stdout": "hello", "stderr": ""}


def test_run_privileged_command_captures_stderr_and_exit_code(tmp_path):
	result = run_privileged(tmp_path, ["/bin/sh", "-c", "echo oops >&2; exit 3"])

	assert result == {"exitCode": 3, "stdout": "", "stderr": "oops"}


# bypass_shell + argument array: shell metacharacters must reach the program as literal text.
def test_run_privileged_command_does_not_interpret_shell_metacharacters(tmp_path):
	result = run_privileged(tmp_path, ["/bin/echo", "a; echo injected $(id)"])

	assert result["stdout"] == "a; echo injected $(id)"


# A fake "sudo" records its arguments, so command construction is testable without real sudo.
def fake_sudo(tmp_path: Path) -> Path:
	script = tmp_path / "fake-sudo"
	script.write_text(
		'#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_SUDO_ARGS"\n'
		'echo "$FAKE_SUDO_OUT"\necho "$FAKE_SUDO_ERR" >&2\nexit "$FAKE_SUDO_EXIT"\n'
	)
	script.chmod(0o755)
	return script


# Render web/public/<page> from a copy of web/ in tmp_path, so projectRoot() is tmp_path. swaps maps
# a file in web/ to (literal, replacement), applied once on the first copy; the assert guards
# against silent no-op swaps. The session holds token and keeps everything else between calls,
# so a POST and the GET after it share it. Returns stdout and the arguments fake sudo got.
def render_page(
	tmp_path: Path,
	page: str,
	swaps: dict,
	get,
	post,
	sudo_exit: int,
	token: str,
	sudo_out: str = "",
):
	site = tmp_path / "web"
	if not site.exists():
		shutil.copytree(WEB_SRC.parent, site)
		for name, (old, new) in swaps.items():
			path = site / name
			text = path.read_text()
			assert old in text, f"{old!r} not found in {name}"
			path.write_text(text.replace(old, new))
	(tmp_path / "videos").mkdir(exist_ok=True)
	sessions = tmp_path / "sessions"
	sessions.mkdir(exist_ok=True)
	args_file = tmp_path / "sudo-args.txt"
	args_file.unlink(missing_ok=True)

	driver = tmp_path / "page-driver.php"
	driver.write_text(
		"<?php\n"
		'session_id("pagetest");\n'
		"session_start();\n"
		f"$_SESSION['csrf_token'] = {json.dumps(token)};\n"
		"session_write_close();\n"
		f"$_SERVER['REQUEST_METHOD'] = {json.dumps('POST' if post is not None else 'GET')};\n"
		f"$_GET = json_decode({json.dumps(json.dumps(get))}, true);\n"
		f"$_POST = json_decode({json.dumps(json.dumps(post or {}))}, true);\n"
		f"require {json.dumps(str(site / 'public' / page))};\n"
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
			"FAKE_SUDO_OUT": sudo_out,
			"FAKE_SUDO_ERR": "denied",
		},
		check=False,
	)
	assert result.returncode == 0, result.stdout + result.stderr
	for problem in ("Warning:", "Notice:", "Deprecated:", "Fatal error"):
		assert problem not in result.stdout, result.stdout
	args = args_file.read_text().splitlines() if args_file.exists() else []
	return result.stdout, args


def run_wrapper(tmp_path: Path, source: str, call: str, exit_code: int, out: str = ""):
	args_file = tmp_path / "sudo-args.txt"
	result = run_php(
		tmp_path,
		source,
		{SUDO_PATH: str(fake_sudo(tmp_path))},
		f"echo json_encode({call});",
		env={
			"FAKE_SUDO_ARGS": str(args_file),
			"FAKE_SUDO_EXIT": str(exit_code),
			"FAKE_SUDO_OUT": out,
			"FAKE_SUDO_ERR": "denied",
		},
	)
	args = args_file.read_text().splitlines() if args_file.exists() else []
	return result, args


def test_start_video_job_passes_daily_buffer_argument(tmp_path):
	result, args = run_wrapper(
		tmp_path,
		"job-runner.php",
		'startVideoJob("daily", "2026-03-05", "cam", 45)',
		0,
	)

	assert result["started"] is True
	assert len(result["jobId"]) == 32
	# The run-as user is the owner of the project folder; for the test copy that is the test user.
	assert args[:3] == ["-n", "-u", pwd.getpwuid(os.getuid()).pw_name]
	assert args[3:] == [
		"/usr/local/sbin/timelapse-web-trigger",
		result["jobId"],
		"daily",
		"2026-03-05",
		"cam",
		"45",
	]


# Monthly/Yearly send the window as two trailing arguments and no buffer.
def test_start_video_job_passes_interval_window_arguments(tmp_path):
	result, args = run_wrapper(
		tmp_path,
		"job-runner.php",
		'startVideoJob("monthly", "2026-03-31", "cam", null, "sunset", 30)',
		0,
		out="accepted",
	)

	assert result["message"] == "accepted"
	assert args[-5:] == ["monthly", "2026-03-31", "cam", "sunset", "30"]


# Exit 75 is the wrapper's "lock already held" code and gets its own message.
def test_start_video_job_reports_busy_on_exit_75(tmp_path):
	result, _ = run_wrapper(
		tmp_path, "job-runner.php", 'startVideoJob("daily", "2026-03-05", "cam", 45)', 75
	)

	assert result == {
		"started": False,
		"jobId": None,
		"message": "Es läuft bereits ein anderer Zeitraffer-Auftrag.",
	}


# Wrapper stderr is logged server-side only, never returned to the browser.
def test_start_video_job_hides_wrapper_error_details(tmp_path):
	result, _ = run_wrapper(
		tmp_path, "job-runner.php", 'startVideoJob("daily", "2026-03-05", "cam", 45)', 1
	)

	assert result["started"] is False
	assert "denied" not in result["message"]


def test_delete_manual_video_success_passes_arguments(tmp_path):
	result, args = run_wrapper(
		tmp_path,
		"video-delete.php",
		'deleteManualVideo("cam", "daily", "cam_2026-03-05.mp4")',
		0,
	)

	assert result == {"deleted": True, "message": "Video erfolgreich gelöscht."}
	assert args[3:] == [
		"/usr/local/sbin/timelapse-web-delete",
		"cam",
		"daily",
		"cam_2026-03-05.mp4",
	]


def test_delete_manual_video_failure_hides_details(tmp_path):
	result, _ = run_wrapper(
		tmp_path, "video-delete.php", 'deleteManualVideo("cam", "daily", "x.mp4")', 1
	)

	assert result == {"deleted": False, "message": "Das Video konnte nicht gelöscht werden."}


# A root-owned (or unreadable) project folder must never turn into "sudo -u root".
def test_project_run_user_refuses_root_owned_folder(tmp_path):
	result = run_php(
		tmp_path,
		"process-runner.php",
		{PROJECT_ROOT_CALL: json.dumps("/")},
		"echo json_encode(projectRunUser());",
	)

	assert result is None


def test_start_video_job_refuses_without_run_user(tmp_path):
	# Point the shared helper at a root-owned folder, then start a job with the same copy.
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")
	result, args = run_wrapper(
		tmp_path,
		"job-runner.php",
		'startVideoJob("daily", "2026-03-05", "cam", 45)',
		0,
	)

	assert result["started"] is False
	assert args == []


def test_delete_manual_video_refuses_without_run_user(tmp_path):
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")
	result, args = run_wrapper(
		tmp_path,
		"video-delete.php",
		'deleteManualVideo("cam", "daily", "cam_2026-03-05.mp4")',
		0,
	)

	assert result["deleted"] is False
	assert args == []


# The rebuild trigger gets the camera and the jobs, nothing else: the browser sends no more.
def test_start_rebuild_job_calls_the_trigger_with_camera_and_jobs(tmp_path):
	result, args = run_wrapper(
		tmp_path,
		"rebuild-runner.php",
		'startRebuildJob("cam", ["daily", "monthly"])',
		0,
	)

	assert result["started"] is True
	assert len(result["jobId"]) == 32
	assert args[:3] == ["-n", "-u", pwd.getpwuid(os.getuid()).pw_name]
	assert args[3:] == [
		"/usr/local/sbin/timelapse-web-rebuild",
		result["jobId"],
		"cam",
		"daily",
		"monthly",
	]


def test_start_rebuild_job_reports_a_busy_lock(tmp_path):
	result, _ = run_wrapper(tmp_path, "rebuild-runner.php", 'startRebuildJob("cam", ["daily"])', 75)

	assert result == {
		"started": False,
		"jobId": None,
		"message": "Es läuft bereits ein anderer Zeitraffer-Auftrag.",
	}


# Wrapper stderr is logged server-side only, never returned to the browser.
def test_start_rebuild_job_hides_wrapper_error_details(tmp_path):
	result, _ = run_wrapper(tmp_path, "rebuild-runner.php", 'startRebuildJob("cam", ["daily"])', 1)

	assert result["started"] is False
	assert "denied" not in result["message"]


def test_start_rebuild_job_refuses_without_run_user(tmp_path):
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")
	result, args = run_wrapper(
		tmp_path, "rebuild-runner.php", 'startRebuildJob("cam", ["daily"])', 0
	)

	assert result["started"] is False
	assert args == []


# The publish trigger gets the camera and nothing else: no file names, no host, no login.
def test_start_publish_job_calls_the_trigger_with_the_camera(tmp_path):
	result, args = run_wrapper(tmp_path, "publish-runner.php", 'startPublishJob("cam")', 0)

	assert result["started"] is True
	assert len(result["jobId"]) == 32
	assert args[:3] == ["-n", "-u", pwd.getpwuid(os.getuid()).pw_name]
	assert args[3:] == ["/usr/local/sbin/timelapse-web-publish", result["jobId"], "cam"]


def test_start_publish_job_reports_a_busy_lock(tmp_path):
	result, _ = run_wrapper(tmp_path, "publish-runner.php", 'startPublishJob("cam")', 75)

	assert result == {
		"started": False,
		"jobId": None,
		"message": "Es läuft bereits ein anderer Zeitraffer-Auftrag.",
	}


# Wrapper stderr is logged server-side only, never returned to the browser.
def test_start_publish_job_hides_wrapper_error_details(tmp_path):
	result, _ = run_wrapper(tmp_path, "publish-runner.php", 'startPublishJob("cam")', 1)

	assert result["started"] is False
	assert "denied" not in result["message"]


def test_start_publish_job_refuses_without_run_user(tmp_path):
	run_php(tmp_path, "process-runner.php", {PROJECT_ROOT_CALL: json.dumps("/")}, "echo 0;")
	result, args = run_wrapper(tmp_path, "publish-runner.php", 'startPublishJob("cam")', 0)

	assert result["started"] is False
	assert args == []


# The upload preview on the camera page: the newest video per period by file name, with the rules
# of scripts/list-deliverable-videos.py (regular, non-empty, non-hidden .mp4 directly in the period
# folder, no symlinks), periods in the fixed order, only those that have one.
def test_newest_automatic_videos_returns_the_newest_file_per_period(tmp_path):
	camera = tmp_path / "videos" / "cam"
	other = tmp_path / "elsewhere"
	other.mkdir()
	(other / "cam_2099-01-01.mp4").write_bytes(b"x")

	for period, names in {
		"daily": ["cam_2026-11-07.mp4", "cam_2026-11-08.mp4"],
		"monthly": ["cam_2026-10-01.mp4"],
	}.items():
		(camera / period).mkdir(parents=True)
		for name in names:
			(camera / period / name).write_bytes(b"x")

	# Things that must never be picked, each sorted AFTER the valid file so a wrong rule shows.
	monthly = camera / "monthly"
	(monthly / "cam_2026-10-09.mp4").write_bytes(b"")
	(monthly / ".cam_2026-10-10.tmp.mp4").write_bytes(b"x")
	(monthly / "cam_2026-10-11.MP4").write_bytes(b"x")
	(monthly / "cam_2026-10-12.mp4").mkdir()
	(monthly / "cam_2026-10-13.mp4").symlink_to(other / "cam_2099-01-01.mp4")
	(monthly / "notes.txt").write_text("x")
	# A period folder that is a link, and a test render folder, are not looked at.
	(camera / "weekly").symlink_to(other, target_is_directory=True)
	(camera / "manual-runs" / "yearly").mkdir(parents=True)
	(camera / "manual-runs" / "yearly" / "cam_2026-11-08.mp4").write_bytes(b"x")

	result = videos_library(tmp_path, 'echo json_encode(newestAutomaticVideos("cam"));')

	assert result == {"daily": "cam_2026-11-08.mp4", "monthly": "cam_2026-10-01.mp4"}
	assert list(result) == ["daily", "monthly"]


def test_newest_automatic_videos_is_empty_without_a_camera_folder(tmp_path):
	result = videos_library(tmp_path, 'echo json_encode(newestAutomaticVideos("cam"));')

	assert result == []


# The worker's result lines for the browser: at most 8, no empty ones, nothing for a missing file
# or an ID that is not 32 hex characters (no path is built from it).
def test_read_job_results_returns_the_lines_or_nothing(tmp_path):
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	two_lines = "a" * 32
	twelve_lines = "b" * 32
	(status_root / f"{two_lines}.result").write_text(
		"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen\n\n"
		"Jährlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen\n"
	)
	(status_root / f"{twelve_lines}.result").write_text(
		"".join(f"Zeile {number}\n" for number in range(12))
	)
	root = json.dumps(str(status_root))

	result = run_php(
		tmp_path,
		"job-state.php",
		{},
		"echo json_encode(["
		f"readJobResults({root}, {json.dumps(two_lines)}), "
		f"count(readJobResults({root}, {json.dumps(twelve_lines)})), "
		f"readJobResults({root}, {json.dumps('c' * 32)}), "
		f'readJobResults({root}, "../x"),'
		"]);",
	)

	assert result == [
		[
			"Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen",
			"Jährlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen",
		],
		8,
		[],
		[],
	]
