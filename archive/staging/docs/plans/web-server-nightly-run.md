# TODO — Nightly run on the Hetzner web server (no SSHFS mount)

Status: planned 2026-10-19, not started. Nothing below has been written or run yet.

## Goal

Make the nightly production run (`python3 -m src.main`, 02:00) work on the Hetzner web server,
exactly as on the Pi: 7 Dailies, and 1 Weekly, 1 Monthly, 1 Yearly per camera. Where the finished
videos go afterwards is decided later and is out of scope.

## Why a copy step is needed

The pipeline reads the originals as ordinary local files (`os.scandir`, `stat`, hashing, copying
into `temp/`). On the Pi `CAMERA_ROOT` is the SSHFS mount. The web server cannot mount: no
`sshfs`/`fusermount`, no root, and `user.max_user_namespaces` is 0. Rewriting the pipeline to
fetch over ssh on demand would be a large change to stable code, so the originals are copied
into a local folder first and `TIMELAPSE_CAMERA_ROOT` points at it. The pipeline itself stays
unchanged: validation, window selection, duplicate filtering, coverage checks, retention.

## State of the server (2026-10-19)

Done: venv on Python 3.11 (numpy 2.4.6 because 2.5.x needs 3.12+), ffmpeg/ffprobe static builds
via npm in `~/bin`, ssh alias `box` for the Storage Box (port 23, dedicated key), rsync 3.2.7
verified against the box, `TIMELAPSE_STORAGE_BOX` support in `get_storage_box()` (committed).
Listing one camera over ssh worked (193,486 files for SLSV).

## Decisions (agreed with Julius, 2026-10-19)

- Stage fresh for every run, delete afterwards (option A). No persistent mirror.
- The copies are deleted after the **entire** run, not between jobs: all four jobs read the same
  staged folder. The wrapper also cleans up on failure (`trap`); the copy script wipes the folder
  before it starts, so stale frames can never leak into a later run.
- Existing crontab entries on the server are never touched; our lines are only appended, after a
  `crontab -l` backup, with our own lock file. Julius pastes them himself.
- Nothing is sent anywhere (no mail/push); verification results go to a report file.

## Pieces to write

1. `scripts/stage-frames.py` (new, read-only on the box)
   - Target date defaults to `get_latest_completed_date`; optional `--target-date`, `--cameras`,
     `--destination` (default `temp/camera-staging`), `--clean-only`.
   - Camera list from the box (`ls -l`, directories only, not hidden), minus `ignored_cameras`.
   - Per camera: `list_camera_files`, then select names as a superset of what the jobs ask for:
     - Daily: target day and previous day, same substring match as `find_images_for_dates`
       (`date_patterns`).
     - Monthly/Yearly: the yearly date range, `extract_date`/`extract_time` and the window from
       `resolve_target_seconds` with the configured tolerance (Monthly is a subset of it).
     - Weekly (automatic) needs no frames, it joins the existing Daily videos.
   - Copy with `rsync -t --from0 --files-from=... --timeout=300 -e "ssh -o BatchMode=yes
     -o StrictHostKeyChecking=yes"` into `<destination>/<camera>/`.
   - A failed camera has its staged folder removed (never a half-copied day for the pipeline);
     exit 0 = all staged, 1 = some cameras failed, 2 = fatal (box unreachable).
   - Deletion is guarded: the destination must be inside `<projektpfad>/temp`.
2. `scripts/timelapse-nightly-staged` (new wrapper, bash)
   - Sets `PATH` (including `~/bin`), `TIMELAPSE_STORAGE_BOX`, `TIMELAPSE_CAMERA_ROOT`.
   - Takes `state/zeitraffer-run.lock` itself (`flock -n`), so manual runs are protected too.
   - Order: stage, abort on exit 2, run `python3 -m src.main`, verify, clean up (also via trap).
3. Verification (exit code of `src.main` is not enough: per-camera errors are caught and logged)
   - Read the `... finished ... created= | skipped= | failed=` summary lines of this run's logs;
     `failed` above 0 is a failed run, `skipped` is only reported.
   - Every video written during the run must exist, be non-empty and have `ffprobe` duration > 0.
   - Result goes to a report file under `logs/`; the wrapper exits non-zero on failure.
4. Tests: selection logic (daily, interval window, previous day, ignored cameras, odd file
   names), the guarded deletion, the failed-camera cleanup. No test touches the box.
5. Cron (last): two appended lines, nightly run and the blur job. Not written before the rest
   works.

## Open questions (answer before starting)

1. Which jobs does the nightly run include? README says `python3 -m src.main` without options,
   i.e. Daily, Weekly, Monthly, Yearly every night. Confirm that this is wanted on the server too.
2. Size and duration of the copy: unmeasured. Rough estimate from SLSV (about 143 frames a day,
   about 42 KB each, window 12:00 +-90 min): a few hundred MB for the Dailies, roughly 0.5 GB per
   camera for the Yearly window, a single-digit number of GB over about 14 cameras. Measure on
   the first manual run and decide whether copying fresh every night is acceptable.
3. Do the job log lines match what the verification parses? Check against real Pi logs.
4. Does `ls -l` on the box handle every camera folder name (spaces, odd characters)?
5. `@reboot` recovery (`state/run-in-progress`) does not exist on the server; a crash leaves the
   marker behind but nothing acts on it. Acceptable for now?
6. Per-account CPU/RAM limits of the shared host are unknown; a multi-hour run may be throttled.
   First test: one camera, one day, run by hand.
7. Is `public_html/Zeitraffer/temp` reachable over HTTP? The staged frames are unblurred. Check
   with `curl -I` (needs the domain) or block the folder before the first staged run.
8. The blur job (`src.privacy.blur_box`) writes to the box. Read `box_writer.py` and decide
   separately; `ALLOW_BOX_WRITES` and the Pi/server overlap question come first.

## Not in scope

Where finished videos are published, the SiteGround transfer, the WordPress plugin, the blur
job, any change to the retention rules or to `src/` beyond the box lookup already done.

## First test, once the pieces exist (Julius runs it, Claude does not)

One camera, one day, by hand: `stage-frames.py --cameras <one> --target-date <date>`, then
`python3 -m src.main --date <date> --cameras <one>`, then `stage-frames.py --clean-only`.
Compare the video with the Pi's for the same day.
