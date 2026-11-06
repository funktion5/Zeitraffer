# Rebuild and publish buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two web UI features on a camera page: a Rebuild form (checkboxes per job) that reruns the automatic night jobs for one camera, and ONE Publish button that sends that camera's videos to SiteGround through the existing delivery script.

**Architecture:** `src.main` learns to run automatic jobs for chosen cameras. Two new root-owned wrapper pairs (trigger + worker), modelled on `timelapse-web-trigger` / `timelapse-web-worker`, share the run lock and the status files; PHP runners call the triggers through sudo; `camera.php` gets two POST actions and two form sections; each worker leaves plain German result lines next to the status file.

**Tech Stack:** Python 3.13 (stays runnable on 3.11), PHP (plain, behind Apache), Bash, pytest (PHP and Bash tested as subprocesses).

**Spec:** `docs/plans/2026-11-06-rebuild-and-publish-buttons.md` (approved by Julius 2026-11-06). One correction to it: the delivery script's dry run makes no FTP connection, so the confirm window lists the files that WOULD be sent (newest automatic video per period); "already on the site" shows afterwards as "übersprungen" in the result.

## Global Constraints

- Tabs for indentation (Python, PHP, Bash); ruff: 100 columns, double quotes. Comments in English and explain why; all user-facing text German.
- No new dependency. The delivery script and the existing wrappers (`timelapse-web-trigger`, `timelapse-web-worker`, `timelapse-web-delete`, `timelapse-web-delete-highlight`, `timelapse-web-status.sh`) are NOT edited.
- Test first, one task at a time. After each task: STOP. Julius runs `python -m pytest` and `ruff check .` / `ruff format --check .` on the VPS after `git pull`; Claude runs neither anywhere (offline checks only: `bash -n`, `php -l`, syntax parse). Julius commits; no Co-Authored-By trailer; stage files by name, never `git add .`.
- New wrapper names: triggers `timelapse-web-rebuild`, `timelapse-web-publish` (installed to `/usr/local/sbin`); workers `timelapse-web-worker-rebuild`, `timelapse-web-worker-publish` (installed to `/usr/local/libexec`). A worker name MUST contain `timelapse-web-worker`: `isWorkerPidAlive()` (`web/src/job-state.php:16`) looks for that string in `/proc/<pid>/cmdline` and would otherwise mark a running job failed.
- All new wrappers: same lock file (`state/zeitraffer-run.lock`, env `TIMELAPSE_WEB_LOCK_FILE`), exit 75 when it is held; same status files via `timelapse-web-status.sh` (`write_job_status`, `write_job_pid`, `is_valid_job_id`, `STATUS_ROOT`); same env overrides as the existing pair (`TIMELAPSE_PROJECT_ROOT`, `TIMELAPSE_WEB_STATUS_HELPER`, `TIMELAPSE_WEB_STATUS_ROOT`, `TIMELAPSE_WEB_PYTHON`).
- Camera names: `^[A-Za-z0-9][A-Za-z0-9._-]*$` AND listed in `state/web-jobs/cameras.json`. No path, host, login or file name ever comes from the browser.
- A worker writes `<STATUS_ROOT>/<jobId>.result` (plain German display lines, max 8) BEFORE it writes the final status.
- No local paths, account names or logins in tracked files. Claude never runs the wrappers or the delivery script and never touches SiteGround.

## Review Focus

Failure modes the spec implies, each pinned by a test in the owning task:
1. Rebuild with no job ticked, or an unknown job value ("hourly"): refused on the server, no sudo call (T2, T3).
2. The same job twice, or jobs sent out of order: each runs once, in the fixed order daily, weekly, monthly, yearly (T2).
3. Publish without exactly `confirm=yes`, or with a missing or wrong CSRF token: refused, nothing started (T5).
4. Camera name `../x`, empty, `.`, or not in the camera list: refused (T2, T4).
5. Run lock held (another job or the night run): a "läuft bereits" message, nothing started (T2, T4).
6. The delivery script prints no `Ergebnis:` line (for example an empty list) or reports `fehlgeschlagen` above 0: status failed, not completed (T4).

