# Frames over ssh: dropping the mount (design)

Status: built, finished 2026-10-30. This is the design as written on 2026-10-27, before the work;
the plan ([2026-10-27-ssh-frames.md](../plans/2026-10-27-ssh-frames.md)) lists the deviations and
[architektur.md](../../architektur.md) describes the result.

## Intent and why

Every job reads the camera frames as ordinary local files under `CAMERA_ROOT` (default
`/mnt/cameras`, an SSHFS mount of the Hetzner Storage Box). The pipeline is moving from the Pi to a
VPS and later possibly to other hosts (a Pi 5, any Debian/Ubuntu machine). Nobody wants an SSHFS
mount there: it costs memory, its scans are slow, and it needs fuse and root. The mount is dropped
everywhere. Frames are listed over ssh and fetched with rsync instead, so the same code runs on any
host that has an ssh alias for the box.

An interim shortcut already exists (`scripts/stage-frames.py` + `scripts/timelapse-nightly-staged`):
it copies frames into a staging folder before the run. It works for the nightly run only, and it
duplicates the frame-selection logic of `src/images.py` in a second place. This design replaces
the shortcut with one mechanism inside the app that every entry point uses.

## Goals

- Every job and tool runs without `/mnt/cameras`: Daily, Weekly, Monthly, Yearly (nightly, CLI and
  web UI), `--blur-people`, the highlights flagger, the blur jobs, the storage filter, the yearly
  backfill and the NAS helpers. All have equal weight; none may break unnoticed.
- One frame-reading mechanism, no second copy of the selection logic.
- The jobs stay the same in what they need and what they do. Only where the bytes come from changes.
- The mount is gone at the end: no default path, no systemd unit, no mount code, no mount docs.
- Host-neutral: any Debian/Ubuntu host with `ssh` and `rsync` and an ssh alias for the box.

## Non-goals

- No new features, no change to video, blur or detection logic, no change to which frames a job
  selects.
- No speed targets. How long jobs take is measured on the new hardware, not demanded here.
- No new dependency; ssh and rsync are already used.
- Not touching `src/privacy` write paths (blur writes to the box over ssh/scp already).

## Anti-goals (a failure even if tests pass)

- A video built from fewer frames than before for the same day.
- A job that "succeeds" with no frames, or with a half-fetched camera.
- Unblurred frames left on disk after a job, including a failed one.
- Anything that writes to the box from the frame-reading code. Fetching is read-only.

## Constraints

- Works on `main`; the user commits each step. One step at a time, each with tests, a fresh
  reviewer and a hand check by the user where a real video or the web UI is involved.
- The Pi keeps running its own checkout of the old code until it is retired, so the local source
  stays the default until the last step and nothing changes for the Pi before then.
- `src/` must stay runnable on Python 3.11 (the shared web server) and 3.13 (CI, VPS). Tabs, 100
  columns, `ruff check` and `ruff format --check` stay green. CI has no FFmpeg: run pytest with
  `ffmpeg`/`ffprobe` hidden before handing a step over.
- Tests never touch the real box. Listing and fetching sit behind an injectable runner, and tests
  use a fake one.
- No secrets, host names, account names or key file names in tracked files. The box is addressed
  by an ssh alias (`TIMELAPSE_STORAGE_BOX=<alias>[:<base dir>]`, already supported); user, host,
  port and key live in `~/.ssh/config`.
- The web UI's PHP runs as `www-data`, which has no ssh key. Only code running as the login user
  (the trigger/worker via sudo, cron) may talk to the box.
- Frames are unblurred until the blur job has processed them. Fetched copies are scratch data.

## What exists today

- **One funnel.** `src/images.py` (779 lines) does four things: it decides which frames a job
  wants (date patterns, daylight window, interval window), lists a camera folder with `scandir`
  on the module-level `CAMERA_ROOT`, filters (empty, duplicate, by hash), and runs scans in
  subprocess workers with a stall timeout (`*_isolated`).
- **Callers.** `src/jobs/{daily,weekly,monthly,yearly}.py`, `src/main.py` (`get_cameras`,
  `require_cameras`), `src/flagger/run.py`, `src/yearly_selection.py`, `src/diagnostics.py`,
  `src/storage_filter.py` (listing already over ssh; its report paths use `CAMERA_ROOT`),
  `scripts/yearly-backfill.py`, `nas/helpers/storagebox_fill.py` (asserts `/mnt/cameras`).
  `src/video.py` and `src/privacy/anonymize.py` consume local `Path` objects: ffmpeg and the
  filters need real files.
- **Already mount-free.** `src/privacy/blur_box.py` and `box_writer.py` (ssh/scp),
  `storage_filter` listing, `scripts/stage-frames.py` (rsync, retries, guarded delete).
- **Mount assumptions outside Python.** `web/src/video-library.php` (camera list from
  `/mnt/cameras`), `scripts/timelapse-web-trigger` (checks a folder under `CAMERA_ROOT`),
  `scripts/timelapse-web-worker` (runs `src.main` against the default root), the sshfs unit and
  preflight script, the `@reboot` cron line, README/handbook install chapters.
- **Duplicate logic.** `stage-frames.py` `select_frame_names` re-implements the frame selection.
- Automatic Weekly joins existing Daily videos and needs no frames. Manual/historical Weekly
  (`collect_weekly_images` in `src/jobs/weekly.py`) scans 7 days of frames and is in scope.

