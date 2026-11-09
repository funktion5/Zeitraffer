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
		"src/rebuild-runner.php": (SUDO_PATH, sudo),
		"src/publish-runner.php": (SUDO_PATH, sudo),
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


# A successful background delete shows the green message above the player: the script unhides this
# paragraph. Any full page load (reload, another video, another page) drops it again, no timer
# needed.
def test_the_delete_message_is_in_the_page_but_hidden_until_a_delete(tmp_path):
	out, _ = render(tmp_path)

	hidden = '<p class="delete-success-message" id="delete-success-message" hidden>'
	assert hidden + "Video erfolgreich gelöscht.</p>" in out
	# The background delete passes the server's message on with the "deleted" event.
	assert "detail: { message: result.message }" in out
	assert 'document.querySelector("#delete-success-message")' in out


# Deleting the playing video reloads the page without it; ?deleted=1 makes the server show the
# message there (the script then drops the parameter from the URL, so a refresh clears it).
def test_the_delete_message_is_visible_after_a_reload_with_deleted(tmp_path):
	out, _ = render(tmp_path, get={"camera": CAMERA, "deleted": "1"})

	visible = '<p class="delete-success-message" id="delete-success-message">'
	assert visible + "Video erfolgreich gelöscht.</p>" in out
	assert 'deleted: "1"' in out


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


# A manual Daily, Monthly or Yearly of a camera in privacy.blur_cameras blurs its frames on the box
# before the video is built, which takes longer: the form says so, only for those cameras.
def write_blur_config(tmp_path: Path, cameras: list[str]) -> None:
	config_path = tmp_path / "config" / "config.json"
	config_path.parent.mkdir(parents=True, exist_ok=True)
	config_path.write_text(json.dumps({"privacy": {"blur_cameras": cameras}}))


def test_a_blur_camera_says_that_creating_a_video_takes_longer(tmp_path):
	write_blur_config(tmp_path, [CAMERA])

	out, _ = render(tmp_path)

	assert '<p id="blur-note">' in out
	assert "vorher automatisch verpixelt" in out
	assert "dauert deshalb deutlich länger" in out
	# Every job type blurs, so the note names none of them.
	assert "tägliche" not in out


def test_a_camera_outside_the_blur_list_has_no_note(tmp_path):
	write_blur_config(tmp_path, ["Another-Camera"])

	out, _ = render(tmp_path)

	assert "blur-note" not in out
	assert "verpixelt" not in out


# The "a job is running" notice sits at the very top, in the header every page shares, so it is seen
# without scrolling; the watcher script fills it, and it starts hidden. Once, and no longer inside
# the manual-video form.
def test_the_job_notice_is_in_the_header_and_hidden_until_a_job_runs(tmp_path):
	out, _ = render(tmp_path)

	assert out.count('id="job-live-status"') == 1
	assert '<p id="job-live-status" role="status" aria-live="polite" hidden></p>' in out
	assert out.index('id="job-live-status"') < out.index("<main")
	assert out.index('id="job-live-status"') < out.index('class="video-create"')


# A job another colleague started is announced on every camera page, not only in the tab that
# started it: the page asks running-job.php (the JavaScript itself is not tested, as elsewhere).
def test_the_page_asks_whether_another_job_is_running(tmp_path):
	out, _ = render(tmp_path)

	assert "/running-job.php" in out


# The rebuild section sits between the player/lists and the historical-video section; a message
# about a rebuild request has to show there, not in the other form.
def rebuild_section(out: str) -> str:
	section = out.split('class="video-rebuild"')[1]

	# The upload section (only there when automatic videos exist) and the manual form follow.
	for next_section in ('class="video-publish"', 'class="video-create"'):
		section = section.split(next_section)[0]

	return section


def rebuild_post(jobs=None, token: str = TOKEN) -> dict:
	post = {"action": "rebuild-jobs", "csrf_token": token, "camera": CAMERA}

	if jobs is not None:
		post["rebuild_jobs"] = jobs

	return post


