# Highlights Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Highlights" page in the existing PHP web UI that shows the flagged images of the whole retention per camera, with download and delete.

**Architecture:** All logic in `web/src/highlights-library.php` and `web/src/highlight-delete.php` (testable with the existing copy-to-`tmp_path` PHP harness); a thin `web/public/highlights.php`; deletion through a new root-owned wrapper called with the same `sudo -n -u <project user>` pattern as the video delete. The page only reads the folders and manifests written by the flagger.

**Tech Stack:** PHP 8.4 (no 8.5-only syntax), bash, pytest, the existing `web/` code and `style.css`.

**Spec:** `docs/superpowers/specs/2026-10-21-highlights-page-design.md`. The data it reads is defined in `docs/superpowers/specs/2026-10-21-highlights-flagger-design.md` (the `manifest.json` contract); the writer is the other plan, `docs/plans/2026-10-21-highlights-flagger.md`. This plan does not depend on it: fixtures are written by hand.

## Global Constraints

- Everything German, same look as the rest of the UI, no external assets, no CDN, no JS library, no Composer dependency.
- `declare(strict_types=1)` in new PHP files; escape every output with `htmlspecialchars($value, ENT_QUOTES, "UTF-8")`; JSON into scripts with `JSON_HEX_TAG | JSON_HEX_AMP`.
- Match the file you edit (tabs in `web/src/*.php` and the wrappers); new files use tabs.
- Do not change `camera.php`, `index.php`, `video-library.php`, `video-delete.php`, `job-*.php` or the existing wrappers. Allowed edits to existing files: one navigation link in `web/src/components/header.php`, appended rules in `web/public/style.css`, the wrapper lines in `migrate.sh` (Task 5) and the README sections (Tasks 5 and 6).
- The delete wrapper accepts exactly `<camera> <date> <filename>`; camera without `/`, `.`, `..`; date `YYYY-MM-DD`; filename matching `^[A-Za-z0-9._-]+\.jpg$`; target only `videos/<camera>/highlights/<date>/<filename>` as a regular file, not a symlink; exit 64 for bad input, 66 for a missing file; `rm --` only; never `manifest.json`.
- POST only for deletion, session CSRF token (`hash_equals`), camera checked against the known list, redirect back to the same filters.
- Period values: `1`, `7`, `30`, `all`; anything else means `7`. Default period 7 days.
- Page layout: per camera, days newest first, items highest score first (manifest order), a camera in `flagger.cameras` with no items stays visible as "geprüft, nichts gefunden". The model's guess is shown with a question mark (for example "Flugzeug?").
- German labels: bird Vogel, airplane Flugzeug, kite Drachen, cat Katze, dog Hund, horse Pferd, sheep Schaf, cow Kuh, elephant Elefant, bear Bär, zebra Zebra, giraffe Giraffe; unknown labels pass through.
- Accessibility (BFSG, WCAG 2.2 AA): semantic headings, labelled filter controls, real buttons and links with visible focus, native `<dialog>` confirm, image `alt` made of camera, time and label, nothing relies on colour or hover alone.
- Test environment: everything runs on the Pi itself with the project venv (`.venv`, Python 3.13) and its `php-cli`, no Docker; check it as in "Task 0: Check the Pi environment" of `docs/plans/2026-10-21-highlights-flagger.md`. Wherever this plan says `python -m pytest ...`, run `nice -n 19 .venv/bin/python -m pytest ...`, one process at a time. Tests must not touch real videos, the installed wrappers or `/usr/bin/sudo`.
- Commits are Julius's: never run `git commit` or `git push`. The work happens on the production Pi, so: never run production jobs, never edit the crontab or sudoers, never install or change anything as root (Julius installs the wrapper and the sudoers line himself), run heavy commands with `nice -n 19`, one heavy process at a time (2 GB RAM). A "Commit" step means: stage the listed paths (`git add <paths>`, never `git add .`), write the message to `<scratchpad>/commit-<n>.txt`, hand Julius `git commit -F <that file>`. The message ends with the `Co-Authored-By` line of the model that did the work.

## Review Focus

1. A corrupt manifest, wrong field types or an unknown schema number must be skipped, never break the page (Task 2).
2. Hostile strings in the manifest or the POST (`../`, a symlink, `<script>` in a label or file name, a camera named `..`) must neither escape the folder nor reach the HTML unescaped (Tasks 1, 2, 3, 4).
3. A manifest entry whose image file is gone (deleted by hand, or between listing and render) is dropped, not shown as a broken image (Task 2).
4. An unknown `days` value or an unknown camera filter falls back or shows an empty state, never an error page (Tasks 2, 4).
5. No highlights anywhere, or only cameras with nothing flagged, still renders a clear page (Task 4).

