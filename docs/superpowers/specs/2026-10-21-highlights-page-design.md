# Highlights page (web UI): design

Status: draft for review, 2026-10-21. Nothing here is built. Written after reading all of `web/`
(about 59 KB), the delete wrapper, the README web chapter and the web tests. Julius and Claude code on the Pi
together and Claude runs the test suite there. Julius installs the wrapper and the sudoers
line himself.

Companion to `2026-10-21-highlights-flagger-design.md`, which defines the data this page shows.

## Intent

One page in the existing web UI where Julius sees the flagged images of the whole retention
(a week, a month, everything), directly as images, can download the ones he wants and delete
the ones he does not.

## Goals

1. Show all flagged images of the chosen period, grouped per camera (layout B, chosen by Julius),
   newest day first, highest score first inside a day.
2. Period choice: last day, last 7 days (default), last 30 days / whole retention. Optional camera
   filter.
3. Per image: the image itself, camera, day and time, what the model thought it saw and how sure
   it was, a download button and a delete button with the existing confirm dialog.
4. A configured camera with nothing flagged stays visible as one line ("geprüft, nichts
   gefunden", with the number of images checked), so a quiet camera is not mistaken for a
   skipped one.
5. Everything German, the same look as the rest of the UI, no external assets.

## Non-goals (version 1)

- Deleting several images at once (see Open questions).
- Thumbnails: the stored copies are 100 to 300 KB and the UI is for the local network, so the
  browser scales them (lazy loading).
- Changing or re-running detection from the page.
- Any change to the existing video pages beyond one navigation link.

## What already exists and is reused

| Need | Existing piece |
|---|---|
| Camera list, ignored cameras | `findAvailableCameras()`, `getIgnoredCameras()` in `web/src/video-library.php` |
| Config read (www-data may read `config/config.json`) | the reader behind `getIgnoredCameras()`; also gives `flagger.cameras` |
| Date helpers | `isValidIsoDate()`, `formatGermanDate()` |
| Login | Apache Basic auth on `web/public` and the `/videos/` alias; nothing to add |
| Serving the images | the `/videos/` alias already covers `videos/<camera>/highlights/...` |
| CSRF for POST | session token pattern in `camera.php` |
| Privileged delete | `runPrivilegedCommand()` + `projectRunUser()`, same `sudo -n -u` pattern |
| Confirm dialog | `<dialog>` with `data-delete-video` forms and a `window.confirm` fallback |
| Download | plain `<a href download>` to the `/videos/...` URL |
| Look | `style.css` tokens, header, `video-actions` buttons |
| Test pattern | `tests/web_php_test.py` copies `web/src` to `tmp_path` with a fake `sudo`; `tests/web_delete_test.py` runs the wrapper against a temporary project root |

## What is new

- `web/public/highlights.php`: thin page (parameters, CSRF, POST handling, markup).
- `web/src/highlights-library.php`: all logic, kept out of the page so it can be tested (the
  existing `camera.php` is untested because it hard-codes paths): list days and manifests for
  a camera and period, validate names, drop items whose file is gone, German labels.
- `web/src/highlight-delete.php`: calls the new wrapper, like `video-delete.php`.
- `scripts/timelapse-web-delete-highlight`: new root-owned wrapper (see Delete).
- A "Highlights" link in `web/src/components/header.php` next to "Kameras".
- Styles appended to `style.css`.
- `migrate.sh`: installs the new wrapper on a reinstall, warns (does not fail) when a restored
  sudoers file lacks its rule, and reports it in `verify`. `backup-from-mac.sh` needs no change,
  it already backs up the whole sudoers file. (Obsolete if the program later moves to a VPS.)
- README: install command and sudoers line in "Wrapper installieren", one bullet in
  "Aktueller Funktionsumfang", the new files in "Webdateien". Details in
  `docs/highlights-seite.md`.

## Page

`/highlights.php?days=7&camera=<name>`; `days` is one of `1`, `7`, `30`, `all`, anything else
falls back to 7. Filters are a labelled `<form method="get">`, so the state is in the URL.

```
Highlights                          Zeitraum: [7 Tage v]  Kamera: [alle v]  [Anzeigen]

Strandallee  (4)
  20.10.2026  (143 Bilder geprüft)
  +--------------------+  +--------------------+
  |      image         |  |      image         |
  +--------------------+  +--------------------+
  08:14  Flugzeug? 87 %    11:02  Vogel 61 %
  [Herunterladen] [Löschen]  [Herunterladen] [Löschen]
  ...
SLSV  (0)  geprüft, nichts gefunden (7 Tage, 1 001 Bilder)
```

- Cameras listed: every camera in `flagger.cameras` plus any camera that has retained highlights.
- A day with a manifest but no remaining images shows only its "geprüft" line.
- Tile = `<figure>` with `<img loading="lazy" width height alt>`, `alt` made of camera, time and
  label so it is meaningful without the picture. Width and height come from `image_size` to
  avoid layout shift.
- The model's box can be shown as an overlay, off by default with a "Markierung zeigen" toggle
  (my call). It is decoration only: the label text carries the information, never colour alone.
- German labels for the COCO classes the flagger uses: Vogel, Flugzeug, Drachen, Katze, Hund,
  Pferd, Schaf, Kuh, Elefant, Bär, Zebra, Giraffe. The model's guess is shown with a question
  mark ("Flugzeug?") because the guess is often wrong, as the bird test showed.
- One line above the list: "Die Bilder sind nicht verpixelt. Vor einer Veröffentlichung
  verpixeln." The copies are unblurred originals and the page exists to pick images for
  YouTube and the website.
- The page never lists a file that is not on disk: each manifest item is checked with
  `is_file` (and not a symlink). So deleting an image needs no manifest rewrite.

## Delete

Same security model as videos: `videos/` is read-only for `www-data`, so a root-owned wrapper,
run through `sudo -n -u <project user>`, does the removal.

`scripts/timelapse-web-delete-highlight <camera> <date> <filename>`:
- exactly three arguments (exit 64 otherwise), camera without `/`, `.`, `..`;
- date matching `YYYY-MM-DD`; filename matching `^[A-Za-z0-9._-]+\.jpg$`, no `/`;
- target only `videos/<camera>/highlights/<date>/<filename>`; must be a regular file and not a
  symlink (exit 66 otherwise); then `rm --`; never touches `manifest.json` or anything else.

PHP validates the same things before calling it, and checks that the camera and file are in the
current listing. POST only, session CSRF token, camera checked against the known list, a
redirect back to the same filters with a short message. Escaping with `htmlspecialchars` at
every output, as in the existing pages.

**Needs Julius on the Pi (root, once):** install the wrapper (`sudo install -o root -g root -m
755 ... /usr/local/sbin/`), add one `sudoers` line for it via `visudo -f
/etc/sudoers.d/timelapse-web`, and reinstall it after any future change, exactly like the
existing two wrappers. A re-run of the flagger for a day replaces that day's folder, so images
deleted earlier on that day come back; this is accepted because re-runs are manual.

## Accessibility (BFSG, WCAG 2.2 AA)

Semantic headings per camera and day, labelled filter controls, real `<button>` and `<a>`
elements with visible focus (the existing styles), native `<dialog>` for the confirm, the
confirm text names the file, nothing relies on hover or colour alone, image `alt` text as above,
all targets reachable by keyboard.

## Testing

- `highlights-library.php`: the same copy-to-`tmp_path` approach as `web_php_test.py`:
  period filtering, ordering, camera with no manifest, corrupt manifest (skipped, not fatal),
  missing image file dropped, bad names rejected, label mapping.
- `timelapse-web-delete-highlight`: like `web_delete_test.py`: removes a file, wrong argument
  count, bad date, path traversal in camera and filename, non-jpg, missing file, symlink,
  leaves `manifest.json` and other days alone.
- `highlights.php` itself and the visual result are checked by hand on the Pi, as with
  `camera.php` today.

## Decided with Julius (2026-10-21)

- The navigation name is "Highlights".
- Highlights older than 30 days are deleted by the flagger's own cleanup (see the flagger
  design); the page only shows what is still there.
- Deleting several images at once is later, not version 1.

## Open questions (Julius)

None left for the page.

## Left to the builder

Markup and CSS details, how the filters are laid out, the exact wording of messages (German,
matching the existing UI), and function names inside `highlights-library.php`.
