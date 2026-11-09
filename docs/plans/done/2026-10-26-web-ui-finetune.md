# Web UI Fine-tuning — Implementation Plan

Status: done 2026-10-26. The delete feedback was reworked on 2026-10-30: the success message is the
green line above the player (camera page) or under the heading (highlights) again. Current behaviour:
[weboberflaeche.md](../../weboberflaeche.md). The checkboxes below were not ticked while building; the code and git history are the record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local web UI more practical: automatic videos on the camera page, deletes
that keep the page state (open list, open image viewer), delete + marker toggle inside the
highlights viewer, a create form that cannot start a job twice, and a readable reason when a
job fails.

**Architecture:** No framework, no new dependency, no new page. Deletes switch from
"POST + redirect" to a background `fetch` of the *same* form with one extra field
`response=json`; the page answers with `{"deleted", "message"}` via the existing
`respondWithJson()` (moved from `job-status.php` to `web/src/json-response.php`), and the shared
confirm dialog fires a `deleted` event the page uses to update itself. Without JavaScript the
old POST + redirect path stays. Automatic videos reuse the manual-video lister with the folder
as a parameter. The failure reason is the last `WARNING` line `src.main` writes to stderr, kept
by the worker in `state/web-jobs/<id>.reason` and translated to German by `job-status.php`
(unknown text is never forwarded).

**Tech Stack:** PHP 8.4 on the Pi (keep 8.3-compatible for CI), vanilla JS, bash wrappers,
pytest driving PHP CLI, ruff.

**Spec:** agreed in the session of 2026-10-26 (no separate spec file):
1. Camera page lists the automatic videos (Daily last 7, Weekly/Monthly/Yearly latest), read-only.
2. Deleting a video keeps its list open and only removes the entry.
3. Highlights viewer gets a Löschen button and the "Markierung zeigen" checkbox; deleting there
   keeps the viewer open and shows the next image.
4. Create form: no double start (redirect after POST + disabled button), date defaults to
   yesterday, no future dates, no "(PID …)" message.
5. A failed job shows its reason (e.g. too few days) in the result dialog.
6. Bug fixes: array GET parameters crash `camera.php`; job polling stops for good after one
   failed request and never clears a vanished job.

## Global Constraints

- Tabs for indentation in PHP, JS inside PHP, CSS, shell and Python; line length 100.
  `camera.php` has mixed indentation: new or rewritten blocks use tabs, untouched lines stay
  as they are (no formatting-only churn). Edit it with small line-based Python edits if the
  Edit tool cannot match whitespace.
- `declare(strict_types=1);`; keep PHP 8.3-compatible (no `array_any` etc.); validate instead
  of catching internal exceptions (CI has Xdebug).
- UI text German; identifiers (`daily`, `source=auto`, `response=json`, event `deleted`) English.
- Escape every output (`htmlspecialchars(..., ENT_QUOTES, "UTF-8")`, `json_encode` with
  `JSON_HEX_TAG | JSON_HEX_AMP` inside `<script>`); every POST keeps the CSRF check; the delete
  allow-lists (`$manualVideos`, `isListedHighlight`) stay the only way to reach a wrapper.
- No new dependency (Composer, npm or Python). No CDN.
- PHP/CSS edits are **live immediately** (Apache serves the working tree). Wrapper scripts are
  not: `scripts/timelapse-web-worker` only takes effect after Julius runs `sudo install`
  (Task 5). Claude never runs `sudo install`.
- README and `docs/` stay in sync with behaviour (README: plain summary, docs: details).
- Commits: Julius commits on `main` himself. Per task, hand over the exact `git add` list and a
  message file in the scratchpad (`git commit -F <file>`), imperative mood, no Co-Authored-By.
- Test command: `.venv/bin/python3 -m pytest tests/web_*.py -q`; before handover also
  `.venv/bin/ruff check . && .venv/bin/ruff format --check .` and `php -l` on every changed
  PHP file.

## Review Focus

1. **Same filename in both lists** (`SLSV_2026-10-25.mp4` as automatic Monthly *and* manual
   Monthly with the default window): the chosen list decides what plays and whether Löschen is
   offered — pinned in Task 1.
2. **Crafted delete of an automatic video** (POST with job/video of an automatic file): must be
   refused before the wrapper — pinned in Task 2.
3. **Deleting the last image in the viewer / the last video of a job type**: viewer closes,
   group disappears, no JS error on close/focus — manual check in Task 2/3 (no JS test infra).
4. **Reload or double click after starting a job** must not start a second job — pinned in
   Task 4 (redirect) plus manual double-click check.
5. **Failure text from the log** must never reach the browser raw; only mapped German text —
   pinned in Task 5 (unknown warning gives no `reason`).

---

### Task 1: Camera page — automatic videos, class-based layout, array-parameter fix

**Files:**
- Modify: `web/src/video-library.php` (`findManualVideos` → `findVideos`)
- Modify: `web/public/camera.php` (selection, library section, player delete form)
- Modify: `web/public/style.css` (selectors `main > div …` → classes)
- Modify: `tests/web_php_test.py` (rename calls, one new test)
- Create: `tests/web_camera_page_test.py`
- Modify: `docs/weboberflaeche.md`, `README.md`

**Interfaces:**
- Produces: `findVideos(string $camera, string $runFolder): array` — `$runFolder` is
  `"manual-runs"` or `""` (automatic); same return shape as before
  (`[job => [["filename","date","bufferMinutes","window","url"], …]]`).
- Produces: GET parameter `source=auto` on camera.php; `$selectedSource` (`"auto"|"manual"`).
- Produces: markup `<div class="video-library-source" data-video-source="auto|manual">` holding
  an `<h2>`, the `<details>` per job, and the empty-text `<p>`; section classes
  `.camera-layout`, `.video-player`, `.video-library`, `.video-create`.
