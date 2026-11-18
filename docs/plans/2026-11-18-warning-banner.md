# Warnings Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A banner on every web UI page that shows only what Julius has to act on (or `Nichts zu melden.`),
fed by a collector at the end of the 02:00 cron line, the blur watchdog's status file and two live checks.

**Architecture:** Python writes two small JSON files into `state/web-jobs/` (the folder the web already
reads `cameras.json` from): `warnings.json` by a new collector step after the night, `blur-watch.json`
by the existing 5-minute watchdog. A PHP reader turns both files plus the storage level and the clock
into a list of German messages; a header component prints it.

**Tech Stack:** Python 3.13 (runnable on 3.11), bash (`install.sh`), PHP 8.4, pytest (PHP through the
`php` CLI driver pattern of `tests/web/`).

**Spec:** `docs/plans/2026-11-18-warning-banner-design.md`

## Global Constraints

- Only the messages of the spec's Goals table; no routine warnings, no "camera fell silent".
- Always visible; nothing to report shows `Nichts zu melden.`; no dismiss button.
- Message and hint texts are German; Python makes the night's texts, PHP only the live ones.
- A missing, unreadable or stale file never reads as "nothing to report".
- `logs/siteground-delivery.log` stays mode 600; only the collector (project user) reads it. The
  colleague's upload script is not changed.
- No new cron entry: the 02:00 line gains a night marker before the upload and the collector at the end.
- Time zone from `config.json` `location.timezone` (Europe/Berlin) on both sides.
- Files: atomic write, folder 0755, file 0644 (the `src/camera_list.py` pattern).
- Project rules: Claude runs no pytest (Julius runs it in Docker, `docs/docker-web.md`); one task at a
  time, tests first, stop for Julius's check and commit; `ruff format` + `ruff check` on edited Python
  files only; web style changes load the `zeitraffer-web-css` skill first. German docs.

## Review Focus

1. A night where the wrapper never made a run folder (lock held at 02:00): one "Nachtlauf nicht
   gestartet" message, no FAILED lines from the night before. Test in Task 2.
2. A daytime web upload after the night: the night's upload verdict must not change. Test in Task 3.
3. The banner opened between 02:00 and 06:00: yesterday's file still counts, no "Nachtlauf fehlt".
   Test in Task 5.
4. A broken JSON file (half a file, wrong types): treated as missing, never as green. Tests in Task 5.
5. A camera name with spaces or HTML characters in a message: printed escaped. Test in Task 5.

## Messages (exact texts)

| Rule | camera | text | hint |
|---|---|---|---|
| night not started | null | `Nachtlauf nicht gestartet` | `Sperre belegt oder Startfehler; Handbuch „Heute Nacht lief nichts“` |
| interrupted (+ `FAILED (run)`) | null | `Nachtlauf unterbrochen` | `Lauf von Hand wiederholen; Handbuch „Lauf wurde nach einem Neustart nicht wiederholt“` |
| `FAILED (run)` alone | null | `Nachtlauf fehlgeschlagen: <reason>` | `Bericht des Nachtlaufs lesen` |
| camera `FAILED` | camera | `Fehlgeschlagen: <reason>` | `Ursache im Bericht beheben, Kamera nachholen` |
| Storage Box | null | `Storage Box nicht erreichbar` | `Handbuch „Kamera-Speicher nicht erreichbar“` |
| unreadable names | camera | `<n> Bildnamen nicht lesbar` | `Neue Schreibweise? Handbuch „Unlesbare Dateinamen“` |
| flagger | camera or null | `Flagger: <log message>` | `Handbuch „Flagger startet nicht oder überspringt“` |
| blur gate | camera | `Kein bestätigtes Bild, Tagesvideo ausgelassen` | `Läuft die Verpixelung? Handbuch „Verpixelung“` |
| model missing | null | `Erkennungsmodell fehlt: <relative path>` | `Handbuch „Modelldatei fehlt“` |
| upload failed | null | `Upload auf die Website fehlgeschlagen (<n> Kameras)`, without a count `Upload auf die Website fehlgeschlagen` | `Upload-Protokoll prüfen; die nächste Nacht lädt erneut hoch` |
| upload not run | null | `Upload auf die Website lief nicht` | `Cron-Zeile prüfen` |
| (PHP) night missing | null | `Nachtlauf fehlt` | `Handbuch „Heute Nacht lief nichts“` |
| (PHP) disk | null | `Speicher wird knapp` / `Speicher fast voll` | `Alte Videos löschen; Handbuch „Festplatte voll“` |
| (PHP) stale images | camera | `<n> Bilder seit über 10 Minuten unverpixelt` | `Verpixelungs-Protokoll prüfen; Handbuch „Verpixelung“` |
| (PHP) watchdog silent | null | `Verpixelungs-Wächter läuft nicht` | `Cron-Zeile des Wächters prüfen` |
| (PHP) watchdog error | null | `Verpixelungs-Wächter: <error>` | `Storage Box erreichbar? Handbuch „Verpixelung“` |

