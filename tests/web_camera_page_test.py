import json
import os
import shutil
import subprocess
from pathlib import Path

from web_php_test import SUDO_PATH, fake_sudo

WEB = Path(__file__).resolve().parent.parent / "web"
TOKEN = "test-token"
CAMERA = "SLSV"


# Render web/public/camera.php from a copy in tmp_path: projectRoot() is tmp_path, the camera
# root is tmp_path/cameras and sudo is faked. The session keeps everything except the token
# between calls, so a POST and the GET after it share it. Returns stdout and the sudo arguments.
def render(tmp_path: Path, get=None, post=None, sudo_exit: int = 0):
	site = tmp_path / "web"
	if not site.exists():
		shutil.copytree(WEB, site)
		swaps = {
			"src/video-delete.php": (SUDO_PATH, str(fake_sudo(tmp_path))),
			"src/job-runner.php": (SUDO_PATH, str(fake_sudo(tmp_path))),
			"src/video-library.php": ('"/mnt/cameras"', json.dumps(str(tmp_path / "cameras"))),
		}
		for name, (old, new) in swaps.items():
			path = site / name
			text = path.read_text()
			assert old in text, f"{old!r} not found in {name}"
			path.write_text(text.replace(old, new))
	(tmp_path / "cameras" / CAMERA).mkdir(parents=True, exist_ok=True)
	(tmp_path / "videos").mkdir(exist_ok=True)
	sessions = tmp_path / "sessions"
	sessions.mkdir(exist_ok=True)
	args_file = tmp_path / "sudo-args.txt"
	args_file.unlink(missing_ok=True)

	driver = tmp_path / "page-driver.php"
	driver.write_text(
		"<?php\n"
		'session_id("cameratest");\n'
		"session_start();\n"
		f"$_SESSION['csrf_token'] = {json.dumps(TOKEN)};\n"
		"session_write_close();\n"
		f"$_SERVER['REQUEST_METHOD'] = {json.dumps('POST' if post is not None else 'GET')};\n"
		f"$_GET = json_decode({json.dumps(json.dumps(get or {'camera': CAMERA}))}, true);\n"
		f"$_POST = json_decode({json.dumps(json.dumps(post or {}))}, true);\n"
		f"require {json.dumps(str(site / 'public' / 'camera.php'))};\n"
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


# folder "" is the automatic videos/<camera>/<job>/, "manual-runs" the historical ones.
def make_video(tmp_path: Path, folder: str, job: str, name: str) -> None:
	job_dir = tmp_path / "videos" / CAMERA / folder / job
	job_dir.mkdir(parents=True, exist_ok=True)
	(job_dir / name).write_bytes(b"x")


def test_both_lists_are_shown_and_say_when_empty(tmp_path):
	out, _ = render(tmp_path)

	assert "<h2>Automatische Videos</h2>" in out
	assert "<h2>Manuelle Videos</h2>" in out
	assert "Keine automatischen Videos gefunden." in out
	assert "Keine manuellen Videos gefunden." in out


def test_automatic_videos_are_listed_playable_and_read_only(tmp_path):
	make_video(tmp_path, "", "daily", "SLSV_2026-10-25.mp4")
	make_video(tmp_path, "manual-runs", "daily", "SLSV_2026-10-22_60min.mp4")

	out, _ = render(tmp_path)

	assert "25.10.2026" in out
	assert "source=auto" in out
	# Only the manual entry carries a delete form.
	assert out.count('class="video-library-delete-form"') == 1

	out, _ = render(
		tmp_path,
		get={"camera": CAMERA, "job": "daily", "video": "SLSV_2026-10-25.mp4", "source": "auto"},
	)

	assert 'src="/videos/SLSV/daily/SLSV_2026-10-25.mp4"' in out
	assert 'class="video-delete-form"' not in out
	assert out.count('class="video-library-delete-form"') == 1


# The same name can exist in both lists (default-window Monthly); the chosen list decides.
def test_same_filename_plays_from_the_chosen_list(tmp_path):
	make_video(tmp_path, "", "monthly", "SLSV_2026-10-25.mp4")
	make_video(tmp_path, "manual-runs", "monthly", "SLSV_2026-10-25.mp4")

	out, _ = render(
		tmp_path, get={"camera": CAMERA, "job": "monthly", "video": "SLSV_2026-10-25.mp4"}
	)

	assert 'src="/videos/SLSV/manual-runs/monthly/SLSV_2026-10-25.mp4"' in out
	assert 'class="video-delete-form"' in out

	out, _ = render(
		tmp_path,
		get={"camera": CAMERA, "job": "monthly", "video": "SLSV_2026-10-25.mp4", "source": "auto"},
	)

	assert 'src="/videos/SLSV/monthly/SLSV_2026-10-25.mp4"' in out
	assert 'class="video-delete-form"' not in out


# ?job[]=x used to throw a TypeError (500).
def test_array_parameters_do_not_break_the_page(tmp_path):
	out, _ = render(
		tmp_path, get={"camera": CAMERA, "job": ["x"], "video": ["y"], "source": ["auto"]}
	)

	assert "Bitte ein Video aus der Liste auswählen." in out


def delete_post(job: str, video: str, token: str = TOKEN) -> dict:
	return {
		"action": "delete-video",
		"csrf_token": token,
		"camera": CAMERA,
		"job": job,
		"video": video,
		"response": "json",
	}


def test_json_delete_answers_with_the_outcome(tmp_path):
	make_video(tmp_path, "manual-runs", "daily", "SLSV_2026-10-22_60min.mp4")

	out, args = render(tmp_path, post=delete_post("daily", "SLSV_2026-10-22_60min.mp4"))

	assert json.loads(out) == {"deleted": True, "message": "Video erfolgreich gelöscht."}
	assert args[3:] == [
		"/usr/local/sbin/timelapse-web-delete",
		CAMERA,
		"daily",
		"SLSV_2026-10-22_60min.mp4",
	]


# Automatic videos are not in the manual list, so a crafted POST never reaches the wrapper.
def test_json_delete_refuses_automatic_videos(tmp_path):
	make_video(tmp_path, "", "daily", "SLSV_2026-10-25.mp4")

	out, args = render(tmp_path, post=delete_post("daily", "SLSV_2026-10-25.mp4"))

	assert json.loads(out) == {
		"deleted": False,
		"message": "Das ausgewählte Video wurde nicht gefunden.",
	}
	assert args == []


def test_json_delete_with_bad_token_is_refused(tmp_path):
	make_video(tmp_path, "manual-runs", "daily", "SLSV_2026-10-22_60min.mp4")

	out, args = render(
		tmp_path, post=delete_post("daily", "SLSV_2026-10-22_60min.mp4", token="wrong")
	)

	assert json.loads(out)["message"] == "Die Anfrage ist ungültig (Sicherheitstoken)."
	assert args == []


# The playing video is marked in its list (and only there, not its namesake in the other list).
def test_selected_video_is_marked_in_the_list(tmp_path):
	make_video(tmp_path, "", "monthly", "SLSV_2026-10-25.mp4")
	make_video(tmp_path, "manual-runs", "monthly", "SLSV_2026-10-25.mp4")
	make_video(tmp_path, "manual-runs", "monthly", "SLSV_2026-09-25.mp4")

	out, _ = render(tmp_path)

	assert "aria-current" not in out

	out, _ = render(
		tmp_path,
		get={"camera": CAMERA, "job": "monthly", "video": "SLSV_2026-10-25.mp4", "source": "auto"},
	)

	assert out.count('aria-current="true"') == 1
	marked = out.split('aria-current="true"')[0].rsplit("<a ", 1)[1]
	assert "source=auto" in marked
	assert "SLSV_2026-10-25.mp4" in marked
