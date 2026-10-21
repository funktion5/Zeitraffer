# Highlights flagger: design

Status: draft for review, 2026-10-21. Nothing here is built. Julius and Claude code on the Pi
together and Claude runs the test suite there. Production runs and the crontab stay with
Julius.

## Intent

Every night, look at the Daily images of each camera and set aside the few that show something
special, so that a person can open a page the next morning, see the images directly (not file
names to look up), and pick the ones worth using for YouTube or the website.

It is a separate program. It does not know about, depend on, or care whether an image was or will
be blurred, and it shares no code path with the pixelation.

## Goals

1. A standalone command that takes the images of one camera and one day and writes a report
   folder: copies of the flagged images plus a manifest.
2. Version 1 flags, in this priority order: big animals, then birds, then balloons (balloons only
   to the extent the model already catches them, see Detection).
3. Testable without the Pi: the same command runs on any folder of images.
4. The output is a stable contract (see Output) so the web UI's future Highlights page only reads
   a folder and never has to know how flags were found.
5. Every flagged image stays reviewable for the whole retention (not only last night): Julius may
   look once a week and must find all flagged images of that week. Nothing is dropped to keep a
   list short.

## Non-goals (version 1)

- Out-of-place content and lens obstructions (a spider as a black shape). Planned later, probably
  background difference; it needs example frames first.
- Dedicated balloon detection (needs another model or training).
- Merging repeated sightings into events: frames are 5 to 10 minutes apart, so the same animal
  is rarely visible twice.
- The Highlights page itself. It gets its own design after reading `web/`.
- Any change to `src/` outside the new package, to `src/privacy/`, or to the existing nightly job.
- New dependencies: onnxruntime, numpy and OpenCV are already in `requirements.txt`.

## Anti-goals

- A page full of false flags. A handful per day is accepted, and the page sorts by score so the
  likely ones come first. Output is not capped (decided 2026-10-21): hiding flagged images is
  worse than a long list.
- Dropping or hiding a flagged image for any reason other than Julius deleting it.
- Anything that slows, blocks or crashes the nightly production run, or competes with its
  encodes for memory on the Pi.
- Any write to the camera originals (`/mnt/cameras`) or the Storage Box. The flagger only reads.

## Detection

Measured on one real frame (Strandallee, 2026-10-20 08:14:58, a large white bird in flight,
about 97 x 46 px) with the production YOLOX model, all 80 COCO classes, whole frame plus the
4 overlapping tiles used by `src/privacy/detect.py`:

| Mode | airplane | bird | kite |
|---|---|---|---|
| whole frame only | 0.73 | 0.05 | 0.24 |
| whole frame + 4 tiles | 0.87 | 0.50 | 0.24 |

Consequences, all decided with Julius unless marked as a call:

- The model labels a flying bird side-on as an aeroplane first. So a "flying object" group,
  `bird` + `airplane` + `kite`, is flagged when any member passes its threshold, and the report
  shows the model's own guess ("airplane 0.87") next to it. Real aeroplanes are flagged too
  (decided 2026-10-21): a plane and a bird that looks like one cannot be told apart by this
  model, and Julius would rather see both.
- An "animal" group: `cat`, `dog`, `horse`, `sheep`, `cow`, `elephant`, `bear`, `zebra`,
  `giraffe`. COCO has no deer, boar, seal or swan; they will come back as horse, cow, sheep, dog
  or bear, or not at all. Flagged generically as "animal" with the model's guess shown. Wrong
  labels do not matter because a person looks at the image.
- A class belongs to exactly one group, so `bird` is only in the flying group. A swan on the
  water is therefore stored as `flying`; this does not matter, because the page shows the
  model's label, not the group.
- Tiles are required: use the same whole frame + 4 tiles as the blur detector.
- Balloons: no COCO class. A balloon may come back as `kite`; this is untested.
- Starting thresholds (my call, to be tuned on real frames): 0.30 for the animal group, 0.30 for
  the flying group. The ordinary-frames folder decides.

## Architecture (my call)

A new package `src/flagger/`, with its own small YOLOX wrapper (letterbox, grid, decode, NMS,
about 60 lines taken from `src/privacy/detect.py`). Duplication is accepted on purpose: it keeps
the blur detector, which is stable and sensitive, completely untouched, and keeps the two
programs independent. If both prove stable, the shared part can be extracted later.

It reads the day's images for one camera with the existing read-only helpers in `src/images.py`
(`find_images_for_dates`, daylight selection), so "the Daily images" means the same set as in the
Daily video. On the CLI an explicit `--images <folder>` bypasses that for testing.

Which cameras are checked comes from `config/config.json`, a new `flagger` section (decided
2026-10-21: chosen cameras, which ones is decided after testing):

```json
"flagger": {
	"cameras": [],
	"retention_days": 30
}
```

The list is empty by default, so the program does nothing until cameras are chosen. A
`--cameras` option overrides it for testing. A camera named there must exist and must not be in
`ignored_cameras`; otherwise the run stops before reading anything.

