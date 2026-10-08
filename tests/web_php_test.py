import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


WEB_SRC = Path(__file__).resolve().parent.parent / "web" / "src"
LIBRARY_ROOT = "/home/zruser/timelapse"
SUDO_PATH = "/usr/bin/sudo"


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
		{f"{LIBRARY_ROOT}/videos/": f"{videos}/"},
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

	result = videos_library(tmp_path, 'echo json_encode(findManualVideos("cam"));')

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

	result = videos_library(tmp_path, 'echo json_encode(findManualVideos("cam"));')

	monthly = result["monthly"]
	assert [v["date"] for v in monthly] == ["2026-03-31", "2026-02-28", "2026-01-31"]
	assert monthly[0]["window"] == "12:00 ±90 Min."
	assert monthly[0]["url"] == "/videos/cam/manual-runs/monthly/cam_2026-03-31_1200-90min.mp4"


# Filenames end up in URLs, so they must be percent-encoded.
def test_find_manual_videos_url_encodes_names(tmp_path):
	make_videos(tmp_path, "cam", "daily", ["my video#1.mp4"])

	result = videos_library(tmp_path, 'echo json_encode(findManualVideos("cam"));')

	assert result["daily"][0]["url"] == "/videos/cam/manual-runs/daily/my%20video%231.mp4"
	assert result["daily"][0]["date"] is None


# Only the four known job directories are scanned; anything else is ignored.
def test_find_manual_videos_ignores_unknown_job_directories(tmp_path):
	make_videos(tmp_path, "cam", "hourly", ["cam_2026-03-05.mp4"])
	make_videos(tmp_path, "cam", "yearly", ["cam_2026-12-31.mp4"])

	result = videos_library(tmp_path, 'echo json_encode(findManualVideos("cam"));')

	assert list(result) == ["yearly"]


def test_find_manual_videos_without_manual_runs_returns_empty_list(tmp_path):
	result = videos_library(tmp_path, 'echo json_encode(findManualVideos("missing"));')

	assert result == []


# Encodes write to `.<name>.tmp.mp4` first; a half-written file must not be offered for
# playback or deletion in the UI.
def test_find_manual_videos_hides_in_progress_tmp_files(tmp_path):
	make_videos(tmp_path, "cam", "daily", ["cam_2026-03-05.mp4", ".cam_2026-03-06.tmp.mp4"])

	result = videos_library(tmp_path, 'echo json_encode(findManualVideos("cam"));')

	assert [v["filename"] for v in result["daily"]] == ["cam_2026-03-05.mp4"]


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
	config_path = tmp_path / "config.json"
	if config is not None:
		config_path.write_text(config)

	result = library(
		tmp_path,
		"echo json_encode(getIgnoredCameras());",
		**{f"{LIBRARY_ROOT}/config/config.json": config_path},
	)

	assert result == expected


def test_find_available_cameras_filters_and_sorts(tmp_path):
	root = tmp_path / "cameras"
	for name in ["cam10", "cam2", "Alpha", ".hidden", "Ignored"]:
		(root / name).mkdir(parents=True)
	(root / "afile").write_text("x")
	config_path = tmp_path / "config.json"
	config_path.write_text('{"ignored_cameras": ["Ignored"]}')

	result = library(
		tmp_path,
		"echo json_encode(findAvailableCameras());",
		**{"/mnt/cameras": root, f"{LIBRARY_ROOT}/config/config.json": config_path},
	)

	assert result == ["Alpha", "cam2", "cam10"]


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
	assert args[:3] == ["-n", "-u", "zruser"]
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