- Produces: test helpers in `tests/web_camera_page_test.py`: `render(tmp_path, get=None,
  post=None, sudo_exit=0)`, `make_video(tmp_path, folder, job, name)`, `CAMERA = "SLSV"`,
  `TOKEN`.

- [ ] **Step 1: Write the failing tests**

`tests/web_php_test.py`: replace every `findManualVideos("cam")` / `findManualVideos("missing")`
with `findVideos("cam", "manual-runs")` / `findVideos("missing", "manual-runs")`
(`sed -i 's/findManualVideos(\("[a-z]*"\))/findVideos(\1, "manual-runs")/' tests/web_php_test.py`)
and add:

```python
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
```

Create `tests/web_camera_page_test.py`:

```python
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
	# Only the manual entry carries a delete form (the dialog script names the attribute too).
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


# ?job[]=x used to throw a TypeError (500).
def test_array_parameters_do_not_break_the_page(tmp_path):
	out, _ = render(
		tmp_path, get={"camera": CAMERA, "job": ["x"], "video": ["y"], "source": ["auto"]}
	)

	assert "Bitte ein Video aus der Liste auswählen." in out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/web_php_test.py tests/web_camera_page_test.py -q`
Expected: FAIL (`findVideos` undefined; no "Automatische Videos"; array test hits `Fatal error`).

- [ ] **Step 3: Implement `findVideos` in `web/src/video-library.php`**

Rename `findManualVideos(string $camera)` to the function below; only the root and URL lines
change, the loop body stays:

```php
// $runFolder "manual-runs" lists the historical videos, "" the automatic ones in
// videos/<camera>/<job>/. Only the four job folders are read, so highlights/ and manual-runs/
// never show up as jobs.
function findVideos(string $camera, string $runFolder): array
{
	$folderPath = $runFolder === "" ? "" : "/" . $runFolder;
	$videoRoot = projectRoot() . "/videos/" . $camera . $folderPath;
```

Replace the old `$manualRoot` name with `$videoRoot` in the function, and the URL with:

```php
				"url" => "/videos/"
					. rawurlencode($camera)
					. $folderPath
					. "/"
					. rawurlencode($job)
					. "/"
					. rawurlencode($filename),
```

- [ ] **Step 4: Selection in `web/public/camera.php` (top of file)**

Replace lines 20-34 (from `$manualVideos = …` to the end of the `foreach` that finds
`$selectedVideo`) with:

```php
$manualVideos = $camera === "" ? [] : findVideos($camera, "manual-runs");
$automaticVideos = $camera === "" ? [] : findVideos($camera, "");

// Strings only: an array here (?job[]=x) would make the lookups below throw.
$selectedJob = is_string($_GET["job"] ?? null) ? $_GET["job"] : "";
$selectedFilename = is_string($_GET["video"] ?? null) ? $_GET["video"] : "";
// Automatic videos are read-only; the same filename can exist in both lists.
$selectedSource = ($_GET["source"] ?? null) === "auto" ? "auto" : "manual";
$selectedVideo = null;
$videoWasDeleted = ($_GET["deleted"] ?? null) === "1";
$selectedList = $selectedSource === "auto" ? $automaticVideos : $manualVideos;

foreach ($selectedList[$selectedJob] ?? [] as $video) {
	if ($video["filename"] === $selectedFilename) {
		$selectedVideo = $video;
		break;
	}
}
```

The delete branch keeps checking `$manualVideos` only — that is what refuses automatic videos.

- [ ] **Step 5: Markup in `camera.php`**

1. `<div>` directly under `<h1>` (line ~263) → `<div class="camera-layout">`; the player
   `<section>` → `<section class="video-player">`; the create `<section>` →
   `<section class="video-create">`.
2. Wrap the player's `<form … class="video-delete-form" …> … </form>` in
   `<?php if ($selectedSource === "manual"): ?> … <?php endif; ?>` (download link stays for both).
3. Replace the whole library `<section>` ("Manuelle Videos", lines ~358-481) with:

```php
		<section class="video-library">
			<?php
			$librarySources = [
				"auto" => ["Automatische Videos", $automaticVideos, "Keine automatischen Videos gefunden."],
				"manual" => ["Manuelle Videos", $manualVideos, "Keine manuellen Videos gefunden."],
			];
			?>
			<?php foreach ($librarySources as $source => [$heading, $videoGroups, $emptyText]): ?>
				<div class="video-library-source" data-video-source="<?= $source ?>">
					<h2><?= $heading ?></h2>

					<?php if ($videoGroups === []): ?>
						<p><?= $emptyText ?></p>
					<?php endif; ?>

					<?php foreach ($videoGroups as $job => $videos): ?>
						<details<?= $source === $selectedSource && $job === $selectedJob ? " open" : "" ?>>
							<summary>
								<?= htmlspecialchars(translateJobLabel($job), ENT_QUOTES, "UTF-8") ?>
							</summary>
							<ul>
								<?php foreach ($videos as $video): ?>
									<?php
									$videoDisplayLabel = $video["date"] !== null ? formatGermanDate($video["date"]) : $video["filename"];
									if ($video["bufferMinutes"] !== null) {
										$videoDisplayLabel .= " ({$video["bufferMinutes"]} Min.)";
									}
									if ($video["window"] !== null) {
										$videoDisplayLabel .= " ({$video["window"]})";
									}
									$videoQuery = ["camera" => $camera, "job" => $job, "video" => $video["filename"]];
									if ($source === "auto") {
										$videoQuery["source"] = "auto";
									}
									?>
									<li class="video-library-item">
										<a href="/camera.php?<?= htmlspecialchars(http_build_query($videoQuery), ENT_QUOTES, "UTF-8") ?>">
											<?= htmlspecialchars($videoDisplayLabel, ENT_QUOTES, "UTF-8") ?>
										</a>

										<?php if ($source === "manual"): ?>
											<form
												method="post"
												action="/camera.php?camera=<?= rawurlencode($camera) ?>"
												class="video-library-delete-form"
												data-delete-confirm
												data-delete-name="<?= htmlspecialchars($video["filename"], ENT_QUOTES, "UTF-8") ?>"
											>
												<input type="hidden" name="action" value="delete-video">
												<input type="hidden" name="csrf_token" value="<?= htmlspecialchars($csrfToken, ENT_QUOTES, "UTF-8") ?>">
												<input type="hidden" name="camera" value="<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>">
												<input type="hidden" name="job" value="<?= htmlspecialchars($job, ENT_QUOTES, "UTF-8") ?>">
												<input type="hidden" name="video" value="<?= htmlspecialchars($video["filename"], ENT_QUOTES, "UTF-8") ?>">

												<button
													type="submit"
													class="video-library-delete"
													title="Video löschen"
													aria-label="<?= htmlspecialchars($video["filename"], ENT_QUOTES, "UTF-8") ?> löschen"
												>
													<svg viewBox="0 0 24 24" aria-hidden="true">
														<path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 12H8L7 9Zm3 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" />
													</svg>
												</button>
											</form>
										<?php endif; ?>
									</li>
								<?php endforeach; ?>
							</ul>
						</details>
					<?php endforeach; ?>
				</div>
			<?php endforeach; ?>
		</section>
```