# The checkboxes start unticked and the button disabled until one is ticked, so a click is always a
# deliberate choice. The server refuses an empty selection anyway (the tests below).
def test_rebuild_form_checkboxes_start_unticked_and_the_button_is_disabled(tmp_path):
	out, _ = render(tmp_path)

	section = rebuild_section(out)
	form = section.split('id="rebuild-form"')[1].split("</form>")[0]

	assert "<h2>Neu erstellen wie der Nachtlauf</h2>" in section
	assert form.count('name="rebuild_jobs[]"') == 4

	for job in ("daily", "weekly", "monthly", "yearly"):
		assert f'name="rebuild_jobs[]" value="{job}"' in form

	assert "checked" not in form
	assert '<button type="submit" disabled>' in form
	# The Weekly is built from the Daily videos that exist.
	assert "Täglich mit ankreuzen" in section


def test_rebuild_without_a_ticked_job_is_refused_without_calling_sudo(tmp_path):
	for jobs in (None, []):
		out, args = render(tmp_path, post=rebuild_post(jobs))

		assert "Bitte mindestens ein Video zum Neuerstellen auswählen." in rebuild_section(out)
		assert "Bitte mindestens ein Video" not in out.split('class="video-create"')[1]
		assert args == []


# A crafted request: unknown values, a mix of known and unknown, a nested array, a plain string.
def test_rebuild_with_an_unknown_job_is_refused(tmp_path):
	for jobs in (["hourly"], ["daily", "hourly"], [["daily"]], "daily"):
		out, args = render(tmp_path, post=rebuild_post(jobs))

		assert "Der ausgewählte Videotyp ist ungültig." in rebuild_section(out)
		assert args == []


def test_rebuild_with_a_bad_csrf_token_is_refused(tmp_path):
	out, args = render(tmp_path, post=rebuild_post(["daily"], token="wrong"))

	assert "Die Anfrage ist ungültig (Sicherheitstoken)." in rebuild_section(out)
	assert args == []


# Post/Redirect/Get as for the manual video: the POST answers with a redirect only, the next page
# load hands the job to the watcher exactly once. The jobs go on in their fixed order.
def test_rebuild_with_valid_jobs_starts_the_job_and_redirects(tmp_path):
	out, args = render(tmp_path, post=rebuild_post(["monthly", "daily"]))

	assert out.strip() == ""
	assert args[3] == "/usr/local/sbin/timelapse-web-rebuild"
	job_id = args[4]
	assert args[5:] == [CAMERA, "daily", "monthly"]

	out, _ = render(tmp_path)

	assert f'"jobId":"{job_id}"' in out
	assert '"kind":"rebuild"' in out
	assert '"jobs":["daily","monthly"]' in out

	out, _ = render(tmp_path)

	assert job_id not in out


# The upload section sits right after the rebuild section; a message about an upload request has to
# show there, and the other forms must not show it.
def publish_section(out: str) -> str:
	return out.split('class="video-publish"')[1].split('class="video-create"')[0]


def publish_post(confirm="yes", token: str = TOKEN) -> dict:
	post = {"action": "publish-camera", "csrf_token": token, "camera": CAMERA}

	if confirm is not None:
		post["confirm"] = confirm

	return post


def make_automatic_videos(tmp_path: Path) -> None:
	make_video(tmp_path, "", "daily", "SLSV_2026-10-24.mp4")
	make_video(tmp_path, "", "daily", "SLSV_2026-10-25.mp4")
	make_video(tmp_path, "", "monthly", "SLSV_2026-10-25.mp4")