---

### Task 1: `src.main` runs automatic jobs for chosen cameras

**Files:**
- Modify: `src/main.py` (the `--cameras` help text ~46-52, the check at ~154-155, the camera filter at ~234-235)
- Test: `tests/main_test.py`

**Interfaces:**
- Consumes: `require_cameras(requested, available)` (existing, raises `ValueError` for an unknown camera).
- Produces: `python -m src.main --jobs <job>... --cameras <camera>...` without `--target-date` runs those automatic jobs for those cameras only, writes to `videos/<camera>/<job>/`, and is NOT the production run (`automatic_production_run` stays False, so `mark_run_started`/`mark_run_finished` are not called). A bare `--cameras` (no `--date`, no `--jobs`) still raises.

- [ ] **Step 1: Write the failing tests** in `tests/main_test.py`, using `patch_common_runtime` and `patch_automatic_jobs` as `test_main_filters_historical_jobs_to_requested_cameras` (line 903) does:
  - `test_main_runs_automatic_jobs_for_requested_cameras_only` (replaces `test_main_rejects_camera_filter_for_automatic_jobs`, line 828): `make_arguments(cameras=["Camera-A"], jobs=["monthly", "daily"])`; assert the jobs ran in the order daily, monthly; each call has `cameras == ["Camera-A"]` and `manual_run is False`; the run-state marker was not started (record `mark_run_started` if the fixture does not).
  - `test_main_rejects_unknown_camera_for_automatic_jobs`: copy of `test_main_rejects_unknown_camera_for_historical_jobs` (line 990) without a date, with `jobs=["daily"]`.
  - `test_main_rejects_camera_filter_without_date` (line 690, keep): change only its `match` to `--cameras can only be used with --date or --jobs.`
- [ ] **Step 2: Run to see them fail.** Julius: `python -m pytest tests/main_test.py -v`. Expected: the first, second and third fail.
- [ ] **Step 3: Implement** in `main()`: the check becomes `if args.cameras and not args.date and not args.jobs:` raising `ValueError("--cameras can only be used with --date or --jobs.")`; the filter runs whenever `args.cameras` is set (the check above guarantees a date or jobs); the `--cameras` help text names automatic jobs too. Nothing else.
- [ ] **Step 4: Run.** Julius: `python -m pytest tests/main_test.py -v`, then the full suite, then ruff. Expected: all pass.
- [ ] **Step 5: STOP.** Julius checks and commits (Claude hands over the file list and a message).

### Task 2: Rebuild wrappers and install lines

**Files:**
- Create: `scripts/web/timelapse-web-rebuild`, `scripts/web/timelapse-web-worker-rebuild`
- Modify: `install.sh` (`step_web_bridge` ~248-253 installs, ~260-264 sudoers heredoc, `step_verify` ~354-362)
- Test: `tests/web/web_rebuild_test.py` (patterns: `test_web_trigger_writes_running_and_launches_worker`, `web_status_test.py:375`; `test_web_worker_reads_frames_over_ssh_from_the_default_box`, `:220`)

**Interfaces:**
- Produces: trigger `timelapse-web-rebuild <job-id> <camera> <job> [<job> ...]` (1 to 4 jobs from daily|weekly|monthly|yearly; exit 64 bad arguments, 66 camera not listed, 69 support files missing, 75 lock held, 0 started with the message `Videoauftrag gestartet (PID <n>).`). It sorts and de-duplicates the jobs and starts `timelapse-web-worker-rebuild <job-id> <camera> <job>...` in the background. Worker override env: `TIMELAPSE_WEB_WORKER_REBUILD`.
- The worker runs `$PYTHON -m src.main --jobs <jobs> --cameras <camera>` WITHOUT `--target-date`, with `TIMELAPSE_FRAME_SOURCE=ssh` and the box default as the existing worker. It keeps stderr in a temp file, writes `<jobId>.result` with one German line per `<Job> timelapse job finished ... created=N ... skipped=N ... failed=N` log line, in the form `Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen` (labels as `translateJobLabel()`, `web/src/video-library.php:7`), then status `completed` when `src.main` exits 0, otherwise `failed` plus the existing reason mechanism.