---

### Task 1: The delete wrapper

**Files:**
- Create: `scripts/timelapse-web-delete-highlight`
- Test: `tests/web_delete_highlight_test.py`

**Interfaces:**
- Produces: `scripts/timelapse-web-delete-highlight <camera> <date> <filename>`. Project root from `TIMELAPSE_PROJECT_ROOT`, else `~/timelapse` of the running user (same line as `scripts/timelapse-web-delete`). Prints `Bild erfolgreich gelöscht.` on success.

- [ ] **Step 1: Write the failing tests**, modelled on `tests/web_delete_test.py` (read it first; same `run_wrapper(project_root, *arguments)` helper pattern):

```python
def test_removes_the_image_and_nothing_else(tmp_path):
	# videos/Cam/highlights/2026-10-20/{a.jpg, b.jpg, manifest.json}
	# run("Cam", "2026-10-20", "a.jpg") -> 0, "Bild erfolgreich gelöscht." in stdout
	# a.jpg gone; b.jpg and manifest.json remain; another day's folder untouched
def test_wrong_argument_count_is_64(tmp_path): ...             # "Usage:" in stderr
@pytest.mark.parametrize("camera", ["", ".", "..", "../Cam", "Cam/x"])
def test_camera_traversal_is_64(tmp_path, camera): ...
@pytest.mark.parametrize("date", ["", "2026-10-2", "2026-13-45x", "../2026-10-20", "2026-10-20/x"])
def test_bad_date_is_64(tmp_path, date): ...
@pytest.mark.parametrize("name", ["", ".", "..", "../a.jpg", "sub/a.jpg", ".hidden.jpg", "a.png", "a.jpg.txt", "manifest.json", "a b.jpg"])
def test_bad_filename_is_64_and_leaves_files(tmp_path, name): ...
def test_missing_file_is_66(tmp_path): ...
def test_symlink_is_refused_and_target_kept(tmp_path): ...     # 66, link and target both remain
def test_a_video_path_cannot_be_reached(tmp_path): ...         # manual-runs file, same names -> 66
```
The date check is a strict `YYYY-MM-DD` shape in bash (`[[ $DATE =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]`); real calendar validity is not needed because a non-existing folder gives 66.

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/web_delete_highlight_test.py -v` expects FAIL (script missing).
- [ ] **Step 3: Implement the wrapper** with `set -euo pipefail`, the checks in the order of the Global Constraints, and `rm -- "$IMAGE_PATH"`. File mode 755.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `scripts/timelapse-web-delete-highlight tests/web_delete_highlight_test.py`, message `feat: add the highlight image delete wrapper`.

### Task 2: Highlights library

**Files:**
- Create: `web/src/highlights-library.php`
- Test: `tests/web_highlights_test.py`

**Interfaces:**
- Consumes (existing, `web/src/video-library.php`, loaded with `require_once __DIR__ . "/video-library.php"`): `projectRoot(): string`, `isValidIsoDate(string): bool`, `formatGermanDate(string): string`, `getIgnoredCameras(): array`.
- Produces (all in `highlights-library.php`):
  - `translateHighlightLabel(string $label): string`
  - `parseHighlightsPeriod(mixed $value): string` returns `"1"|"7"|"30"|"all"`, default `"7"`
  - `highlightsSinceDate(string $period, DateTimeImmutable $today): ?string` returns `today minus N days` as ISO date, `null` for `"all"`
  - `isValidHighlightCamera(string $camera): bool` (non-empty, no `/`, not starting with `.`, no control characters)
  - `isValidHighlightName(string $name): bool` (regex `^[A-Za-z0-9._-]+\.jpg$`, not starting with `.`)
  - `getFlaggerCameras(): array` (strings from `config.json` key `flagger.cameras`, `[]` when missing or malformed)
  - `listHighlightCameras(): array` (union of `getFlaggerCameras()` and every `videos/*/highlights` directory, valid names only, natural case-insensitive order)
  - `findHighlightDays(string $camera, ?string $sinceIso): array` returns `list<array{date: string, checked: int, items: list<array{file: string, url: string, time: string, group: string, label: string, score: float, box: array{int,int,int,int}, imageSize: array{int,int}}>}>`, newest day first, items in manifest order. `time` is `HH:MM` taken from `taken_at`; `url` is `/videos/<rawurlencode camera>/highlights/<date>/<rawurlencode file>`.

- [ ] **Step 1: Write the failing tests** with the harness from `tests/web_php_test.py`: reuse `run_php`, `PROJECT_ROOT_CALL` and the `videos_library` approach, but patch `video-library.php` and then load `highlights-library.php` in the driver code: `run_php(tmp_path, "video-library.php", {PROJECT_ROOT_CALL: json.dumps(str(tmp_path))}, 'require_once "<tmp_path>/php-src/highlights-library.php"; ' + code)`. Write a local helper `highlights(tmp_path, code)` for this and `make_day(tmp_path, camera, date, items, checked=10)` that writes `videos/<camera>/highlights/<date>/manifest.json` (schema 1) and the image files. Tests:

```python
def test_labels_period_and_names(tmp_path):
	...
	# translateHighlightLabel: bird->Vogel, airplane->Flugzeug, kite->Drachen, horse->Pferd, "zzz"->"zzz"
	# parseHighlightsPeriod: "1","7","30","all" kept; "8", "", null, [] -> "7"
	# highlightsSinceDate("7", 2026-10-21) == "2026-10-14"; ("all", ...) is null
	# isValidHighlightName: "a-1_b.2.jpg" true; "", ".a.jpg", "a.png", "a/b.jpg", "a b.jpg", "<x>.jpg" false
	# isValidHighlightCamera: "SLSV" true; "", ".", "..", "a/b", ".hidden" false


def test_days_are_newest_first_and_items_keep_manifest_order(tmp_path): ...
def test_period_limits_the_days(tmp_path): ...  # since filter keeps date >= since
def test_item_fields_and_url(tmp_path): ...  # time "08:14", url encoded, box ints, imageSize ints
def test_corrupt_or_wrong_schema_manifest_is_skipped(
	tmp_path,
): ...  # not json, schema 2, items not a list, item missing fields -> dropped, other days fine
def test_item_whose_image_is_missing_or_a_symlink_is_dropped(tmp_path): ...
def test_hostile_names_in_the_manifest_are_dropped(tmp_path): ...  # "../x.jpg", "a/b.jpg", ".h.jpg"
def test_unknown_group_is_dropped(tmp_path): ...  # only "animal" and "flying"
def test_day_without_remaining_items_keeps_its_checked_count(tmp_path): ...
def test_non_date_folders_and_symlinked_days_are_ignored(tmp_path): ...
def test_cameras_are_the_union_of_config_and_folders(
	tmp_path,
): ...  # config flagger.cameras ["A"], folder for "B" -> ["A","B"]; malformed config -> folders only
def test_unknown_camera_gives_no_days(tmp_path): ...
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/web_highlights_test.py -v` expects FAIL.
- [ ] **Step 3: Implement the functions.** Read manifests with `json_decode(..., true)` guarded by `is_array`; validate every field type before use; skip a day directory that is a symlink or whose name is not a valid ISO date; never throw on bad data.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `web/src/highlights-library.php tests/web_highlights_test.py`, message `feat: add the highlights library for the web UI`.

### Task 3: Delete call from PHP

**Files:**
- Create: `web/src/highlight-delete.php`
- Modify: `tests/web_highlights_test.py` (add tests)

**Interfaces:**
- Consumes: `projectRunUser(): ?string`, `runPrivilegedCommand(array): array{exitCode: ?int, stdout: string, stderr: string}` from `web/src/process-runner.php`.
- Produces: `deleteHighlightImage(string $camera, string $date, string $filename): array{deleted: bool, message: string}` calling `/usr/bin/sudo -n -u <runUser> /usr/local/sbin/timelapse-web-delete-highlight <camera> <date> <filename>`. Success message: the wrapper's stdout, else `Bild erfolgreich gelöscht.`; every failure: `Das Bild konnte nicht gelöscht werden.` (details only to `error_log`).

- [ ] **Step 1: Write the failing tests**, following the existing `video-delete.php` tests in `tests/web_php_test.py` (read them first: they replace `SUDO_PATH` in the copied file with a fake `sudo` script that records its arguments and exits with a chosen code, and replace the project-owner lookup the same way):

```python
def test_delete_calls_the_wrapper_with_exactly_three_arguments(
	tmp_path,
): ...  # recorded argv == ["-n","-u",<user>,"/usr/local/sbin/timelapse-web-delete-highlight","Cam","2026-10-20","a.jpg"]
def test_delete_reports_success_message(tmp_path): ...
def test_wrapper_failure_gives_the_generic_message_without_details(
	tmp_path,
): ...  # exit 66 and stderr text not in the message
def test_missing_run_user_refuses_without_calling_sudo(tmp_path): ...
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/web_highlights_test.py -v` expects the new tests FAIL.
- [ ] **Step 3: Implement** `highlight-delete.php` mirroring `video-delete.php` (same `require_once` of `process-runner.php`).
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `web/src/highlight-delete.php tests/web_highlights_test.py`, message `feat: add the highlight delete call`.

### Task 4: The page, navigation and styles

**Files:**
- Create: `web/public/highlights.php`
- Modify: `web/src/components/header.php` (one link `<a href="/highlights.php">Highlights</a>` inside the existing `<nav>`, after "Kameras"), `web/public/style.css` (append rules)
- Test: `tests/web_highlights_page_test.py`

**Interfaces:**
- Consumes: everything from Tasks 2 and 3; the session CSRF pattern from `web/public/camera.php`; the header's `$storage` variable (`getStorageUsage()` as in `index.php`).
- Produces: `GET /highlights.php?days=<1|7|30|all>&camera=<name>`; `POST /highlights.php` with fields `action=delete-highlight`, `csrf_token`, `camera`, `date`, `file`, `days`, `filter_camera`. After a valid delete it redirects to `/highlights.php?days=...&camera=...&deleted=1` and shows "Bild erfolgreich gelöscht." once.

Page content (all values escaped): `<h1>Highlights</h1>`; a labelled `<form method="get">` with a period `<select>` (Letzter Tag, 7 Tage, 30 Tage, Alles) and a camera `<select>` (Alle plus the known cameras); per camera an `<h2>` with the number of images; per day an `<h3>` with the German date and "N Bilder geprüft"; per image a `<figure>` with `<img loading="lazy" width height alt>`, a `<figcaption>` (time, German label with `?`, score as whole percent), a download `<a href download>` and a delete `<form>` with the hidden fields and a confirm `<dialog>` copied in behaviour from `camera.php` (inline script, `window.confirm` fallback; duplicated on purpose, because changing `camera.php` is out of scope); one line above the list "Die Bilder sind nicht verpixelt. Vor einer Veröffentlichung verpixeln."; a checkbox "Markierung zeigen" that toggles absolutely positioned box overlays computed from `box` and `imageSize` in percent; empty states "Noch keine Highlights vorhanden." and, for a camera without items, "geprüft, nichts gefunden".

- [ ] **Step 1: Write the failing render tests.** Copy `web/` into `tmp_path/web` (`shutil.copytree`), swap `PROJECT_ROOT_CALL` in the copied `web/src/video-library.php` for the temp project path, build `tmp_path/videos/...` fixtures and `tmp_path/config/config.json`, and render the page with the PHP CLI: `php -d session.save_path=<tmp> -d display_errors=1 -r '<set $_GET/$_POST/$_SERVER, preset session token, require the page>'` and assert on stdout. For POST tests, preset the session first (`session_start(); $_SESSION["csrf_token"]="tok"; session_write_close();`) and replace `SUDO_PATH` in the copied `highlight-delete.php` with the fake `sudo` from Task 3.

```python
def test_page_shows_cameras_days_and_images(...):        # h1, camera h2, German date, "143 Bilder geprüft", the "nicht verpixelt" line, alt contains camera, time and "Flugzeug", download link has "download", csrf field present
def test_default_period_is_seven_days(...):              # a day 10 days old is absent, a 3-day-old one present; ?days=all shows both; ?days=bogus behaves like 7
def test_camera_filter_and_unknown_camera(...):          # ?camera=B shows only B; ?camera=Nope shows the empty state, HTTP content still renders
def test_configured_camera_without_items_is_listed(...): # "geprüft, nichts gefunden"
def test_no_highlights_at_all_shows_the_empty_message(...):
def test_hostile_label_and_name_are_escaped_or_dropped(...):   # label "<script>alert(1)</script>" appears only escaped; name with ".." never rendered
def test_post_with_bad_token_deletes_nothing(...):       # message "Die Anfrage ist ungültig", fake sudo not called
def test_post_with_valid_token_calls_the_wrapper_once(...):    # recorded argv for the posted camera/date/file
def test_post_for_an_image_not_in_the_listing_is_refused(...): # fake sudo not called
def test_post_with_unknown_camera_is_refused(...):
def test_navigation_link_exists_in_the_header(...):      # header.php renders href="/highlights.php" next to "Kameras"
```
The redirect after a successful delete is not asserted through headers (the CLI does not expose them); assert the wrapper call and that the output is empty.

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/web_highlights_page_test.py -v` expects FAIL.
- [ ] **Step 3: Implement the page, the header link and the CSS.** Reuse the existing CSS variables (`--color-*`, `--radius-*`); new class names prefixed `highlights-`; visible focus styles on the new buttons and links.
- [ ] **Step 4: Run** `python -m pytest tests/web_highlights_page_test.py tests/web_highlights_test.py tests/web_php_test.py -v` and `php -l web/public/highlights.php`. Expected: PASS, "No syntax errors detected". The existing web tests must still pass.
- [ ] **Step 5: Commit:** paths `web/public/highlights.php web/src/components/header.php web/public/style.css tests/web_highlights_page_test.py`, message `feat: add the highlights page to the web UI`.

### Task 5: Reinstall path for the wrapper

**Files:**
- Modify: `migrate.sh`, `README.md` (section "Wrapper installieren")

Applies while the program runs on the Pi; obsolete if it later moves to a VPS. `backup-from-mac.sh` needs no change: it already backs up the whole `/etc/sudoers.d/timelapse-web`.

- [ ] **Step 1: `step_web_bridge`:** one more line next to the existing two: `sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/timelapse-web-delete-highlight" /usr/local/sbin/timelapse-web-delete-highlight`.
- [ ] **Step 2: sudoers check on restore** (next to the trigger/delete checks): when the backed-up file lacks `/usr/local/sbin/timelapse-web-delete-highlight`, `warn` (not `fail`, so backups from before this feature still restore) and name the line to add with `visudo`. Note that a plain `grep -q "/usr/local/sbin/timelapse-web-delete"` also matches the new name, so the new check must match the full name.
- [ ] **Step 3: `step_verify`:** report whether `/usr/local/sbin/timelapse-web-delete-highlight` is installed (`warn` if not), like the existing checks there.
- [ ] **Step 4: README "Wrapper installieren":** the `sudo install` command and the third sudoers line `www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight` next to the existing two; check that "Neuinstallation des Raspberry Pi" needs nothing because `migrate.sh` does it.
- [ ] **Step 5: Verify:** `bash -n migrate.sh` and read the diff. Never run `migrate.sh` (it changes the live system).
- [ ] **Step 6: Commit:** paths `migrate.sh README.md`, message `feat: install the highlight delete wrapper on reinstall`.

### Task 6: Documentation and hand-over

**Files:**
- Create: `docs/highlights-seite.md` (German)
- Modify: `README.md` ("Aktueller Funktionsumfang", "Webdateien")

- [ ] **Step 1: Write `docs/highlights-seite.md`:** what the page shows, the filters, the folder layout it reads (`videos/<camera>/highlights/<date>/`, `manifest.json`), delete and the confirm dialog, the 30-day cleanup done by the flagger (see `docs/flagger.md`), and the one-time install on the Pi in the style of the README's "Wrapper installieren": `sudo install -o root -g root -m 755 scripts/timelapse-web-delete-highlight /usr/local/sbin/timelapse-web-delete-highlight`, the sudoers line `www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight` added with `sudo visudo -f /etc/sudoers.d/timelapse-web`, and the reminder to reinstall after changes. Note that a re-run of the flagger for a day brings deleted images of that day back.
- [ ] **Step 1b: README:** one bullet for the Highlights page in "Aktueller Funktionsumfang" with a link to `docs/highlights-seite.md`, and the three new PHP files in "Webdateien".
- [ ] **Step 2: Run the whole web test set:** `python -m pytest tests/web_*.py -v`. Expected: PASS.
- [ ] **Step 3:** `ruff check .`, `ruff format --check .`, and `git diff --stat` shows no change to `camera.php`, `index.php`, `video-library.php`, `video-delete.php`, `job-*.php` or the existing wrappers.
- [ ] **Step 4: Commit:** paths `docs/highlights-seite.md README.md`, message `docs: describe the highlights page`.
- [ ] **Step 5: Hand Julius** the commit commands and the checks on the Pi, in this order: install the wrapper and the sudoers line as documented; create a sample report by hand or with the flagger's test mode into `videos/<camera>/highlights/<date>/`; open `/highlights.php` and check the filters, the images, the download, the delete with confirm (the file disappears and the page shows the message), and a camera with nothing flagged; try `curl -i http://localhost/highlights.php` for the 401 without a login; check `apache2` error log for PHP warnings.
