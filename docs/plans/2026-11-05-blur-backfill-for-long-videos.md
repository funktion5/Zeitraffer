# Plan: blur the old frames that Monthly and Yearly videos use (SLSV, Scheunenviertel)

Status: **BUILT on 2026-11-05 and green on the VPS.** This file keeps the reasoning of the day; the
sections below are the draft as it was written, so everything about the `--blur-box` flag, a dry run, a
deadline, the steps "2d" and "3" and a web checkbox is HISTORY.

## Outcome (end of 2026-11-05)

- **The rule that was built:** a MANUAL Daily, Monthly or Yearly run of a camera listed in
  `privacy.blur_cameras` blurs the frames it selected on the Storage Box first (in place, backups in
  `<camera>/original/`), with any window (noon, sunset, a future sunrise). Automatic runs never do. No flag,
  no opt-out, no dry run, no deadline, no video suffix (Julius's decisions). No video unless every frame is
  confirmed (cut-off JPEGs excepted). The manual Weekly comes later.
- **Code:** `src/privacy/blur_box.py` (`blur_frames`, `load_processed_for_names`, the guard), `blur_job.py`
  (`blur_job_frames`), `box_writer.py` (`list_backups`), `src/frame_source.py` (`release_frames`), the three jobs,
  and in the web UI the note in `camera.php`, `getBlurCameras()` and German failure reasons in `job-status.php`.
- **Found during the first real runs and fixed:** (1) the nightly records frames on the page of the round's
  time, so the last day of a month sits on the next month's page: the lookup now reads the next two days'
  pages; (2) frames the Pi blurred before the VPS state existed would be blurred and backed up a second time:
  a frame with a backup whose hash no longer matches it counts as already blurred.
- **Done on the box:** Scheunenviertel and SLSV for 2026-10-06..11-04. Remaining windows, the open list (docs,
  Weekly, `--blur-people`, gate for automatic Monthly/Yearly, live round) and the check routine are in memory
  `project-timelapse-blur-backfill`.

---

Draft as written on 2026-11-05 (history):

## Problem

The box blur job only looks at the last 48 hours (`blur_box --catch-up`, nightly at 02:00). The
archive of the two blur cameras is therefore blurred from 2026-10-23 on (Pi) and 2026-10-30 (VPS) only.
The automatic **Monthly** and **Yearly** videos of SLSV and Scheunenviertel still contain older,
unblurred frames. The Daily gate (built 2026-11-04) does not cover them; Julius decided then not to hold
Monthly/Yearly back (known gap, `docs/verpixelung-box.md`, Grenzen). The videos reached SiteGround for the
first time in the night of 2026-11-04/05; the folders there are guarded and nothing is public yet
(Julius, 2026-11-05), so there is no stopgap to build.

## What the long videos actually use (read from the code, 2026-11-05)

- **Monthly** (`src/jobs/monthly.py`): **every** frame inside the daily time window
  (`interval_window` in `config/config.json`: 12:00, 90 minutes either side) for each of the 30 days;
  `remove_duplicates_by_date` only drops identical files, and empty files are dropped too. At one image
  every 10 minutes (SLSV) that is about 18 frames a day, about 540 in total; Scheunenviertel (every 15
  minutes) about 12 a day, about 360 (estimates). Corrected 2026-11-05 by Julius: Claude had read the
  parameter name and wrongly assumed one frame per day.
- **Yearly** (`src/jobs/yearly.py`): the same window list for 365 days, then the **5 closest to the
  target time per day** (`select_yearly_images_isolated`, `IMAGES_PER_DAY = 5`), cut-off and duplicate
  images skipped. The 2025 SLSV rebuild used 1640 frames for 328 days, about 5 per day. On the days both
  cover, the Yearly's frames are a subset of the Monthly's.
- Both windows are rolling: they end on the latest completed day (`get_coverage_date_range`). The Yearly
  comment says it is a true calendar year of 365/366 days **(to verify)**. A frame older than that drops
  out of every automatic video by itself.
- Frames reach the video through `FrameSource` (ssh/rsync) and are removed again afterwards
  (`release_camera_frames`). So a frame that is already blurred in the box archive comes out blurred
  with no change to the video code.

## Julius's idea (2026-11-05)

Blur the archive **in chunks, only the frames a job needs**, using the box job itself:

- The catch-up gets a mode that does not take "the last 2 days" but **the images a given job needs**.
- Manual videos get a setting "with blur / without". Without blur nothing changes.
- One chunk = one normal manual video with blur, then the same again for the next month, and so on.
- The web UI gets that setting later; the first usable version can be a terminal command.

Why this beats "blur the whole archive" (Claude's reading): the whole archive is about 160 images a day
for SLSV (estimate from the 2026-10-30 catch-up counts), so roughly 100k images since 2025-01-01, around
10 days of pure detector time on the 2-core VPS that also runs the nightly job (estimate from about 9 s
per frame measured on the Pi on 2026-10-16). The needed frames are a few thousand, and the window rolls
forward: frames older than a year are never needed again.

Why this beats "video-mode blur only" (detector cache, blurred manual video, box untouched): the
automatic Monthly/Yearly do not blur in video mode, so they would stay unblurred. Only the in-place
blur fixes them. The price is that it writes to the box (backups in `original/`, as the nightly job does).

## Rough scope (estimates, label as such; measure before the first real run)

| Camera | Needed range for the automatic videos | Frames (about) |
|---|---|---|
| SLSV | Yearly: 5 a day for the days before the blur started (2025-11-05 to 2026-10-22); Monthly: all window frames of its 17 unblurred days | about 1.7k + 0.3k = about 2k |
| Scheunenviertel | from the cutoff Julius named ("somewhere in August", year and direction not confirmed) to 2026-10-22: Yearly 5 a day, plus the Monthly's 17 unblurred days | about 0.6k |

A cutoff of 2025-01-01 for SLSV is only needed for a **manual** calendar-year video of 2025, not for the
automatic ones. That is why Julius's answer to the cutoff question depends on this plan (his words:
"make that depend on 1").

## Steps (proposal)

0. **Checks before building** (no code change; read 2026-11-05):
   - **Same frames every night: yes. The Monthly's set is the bigger one on its 30 days (corrected).**
     Both jobs take their frames from the same `find_interval_images` window (same target time of day per
     date). The Monthly uses all of them, the Yearly the 5 closest per day (`src/yearly_selection.py`).
     The pick depends only on the file names (and hash/completeness) of a finished day, so it stays the
     same night after night. Neither set covers the other fully: the Yearly spans 365 days with 5 a day,
     the Monthly 30 days with all window frames. The blur must therefore follow each job's **own** frame
     list, not one shared rule. Cut-off and duplicate images are never in a job's list, so they never
     need blurring (Julius, 2026-11-05); using the job's real list also removes my earlier worry about
     the "next closest" replacement frame.
   - **State month: a real design point for step 1.** `record_processed(..., now)` writes into the file of
     the month of `now` (the time of the run), and `load_processed` reads only the months of the last
     `LISTED_DAYS` days. A backfilled frame from last year would be recorded on this month's page, so a
     later lookup (a re-run's "already done" check, or a gate for Monthly/Yearly) looks on last year's
     page and finds nothing; a re-run would judge and possibly pixelate the same frame again (as the 35
     double backups on 2026-10-30). Step 1 must record backfilled frames under the frame's own month, or
     the loaders must read the months a job needs.
   - **Web user and the box: fine.** The web UI starts jobs through PHP and `sudo -u <run user>` wrappers
     (`web/src/job-runner.php`, `scripts/web/`). `timelapse-web-worker` exports
     `TIMELAPSE_FRAME_SOURCE=ssh` and `TIMELAPSE_STORAGE_BOX`, and the ssh key stays with the project
     account, so the writer reaches the box the same way the frame fetch does. The box sub-account's
     read-only setting is still unchecked in the Hetzner panel, so writing is allowed. The first real
     write from the web path is still untested.
1. **Blur engine in `blur_box` that takes a list of frames** (no CLI of its own; tests drive it): for a
   camera and the names a job hands over, it does what the nightly round does per image (detect first,
   backup, upload, swap, state line, via `_process_image`), but without the "last `LISTED_DAYS` days"
   listing. It uses a `BoxWriter` with a larger `max_image_age` and `max_backups_per_camera` (constructor
   arguments, not hard-coded; the nightly and live paths keep 48 h and 300), skips frames the state book
   already confirms, records each frame under its own month (point from step 0), newest first, the same
   `privacy-blur.lock`. No deadline or time budget (Julius, 2026-11-05): he sizes the runs himself.
2. **A blur flag on the manual job** (Julius's idea, 2026-11-05: keep the existing logic of choosing a
   job and add a flag, the job knows its own frames). Plausible: every job already computes its frame
   list. With the flag the job (a) selects its frames as today, (b) hands that list to the engine,
   (c) releases its local frame cache (`release_camera_frames`), because the copies it fetched before the
   blur are stale and unblurred, (d) fetches again and builds the video from the now blurred frames. Cost:
   one extra fetch of the selected frames. Monthly and Yearly first, because that is the gap; the Daily has
   its gate and the Weekly's 7 days are largely covered since 2026-10-30. Without the flag nothing
   changes. Proposed: a way to see the numbers first (frames in the list, already confirmed, to blur)
   before anything is written to the box; the exact switch is a small detail to settle at the tests.
3. **Web UI setting** "with blur / without" on the manual run, German UI text. Only after 1 and 2 have
   been used by hand and Julius is happy. Open: the root-owned wrappers in `scripts/web/` and the
   ssh question from step 0.

Later and separate, not part of this plan: extending the Daily gate to Monthly/Yearly (Julius decided
against it on 2026-11-04; the backfill makes it cheap to revisit), and the `--check-stale` watchdog.

## Review findings (2026-11-05, read: box_writer, blur_box, frame_source, images, jobs, main, video, web wrappers, tests)

Things the plan above has to respect. Ranked by how much they change the design.

1. **The 02:00 collision is real and sharper than the plan said.** The VPS cron line is
   `flock -n state/zeitraffer-run.lock sh -c '... blur_box --all-blur-cameras --catch-up'; nightly-staged; delivery; flagger`,
   and the web trigger (`timelapse-web-trigger`) takes the **same** `zeitraffer-run.lock`. A manual job
   still running at 02:00 makes the catch-up skip (flock -n fails) and, as noted for the 2025 backfill,
   probably the nightly too. Julius wished for a separate lock for manual runs (item 14) and then
   **parked it on 2026-11-05** ("so we don't do too much at once"). So for now a manual web job still
   holds the shared lock. **Decided by Julius (2026-11-05): no deadline in the flag.** He starts the
   runs himself and sizes them (a Monthly run is about 70 minutes, estimate) so they end before 02:00.
   Accepted consequence: a flagged job still running at 02:00 makes the catch-up skip, and probably the
   nightly. The state book still lets an interrupted run carry on where it stopped. The blur lock
   (`privacy-blur.lock`) is held only during the blur step, not while the video is built.
2. **No video from an incomplete blur, but truncated frames must not block it.** After the blur step the
   job checks its list against the state book (blurred/clean/night = confirmed) and builds only if all
   are confirmed. Exception: frames the video step skips anyway. `src/video.py:295` drops truncated JPEGs
   from every video, and the Monthly list does not filter them (only empty files and duplicates), while
   `_process_image` raises "incomplete for over 10 minutes" for them. Without the exception one cut-off
   frame would block a Monthly forever. (Julius's point that such frames never need blurring is right;
   the job just has to know it.)
3. **`refused` is not "done".** The first VPS catch-up recorded about 100 frames from 2026-10-28 as
   `refused` (Scheunenviertel 40, SLSV 60: older than 48 h). The nightly treats any state line except
   `replacing` as final. The engine must count only blurred/clean/night as done (`CONFIRMED_STATUSES` in
   `src/jobs/daily.py`) and retry `refused`, with the larger age limit; otherwise those frames stay
   unblurred without anyone noticing.
4. **The frame cache goes stale after a blur, and a full release is expensive.**
   `SshFrameSource.localize` fetches only names that are missing (`src/frame_source.py`, `_missing`), so
   the job's copies from before the blur would be reused. `release(camera)` drops the whole camera, and
   the job's scan fetches **all** window frames first (`src/images.py` around line 706): for the Yearly
   about 6.5k frames, not the 1.8k selected. Needed: a small `release_frames(camera, names)` on the frame
   source (Protocol, local no-op, ssh version) so only the blurred names are fetched again. Caution: the
   structural test (`tests/privacy/privacy_box_writer_test.py`, from line 635) rejects write-verb words
   as separate tokens in string constants of `frame_source.py`; keep new log texts clear of them.
5. **Flag name.** `--blur-people` already exists (`src/main.py:101`, manual Daily, video mode, `_blur`
   suffix) and means something else. The new flag needs a clearly different name (`--blur-box`, Julius's
   choice on 2026-11-05; `--full-blur` was considered but can be read as "blur the whole image", while
   the job pixelates people and plates only), valid only for manual Monthly/Yearly and only for cameras in `privacy.blur_cameras`, rejected otherwise
   in the same style as `src/main.py:148`.
6. **Step 3 is more than a checkbox.** The web path is PHP (`job-runner.php`) plus two root-owned
   wrappers (`timelapse-web-trigger`, `timelapse-web-worker`) with fixed positional arguments (argument
   count 5/6 tells buffer from window). A flag means a new argument form in all three, their tests, and a
   reinstall of the wrappers (`./install.sh`). Also: a job that stops before building ends as "finished
   without publishing a new video"; the worker shows the last log line containing ` - skipping `, so the
   engine's message should use that wording to give the user a reason.
7. **Video name.** The video-mode blur adds `_blur` to the file name, and the worker predicts the file
   name exactly. For the flag: **no suffix** (Julius, 2026-11-05, preference). The frames are really
   blurred and the video is a normal one; a suffix would also have needed the root-owned worker changed.
8. **Engine details** (all reuse `_process_image`): pass `age_seconds` as now minus the frame's time
   (the settle check then never triggers); pass the frame's own moment as `now` so the state line lands
   on its own month page; no night classification (frames in a 12:00 +-90 minute window are daytime, and
   a dark frame from a moved window only costs one detector pass and is recorded as clean). Each frame is
   fetched a second time by scp (`BoxWriter.fetch` takes the judged bytes from where it writes, on
   purpose): about 1.8k extra downloads for the SLSV Yearly, accepted.
9. **Detector rules carry over.** The box job applies `skip_labels`, `min_person_score` and
   `ignore_boxes` (`blur_box.py:251` and `:459`), so SLSV's no-vehicle rule and 0.35 person score also
   hold for the backfill. The `ignore_boxes` of Scheunenviertel are pixel positions that only fit while
   the camera view is unchanged: check one frame from the oldest day of the range against them before
   the first run (a wrong box only pixelates a sign again; the risk is a person standing exactly there).
10. **Run time** (estimates from the comments in `blur_box.py`, about 8 s per frame): SLSV Yearly 1.8k
    frames about 4 h (resumable); a Monthly for one camera 360 to 540 frames about 50 to 70 minutes.
    **Julius's way (2026-11-05, preference):** the backfill is done with the flagged **Monthly**. The
    chunks are only how he uses it, nothing in the code fixes them: he runs a manual Monthly with the
    flag for an end date (for example the day before the blur began), then for the end date 30 days
    earlier, and so on, until he reaches the date the blur started. Any date can be used later when a
    period must be blurred. The Monthly blurs all window frames (about 18 a day for SLSV), which include
    the Yearly's 5 a day, so afterwards no extra Yearly blur is needed for that period; the Yearly keeps
    the flag for other cases. Cost, estimate only: SLSV from 2025-11-05 to 2026-10-22 is about 6.3k
    frames, roughly 14 h of detector time in about 12 runs of about 70 minutes (a flagged Yearly would
    be about 4 h, 3.6 times less); Scheunenviertel from August about 1k frames, 3 runs. Each run also
    leaves a manual video for Julius to review. Notes: use the default window (12:00 +-90 minutes), not
    `--window-time`, or the frames differ from the Yearly's; the first end date can be the latest
    completed day, so the current automatic Monthly is covered first (already blurred days are skipped);
    if a duplicate pair exists, the Yearly may choose the twin the Monthly dropped, which a later flagged
    Yearly would catch.
11. **Docs.** `docs/verpixelung-box.md` lines 156-157 still say SLSV is "keine Box-Job-Kamera" (wrong
    since 2026-10-23; `config.json` lists it in `blur_cameras`). After the build: update
    `verpixelung-box.md` (Grenzen and Sperre), `cli.md`, `weboberflaeche.md`, `handbuch.md` and the README,
    in German.
12. **Tests.** Reuse the `Setup` class and `privacy_fakes` (`FakeBox`, `FAKE_DETECTOR`) of
    `tests/privacy/privacy_blur_box_test.py`. The structural guard allows only `box_writer.py` to start
    ssh/scp, so the engine must live in `blur_box.py` or the jobs without such strings.

13. **The blur must run before the coverage check.** `run_monthly_job` skips a camera whose period has
    fewer than `min_coverage_days` (Monthly 25 of 30, Yearly 300) before it builds. If the blur sat after
    that check, a thin month (a camera outage) would be skipped and stay unblurred, and the Yearly would
    later show it. So the order in the flagged job is: select frames, blur them, release the stale
    copies, then the existing coverage check and video build. A thin month blurs but builds no video.
14. **PARKED, not part of this work: manual runs get their own lock** (Julius, 2026-11-05: skip it for
    now, one thing at a time). Notes kept for later. Today only the web trigger
    puts manual jobs on `zeitraffer-run.lock`; manual runs from the terminal take no lock. The same lock
    is held by the nightly wrapper for its whole run and taken by the flagger, the storage filter scan,
    `yearly-backfill.py` and `nas-extract.py`. Moving the web trigger to its own file (for example
    `state/zeitraffer-manual.lock`, default in the root-owned `timelapse-web-trigger`, still overridable
    by `TIMELAPSE_WEB_LOCK_FILE`) keeps manual web jobs one at a time, and stops them from blocking the
    nightly or being blocked by it. What the shared lock also did, and what would then be allowed to
    overlap: a manual job together with the storage filter scan (the frame set could change under the
    job) or the flagger. Not measured: memory and CPU of a manual run during the nightly run on the
    2-core 3.8 GB VPS; the first overlap is worth a look at `free -m`. Touches the wrapper (reinstall),
    `docs/weboberflaeche.md` (lines 74 and 112), `docs/handbuch.md`, and the web tests. Proposed as its
    **own task**, not bundled with the blur engine, so each can be checked and committed alone.

## Risks and open questions

- **Time window**: a run holds `privacy-blur.lock` and must end before 02:00, otherwise the nightly
  catch-up is skipped ("Skipped: another blur round holds the lock") and the nightly Dailies are built
  from unconfirmed images, which the Daily gate would then leave out. Chunks must be sized to fit; the
  run is started by Julius, detached, like the 2025 Yearly backfill.
- **Box storage**: every blurred frame adds a backup in `<camera>/original/`. The box quota and the
  space for about 2k extra backups are not checked.
- **Backups reachable** by a recursive fetcher of the website: accepted by Julius on 2026-10-23.
- **Age guard**: the 48 h limit in `BoxWriter` is a deliberate proportion guard. Lifting it only for the
  backfill, with an explicit range, keeps the guard for everything else.
- **Open decisions for Julius**: the cutoffs (depends on step 0 and on whether manual 2025 videos are
  wanted), chunk size (one month at a time as he proposed, or larger), whether the first run is SLSV or
  Scheunenviertel.

## What this plan does not do

No change to `src/` until Julius says "decided". No new dependency. No run against the box until the
dry run has been read. No change to the live or nightly blur path.