- [ ] **Step 6: CSS selectors to classes (`web/public/style.css`)**

```bash
sed -i \
  -e 's/^main > div {/.camera-layout {/' \
  -e 's/main > div > section:first-child/.video-player/' \
  -e 's/main > div > section:nth-child(2)/.video-library/g' \
  -e 's/main > div > section:nth-child(3)/.video-create/' \
  web/public/style.css
grep -n "main > div" web/public/style.css   # expected: no output
```

Append after the `.video-library details[open] summary::before` rule:

```css
.video-library-source + .video-library-source {
	margin-top: 1.5rem;
}
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/web_php_test.py tests/web_camera_page_test.py -q && php -l web/public/camera.php && php -l web/src/video-library.php`
Expected: all PASS, "No syntax errors detected".

- [ ] **Step 8: Docs**

- `docs/weboberflaeche.md`, "Aktueller Funktionsumfang": add a bullet "Liste **Automatische
  Videos** (nur ansehen und herunterladen, kein Löschen; die Aufräumregel entfernt sie): Täglich
  die letzten 7, Wöchentlich/Monatlich/Jährlich jeweils das neueste; Auswahl per
  `source=auto` in der URL". Replace "Die Bibliothek zeigt derzeit ausschließlich
  `manual-runs`." and "Automatische Videos werden noch nicht in der Oberfläche aufgelistet" with
  the new state. Tests section: add `web_camera_page_test.py` (Kameraseite: Listen, Auswahl,
  Löschen, Auftragsstart) and drop `camera.php` from "Nicht automatisiert getestet".
- `README.md` line ~512: replace "Die nächtlich erstellten Videos werden in der Weboberfläche
  derzeit nicht angezeigt." with "Die nächtlich erstellten Videos lassen sich dort ebenfalls
  ansehen und herunterladen (löschen nur die selbst erstellten)."; line ~234: drop ", auch wenn
  die PHP-Bibliothek nur `manual-runs` auflistet".

- [ ] **Step 9: Handover commit**

Files: `web/src/video-library.php web/public/camera.php web/public/style.css
tests/web_php_test.py tests/web_camera_page_test.py docs/weboberflaeche.md README.md`
Message: `web: list the automatic videos on the camera page`

---

### Task 2: Background delete that keeps the page state (both pages)

**Files:**
- Create: `web/src/json-response.php`
- Modify: `web/public/job-status.php` (use the shared helper)
- Modify: `web/src/components/confirm-delete.php`
- Modify: `web/public/camera.php` (JSON answer, redirect keeps `job`, `deleted` handler)
- Modify: `web/public/highlights.php` (JSON answer, `deleted` handler, focus guard)
- Modify: `tests/web_camera_page_test.py`, `tests/web_highlights_page_test.py`
- Modify: `docs/weboberflaeche.md`, `docs/highlights-seite.md`

**Interfaces:**
- Consumes: `render`, `make_video`, `CAMERA`, `TOKEN` (Task 1); `data-video-source` markup.
- Produces: `respondWithJson(int $statusCode, array $payload): never` in
  `web/src/json-response.php`.
- Produces: POST field `response=json` → body `{"deleted": bool, "message": string}`, HTTP 200.
- Produces: DOM event `deleted` (bubbles) dispatched on the delete form after a successful
  background delete. Task 3 relies on it and on `updateViewerNavigation()` in highlights.php.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web_camera_page_test.py`:

```python
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
```

Append to `tests/web_highlights_page_test.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/web_camera_page_test.py tests/web_highlights_page_test.py -q`
Expected: the five new tests FAIL (`json.loads` gets HTML or an empty body).

- [ ] **Step 3: Shared JSON helper**

Create `web/src/json-response.php` with the function moved verbatim out of
`web/public/job-status.php` (delete it there and add
`require_once __DIR__ . "/../src/json-response.php";` after `declare(strict_types=1);`):

```php
<?php

declare(strict_types=1);


// Return one JSON response and stop processing (job status and the background deletes).
function respondWithJson(int $statusCode, array $payload): never
{
	http_response_code($statusCode);
	header("Content-Type: application/json; charset=UTF-8");
	header("Cache-Control: no-store");

	echo json_encode(
		$payload,
		JSON_THROW_ON_ERROR,
	);

	exit;
}
```

- [ ] **Step 4: Server side of `camera.php`**

Add `require_once __DIR__ . "/../src/json-response.php";` to the requires. Next to
`$formMessage = null;` add `$videoDeleted = false;`. In the delete branch replace the
`$formMessage = $deleteResult["message"]; if ($deleteResult["deleted"]) { header(…); exit; }`
block with:

```php
				$formMessage = $deleteResult["message"];
				$videoDeleted = $deleteResult["deleted"];