---

### Task 1: Shared writer and the watchdog's status file

**Files:**
- Create: `src/web_state.py`
- Modify: `src/privacy/blur_watch.py` (`main`)
- Test: `tests/web_state_test.py`, `tests/privacy/privacy_blur_watch_test.py`

**Interfaces:**
- Produces: `WEB_STATE_ROOT = PROJECT_ROOT / "state" / "web-jobs"`;
  `write_web_json(destination: Path, payload: object) -> None` (temp file in the same folder, 0644,
  `os.replace`, folder 0755);
  `blur_watch.STATUS_PATH = WEB_STATE_ROOT / "blur-watch.json"`, written on every `main()` run as
  `{"checked": "<ISO time with offset>", "stale": {"<camera>": <int>}, "error": "<text>" | null}`.

- [ ] **Step 1: Write the failing tests.** `web_state_test.py`:
  `test_write_web_json_replaces_the_file_readable_for_the_web` (content round-trips with `json.loads`,
  mode `0o644`, no temp file left). `privacy_blur_watch_test.py` (monkeypatch `STATUS_PATH` into
  `tmp_path`): `test_status_file_lists_stale_counts` (camera A 2 stale, B 0 → `{"A": 2, "B": 0}`,
  `error` null, `checked == now.isoformat()`), `test_status_file_records_an_unreachable_box`
  (`get_storage_box` raises `OSError("no box")` → `error` contains `no box`, exit code 1),
  `test_status_file_records_a_failed_camera_check`.
- [ ] **Step 2: Julius runs them** (`… -m pytest tests/web_state_test.py tests/privacy/privacy_blur_watch_test.py -q`).
  Expected: the new tests FAIL (module or attribute missing).
- [ ] **Step 3: Implement** `src/web_state.py` and the status write in `blur_watch.main` on all three
  paths, after the existing log lines; a failing write is logged at ERROR, never raised.
- [ ] **Step 4: Julius runs the two files and the full suite.** Expected: PASS.
- [ ] **Step 5: ruff on the edited files; Julius commits** (`feat: watchdog writes a status file for the web UI`).

### Task 2: Collector, night part

**Files:**
- Create: `src/night_warnings.py`
- Test: `tests/night_warnings_test.py`

**Interfaces:**
- Consumes: `write_web_json`, `WEB_STATE_ROOT` (Task 1).
- Produces: `WARNINGS_PATH = WEB_STATE_ROOT / "warnings.json"`;
  `collect(now: datetime, project_root: Path) -> dict` returning
  `{"night": {"date": "YYYY-MM-DD", "run": "<folder>" | None, "started": "<ISO>" | None, "finished": now.isoformat()}, "messages": [{"camera": str | None, "text": str, "hint": str}]}`;
  `main() -> int` (time zone from config, writes `WARNINGS_PATH`, exit 0 also with messages).
  Run folder: newest `logs/nightly/<YYYYMMDD-HHMMSS>/`; it is "this night" only if its date equals
  `now.date()`; `started` is the folder name read in the config time zone.

