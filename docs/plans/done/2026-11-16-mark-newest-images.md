# Plan: mark the newest image of every camera that is not blurred

**DONE 2026-11-16:** built and merged (PR #10) as `extras/mark_newest.py`; not connected on the VPS (docs: `extras/README.md`).

Status: DRAFT 2026-11-16, reviewed by Julius the same evening (three changes below, "Decided"). Branch `feature/mark-newest-images` (from `main` after
the checked mark, PR #9). Builds on `2026-11-16-blur-checked-mark.md` (the mark itself).

## Goal

The website's pick-up job publishes **only images that carry the mark `blur:checked=true`**, for every
camera, with no list of cameras of its own (Julius and the colleague, 2026-11-16: one source, no
second list). Blur cameras are already marked by the live round. All other cameras are cleared for
the website by default, so their newest image gets the same mark without being looked at.

## Decided (Julius, 2026-11-16)

- **An optional extra in its own folder** (Julius, 2026-11-16 evening): `extras/mark_newest.py`, in git
  but not connected to anything. It changes no existing code and nothing depends on it. Whoever wants
  it appends one command to the live round's cron line (`…; …`, so it also runs when the round
  failed); removing that command switches it off again.
- It marks only the **newest** image of each camera that is neither in `privacy.blur_cameras` nor in
  `ignored_cameras`. No check, no backup, no backfill.
- Same mark text as the blur cameras: `blur:checked=true` (meaning: cleared for the website).
- Ignored cameras (e.g. `BlurTest`) are never written.
- **The same image as the pick-up script** (decided after reading it): the colleague's
  `copy_hetzner2siteground_byfolder.sh` takes the newest **non-empty** JPG of a folder (it skips
  0-byte files and falls back to older ones). We mark exactly that one: the newest image whose
  listed size is not 0. Otherwise an empty newest upload would freeze the camera on the website.
- **Afterwards the pick-up script requires the mark for every camera** (its `IS_BLUR_CAMERA` check,
  `blur_cameras.conf` and `BLUR_CAMERAS_FILE` go away). Until this process is live, the script keeps
  the list (sent to the colleague 2026-11-16; local copy in the git-ignored `local/` folder).
- **A module with functions**, like `blur_box` and `blur_watch`, not a class: no state is shared
  between calls; the writer (`BoxWriter`) already is the class that holds the box.

## Folder

```
extras/
  mark_newest.py        # the module: the functions and main(), started with
                        # python -m extras.mark_newest; imports only what src/ already offers
                        # (BoxWriter.mark_clean, checked_mark, storage_box, config, logger),
                        # never the other way round
  mark_newest_test.py   # its tests
  README.md             # what it does, the cron command to connect it, how to switch it off (German)
```

No `__init__.py` or `__main__.py`: one file runs with `python -m`, like `blur_watch.py`. Another
optional add-on, if one ever comes, is one more file next to it.

Four one-line hooks outside the folder, so it is still tested and checked like the rest (the
Docker mount `../../extras` in `docker/zeitraffer-web/compose.yaml`, added with task 1, so the local
test container sees the folder):
`pyproject.toml` `testpaths` gets `"extras"` (pytest), the box-write guard test in
`tests/privacy/privacy_box_writer_test.py` also scans `extras/` (it must never write to the box
except through `BoxWriter`), and `docs/verpixelung-box.md` gets one line pointing to the README.
ruff already covers every folder except `archive/`.

## Design

Per camera of the box (`get_cameras()`) minus blur cameras minus ignored cameras:

1. List today's and yesterday's images with their size (yesterday so the last image before
   midnight is still found at 00:05) and take the newest **non-empty** one by the time in its name,
   the same choice as the pick-up script. The listing with sizes lives in the extra itself (a
   read-only `ls -l` through `StorageBox.run`, like `list_images_for_dates`), so `src/` stays
   unchanged.
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

To connect it, the live round's cron line becomes (documented in the README, not printed by
`install.sh cron_hint`, which stays as it is):

```cron
*/5 * * * * cd <projektpfad> && export TIMELAPSE_STORAGE_BOX=<ssh-alias> && timeout -k 10 240 .venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras; timeout 60 .venv/bin/python3 -m extras.mark_newest
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

1. **Choose the newest image of a camera** (pure function): newest non-empty by the name's time over
   today and yesterday; an empty newest file falls back to the one before; nothing when the camera
   has no non-empty image.
2. **Mark one camera** (`mark_newest_image`): skip remembered, settling, cut-off or already marked
   images; otherwise download, mark with `mark_clean`, remember. Tests with the fake box: the box image
   is the original plus the mark, no backup, nothing else touched.
3. **`main()`**: the camera list (box minus blur minus ignored cameras), one writer for exactly those,
   one failing camera does not stop the others, the summary line, exit codes.
4. **The remaining hooks** (guard test scans `extras/`, one docs line; testpaths and the Docker
   mount came with task 1) and the folder's
   `README.md` with the connect and disconnect steps.

## Afterwards in the pick-up script (the colleague's, after this is live)

Drop the list: every camera's newest image must carry `blur:checked=true`. The A/B test in
`local/hetzner2siteground-blur/test/` then needs the cases "other camera without a mark: no upload".

## Go-live order (after the merge)

1. `git pull` on the VPS (no job running).
2. Julius appends the command from `extras/README.md` to the live round's `*/5` line.
3. After the first runs (log line, a marked image of a non-blur camera checked read-only) the colleague
   switches to "marked images only" for all cameras.

## Out of scope

- A watchdog for non-blur cameras (newest image unmarked for too long): only if the colleague's switch
  shows it is needed.
- Marking older images of non-blur cameras.