```

and directly before the closing `}` of `if ($_SERVER["REQUEST_METHOD"] === "POST") {` add:

```php
	// The background delete (confirm-delete.php) only needs the outcome.
	if (($_POST["response"] ?? null) === "json") {
		respondWithJson(200, ["deleted" => $videoDeleted, "message" => $formMessage]);
	}

	// Without JavaScript: back to the page with the same list open.
	if ($videoDeleted) {
		header(
			"Location: /camera.php?"
			. http_build_query(["camera" => $camera, "job" => $submittedJob, "deleted" => "1"])
		);

		exit;
	}
```

- [ ] **Step 5: Server side of `highlights.php`**

Add `require_once __DIR__ . "/../src/json-response.php";`. At the top of the POST block add
`$deleteResult = null;`. Replace the `else` branch and what follows up to the end of the POST
block with:

```php
	} else {
		$deleteResult = deleteHighlightImage($submittedCamera, $submittedDate, $submittedFile);
		$formMessage = $deleteResult["message"];
	}

	$imageDeleted = ($deleteResult["deleted"] ?? false) === true;

	// The background delete (confirm-delete.php) only needs the outcome.
	if (($_POST["response"] ?? null) === "json") {
		respondWithJson(200, ["deleted" => $imageDeleted, "message" => $formMessage]);
	}

	if ($imageDeleted) {
		$query = ["days" => $period, "camera" => $cameraFilter, "deleted" => "1"];
		header("Location: /highlights.php?" . http_build_query($query));

		exit;
	}
}
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/web_*.py -q`
Expected: all PASS (including the old redirect tests and `web_status_endpoint_test.py`).

- [ ] **Step 7: Background delete in `confirm-delete.php`**

Replace the `deleteDialogConfirmButton` click handler and update the opener; full script body:

```js
	(function () {
		const deleteDialog = document.querySelector("#confirm-delete-dialog");
		const deleteDialogMessage = document.querySelector("#confirm-delete-message");
		const deleteDialogConfirmButton = document.querySelector("#confirm-delete-button");
		let pendingDeleteForm = null;

		function buildDeleteConfirmMessage(name) {
			return `„${name}“ wirklich löschen? Dies kann nicht rückgängig gemacht werden.`;
		}

		// Require an explicit confirm click before any delete form is submitted. Falls back to
		// window.confirm() and a normal page post where <dialog>.showModal is unavailable.
		document.querySelectorAll("form[data-delete-confirm]").forEach((form) => {
			form.addEventListener("submit", (event) => {
				event.preventDefault();

				if (typeof deleteDialog.showModal !== "function") {
					if (window.confirm(buildDeleteConfirmMessage(form.dataset.deleteName))) {
						form.submit();
					}

					return;
				}

				pendingDeleteForm = form;
				deleteDialogMessage.textContent = buildDeleteConfirmMessage(form.dataset.deleteName);
				deleteDialogConfirmButton.hidden = false;
				deleteDialogConfirmButton.disabled = false;
				deleteDialog.showModal();
			});
		});

		// Delete in the background so the page keeps its state (open lists, the image viewer):
		// the form then fires "deleted" and the page updates itself. A refusal or a lost
		// connection stays in the dialog; "Abbrechen" closes it.
		deleteDialogConfirmButton.addEventListener("click", async () => {
			const form = pendingDeleteForm;

			if (form === null) {
				return;
			}

			deleteDialogConfirmButton.disabled = true;
			const body = new FormData(form);
			body.append("response", "json");
			let result;

			try {
				const response = await fetch(form.action, { method: "POST", body });
				result = await response.json();
			} catch (error) {
				result = {
					deleted: false,
					message: "Das Löschen hat nicht geklappt. Bitte die Seite neu laden.",
				};
			}

			if (!result.deleted) {
				deleteDialogMessage.textContent = result.message;
				deleteDialogConfirmButton.hidden = true;
				return;
			}

			pendingDeleteForm = null;
			deleteDialog.close();
			form.dispatchEvent(new CustomEvent("deleted", { bubbles: true }));
		});
	})();
```

Also update the header comment of the file: "On confirm it deletes in the background and fires
`deleted` on the form; the page decides what to update."

- [ ] **Step 8: `deleted` handler in `camera.php`**

In the last `<script>` of camera.php (before `const videoWasDeleted`), add:

```js
	// After a background delete (confirm-delete.php): drop the entry and keep its list open.
	// Deleting the video that is playing reloads the page without it, same list open.
	const playingVideo = <?= json_encode(
		$selectedVideo !== null && $selectedSource === "manual"
			? ["job" => $selectedJob, "filename" => $selectedVideo["filename"]]
			: null,
		JSON_HEX_TAG | JSON_HEX_AMP,
	) ?>;

	document.addEventListener("deleted", (event) => {
		const form = event.target;
		const job = form.elements.job.value;
		const filename = form.elements.video.value;

		if (playingVideo !== null && playingVideo.job === job && playingVideo.filename === filename) {
			window.location.replace("/camera.php?" + new URLSearchParams({
				camera: form.elements.camera.value,
				job,
			}));
			return;
		}

		const item = form.closest("li");
		const next = item.nextElementSibling ?? item.previousElementSibling;
		const details = item.closest("details");
		const source = item.closest("[data-video-source]");
		item.remove();

		// Last video of this job type: its group goes, and an empty list says so.
		if (next === null) {
			details.remove();

			if (source.querySelector("details") === null) {
				const empty = document.createElement("p");
				empty.textContent = "Keine manuellen Videos gefunden.";
				source.append(empty);
			}
		}

		// Keep the keyboard in the list instead of dropping it to the page start.
		(next?.querySelector("a") ?? source.querySelector("summary"))?.focus();
	});
