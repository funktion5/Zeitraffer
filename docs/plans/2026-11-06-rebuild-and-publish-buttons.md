# Rebuild and publish buttons (web UI)

Status: DRAFT design, 2026-11-06. Not approved, nothing built.

## Why

The night job runs once, at 02:00. If a camera fails in that run, nobody sees it before the next day, and the
public site then lacks that camera's video for the day. It has not happened yet (the videos are not live for
long, no failures so far); this is insurance. Today the only way out is a manual Daily, which lands in
`manual-runs/` and never reaches the site as the "normal" video.

## What it is

Two buttons on a camera's page in the web UI, used one after the other:

1. **Rebuild** (Step 1): runs what the night run does for that one camera, for the jobs the user ticks
   (checkboxes: Daily, Weekly, Monthly, Yearly; all four ticked is the night run), and writes the real files
   in `videos/<camera>/<job>/`, with the real names. A Yearly that is skipped for too few days is fine.
2. **Publish** (Step 2): ONE button per camera that sends that camera's videos to SiteGround, the way the
   night delivery does. The user watches the rebuilt video in the web UI first, then clicks.

## Decisions by Julius

- Rebuild reproduces the night run for one camera, not a manual run with a prefix, and not a checkbox on
  manual runs.
- Rebuild has one checkbox per job (Daily, Weekly, Monthly, Yearly); the user ticks what needs a rerun, one,
  several or all four. This is possible because the jobs fail independently per camera at night (checked in
  `src/main.py:243` and the four job runners). The jobs always run in the fixed order Daily, Weekly, Monthly,
  Yearly; the Weekly is built from the existing Daily videos, so it should be ticked together with a Daily
  that was missing (the page shows a hint).
- Publish is ONE button per camera, because the upload script always sends the newest video of all four
  periods of a camera. The confirm window lists the files it will send.
- Rebuild and publish are two separate steps, so the video can be watched in between.
- Mostly used for a camera that failed at night: usually no video for that day is on the site yet. Replacing a
  video that is already on the site is a rare case; whether to support it explicitly is open (see below).
- The cameras are blurred every night by the box blur job, whether or not the video step failed. The blur
  check for the automatic Monthly and Yearly (today only the Daily has one) is NOT part of this: Julius still
  wants it for the other videos, as its own task.

## Goals, non-goals, anti-goals

Goals: one click per step, same result as the night run, usable by any colleague with web UI access.

Non-goals: roles or permissions beyond the existing Basic Auth, a progress bar, FTPS, changing the delivery
script's rules, the blur check for Monthly/Yearly, publishing manual-run videos.

Anti-goals (a failure even if it technically works):
- Sending unfinished, broken or unblurred videos: the criteria are the night job's (the Daily gate stays, the
  delivery script's file rules stay).
- Sending anywhere except the configured SiteGround folder.
- A confirmation that does not hold: it must be enforced on the server, not only by a browser pop-up.

## What exists today (read on 2026-11-06)

- Web flow: `web/public/camera.php` (POST, CSRF token, action field) calls `web/src/job-runner.php`, which runs
  `sudo -n -u <run user> /usr/local/sbin/timelapse-web-trigger`. The trigger validates everything, takes the
  run lock (`state/zeitraffer-run.lock`, exit 75 if busy), writes the job status and starts
  `/usr/local/libexec/timelapse-web-worker` in the background. `job-status.php` polls the status files.
  `./install.sh` installs the wrappers root-owned and writes the sudoers rules for `www-data`.
- `src/main.py`: automatic runs have no `--target-date` and write to `videos/<camera>/<job>/`; `--cameras` is
  only accepted together with `--date` or `--target-date` (`main.py:155`), which makes a run manual.
- Delivery: `scripts/copy_zeitraffer_videos_vps2siteground.sh [<camera>] [--run]`: dry run by default, takes
  the file list from `scripts/list-deliverable-videos.py` (regular, non-empty, non-hidden `.mp4` directly in
  the period folders, newest valid file per camera and period, cameras in `ignored_cameras` never), skips a
  file that is already on SiteGround with the same size, uploads under a hidden name and renames, keeps the
  newest 2 per camera and period only where every upload worked. The login comes only from
  `config/siteground.env` on the VPS.

## Design

### Step 1: Rebuild

