# Blur (Verpixelung) settings tab

Status: DRAFT design, 2026-11-10. Not approved, nothing built. It extends
`2026-11-10-settings-page.md` and REPLACES its rule that the `privacy` block is never changeable on the
page. Julius and a colleague decided on 2026-11-10 that the people who use the web UI may change the blur
settings themselves: "the people here know what they do".

## Why

Adding a camera to the blur job, tuning how strongly people are pixelated, and fixing false detections
(a buoy, a camera hook) currently needs IT and a hand edit of `config.json`. The colleagues want to do it on
the page, and to fix false detections by drawing on a preview picture of the camera.

## Decisions by Julius

- A second tab "Verpixelung" next to "Allgemein". Each tab has its OWN save button and they must never
  conflict. Two pages shown as tabs (my reading of "2 tabs"): a tab strip on top of `/settings.php` and the
  new `/verpixelung.php`.
- The sliders use the limits the code already enforces (below). No "may only get stronger" minimums.
- Cameras may be added AND removed from the blur job. The page shows an important note: a camera that is
  already live and blurring must not be removed.
- A confirm dialog before every save on the Verpixelung tab, because it is a privacy setting.
- Every value is explained on the page in words a five-year-old understands (German, short sentences, an
  everyday example).
- Ignore boxes are edited by drawing on a preview picture of the camera, and the top share is shown on it.
  The preview is required; it shows only frames the blur job has confirmed, never raw frames. The editor
  must work whether or not the picture happens to show a false detection: a box may be added on purpose,
  where one might appear.
- The restore buttons (per section and "Alles auf Standard") exist on the Verpixelung tab too, and every
  button only resets inside its own tab.
- The Standard everywhere is the current live setting, which is `config.json`: the pages show it and the
  restore buttons set it (see "Defaults and restore").

## What becomes changeable (the privacy scope)