```

- [ ] **Step 9: `deleted` handler in `highlights.php`**

In the page script, replace the two lines `viewerPrevious.hidden = …; viewerNext.hidden = …;`
inside `if (typeof viewer.showModal === "function")` with `updateViewerNavigation();` and add
above that `if`:

```js
		function updateViewerNavigation() {
			viewerPrevious.hidden = viewerLinks.length < 2;
			viewerNext.hidden = viewerLinks.length < 2;
		}

		// After a background delete (confirm-delete.php): drop the image from the grid and the
		// viewer, fix the camera's count, and in the open viewer show the next image.
		document.addEventListener("deleted", (event) => {
			const item = event.target.closest("li");
			const list = item.parentElement;
			const section = item.closest(".highlights-camera");
			const index = viewerLinks.indexOf(item.querySelector("a.highlights-open"));

			viewerLinks.splice(index, 1);
			item.remove();

			if (list.children.length === 0) {
				list.remove();
			}

			const count = section.querySelectorAll(".highlights-grid li").length;
			section.querySelector(".highlights-count").textContent =
				`(${count} ${count === 1 ? "Bild" : "Bilder"})`;
			updateViewerNavigation();

			if (viewer.open) {
				if (viewerLinks.length === 0) {
					viewer.close();
				} else {
					showViewerImage(index);
				}

				return;
			}

			// Keep the keyboard where the image was.
			viewerLinks[Math.min(index, viewerLinks.length - 1)]?.focus();
		});
