# PLAN — Blur catch-up before the nightly run + Daily blur gate

Status: Part 1 (catch-up) built and in cron since 2026-10-23, see
[2026-10-23-blur-catch-up.md](2026-10-23-blur-catch-up.md). Part 2 (gate) planned, **not started**. Blocked on where the live infrastructure runs
(boss decision: Pi, Hetzner web server or a VPS). Build only once the box blur job
(`src/privacy/blur_box.py`, docs/verpixelung-box.md) is scheduled for real on that host.

## Goal

An automatic Daily of a blur camera goes public. It must never contain an image that the box
blur job has not confirmed. Two parts:

1. **Catch-up** right before the nightly run blurs whatever the live job missed for the Daily's
   images, so the gate below rarely trips.
2. **Gate** inside the Daily refuses to encode if any selected image is still unconfirmed.

The catch-up reduces skipped Dailies; only the gate guarantees nothing unblurred is published.

## Decisions (agreed with Julius, 2026-10-23)

- Order: catch-up first, then the Daily with the gate.
- No blurring inside the timelapse job: `box_writer.py` stays the only module that writes to
  the box, and `src.main` / `src.video` keep never touching it.
- The writer's age limit goes from 24 h to **48 h** (`DEFAULT_MAX_IMAGE_AGE` in
  `src/privacy/box_writer.py`), so a `@reboot` rerun the next morning can still catch up.
  Anything later is accepted as a missing Daily; no extra handling. Update
  docs/verpixelung-box.md and the writer tests with it.

## Open decisions (answer before building)

1. **Gate fails:** skip that camera's Daily (log error, other cameras continue, Weekly gets a
   gap) or encode only the confirmed images? Proposal: skip. Deferred by Julius until the
   infrastructure is decided.
2. **Checksum:** also compare the hash of the Daily's local `temp/` copy with the state file's
   `blurred_sha256` / `original_sha256` (catches a camera rewriting an image after the check)?
   Proposal: yes; it costs CPU only, no extra reads over the mount.
3. **Host timing:** the catch-up's worst case (~70 images x 8 s = ~10 min per camera, estimate)
   delays the Daily. Check the budget on the chosen host, together with the flagger (~40 min).
## Part 1: catch-up mode

- New mode of the existing job, e.g. `python3 -m src.privacy.blur_box --all-blur-cameras
  --catch-up <YYYY-MM-DD>` (default: yesterday).
- Image list: exactly the Daily's selection for that day (`find_daily_images_isolated` with
  `automatic_daylight_buffer_for`), not the job's usual "today and two days back" listing.
- Every image without a final status goes through the normal `_process_image` path, same
  writer, same safety rules, same state file.
- No 40 s time budget (`DEFAULT_TIME_BUDGET_SECONDS`); waits for `state/privacy-blur.lock`
  (bounded wait) instead of skipping, so it never races a live round.
- Exit code 0 when everything is final, 1 otherwise; the Daily's gate is the real decision.
- Cron: inside the run lock, before the timelapse run:
  `flock -n <run.lock> -c '<catch-up>; <src.main>'` (flagger stays after it, as now).

## Part 2: gate in the Daily

- Only for cameras in `privacy.blur_cameras` and only for automatic Dailies. Historical runs
  stay exempt (they go to `manual-runs/`, not public).
- Read the state with the existing reader (`load_processed`); the last line per image counts.
- Accept `blurred`, `clean`, `night`. Reject `refused`, `replacing` and a missing entry.
- If open decision 2 is yes: after `copy_images_to_temp`, hash each copy and compare.
- On failure: log every offending image (name + status) in one error line per camera, then
  behave as decided in open decision 1. Never raise past the camera loop (per-camera errors keep
  later cameras running, see CLAUDE.md conventions).
- The Weekly is built from Dailies, so it inherits the gate. Monthly/Yearly are not covered:
  their frames are older than 24 h; they depend on the live job or the planned backfill
  (docs/verpixelung-box.md, open items).

## Tests (pytest, no box, no detector)

- Gate: each status (`blurred`/`clean`/`night` pass; `refused`/`replacing`/missing fail),
  last-line-wins, non-blur camera unaffected, historical run unaffected, checksum mismatch fails.
- Catch-up: selects the same images as the Daily; skips images with a final status; no time
  budget; waits for the blur lock; exit code 1 when anything stays open.
- Existing guard tests keep passing (only `box_writer.py` may start ssh/scp).

## Docs to update when built

docs/verpixelung-box.md (catch-up mode, cron), docs/betrieb.md (cron line, gate behaviour),
docs/handbuch.md (error case "Daily skipped: images not blurred"), README summary.
