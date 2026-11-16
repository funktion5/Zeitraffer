# Plan: the "checked" mark in every blurred or clean image

Status: DRAFT 2026-11-16, for Julius's review. Branch `feature/blur-checked-mark` (from `main` after
the watchdog, PR #8). Decisions behind it: [2026-10-30-live-blur-cron.md](2026-10-30-live-blur-cron.md)
(status block, 2026-11-16).

## Goal

The website's pick-up job (the colleague's, every 5 minutes) publishes an image of a blur camera
only when it carries our mark. An image the detector has not checked yet carries no mark, so it is
never published: the rule fails closed. The live round itself goes into cron only after this is
live (Julius, 2026-11-16).

## Decided (Julius, 2026-11-16)

- The mark is a JPEG comment with the text `blur:checked=true`. No mark means "not checked"; we
  never write `false`.
- Blurred **and** clean images get it. Clean images get **no backup**: their pixels do not change,
  so the original is the marked file minus the mark. The writer proves that before the swap.
- The detector runs around the clock: the round's night rule goes away, every image is checked.
- The colleague's job keeps its own list of blur cameras; images of other cameras never get a mark
  and are published as today.
- No new folder, no extra copy, no extra file next to the images.
- Only the round (live and 02:00 catch-up) marks; manual runs (`blur_frames`) blur as before, without
  the mark, and leave clean frames untouched (Julius, 2026-11-16 after the review: cleaner).

## Design

**The mark.** A JPEG comment segment directly after the first two bytes (the SOI marker `FF D8`):
`FF FE`, a two-byte length (payload plus 2), then the ASCII text `blur:checked=true`. 21 bytes in
total, always at the same place, so the pick-up job only reads the first 32 bytes of the file. The
pixels are untouched, so FFmpeg, the timelapse and the preview show the same image. A small module
`src/privacy/checked_mark.py` holds three pure functions: `add_mark(data)`, `has_mark(data)`,
`remove_mark(data)`. No new dependency.

**Blurred image** (`blur_box._process_image`): after `blur_frame`, the local copy gets the mark,
then backup, upload and swap run as today. `blurred_sha256` is the hash of the marked file, so the
existing checks (`replace`, power-cut recovery, preview) stay as they are.

**Clean image** (new writer method `BoxWriter.mark_clean(camera, name, original_sha256,
local_file)`):

1. the local file must be a complete JPEG with the mark, and `remove_mark` of it must hash to
   `original_sha256`: the only difference is the mark, nothing else can be swapped in this way;
2. the image on the box must still hash to `original_sha256` (unchanged since it was judged);
3. upload under the hidden temporary name (`scp`, as `upload_blurred`), check its hash;
4. check the box image once more, then `mv -T` the temporary file over it, check the result.

No new box command: `scp` and `mv -T` are already allowed. The round records `clean` with
`original_sha256` (as today) plus `marked_sha256`.

**An image that already has the mark** (a round cut off between swap and status line): the round
does not check it again. With a backup it is caught by the existing "already blurred" guard; without
one it is recorded as `clean` with `marked_sha256`, and never marked twice.

**Night images:** `_is_night` and the status `night` go out of the round. Old `night` lines stay
valid everywhere they are read (gate, watchdog, preview).

## Tasks (one at a time: failing tests first, then Julius checks and saves)

1. **The mark functions** (`src/privacy/checked_mark.py`, `tests/privacy/privacy_checked_mark_test.py`):
   add, detect, remove; adding twice is refused; a file that does not start with `FF D8` is
   refused; `remove_mark(add_mark(x)) == x`; the mark sits in the first 32 bytes.
2. **Blurred images get the mark** (`blur_box._process_image`): the uploaded copy starts with the
   mark; everything else of the blurred path unchanged (existing tests stay green).
3. **`BoxWriter.mark_clean`** (`box_writer.py`, `privacy_box_writer_test.py`): the happy path; a
   copy that differs in more than the mark is refused before any upload; a box image that changed
   is never overwritten (checked before upload and before the swap); no backup is written; only
   allowed commands are sent.
4. **Clean images get the mark in the round** (`blur_box._process_image`): status `clean` with
   `marked_sha256`; an image that already has the mark is recorded, not marked twice, and not sent
   to the detector.
5. **The night rule goes away** (`blur_box.process_box_camera`): a night image is checked like any
   other; old `night` lines still count as finished.
6. **The preview** (`src/privacy/preview.py`): a clean frame is accepted when it matches
   `marked_sha256` (new lines) or `original_sha256` (old lines).
7. **Docs and handover:** [verpixelung-box.md](../verpixelung-box.md) (the mark, clean images,
   no night rule), [verpixelung.md](../verpixelung.md) where the night rule is mentioned, and a
   short German note for the colleague (text, position, cameras, switch-over order).

## Checked, no change needed

- Manual runs (`blur_job.py`) fetch the blurred frames again after the blur; their clean frames now
  differ on the box only by the mark, the pixels are the same, so the video is unchanged.
- The "already blurred" guard compares with the backups; clean images have none, so it is not
  affected.
- The watchdog reads only statuses.

## Go-live order (after the merge)

1. `git pull` on the VPS (no job running).
2. Remove `BlurTest` from `privacy.blur_cameras` and `ignored_cameras`; `./install.sh cron_hint`
   prints the two `*/5` lines (own small step).
3. Julius pastes the live round and watchdog lines; the first rounds mark new images.
4. Only then the colleague switches the pick-up job to "marked images only" for SLSV and
   Scheunenviertel, and only for images from that moment on: older images carry no mark.

## Out of scope

- Marking old images: only new ones matter for the website.
- A push message from the watchdog.
- The parked blur-lock wait (see the live blur plan).
