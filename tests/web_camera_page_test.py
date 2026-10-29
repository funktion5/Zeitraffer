import json
from pathlib import Path

from web_php_test import SUDO_PATH, fake_sudo, render_page

TOKEN = "test-token"
CAMERA = "SLSV"


# camera.php with the camera list at tmp_path/state/web-jobs/cameras.json and sudo faked.
def render(tmp_path: Path, get=None, post=None, sudo_exit: int = 0):
	sudo = str(fake_sudo(tmp_path))
	list_path = tmp_path / "state" / "web-jobs" / "cameras.json"
	list_path.parent.mkdir(parents=True, exist_ok=True)
	list_path.write_text(json.dumps([CAMERA]))
	swaps = {
		"src/video-delete.php": (SUDO_PATH, sudo),
		"src/job-runner.php": (SUDO_PATH, sudo),
	}
	return render_page(
		tmp_path, "camera.php", swaps, get or {"camera": CAMERA}, post, sudo_exit, TOKEN
	)


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
	# The script takes the empty text from here when the last video of a list is deleted.
	assert 'data-empty-text="Keine manuellen Videos gefunden."' in out


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


def create_post(token: str = TOKEN) -> dict:
	return {
		"action": "create-video",
		"csrf_token": token,
		"camera": CAMERA,
		"job": "daily",
		"target_date": "2026-10-25",
		"daylight_buffer_minutes": "60",
	}


# Post/Redirect/Get: the POST answers with a redirect only, the next page load hands the job to
# the watcher exactly once, so a reload cannot start it again.
def test_started_job_redirects_and_reaches_the_watcher_once(tmp_path):
	out, args = render(tmp_path, post=create_post())

	assert out.strip() == ""
	assert args[3] == "/usr/local/sbin/timelapse-web-trigger"
	job_id = args[4]

	out, _ = render(tmp_path)

	assert f'"jobId":"{job_id}"' in out
	assert "PID" not in out
	assert '"bufferMinutes":60' in out

	out, _ = render(tmp_path)

	assert job_id not in out


def test_busy_lock_keeps_the_form_page_with_its_message(tmp_path):
	out, _ = render(tmp_path, post=create_post(), sudo_exit=75)

	assert "Es läuft bereits ein anderer Zeitraffer-Auftrag." in out

	# A refused start leaves nothing in the session for the next page load.
	out, _ = render(tmp_path)

	assert '"jobId"' not in out