- [ ] **Step 1: Write the failing tests** (fake project in `tmp_path` with
  `logs/nightly/<run>/report.txt`, `main.out`, `state/run-in-progress`; texts from the Messages table):
  `test_a_clean_night_has_no_messages`; `test_a_missing_run_folder_gives_night_not_started` (only
  yesterday's folder, with `   FAILED: x` in its report → exactly one message `Nachtlauf nicht gestartet`;
  Review Focus 1); `test_failed_camera_lines_are_reported` (`== Bravo Cam` then
  `   FAILED: the log names it as failed; (see …)` → camera `Bravo Cam`);
  `test_run_marker_and_failed_run_give_one_interrupted_message`; `test_failed_run_alone`;
  `test_storage_box_unreachable_from_main_out`; `test_unreadable_names_from_the_report`
  (`   WARNING: 856 image names cannot be read` under `== Strandterrassen` → `856 Bildnamen nicht lesbar`);
  `test_main_writes_the_file_also_without_messages`.
- [ ] **Step 2: Julius runs them.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `collect` for these rules and `main`; the report is read by camera block
  (`== <camera>` starts a block).
- [ ] **Step 4: Julius runs the file and the full suite.** Expected: PASS.
- [ ] **Step 5: ruff; Julius commits** (`feat: collect the night's warnings for the web UI`).

### Task 3: Collector, flagger, privacy and upload

**Files:**
- Modify: `src/night_warnings.py`
- Test: `tests/night_warnings_test.py`

**Interfaces:**
- Consumes: `collect` (Task 2). Log lines are `YYYY-MM-DD HH:MM:SS,mmm | LEVEL | message`; only lines
  between the run's `started` and `now` count. Without a run folder these rules count from 02:00 of
  `now.date()`.
- Model paths: the value after `--model` in `config["privacy"]["detector_command"]` and
  `src.flagger.run.DEFAULT_MODEL`, relative ones resolved against `project_root`; one message per
  missing path (both point at the same file today, so normally one).
- Upload block: the lines after the last `=== Nachtlauf <now.date()> ===` in
  `logs/siteground-delivery.log`, read at `collect()` time (the collector runs right after the night's
  upload in the same cron line). Failed when a line has `fehlgeschlagen=` above 0 (count these lines for
  `(<n> Kameras)`), or contains `Mindestens eine Kamera ist fehlgeschlagen.` or
  `SITEGROUND_HOST, SITEGROUND_USER und SITEGROUND_PASS müssen ausgefüllt sein.`; no marker for
  `now.date()` → `Upload auf die Website lief nicht`.

- [ ] **Step 1: Write the failing tests:** `test_flagger_errors_are_reported`
  (`[Strandterrassen] none of 38 images could be read - nothing written` → camera `Strandterrassen`;
  `Flagger not started: …` → camera null); `test_flagger_lines_before_the_run_are_ignored`;
  `test_blur_gate_from_the_daily_log_only` (the same line in `logs/monthly/<date>.log` gives nothing);
  `test_missing_model_is_reported_once_per_path`; `test_upload_failure_counts_cameras`;
  `test_upload_without_marker_did_not_run`; `test_upload_all_skipped_is_not_a_failure`;
  `test_upload_verdict_is_taken_at_collect_time` (a clean night block; `collect()` → no upload message;
  lines with `fehlgeschlagen=1` appended afterwards do not change the earlier result; Review Focus 2).
- [ ] **Step 2: Julius runs them.** Expected: FAIL.
- [ ] **Step 3: Implement the four rules** in `collect`.
- [ ] **Step 4: Julius runs the file and the full suite.** Expected: PASS.
- [ ] **Step 5: ruff; Julius commits** (`feat: report flagger, privacy and upload problems of the night`).

### Task 4: The cron line

**Files:**
- Modify: `install.sh` (`cron_hint`: the 02:00 line and its comment, about lines 447-455)
- Test: `tests/scripts/install_cron_hint_test.py`
- Modify (docs): `docs/vps.md` (cron line), `docs/handbuch.md` „Was wann läuft“