- A button on the camera page, German label, with a note that it takes long (as the manual runs have).
- A new web job kind that runs `src.main --jobs <ticked jobs> --cameras <camera>` WITHOUT `--target-date`.
  This needs two small changes in `src/main.py`: the check that rejects `--cameras` without a target date
  (around line 155) and the camera filter that only applies to dated runs (line 234). My call; the
  alternative is a new flag. A run with `--jobs` and no date is not the nightly production run, so the
  run-state marker stays untouched. Everything else about automatic runs stays as it is.
- Reuse the trigger's validation (camera name pattern, camera list), the run lock, the status files and the
  "job running" notice. The success check differs from the manual worker's, which waits for one file in
  `manual-runs/` (see the result handling below).
- A rebuild over an existing video works: an automatic job removes the outdated video of that type and
  replaces the file atomically (FFmpeg writes a hidden temp file first, `src/video.py:375-382` and
  `411-433`). No force flag is needed, and a replaced file gets a new inode, which a test can check. (No skip-if-exists was found in the daily, weekly
  or video code; a test should pin this.)
- The result is shown per ticked job: created, skipped or failed, taken from the summary line every job logs
  (`... job finished ... | created=1 | skipped=0 | failed=0`, which the night report reads too). A skipped
  Yearly shows as skipped, not as an error. The job status itself is completed when the process finished
  without an uncaught error; the per-job lines say what each job did.
- Only operational errors are caught per camera (file errors, timeouts, ffmpeg failures, blur-not-ready for
  the Weekly); any other error ends the whole process, as at night.
- For blur cameras the automatic Daily only uses frames confirmed as blurred; if they are not, the job fails
  and shows the reason. Nothing new is built for this.

### Step 2: Publish

- ONE button per camera on the camera page, because the delivery script always sends the newest valid video
  of all four periods. The confirm window lists exactly those files (up to four). Whether a file is already
  on the site is not known beforehand (the script's dry run makes no connection); files that were skipped
  show in the result afterwards. No button under single videos, none for manual-run videos.
- The request carries only the camera name, the CSRF token and an explicit confirmation value. No host, user,
  folder or file path comes from the browser. The server refuses without the confirmation value, so the check
  does not depend on browser JavaScript.
- A new root-owned wrapper (like the trigger) runs the delivery script with `--run` for that camera as the run
  user, in the background, under the same run lock, and writes the job status. Output goes to a log.
- Shown to the user: uploaded / skipped (already on the site) / failed, in plain German. The button is
  disabled while any video job runs.
- The delivery script is not changed.
- The server refuses the request when any video job is running (the run lock). It does not check whether
  the user watched the same file that is now newest (the night run is at 02:00, publishing happens in the
  daytime): accepted as rare. The unfinished-file protection is the delivery script's own rule (hidden and
  empty files never count), and the lock keeps the publish from starting during a build.
- The wrapper runs as the account that owns the project folder, the same account the night cron runs as, so
  it can read `config/siteground.env` (the web server user `www-data` cannot and must not). The builder
  checks this once with a dry run through the wrapper.

## Calls made by Claude (to check while reading)

- `--cameras` for automatic runs is lifted in `src/main.py` (two spots) instead of adding a new flag.
- The rebuild shows a result per ticked job from the log summary lines; the overall status is only
  completed or failed for the process.
- The checkboxes start unticked and the rebuild button stays disabled until one is ticked, so a click is
  always a deliberate choice.
- The publish confirmation is a fixed value plus the CSRF token, and the server refuses while a job runs;
  no "same file as watched" check.

## Order of work

One task at a time: failing tests first, only that task, then stop for Julius's check and commit.
1. `src/main.py`: `--cameras` for automatic runs, both places (offline tests).
2. Rebuild: wrapper path, PHP runner, camera page button, tests.
3. Publish: wrapper, PHP runner, button and confirmation, tests.
4. `install.sh`: install the new wrappers and the sudoers lines; Julius runs it on the VPS.
5. Docs (German): `weboberflaeche.md`, `werkzeuge.md` or a new short section.

## Open, left to the builder (mark as calls)

- Exact button wording and placement.
- The log file for the publish step.
- Replacing a video that is already on the site: the script skips an identical size and sends a changed one;
  renaming onto an existing remote name has not been seen on the real server. Not needed for the main case.