Scheduling (decided 2026-10-21): runs after the nightly job, never alongside its encodes. The
flagger takes the shared run lock `state/zeitraffer-run.lock` itself (the lock cron, web jobs
and the storage filter already use) and skips with a log line when it is held. The cron line
runs it after `src.main` has released that lock:

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && .venv/bin/python3 -m src.main'; cd <projektpfad> && .venv/bin/python3 -m src.flagger.run
```

It must not run inside `flock -c` itself: its own lock attempt would then fail against the
lock cron is holding. Building it into the Daily job (frames already in `temp/`) was
considered and rejected, because it would change `src/jobs/`. Only Julius edits the crontab.

## Output (the contract with the web UI)

```
videos/<camera>/highlights/<YYYY-MM-DD>/
	<original file name>.jpg      clean copy of the flagged image, no overlay; the suffix
	                              is always lowercase `.jpg` (originals may end in `.JPG`)
	manifest.json
```

This sits next to `videos/<camera>/manual-runs/`, so the existing Apache `/videos/` alias and
its Basic auth already serve it, and the pipeline's retention (which only touches
`videos/<camera>/<job>/` for known jobs) never looks at it (checked in `src/video.py` and
`src/jobs/`, 2026-10-21).

`manifest.json` (written to a temporary name and renamed, so a reader never sees a partial file):

```json
{
	"schema": 1,
	"camera": "Strandallee",
	"date": "2026-10-20",
	"created": "2026-10-21T03:12:44+02:00",
	"detector": "<model name and hash, settings>",
	"checked": 143,
	"items": [
		{
			"file": "strandallee-26-10-20_08-14-58-20.jpg",
			"taken_at": "2026-10-20T08:14:58+02:00",
			"group": "flying",
			"label": "airplane",
			"score": 0.87,
			"box": [716, 579, 814, 625],
			"image_size": [1920, 1080]
		}
	]
}
```

- A camera with nothing flagged still gets a manifest with `items: []` and `checked`, so the page
  can show "checked, nothing found" instead of an absence.
- The page draws boxes from `box` as an overlay; the stored image stays clean so a download is
  usable as is.
- No cap: every image above the threshold is kept and listed. Order inside the manifest is by
  score, highest first. Even a camera where every frame is flagged costs only about 40 MB a day
  at today's image sizes.
- The page must be able to show all retained days at once (a week, or the whole retention), per
  camera and per day, not only the latest night. That is a requirement on the web UI design.
- `taken_at` is the image's local time, parsed from its file name with the existing helpers in
  `src/images.py` (`image_moment`), so the page can show a time without parsing names itself.
  An unparseable name is skipped and logged, never guessed.
- The web side is specified in `2026-10-21-highlights-page-design.md`.

## Behaviour

- One camera failing never stops the others. Exit code 1 if any camera failed, otherwise 0.
- An unreadable image is logged and skipped. This is not fail-closed like the blur job: a missed
  flag costs nothing.
- Log: `logs/flagger/<date>.log`, one summary line per camera (checked, flagged, failed).
- Re-running a camera and day replaces its report folder (written to a temporary folder, then
  swapped). It never touches another day or camera.
- Cleanup (decided 2026-10-21): everything older than `flagger.retention_days` (30) is deleted
  by the flagger itself at the end of each run, whether or not the camera is still in
  `flagger.cameras`. It goes by the date in the folder name, not file times: every
  `videos/<camera>/highlights/<YYYY-MM-DD>/` folder whose date is more than 30 days before today
  is removed with its images and manifest. It looks only at `videos/<camera>/highlights/`
  directories whose names match the date pattern exactly, and touches nothing else. Deleting by
  hand on the page stays possible. A failed cleanup is logged and never fails the run.

## Testing

- Unit tests with synthetic images and an injected fake model: grouping and thresholds,
  manifest content and atomic write, empty-day manifest, unreadable image, re-run replacing a
  folder, cleanup staying inside the output root, empty camera list doing nothing, an unknown or
  ignored camera stopping the run. CI has no model file
  (`models/` is gitignored), so no CI test needs the real one.
- Manual acceptance test on the Pi: the Strandallee bird frame (kept locally under
  `sandbox/flagger-samples/`, not in git) must be flagged. A folder of ordinary frames from
  several cameras shows the false-flag rate; thresholds are tuned from that.
- Speed is measured on the Pi, per image and per night. The only number so far is 0.13 s (whole
  frame) and 0.57 s (tiled) on a Mac, which says nothing about the Pi.

## Decided with Julius (2026-10-21)

- Real aeroplanes are flagged together with birds.
- Chosen cameras only, listed in `flagger.cameras`; which ones is decided after testing.
- No cap on flagged images. They must be reviewable for the whole retention.

- Retention is 30 days, applied to everything (see Behaviour).

## Open questions (Julius)

None left for the flagger.

## Left to the builder

File layout inside `src/flagger/`, the CLI flag names, the exact JSON field order, log wording,
and how the shared YOLOX plumbing is written, as long as the contract above holds.