```

and change the close handler to `viewer.addEventListener("close", () => viewerLinks[viewerIndex]?.focus());`.

- [ ] **Step 10: Run the tests and lint**

Run: `.venv/bin/python3 -m pytest tests/web_*.py -q && for f in web/public/*.php web/src/*.php web/src/components/*.php; do php -l "$f"; done`
Expected: all PASS, no syntax errors.

- [ ] **Step 11: Manual check (Julius, browser; live immediately)**

1. Camera page, open "Täglich" under Manuelle Videos, delete a test video from the list: the
   entry disappears, the list stays open, no reload.
2. Delete the video that is playing: page reloads, player shows "Bitte ein Video …", the list
   is still open.
3. Highlights: delete an image in the grid: it disappears in place, the count in the heading
   drops, the scroll position stays.

- [ ] **Step 12: Docs**

- `docs/weboberflaeche.md`: the delete bullet: "Löschen läuft im Hintergrund: der Eintrag
  verschwindet, die Liste bleibt offen; wird das gerade laufende Video gelöscht, lädt die Seite
  neu (gleiche Liste offen). Ohne JavaScript wie bisher per Formular." Add
  `web/src/json-response.php` to "Webdateien" ("gemeinsame JSON-Antwort für Status und
  Löschen").
- `docs/highlights-seite.md`, "Löschen": "Nach **Löschen** im Dialog verschwindet das Bild
  ohne Neuladen, die Anzahl im Kameratitel passt sich an. Schlägt es fehl, steht der Grund im
  Dialog." Keep the no-JS sentence about "Bild erfolgreich gelöscht.".

- [ ] **Step 13: Handover commit**

Files: `web/src/json-response.php web/public/job-status.php web/src/components/confirm-delete.php
web/public/camera.php web/public/highlights.php tests/web_camera_page_test.py
tests/web_highlights_page_test.py docs/weboberflaeche.md docs/highlights-seite.md`
Message: `web: delete in the background and keep lists and scroll position`

---

### Task 3: Highlights viewer — Löschen and Markierung inside the big view

**Files:**
- Modify: `web/public/highlights.php` (viewer markup + script)
- Modify: `web/public/style.css`
- Modify: `tests/web_highlights_page_test.py`
- Modify: `docs/highlights-seite.md`

**Interfaces:**
- Consumes: `deleted` event, `updateViewerNavigation()`, background delete (Task 2).

- [ ] **Step 1: Write the failing test**

In `test_page_shows_cameras_days_and_images` add after `assert 'id="highlights-viewer"' in out`:

```python
	# The viewer has its own delete button and marker toggle.
	assert 'id="highlights-viewer-delete"' in out
	assert 'id="highlights-viewer-show-boxes"' in out
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/web_highlights_page_test.py -q`
Expected: FAIL on `highlights-viewer-delete`.

- [ ] **Step 3: Viewer markup**

Replace the `<div class="highlights-viewer-nav">…</div>` in highlights.php with:

```php
		<div class="highlights-viewer-nav">
			<button type="button" id="highlights-viewer-prev">← Vorheriges</button>
			<button type="button" id="highlights-viewer-next">Nächstes →</button>
			<button type="button" id="highlights-viewer-delete" class="delete-video-button">
				<svg viewBox="0 0 24 24" aria-hidden="true">
					<path d="M9 3h6l1 1h4v2H4V4h4l1-1zm-3 5h12l-1 13H7L6 8z" />
				</svg>
				<span>Löschen</span>
			</button>
			<label class="highlights-viewer-toggle">
				<input type="checkbox" id="highlights-viewer-show-boxes">
				Markierung zeigen
			</label>
			<button type="button" id="highlights-viewer-close">Schließen</button>
		</div>
```

- [ ] **Step 4: Viewer script**

Add after `const viewerNext = …`:

```js
		const viewerDelete = document.querySelector("#highlights-viewer-delete");
		const boxToggles = document.querySelectorAll(
			"#highlights-show-boxes, #highlights-viewer-show-boxes",
		);

		// Two checkboxes, one setting: the CSS follows the one on the page.
		boxToggles.forEach((toggle) => {
			toggle.addEventListener("change", () => {
				boxToggles.forEach((other) => {
					other.checked = toggle.checked;
				});
			});
		});
```

Inside `if (typeof viewer.showModal === "function") {` add:

```js
			// Same form as the image's own Löschen button, so the confirm dialog and the
			// background delete (and the jump to the next image) work the same way.
			viewerDelete.addEventListener("click", () => {
				viewerLinks[viewerIndex]
					.closest("li")
					.querySelector("form[data-delete-confirm]")
					.requestSubmit();
			});
```

- [ ] **Step 5: CSS**

In `web/public/style.css` extend three existing highlights selectors:

```css
.highlights-toggle label,
.highlights-viewer-toggle {
```
```css
.highlights-toggle input,
.highlights-viewer-toggle input {
```
```css
.highlights-filter select:focus-visible,
.highlights-filter button:focus-visible,
.highlights-toggle input:focus-visible,
.highlights-viewer-toggle input:focus-visible {
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/web_highlights_page_test.py -q && php -l web/public/highlights.php`
Expected: PASS.

- [ ] **Step 7: Manual check (Julius, browser)**

1. Open an image, tick "Markierung zeigen" in the viewer: box shows; close: the page checkbox is
   ticked too, and the reverse.
2. In the viewer, Löschen → confirm: the viewer stays open and shows the next image; the image
   is gone from the grid behind it.
3. Delete the last remaining image of the page in the viewer: the viewer closes, no error in
   the browser console.
4. Abbrechen in the confirm dialog: the viewer is still open on the same image.

- [ ] **Step 8: Docs**

`docs/highlights-seite.md`, "Was die Seite zeigt", viewer bullet: add "In der Großansicht gibt
es auch **Löschen** (mit Bestätigung; danach erscheint das nächste Bild, nach dem letzten
schließt sie sich) und **Markierung zeigen** (gleiche Einstellung wie auf der Seite)."

- [ ] **Step 9: Handover commit**

Files: `web/public/highlights.php web/public/style.css tests/web_highlights_page_test.py
docs/highlights-seite.md`
Message: `web: delete and marker toggle in the highlights viewer`

---

### Task 4: Create form — no double start, sensible date

**Files:**
- Modify: `web/public/camera.php`
- Modify: `web/public/style.css`
- Modify: `tests/web_camera_page_test.py`
- Modify: `docs/weboberflaeche.md`

**Interfaces:**
- Consumes: `render`, `CAMERA`, `TOKEN` (Task 1).
- Produces: session key `$_SESSION["started_job"]` (array with `jobId, job, targetDate,
  camera, bufferMinutes, windowTime, windowToleranceMinutes`), read once on the next page load
  and handed to `sessionStorage["timelapsePendingJob"]` (same object shape job-watcher reads).

- [ ] **Step 1: Write the failing tests**

Append to `tests/web_camera_page_test.py`:

```python
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
	assert '"bufferMinutes":60' in out

	out, _ = render(tmp_path)

	assert job_id not in out


def test_busy_lock_keeps_the_form_page_with_its_message(tmp_path):
	out, _ = render(tmp_path, post=create_post(), sudo_exit=75)

	assert "Es läuft bereits ein anderer Zeitraffer-Auftrag." in out
	assert '"jobId"' not in out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/web_camera_page_test.py -q`
Expected: `test_started_job_redirects_and_reaches_the_watcher_once` FAILS (page body is not
empty).

- [ ] **Step 3: PRG in `camera.php`**

1. Delete `$formIsValid` (declaration and the `$formIsValid = true;` line; it is never read)
   and the six `$active…` declarations.
2. In the create branch replace everything from `$formMessage = $jobResult["message"];` to the
   end of that `else` with:

```php
			$formMessage = $jobResult["message"];

			// Post/Redirect/Get: a reload or a second click cannot start the job again. The
			// next page load hands it to the job watcher (see startedJob below).
			if ($jobResult["started"]) {
				$_SESSION["started_job"] = [
					"jobId" => $jobResult["jobId"],
					"job" => $submittedJob,
					"targetDate" => $submittedDate,
					"camera" => $submittedCamera,
					"bufferMinutes" => $daylightBufferMinutes,
					"windowTime" => $windowTime,
					"windowToleranceMinutes" => $windowToleranceMinutes,
				];
				header("Location: /camera.php?camera=" . rawurlencode($camera));

				exit;
			}
```

   The trigger's "Videoauftrag gestartet (PID …)" message is thereby never shown.
3. After the closing `}` of the POST block add:

```php
// Set once by the redirect after a job start; read and dropped on the next page load.
$startedJob = $_SESSION["started_job"] ?? null;
unset($_SESSION["started_job"]);
```

4. Replace the first `<script>` block (the `activeJobId` one) with:

```php
	<script>
		// A job was started right before this page load: hand it to the shared job-watcher
		// (required right below), which polls it to completion from any page.
		const startedJob = <?= json_encode($startedJob, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

		if (startedJob !== null) {
			sessionStorage.setItem("timelapsePendingJob", JSON.stringify(startedJob));
		}
	</script>
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/web_camera_page_test.py -q`
Expected: PASS.

- [ ] **Step 5: Button and date (client side)**

Give the create form an id: `<form method="post" id="create-video-form" action="…">`. Wrap the
last `<script>` of camera.php (the form-visibility one) in `<?php if ($camera !== ""): ?> …
<?php endif; ?>` (on the 404 page it currently throws on the missing fieldsets) and add at its
end:

```js
	// One click, one job: the button stays disabled until the page is shown again, also when
	// the browser restores it from the back/forward cache.
	const createButton = document.querySelector('#create-video-form button[type="submit"]');
	document.querySelector("#create-video-form").addEventListener("submit", () => {
		createButton.disabled = true;
	});
	window.addEventListener("pageshow", () => {
		createButton.disabled = false;
	});

	// Yesterday by default and nothing after today, in the browser's (local) time.
	function isoDate(date) {
		return [
			date.getFullYear(),
			String(date.getMonth() + 1).padStart(2, "0"),
			String(date.getDate()).padStart(2, "0"),
		].join("-");
	}

	const targetDateInput = document.querySelector("#target-date");
	const today = new Date();
	targetDateInput.max = isoDate(today);

	if (targetDateInput.value === "") {
		const yesterday = new Date(today);
		yesterday.setDate(yesterday.getDate() - 1);
		targetDateInput.value = isoDate(yesterday);
	}
```

CSS (`web/public/style.css`, after `button:hover`):

```css
button:disabled {
	opacity: 0.6;
	cursor: progress;
}
```

- [ ] **Step 6: Run all web tests**

Run: `.venv/bin/python3 -m pytest tests/web_*.py -q && php -l web/public/camera.php`
Expected: PASS.

- [ ] **Step 7: Manual check (Julius, browser)**

1. Camera page: date field shows yesterday; the calendar does not allow tomorrow.
2. Start a short Daily, double-click the button: one job, the page reloads, "… läuft." appears,
   later the result dialog. F5 during the run asks nothing and starts nothing.

- [ ] **Step 8: Docs**

`docs/weboberflaeche.md`: form bullet: "Zieldatum steht anfangs auf gestern, spätere Tage als
heute sind gesperrt. Nach dem Start leitet die Seite einmal weiter (Neuladen startet nichts
doppelt), der Button ist bis dahin gesperrt." In "Job-Ausführung und Status": the job is handed
over through the PHP session (`started_job`) to `sessionStorage`.

- [ ] **Step 9: Handover commit**

Files: `web/public/camera.php web/public/style.css tests/web_camera_page_test.py
docs/weboberflaeche.md`
Message: `web: start a job once per click and default the date to yesterday`

---

### Task 5: Failure reason in the dialog, polling that survives a hiccup

**Files:**
- Modify: `scripts/timelapse-web-worker`
- Modify: `web/public/job-status.php`
- Modify: `web/src/components/job-watcher.php`
- Modify: `tests/web_status_test.py`, `tests/web_status_endpoint_test.py`
- Modify: `docs/weboberflaeche.md`

**Interfaces:**
- Consumes: `respondWithJson` (Task 2).
- Produces: file `state/web-jobs/<id>.reason` (one line: the last `WARNING` message of
  `src.main`, mode 644), written before `failed`.
- Produces: `job-status.php` answer `{"status": "failed", "reason": "<German>"}` when the reason
  is known; otherwise unchanged.

- [ ] **Step 1: Write the failing tests**

`tests/web_status_test.py`: add a parameter `python_stderr: str = ""` to `run_web_worker`
(after `expected_video_suffix`) and before `fake_python_lines.append(f"exit {python_exit_code}")`
insert:

```python
	if python_stderr:
		fake_python_lines.append(f"printf '%s' {shlex.quote(python_stderr)} >&2")
```

(add `import shlex` at the top) and expose `result.reason_file = status_root / f"{job_id}.reason"`.
New tests:

```python
SKIP_LOG = (
	"2026-10-26 10:00:00,000 | WARNING | Monthly coverage partial: 26 of 30 days\n"
	"2026-10-26 10:00:01,000 | WARNING | Monthly coverage too low: 21 of 30 days available"
	" (minimum 25) - skipping camera: Scheunenviertel\n"
	"2026-10-26 10:00:02,000 | INFO | Monthly timelapse job finished\n"
)


# The last warning is the reason no video came out; job-status.php translates it.
def test_web_worker_keeps_the_last_warning_as_failure_reason(tmp_path):
	result = run_web_worker(tmp_path, python_exit_code=0, python_stderr=SKIP_LOG)

	assert result.status_file.read_text() == "failed\n"
	assert result.reason_file.read_text() == (
		"Monthly coverage too low: 21 of 30 days available (minimum 25)"
		" - skipping camera: Scheunenviertel\n"
	)
	assert result.reason_file.stat().st_mode & 0o777 == 0o644


def test_web_worker_leaves_no_reason_on_success(tmp_path):
	result = run_web_worker(
		tmp_path, python_exit_code=0, publish_video=True, python_stderr=SKIP_LOG
	)

	assert result.status_file.read_text() == "completed\n"
	assert not result.reason_file.exists()
```

`tests/web_status_endpoint_test.py` (add `import pytest`):

```python
@pytest.mark.parametrize(
	("warning", "expected"),
	[
		(
			"Monthly coverage too low: 21 of 30 days available (minimum 25)"
			" - skipping camera: SLSV",
			"Zu wenige Tage mit Bildern: 21 von 30 (mindestens 25).",
		),
		(
			"Weekly image coverage incomplete: 5 of 7 days available - skipping camera: SLSV",
			"Nur an 5 von 7 Tagen gibt es Bilder; Wöchentlich braucht alle 7.",
		),
		("Found 0 images - skipping camera.", "Für diesen Tag wurden keine Bilder gefunden."),
		(
			"No valid Yearly images available - skipping camera: SLSV",
			"Im gewählten Zeitraum gibt es keine verwendbaren Bilder.",
		),
		("/home/someone/secret path exploded", None),
	],
)
def test_status_endpoint_translates_known_failure_reasons_only(tmp_path, warning, expected):
	job_id = "e" * 32
	status_root = tmp_path / "web-jobs"
	status_root.mkdir()
	(status_root / f"{job_id}.status").write_text("failed\n")
	(status_root / f"{job_id}.reason").write_text(warning + "\n")

	result = run_status_endpoint(status_root, f"id={job_id}")

	payload = json.loads(result.stdout)
	assert payload == (
		{"status": "failed", "reason": expected} if expected else {"status": "failed"}
	)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/web_status_test.py tests/web_status_endpoint_test.py -q`
Expected: new tests FAIL (no `.reason` file; no `reason` key).

- [ ] **Step 3: Worker (`scripts/timelapse-web-worker`)**

After `cd "$PROJECT_ROOT" || exit 69` add:

```bash
# src.main logs to stderr; keep it for this run so a failure can leave its cause behind.
output_file="$(mktemp)"
trap 'rm -f "$output_file"' EXIT

# The last warning says why no video came out (e.g. too few days); job-status.php translates
# the known ones and shows nothing for the rest. Written before "failed", so it is there when
# the browser sees the status.
write_failure_reason() {
	local reason_file="${STATUS_ROOT}/${JOB_ID}.reason"

	grep -F ' | WARNING | ' "$output_file" | tail -n 1 | sed 's/^.* | WARNING | //' \
		>"$reason_file" || true
	chmod 644 "$reason_file" 2>/dev/null || true
}
```

Change `if "${COMMAND[@]}"; then` to `if "${COMMAND[@]}" 2>"$output_file"; then`, and call
`write_failure_reason` directly before both `write_job_status "$JOB_ID" "failed" || true` lines.

- [ ] **Step 4: Endpoint (`web/public/job-status.php`)**

Add after `isWorkerPidAlive()`:

```php
// German text for the known reasons a historical run ends without a video (the worker keeps
// src.main's last warning). Anything else gives null: log text never reaches the browser.
function describeFailureReason(string $warning): ?string
{
	if (preg_match('/coverage too low: (\d+) of (\d+) days available \(minimum (\d+)\)/', $warning, $match) === 1) {
		return "Zu wenige Tage mit Bildern: {$match[1]} von {$match[2]} (mindestens {$match[3]}).";
	}

	if (preg_match('/Weekly image coverage incomplete: (\d+) of 7 days/', $warning, $match) === 1) {
		return "Nur an {$match[1]} von 7 Tagen gibt es Bilder; Wöchentlich braucht alle 7.";
	}

	if (str_contains($warning, "Found 0 images")) {
		return "Für diesen Tag wurden keine Bilder gefunden.";
	}

	if (preg_match('/No valid \w+ images available/', $warning) === 1) {
		return "Im gewählten Zeitraum gibt es keine verwendbaren Bilder.";
	}

	return null;
}
```

Replace the final `respondWithJson(200, ["status" => $status]);` with:

```php
$payload = ["status" => $status];
$reasonFile = $statusRoot . "/" . $jobId . ".reason";

if ($status === "failed" && is_file($reasonFile) && is_readable($reasonFile)) {
	$reason = describeFailureReason((string) file_get_contents($reasonFile));

	if ($reason !== null) {
		$payload["reason"] = $reason;
	}
}

respondWithJson(200, $payload);
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/web_status_test.py tests/web_status_endpoint_test.py -q`
Expected: PASS.

- [ ] **Step 6: Watcher (`web/src/components/job-watcher.php`)**

1. `function showResult(pendingJob, status)` → `function showResult(pendingJob, status, reason)`;
   failed message:

```js
				message.textContent = `${jobLabel} für den ${dateLabel} konnte nicht erstellt werden. `
					+ (reason ?? "Bitte das Anwendungsprotokoll prüfen.");
```

2. In `pollPendingJob`, before `if (!response.ok)`:

```js
				// The job is gone (status file removed): nothing left to wait for.
				if (response.status === 404) {
					sessionStorage.removeItem(PENDING_JOB_KEY);
					return;
				}
```

3. `showResult(pendingJob, result.status);` → `showResult(pendingJob, result.status, result.reason);`
4. Replace the `catch` body with:

```js
				// A dropped connection or a busy Pi must not end the wait: try again next tick.
				console.error("Video-job polling failed, retrying.", error);
				window.setTimeout(() => pollPendingJob(pendingJob), 5000);
```

- [ ] **Step 7: Full verification**

Run: `.venv/bin/python3 -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && php -l web/public/job-status.php && php -l web/src/components/job-watcher.php && bash -n scripts/timelapse-web-worker`
Expected: all green (857 + new tests).

- [ ] **Step 8: Install the worker (Julius runs it; live-system change)**

```bash
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-worker \
  /usr/local/libexec/timelapse-web-worker
```

Check: `cmp scripts/timelapse-web-worker /usr/local/libexec/timelapse-web-worker && echo same`.

- [ ] **Step 9: Manual check (Julius, browser)**

1. Start a Monthly for a date with too few days (e.g. a camera's first month): the dialog says
   "… konnte nicht erstellt werden. Zu wenige Tage mit Bildern: N von 30 (mindestens 25)."
2. During a running job, switch the Wi-Fi off for ~15 s and on again: the dialog still appears
   at the end.

- [ ] **Step 10: Docs**

`docs/weboberflaeche.md`, "Job-Ausführung und Status": the worker keeps `src.main`'s stderr
for the run and writes the last warning to `<job-id>.reason`; `job-status.php` returns a German
`reason` for known causes (zu wenige Tage, Woche unvollständig, keine Bilder), never raw log
text; the browser keeps polling after a failed request and drops a job whose status is gone
(404). Add `.reason` to the status-file list. README "Wrapper installieren" needs no change
(same install line).

- [ ] **Step 11: Handover commit**

Files: `scripts/timelapse-web-worker web/public/job-status.php
web/src/components/job-watcher.php tests/web_status_test.py tests/web_status_endpoint_test.py
docs/weboberflaeche.md`
Message: `web: show why a job failed and keep polling through a lost request`