- [ ] **Step 1: Write the failing tests** (`tests/web/web_rebuild_test.py`; fake worker and fake python as in the patterns):
  - `test_rebuild_trigger_starts_the_worker_with_jobs_in_fixed_order`: arguments `monthly daily` reach the fake worker as `daily monthly`; status file says `running`.
  - `test_rebuild_trigger_runs_each_job_once`: `daily daily` becomes `daily`.
  - `test_rebuild_trigger_rejects_no_job_an_unknown_job_and_a_fifth_value`: exit 64, worker not started.
  - `test_rebuild_trigger_rejects_unsafe_camera_names`: `../x`, an empty name, `.`: exit 64.
  - `test_rebuild_trigger_rejects_an_unlisted_camera`: exit 66.
  - `test_rebuild_trigger_refuses_while_the_lock_is_held`: exit 75, no status file.
  - `test_rebuild_worker_runs_main_for_one_camera_without_a_target_date`: the fake python records `-m src.main --jobs daily monthly --cameras Cam` and no `--target-date`.
  - `test_rebuild_worker_writes_one_german_result_line_per_job`: fake output has a Daily line (`created=1`) and a Yearly line (`skipped=1`); expect the two lines in `.result` and status `completed`.
  - `test_rebuild_worker_marks_failed_when_main_exits_nonzero`: exit 3 gives status `failed`.
- [ ] **Step 2: Run to see them fail.** Julius: `python -m pytest tests/web/web_rebuild_test.py -v`. Expected: FAIL (scripts missing).
- [ ] **Step 3: Implement both scripts** by copying the structure, validation helpers and error style of `timelapse-web-trigger` / `timelapse-web-worker`; only the arguments, the command and the result file differ.
- [ ] **Step 4: `install.sh`:** install the two new files with the same `sudo install` lines, add `www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-rebuild *` to the sudoers heredoc, add a verify grep for it. Offline check: `bash -n install.sh scripts/web/timelapse-web-rebuild scripts/web/timelapse-web-worker-rebuild`.
- [ ] **Step 5: Run.** Julius: the new test file, the full suite, ruff. Expected: pass.
- [ ] **Step 6: STOP.** Julius commits. Later on the VPS (not needed for this commit): `git pull`, `./install.sh`, `./install.sh verify`.

### Task 3: Rebuild form on the camera page and result display

**Files:**
- Create: `web/src/rebuild-runner.php`
- Modify: `web/public/camera.php` (POST block, pattern `create-video` ~149-233; form section above `#create-video-form` ~478), `web/public/job-status.php`, `web/src/job-state.php`, `web/src/components/job-watcher.php`
- Test: `tests/web/web_php_test.py`, `tests/web/web_status_endpoint_test.py`, `tests/web/web_camera_page_test.py`

**Interfaces:**
- Consumes: `projectRunUser(): ?string`, `runPrivilegedCommand(array $command): array` (`web/src/process-runner.php`).
- Produces: `startRebuildJob(string $camera, array $jobs): array` returning `["started" => bool, "jobId" => ?string, "message" => string]` (same shape as `startVideoJob`; exit 75 gives "Es läuft bereits ein anderer Zeitraffer-Auftrag."); `readJobResults(string $statusRoot, string $jobId): array` returning the lines of `<jobId>.result` (max 8), `[]` without the file; `job-status.php` adds `"results": [...]` to a 200 answer when lines exist.
- POST action `rebuild-jobs`: fields `camera`, `csrf_token`, `rebuild_jobs[]` (values from daily|weekly|monthly|yearly).