## Fetch scope (checked against the code)

"Only the selected frames" is not enough, because three jobs read bytes beyond the final selection:

- **Daily** (`_find_daily_images_worker`): the target day's frames inside the daylight window, and
  all frames of the previous day, which serve as the duplicate reference (empty and duplicate
  filters read them).
- **Yearly** (`select_unique_yearly_images`): opens candidates lazily, nearest the target time
  first, checking the JPEG end marker and a hash. Which files it opens depends on file contents,
  so a listing cannot decide it.
- **Manual Weekly**: the duplicate filter hashes every frame of the 7 days.

My call: the first implementation fetches the whole candidate set of a job (everything the job
could open) in one bulk rsync. It is correct and simple. Fetching by size group (duplicates must
have equal sizes, and the listing gives sizes) or lazily per file is an optimisation for later, if
disk or time demand it. The expected volume is small for Daily (about two days of frames per camera
and job); for a full-year Yearly it was estimated earlier at about 0.5 GB per camera, unmeasured.
The VPS has about 32 GB free.

## Decided

- **Architecture A:** a frame source inside `src/images.py`. A local implementation (today's
  `scandir`) and an ssh implementation sit behind one interface. Jobs select frames as they do now
  and only the frames a job actually opens are fetched (see "Fetch scope"). Every entry point
  (nightly, web, CLI, flagger, tools) goes through it. The local implementation stays: the NAS
  archive tools and tests read local folders. What goes is the `/mnt/cameras` default, the mount
  setup and the mount docs.
- Everything over ssh and rsync; the mount is removed everywhere, last.
- Tiny steps. A step is done when its tests pass and the job it touches does what it is meant to
  do; the jobs themselves are not redesigned.

## Left to the builder, with my calls marked

- **Interface shape.** Names and signatures of the source and how `CAMERA_ROOT` stops being a
  module-level global read at import.
- **Choosing the source.** My call: a dedicated switch, `TIMELAPSE_FRAME_SOURCE=ssh`, default
  `local` until the last step, because `TIMELAPSE_STORAGE_BOX` is already set on hosts for blur
  and the storage filter and must not switch the frame source by itself. The ssh source reads the
  box from `TIMELAPSE_STORAGE_BOX`. In the last step the default flips: ssh when a box is
  configured, otherwise an explicit local root is required (no `/mnt/cameras` default).
- **Failures, per camera.** My call: keep today's meaning. A camera with no frames is skipped and
  the job goes on. A listing or fetch error for a camera counts as failed, not skipped, the other
  cameras still run, and the job exits non-zero; logs and counters tell "skipped, no frames" from
  "failed, fetch error". An unreachable box makes every camera fail.
- **Fetch point.** My call: the selection of names (which depends on listing only) happens first;
  the fetch happens just before the content-based filters (empty/duplicate), because those read
  file bytes. Listing gives sizes, so cheap checks may run before the fetch.
- **Cache and cleanup.** My call: under `temp/`, in its own folder, separate from the
  `temp/<camera>/<date>` folder that `src/video.py` wipes and refills, with a unique run suffix.
  The parent process owns cleanup, because a worker killed on a stall cannot clean up after
  itself. The unit is one camera in one job: cleanup runs when the video build, the flagger scan
  or the `--blur-people` step for that camera is finished, also on failure, and only folders the
  code created are wiped (as `stage-frames.py` does). `video.py` already copies frames into its
  own temp folder, so frames are copied twice at first; merging the two is a later optimisation.
  A web job and the nightly run on one host share `state/zeitraffer-run.lock`, so they do not
  overlap; the unique suffix covers a hand run that ignores the lock.
- **Failures.** My call: reuse `stage-frames.py`'s behaviour: bounded retries with waits, rsync
  and total timeouts, a half-fetched camera is removed and never handed on, and an unreachable box
  fails the job loudly.
- **Subprocess workers (`*_isolated`).** My call: leave them in the first steps; revisit once
  scans are over ssh, since they exist to survive stalled scans.
- **Camera list for the web UI.** PHP cannot reach the box. Where the list lives (for example a
  small file refreshed by a job) is the builder's choice, as long as the trigger's existence check
  and the video library read the same source.
- **Nightly wrapper.** With the jobs fetching for themselves, `timelapse-nightly-staged` no longer
  stages. It can shrink to what the Pi's cron did (run, then the flagger) plus the report; this
  also removes the earlier problem that the flagger takes the run lock itself. Builder's choice
  whether the wrapper stays or cron calls the app directly.
- **`stage-frames.py`.** Retire it or keep a thin tool; the builder decides once the code lives
  in `src/`.
- **Step order.** Proposed: characterization tests; interface with the local source only; ssh
  listing; fetch; Daily; manual Weekly; Monthly; Yearly; flagger; CLI (`--blur-people`); web trio; wrapper; tools
  (backfill, NAS helpers, storage-filter report paths); finally mount removal and docs.

## How each step is judged

- Equivalence: for the same listing, the local and the ssh source select exactly the same frames.
  Tested offline with a fake runner.
- Existing tests stay green; new tests cover the new code including failure and cleanup paths.
- A fresh reviewer reads the step; the user checks one real result per job by hand and commits.
- The last step additionally checks that nothing references `/mnt/cameras` or the sshfs files, and
  updates `docs/vps.md`, README, handbook, architecture and `install.sh` text.
