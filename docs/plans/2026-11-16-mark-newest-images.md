# Plan: mark the newest image of every camera that is not blurred

Status: DRAFT 2026-11-16, for Julius's review. Branch `feature/mark-newest-images` (from `main` after
the checked mark, PR #9). Builds on `2026-11-16-blur-checked-mark.md` (the mark itself).

## Goal

The website's pick-up job publishes **only images that carry the mark `blur:checked=true`**, for every
camera, with no list of cameras of its own (Julius and the colleague, 2026-11-16: one source, no
second list). Blur cameras are already marked by the live round. All other cameras are cleared for
the website by default, so their newest image gets the same mark without being looked at.

## Decided (Julius, 2026-11-16)

- A separate process, `src/privacy/mark_newest.py`, runs right after the blur round in the same cron
  line (`…; …`), so it also runs when the round failed.
- It marks only the **newest** image of each camera that is neither in `privacy.blur_cameras` nor in
  `ignored_cameras`. No check, no backup, no backfill.
- Same mark text as the blur cameras: `blur:checked=true` (meaning: cleared for the website).
- Ignored cameras (e.g. `BlurTest`) are never written.

## Design

Per camera of the box (`get_cameras()`) minus blur cameras minus ignored cameras:

1. List today's and yesterday's images (`list_images_for_dates`, as the round does; yesterday so the
   last image before midnight is still found at 00:05) and take the newest by the time in its name.
2. Skip it if it is the one already marked last time (`state/privacy/newest-marked.json`,
   `{camera: image name}`; saves a download every 5 minutes for every camera).
3. Skip it if it was uploaded less than 15 seconds ago (still uploading): the next run takes it.
4. Download it; skip it if it is cut off (no JPEG end marker) or already carries the mark (then just
   remember it).
5. Add the mark and swap it in with the existing `BoxWriter.mark_clean` (proves the copy is the
   original plus the mark, checks the box image is unchanged right before the swap, no backup).
   One writer per run, allowed only for these cameras.
6. Remember the name. One log line per run: `Newest marked: N cameras, M marked, K unchanged, F failed`.

A failure affects only that camera; the next run (5 minutes later) tries again. No lock: it never
writes to a blur camera, and two runs cannot overlap thanks to the time cap (`timeout 60`).

The cron line becomes:

```cron
*/5 * * * * cd <projektpfad> && export TIMELAPSE_STORAGE_BOX=<ssh-alias> && timeout -k 10 240 .venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras; timeout 60 .venv/bin/python3 -m src.privacy.mark_newest
```

(The watchdog line stays as it is.)

## Consequences (explained to Julius 2026-11-16)

- Once the colleague switches to "marked images only", **every** camera depends on the VPS: if it or
  ssh is down, nothing is marked and the website keeps the last marked image of every camera.
- A camera that uploads twice within 5 minutes: the older image is never marked, never published.
- The originals of all cameras change by the 21-byte mark (no pixel); another exception to "the
  pipeline never modifies the originals".
- About 15 listings every 5 minutes, plus one download and upload per new image.

## Tasks (one at a time: failing tests first, then Julius checks and saves)

1. **Choose the newest image of a camera** (pure function): newest by the name's time over today and
   yesterday; nothing when the camera has no image.
2. **Mark one camera** (`mark_newest_image`): skip remembered, settling, cut-off or already marked
   images; otherwise download, mark with `mark_clean`, remember. Tests with the fake box: the box image
   is the original plus the mark, no backup, nothing else touched.
3. **`main()`**: the camera list (box minus blur minus ignored cameras), one writer for exactly those,
   one failing camera does not stop the others, the summary line, exit codes.
4. **The cron line**: `install.sh cron_hint` prints the extended line (test first).
5. **Docs**: `verpixelung-box.md` (new section, cron line), `betrieb.md`, and a short list of what the
   colleague's job does after the switch (facts for Julius, no message).

## Go-live order (after the merge)

1. `git pull` on the VPS (no job running).
2. Julius replaces the live round's `*/5` line with the extended line from `./install.sh cron_hint`.
3. After the first runs (log line, a marked image of a non-blur camera checked read-only) the colleague
   switches to "marked images only" for all cameras.

## Out of scope

- A watchdog for non-blur cameras (newest image unmarked for too long): only if the colleague's switch
  shows it is needed.
- Marking older images of non-blur cameras.