# What the upload would send: the newest automatic video per period, like the delivery script's own
# list. The confirm box starts unticked and the button disabled until it is ticked; the server
# refuses without the confirmation anyway (the tests below). The text says that older videos on
# the website are deleted, so nobody confirms without knowing.
def test_publish_section_lists_the_newest_file_per_period_with_an_unticked_confirm_box(tmp_path):
	make_automatic_videos(tmp_path)
	make_video(tmp_path, "manual-runs", "daily", "SLSV_2026-10-26_60min.mp4")

	out, _ = render(tmp_path)

	section = publish_section(out)
	form = section.split('id="publish-form"')[1].split("</form>")[0]

	assert "<h2>Auf die Website übertragen</h2>" in section
	assert "SLSV_2026-10-25.mp4" in section
	assert section.count("SLSV_2026-10-25.mp4") == 2
	assert "SLSV_2026-10-24.mp4" not in section
	assert "SLSV_2026-10-26_60min.mp4" not in section
	assert "Täglich" in section
	assert "Monatlich" in section
	assert "Wöchentlich" not in section
	assert 'name="confirm" value="yes"' in form
	assert "checked" not in form
	assert '<button type="submit" disabled>' in form
	assert "gelöscht" in section
	assert "zwei neuesten" in section


# Nothing to send, no section: a manual video does not count, the upload only sends automatic ones.
def test_publish_section_is_absent_without_automatic_videos(tmp_path):
	out, _ = render(tmp_path)

	assert 'class="video-publish"' not in out

	make_video(tmp_path, "manual-runs", "daily", "SLSV_2026-10-26_60min.mp4")

	out, _ = render(tmp_path)

	assert 'class="video-publish"' not in out


def test_publish_without_confirm_is_refused_without_calling_sudo(tmp_path):
	make_automatic_videos(tmp_path)

	out, args = render(tmp_path, post=publish_post(confirm=None))

	assert "Bitte bestätigen, dass die Videos übertragen werden sollen." in publish_section(out)
	assert "Bitte bestätigen" not in out.split('class="video-create"')[1]
	assert args == []


# Only the exact string "yes" counts; a browser sends "on" for a bare checkbox, and a crafted
# request can send anything else, also an array.
def test_publish_with_confirm_other_than_yes_is_refused(tmp_path):
	make_automatic_videos(tmp_path)

	for confirm in ("on", "1", "YES", "true", "yes ", "", ["yes"]):
		out, args = render(tmp_path, post=publish_post(confirm=confirm))

		assert "Bitte bestätigen, dass die Videos übertragen werden sollen." in publish_section(out)
		assert args == []


def test_publish_with_a_bad_csrf_token_is_refused(tmp_path):
	make_automatic_videos(tmp_path)

	out, args = render(tmp_path, post=publish_post(token="wrong"))

	assert "Die Anfrage ist ungültig (Sicherheitstoken)." in publish_section(out)
	assert args == []


# Post/Redirect/Get as for the other jobs: the POST answers with a redirect only, the next page
# load hands the job to the watcher exactly once. Only the camera goes to the trigger.
def test_publish_with_confirm_yes_starts_the_job_and_redirects(tmp_path):
	make_automatic_videos(tmp_path)

	out, args = render(tmp_path, post=publish_post())

	assert out.strip() == ""
	assert args[3] == "/usr/local/sbin/timelapse-web-publish"
	job_id = args[4]
	assert args[5:] == [CAMERA]

	out, _ = render(tmp_path)

	assert f'"jobId":"{job_id}"' in out
	assert '"kind":"publish"' in out

	out, _ = render(tmp_path)

	assert job_id not in out


def test_publish_busy_lock_keeps_the_page_with_its_message(tmp_path):
	make_automatic_videos(tmp_path)

	out, _ = render(tmp_path, post=publish_post(), sudo_exit=75)

	assert "Es läuft bereits ein anderer Zeitraffer-Auftrag." in publish_section(out)

	# A refused start leaves nothing in the session for the next page load.
	out, _ = render(tmp_path)

	assert '"jobId"' not in out


def test_rebuild_busy_lock_keeps_the_page_with_its_message(tmp_path):
	out, _ = render(tmp_path, post=rebuild_post(["daily"]), sudo_exit=75)

	assert "Es läuft bereits ein anderer Zeitraffer-Auftrag." in rebuild_section(out)

	# A refused start leaves nothing in the session for the next page load.
	out, _ = render(tmp_path)

	assert '"jobId"' not in out