| Key | Rule (the code's own limits, `src/privacy/anonymize.py`) |
|---|---|
| `privacy.blur_cameras` | list of plain camera names (the cameras whose images the box job may pixelate in place) |
| `privacy.blur.strength` | number 0.05 to 0.5: size of the pixel blocks, bigger = coarser = stronger |
| `privacy.blur.padding_ratio` | number 0.05 to 1.0: how far the blur reaches around a person, per side |
| `privacy.blur.feather` | number 0 to 1: how much of that margin fades softly (the person's own box is always fully blurred) |
| `privacy.ignore_top_share` | number from 0 up to below 0.5, GLOBAL: a detection mostly in the top band is dropped, 0 = off |
| `privacy.min_person_score.<camera>` | number 0 to 0.5 per camera: persons scoring below it are NOT blurred (higher = fewer blurred; the detector already ignores everything under 0.25) |
| `privacy.ignore_boxes.<camera>` | list of boxes `[x0, y0, x1, y1]`, whole numbers, x1 > x0, y1 > y0: a detection that overlaps a box with an intersection over union of at least 0.5 is dropped |

Still NOT on the page, IT only: `skip_labels`, the detector command and its thresholds, `location`, ffmpeg
threads, the scan timeout (nobody asked for them; they change what is detected or break the run).

Facts that shape the page: a camera in `blur_cameras` is the allow-list that lets the NIGHTLY box job rewrite
its images in place on the Storage Box (originals backed up). From the next night the job pixelates today and
the two days before. Automatic videos of that camera use confirmed frames only (older, unblurred frames are
left out, so its first videos may be skipped or short). Manual runs blur their frames on the box first. A new
camera uses the global detector thresholds; its quality is unchecked until someone looks at the first results.
Ignore boxes match by overlap (>= 0.5), so a big box does not swallow people inside it. Values only affect
images blurred afterwards; already pixelated images stay as they are.

## How saving works (two files, no conflict)

- `config/settings.json` stays the "Allgemein" file. The privacy values go to `config/settings-privacy.json`
  (git-ignored like the first, one per host). `load_config()` lays both over `config.json`.
- The writer takes a SCOPE (`general` or `privacy`). A scope has its own allowlist, its own file, its own
  modification-time check and its own line in the log (`logs/settings.log`, tagged with the scope). A save in
  one scope can neither overwrite nor make stale the other.
- The wrapper gets the scope as a first argument, checked against a fixed list. `install.sh permissions`,
  `backup.sh`, `.gitignore` and the restore step learn the second file.
- Per-camera keys (`min_person_score.<camera>`, `ignore_boxes.<camera>`) are keyed by plain camera names, so the
  privacy allowlist needs rule TYPES beyond fixed keys: decimal numbers, a camera-keyed map, a list of boxes.
  The drift test between the Python and PHP key lists compares patterns for those.
- The privacy form submits ONLY privacy keys, and the writer refuses any key outside the scope.

## The page

- Tab strip "Allgemein | Verpixelung" on both pages, `aria-current` on the open one, each tab a real page with
  its own form and save button.
- Verpixelung, in this order: the camera list (with the important note), the three blur sliders, the top-share
  slider, then one block per blur camera with its minimum-person-score slider and its ignore boxes.
- Every control has a short explanation under it in simple German and the "Standard" from `config.json`.
  Sliders show their number next to them; the numbers are also typed fields, for keyboard use.
- Ignore boxes are rows of four numbers (also the keyboard and no-preview fallback) kept in step with the
  drawing on the preview. The preview picture shows the pixelated frame, the existing boxes, and the top-share
  band; you drag a rectangle to add a box and remove a box from its row.
- The confirm dialog (`<dialog>`) opens on Save and lists in plain words what changes. A change to the camera
  list is shown in an "Wichtig!" block. Without JavaScript the same confirmation is a tick box. The server
  accepts a save only with the exact confirmation value, as on the other pages.

## The preview picture

- The web server user cannot reach the Storage Box. A root-owned wrapper (`timelapse-web-preview <camera>`, same
  pattern as the others) runs a small Python script as the run user. It picks a frame the box job has CONFIRMED
  (the blur state lists them): a daylight frame nearest midday, one that shows blurring first, then a clean
  one, a night frame only as a last resort. A camera with no confirmed frame at all gets no preview and
  shows the number rows only,
  fetches it with the existing frame source, and writes `state/web-jobs/previews/<camera>.jpg` plus a small
  JSON file with its width and height. The page's button "Vorschau aktualisieren" starts it; the cache is
  served by `web/public/preview.php?camera=<name>` (plain name, known blur camera, JPEG only).
- The picture keeps its original size, so a rectangle drawn in the browser converts to pixel coordinates by one
  scale factor.

## Defaults and restore

- The Standard is whatever `config/config.json` holds, which is the current live setting. Today that is:
  `blur_cameras` BlurTest, Scheunenviertel, SLSV; `strength` 0.08, `padding_ratio` 0.05, `feather` 0.5;
  `ignore_top_share` 0.333; `min_person_score` SLSV 0.35; `ignore_boxes` for BlurTest (1 box) and
  Scheunenviertel (5 boxes). With both privacy and general files empty, each page therefore opens showing
  exactly the live values, and nothing changes until someone saves.
- Every control shows its Standard, and the restore buttons set it: per section and "Alles auf Standard" in
  the bar, on BOTH tabs. A button only resets the fields of its own tab, because the tabs are separate pages
  and forms and the script only touches its own form. Nothing is saved until Save (and, on the Verpixelung
  tab, the confirm dialog).
- The camera list restores to the base list (a camera that was added is unticked again). For a camera that is
  not in `config.json`, the Standard is "no minimum score" and "no ignore boxes". The box rows and the
  per-camera blocks are rebuilt from the Standard, which the page hands to the script as data.
- Tests: every Standard shown equals the value in a test config; one test renders both pages against the REAL
  `config/config.json` and compares what they show with the file, so the two cannot drift apart; one test
  checks that a restore button of one tab touches no field outside its own form.

## Goals, non-goals, anti-goals

Goals: the colleagues can add or remove blur cameras, tune the blur and fix false detections themselves, and
understand every value without help.

Non-goals: per-camera blur strength, editing `skip_labels` or the detector, a history or undo page, showing raw
(unblurred) frames.

Anti-goals: a save in one tab that changes or blocks the other; any raw frame reaching the web UI; a blur
camera removed or an ignore box added without the confirm dialog (or its no-JavaScript tick box).

## Build order (tasks, one at a time, tests first, Julius saves each)

1. Scopes: the privacy file, the scoped allowlist and loader, the scope argument through writer, wrapper,
   runner and PHP reader; install, backup, restore and ignore rules. The general page keeps working unchanged.
2. The privacy rule types (decimal, camera-keyed map, box list, camera list) with the code's limits, in the
   writer and the PHP key patterns, with the drift test.
3. The Verpixelung page without the preview: tab strip, camera list and note, sliders, per-camera score and
   box rows, plain-German explanations, confirm dialog.
4. The preview: the picking script, the wrapper, the endpoint, the button.
5. The drawing editor on the preview, kept in step with the number rows, with the top-share band; clicked for
   real in headless Chrome.
6. Docs (`docs/weboberflaeche.md`, `docs/konfiguration.md`, `docs/verpixelung-box.md`) and the memory note.

## Calls I made (Julius to check)

- Two pages shown as tabs, not one page with a script-driven tab list.
- A separate file and scope per tab instead of one file with a revision counter.
- The preview refreshes on a button press through a wrapper, not from a cron line (no crontab change); a new
  camera has a preview only after its first blurred night.
- The preview frame: confirmed, daylight, nearest midday, status "blurred" first (it shows pixelated blobs),
  then "clean". The editor does not depend on a false detection being visible.
- The dialog on EVERY Verpixelung save, not only when the camera list changes.
- At most 50 ignore boxes per camera and coordinates up to 20000, as sanity limits.
- The preview (Task 4): the button asks the server synchronously (one frame takes seconds), not through a
  background job. The fetch is tried once, with no retry waits, and the wrapper stops the run after 90 s, so a
  box that does not answer cannot hold a web request for minutes.
- The preview frame must be the bytes the blur job recorded: a "blurred" frame is checked against
  `blurred_sha256`, a "clean" one against `original_sha256`; a frame that differs (rewritten since) is skipped
  and the next candidate is taken, at most three. A night frame has no recorded bytes and is the last resort.
- Only the state of the last days is read (today and the two days before, as the nightly round does), so a
  camera the job has not touched for longer has no preview until its next round.
- "Vorschau aktualisieren" needs JavaScript and is hidden without it: a full page reload would throw away the
  unsaved edits of the form, so the button asks in the background and changes only the picture.

## Open for Julius

- The German explanation texts: I write them, Julius reads them.
- Nothing else at the moment, apart from approving this design.