**Interfaces:**
- The 02:00 line becomes: blur catch-up `;` nightly wrapper `;`
  `echo "=== Nachtlauf $(date +\%F) ===" >> ${PROJECT_ROOT}/logs/siteground-delivery.log;` upload `;`
  flagger `;` `${PROJECT_ROOT}/.venv/bin/python3 -m src.night_warnings` (`%` escaped for cron).

- [ ] **Step 1: Write the failing test** `test_cron_hint_marks_the_upload_and_ends_with_the_collector`:
  the printed `0 2` line has the marker `echo` before `copy_zeitraffer_videos_vps2siteground.sh`,
  contains `\%F`, ends with `-m src.night_warnings`; still exactly one `0 2` line.
- [ ] **Step 2: Julius runs it.** Expected: FAIL.
- [ ] **Step 3: Implement** the line and its comment; docs.
- [ ] **Step 4: Julius runs the file, the full suite and `bash -n install.sh`.** Expected: PASS.
- [ ] **Step 5: Julius commits** (`feat: cron line marks the night's upload and runs the collector`).
  After the merge he pastes the new line on the VPS (`./install.sh cron_hint`, `crontab -e`).

### Task 5: The banner

**Files:**
- Create: `web/src/warnings.php`, `web/src/components/warning-banner.php`
- Modify: `web/src/components/header.php` (require the banner after `</header>`), `web/public/style.css`
- Test: `tests/web/web_warning_banner_test.py`
- Modify (docs): `docs/weboberflaeche.md`, `docs/handbuch.md` (new section „Meldungen in der Weboberfläche“)

**Interfaces:**
- Consumes: `warnings.json` and `blur-watch.json` (Tasks 1-3) from
  `getenv("TIMELAPSE_WEB_STATUS_ROOT") ?: projectRoot() . "/state/web-jobs"` (the root `job-state.php`
  uses); the storage level from `$storage["level"]`; the time zone from
  `readProjectConfig()["location"]["timezone"]`.
- Produces: `bannerMessages(DateTimeImmutable $now, ?array $storage): array` returning
  `["messages" => list<array{camera: ?string, text: string, hint: string}>, "lastRun" => ?string]`
  (`lastRun` like `18.11.2026, 02:00–02:55 Uhr`, null without a readable night). Live rules: night
  missing (file missing or broken, or `$now` at or after 06:00 and `night.date` ≠ today); disk
  (`warn`, `critical`); each camera with `stale` above 0; watchdog file missing, broken or `checked`
  older than 15 minutes; `error` not null.

- [ ] **Step 0:** load the `zeitraffer-web-css` skill.
- [ ] **Step 1: Write the failing tests** (driver pattern of `web_header_test.py`, env
  `TIMELAPSE_WEB_STATUS_ROOT` pointing at `tmp_path`): `test_nothing_to_report` (fresh files, 07:00 →
  no messages, page shows `Nichts zu melden.` and the `lastRun` text); `test_night_messages_are_shown`;
  `test_missing_file_is_not_green`; `test_broken_json_is_not_green` (Review Focus 4);
  `test_before_six_yesterday_still_counts` and `test_after_six_yesterday_is_missing` (Review Focus 3);
  `test_stale_watchdog_file`; `test_stale_images_per_camera`; `test_disk_level_warn_and_critical`;
  `test_camera_names_are_escaped` (`<b>Cam & Co</b>`, Review Focus 5);
  `test_every_page_shows_the_banner` (the five pages require `header.php`).
- [ ] **Step 2: Julius runs them.** Expected: FAIL.
- [ ] **Step 3: Implement** the reader, the component (✓ or ⚠ plus text, a list with camera, text and
  hint per message, the `lastRun` line, `role="status"`), CSS with the skill's tokens, docs. Existing
  header tests: if one asserts the absence of a word the banner now adds, adapt only that assertion
  and say why.
- [ ] **Step 4: Julius runs the file and the full suite, and looks at it in the Docker web setup** with
  the fake files from the tests. Expected: PASS; the banner green and orange as in the spec's sketch.
- [ ] **Step 5: Julius commits** (`feat: warnings banner on every web UI page`).