- [ ] **Step 1: Write the failing tests:**
  - `web_php_test.py`: `test_start_rebuild_job_calls_the_trigger_with_camera_and_jobs`, `test_start_rebuild_job_reports_a_busy_lock`, `test_read_job_results_returns_the_lines_or_nothing`.
  - `web_status_endpoint_test.py`: `test_status_endpoint_includes_results_when_the_file_exists`.
  - `web_camera_page_test.py` (patterns `test_started_job_redirects_and_reaches_the_watcher_once`, `fake_sudo`, `render_page`): `test_rebuild_without_a_ticked_job_is_refused_without_calling_sudo`, `test_rebuild_with_an_unknown_job_is_refused`, `test_rebuild_with_a_bad_csrf_token_is_refused`, `test_rebuild_with_valid_jobs_starts_the_job_and_redirects` (the fake sudo log shows `timelapse-web-rebuild <jobId> <camera> daily monthly`), `test_rebuild_form_checkboxes_start_unticked_and_the_button_is_disabled`.
- [ ] **Step 2: Run to see them fail.** Julius: the three test files. Expected: FAIL.
- [ ] **Step 3: Implement** `startRebuildJob` (command as `startVideoJob`, trigger `/usr/local/sbin/timelapse-web-rebuild`); in `camera.php` the `rebuild-jobs` action after the CSRF and camera checks: keep only known values, refuse an empty selection with a German message, on success store `$_SESSION["started_job"]` and redirect exactly as `create-video` does; the form section "Neu erstellen wie der Nachtlauf": four unticked checkboxes, a hint at Weekly ("baut auf den vorhandenen Daily-Videos auf, bei fehlendem Daily mit ankreuzen"), the note that it takes long, and a submit button disabled until a box is ticked (a few lines of inline script; without script the server still refuses an empty selection); `job-watcher.php` prints `results` lines with `textContent` under the final message.
- [ ] **Step 4: Run.** Julius: the three files, the full suite, ruff, `php -l` on the changed files. Expected: pass.
- [ ] **Step 5: STOP.** Julius browser-checks (Docker or VPS) and commits. First VPS test: one camera, only Daily ticked.

### Task 4: Publish wrappers and install lines

**Files:**
- Create: `scripts/web/timelapse-web-publish`, `scripts/web/timelapse-web-worker-publish`
- Modify: `install.sh` (same places as Task 2)
- Test: `tests/web/web_publish_test.py`

**Interfaces:**
- Produces: trigger `timelapse-web-publish <job-id> <camera>` (exit codes as Task 2; worker override env `TIMELAPSE_WEB_WORKER_PUBLISH`). The worker runs `bash "$PUBLISH_SCRIPT" "$CAMERA" --run`, with `PUBLISH_SCRIPT=${TIMELAPSE_WEB_PUBLISH_SCRIPT:-$PROJECT_ROOT/scripts/copy_zeitraffer_videos_vps2siteground.sh}`, appends its full output to `$PROJECT_ROOT/logs/siteground-delivery.log` (the file the night delivery uses; Julius's open check "does that log contain the FTP password" applies to both), and turns the line `Ergebnis: hochgeladen=N übersprungen=N fehlgeschlagen=N gelöscht=N` into one result line `Hochgeladen: N, übersprungen: N, fehlgeschlagen: N, gelöscht: N`. Status `completed` only when the script exits 0, the line exists and `fehlgeschlagen` is 0; otherwise `failed`.

- [ ] **Step 1: Write the failing tests** (`tests/web/web_publish_test.py`; the delivery script is replaced by a fake via `TIMELAPSE_WEB_PUBLISH_SCRIPT`):
  - trigger: `test_publish_trigger_starts_the_worker`, `test_publish_trigger_rejects_a_bad_job_id`, `test_publish_trigger_rejects_unsafe_camera_names` (`../x`, empty, `.`), `test_publish_trigger_rejects_an_unlisted_camera` (66), `test_publish_trigger_refuses_while_the_lock_is_held` (75).
  - worker: `test_publish_worker_runs_the_script_for_one_camera_with_run` (fake records `<camera> --run`), `test_publish_worker_writes_the_result_line_and_completes`, `test_publish_worker_fails_when_a_file_failed` (`fehlgeschlagen=1`), `test_publish_worker_fails_without_a_result_line` (empty-list abort, exit 1), `test_publish_worker_appends_to_the_delivery_log`.
- [ ] **Step 2: Run to see them fail.** Julius: `python -m pytest tests/web/web_publish_test.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement both scripts** by the same pattern as Task 2.
- [ ] **Step 4: `install.sh`:** the installs, the sudoers line `.../timelapse-web-publish *`, the verify grep; `bash -n` on the new files.
- [ ] **Step 5: Run.** Julius: the new test file, the full suite, ruff. Expected: pass.
- [ ] **Step 6: STOP.** Julius commits. Do not try the real publish yet (Task 5 first).

### Task 5: Publish section on the camera page

**Files:**
- Modify: `web/src/video-library.php`, `web/public/camera.php`
- Create: `web/src/publish-runner.php`
- Test: `tests/web/web_php_test.py`, `tests/web/web_camera_page_test.py`

**Interfaces:**
- Consumes: `findVideos(string $camera, string $runFolder): array` (`web/src/video-library.php:122`), `translateJobLabel()`.
- Produces: `newestAutomaticVideos(string $camera): array` returning `[job => filename]`, the newest automatic video per period, only periods that have one, in the order daily, weekly, monthly, yearly; `startPublishJob(string $camera): array` (same return shape as Task 3; trigger `/usr/local/sbin/timelapse-web-publish <jobId> <camera>`).
- POST action `publish-camera`: fields `camera`, `csrf_token`, `confirm`. The server accepts ONLY `confirm` equal to the string `yes`.

- [ ] **Step 1: Write the failing tests:**
  - `web_php_test.py` (pattern `test_find_videos_reads_automatic_videos_from_the_camera_folder`, line 196): `test_newest_automatic_videos_returns_the_newest_file_per_period`, `test_start_publish_job_calls_the_trigger_with_the_camera`, `test_start_publish_job_reports_a_busy_lock`.
  - `web_camera_page_test.py`: `test_publish_without_confirm_is_refused_without_calling_sudo`, `test_publish_with_confirm_other_than_yes_is_refused` (`on`, `1`, `YES`), `test_publish_with_a_bad_csrf_token_is_refused`, `test_publish_with_confirm_yes_starts_the_job_and_redirects` (fake sudo log shows `timelapse-web-publish <jobId> <camera>`), `test_publish_section_lists_the_newest_file_per_period_with_an_unticked_confirm_box`, `test_publish_section_is_absent_without_automatic_videos`.
- [ ] **Step 2: Run to see them fail.** Julius: both files. Expected: FAIL.
- [ ] **Step 3: Implement** `newestAutomaticVideos`, `startPublishJob`, and the `publish-camera` action in `camera.php` (CSRF, camera, strict `confirm === "yes"`, then the same session and redirect as the other starts). The section "Auf die Website übertragen": the files that would be sent (one per period), one checkbox "Ja, diese Videos jetzt auf die Website übertragen" (name `confirm`, value `yes`, unticked), a button disabled until the box is ticked (inline script; the server check is what counts), and the note that files already on the site are skipped. The job watcher already shows the result lines from Task 3.
- [ ] **Step 4: Run.** Julius: both files, the full suite, ruff, `php -l`. Expected: pass.
- [ ] **Step 5: STOP.** Julius browser-checks and commits. First real publish on the VPS: a camera whose newest videos are already on the site, expecting `übersprungen` and no uploads.

### Task 6: Docs (German)

**Files:**
- Modify: `docs/weboberflaeche.md`, `docs/cli.md`

- [ ] **Step 1: Write** in `docs/weboberflaeche.md` two short sections, "Neu erstellen wie der Nachtlauf" and "Auf die Website übertragen": what each button does, the job order and the Weekly hint, that a long rebuild holds the run lock and can make the 02:00 run skip, the confirmation, where the log goes. In `docs/cli.md` one example `--jobs ... --cameras <Kamera>` for automatic jobs of one camera and the note that it is not the production run.
- [ ] **Step 2: Offline check:** every code name used exists (grep for the wrapper and action names); line length and links.
- [ ] **Step 3: STOP.** Julius reads and commits.
