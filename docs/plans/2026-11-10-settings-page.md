# Settings page (web UI)

Status: DRAFT design, 2026-11-10. Not approved, nothing built.

## Why

`config/config.json` holds every setting, and only IT colleagues touch it. Julius wants the other
colleagues who use the web UI to change the values that are safe to change, and nothing else: a second
"public" settings layer controls which keys may be altered and which not. This is Julius's own idea, not a
reaction to a request from the colleagues.

## What it is

A new page `/settings.php`, a link "Einstellungen" with a gear icon at the right end of the header, and
one form with the settings in groups and ONE save bar at the bottom (mockup A of the 2026-11-10 session:
groups, a "last saved" line, a reset button, one Save). The changes go to a separate file
`config/settings.json`; `load_config()` lays its allowed keys over `config.json`.

## Decisions by Julius

- Audience: the colleagues who use the web UI. IT colleagues keep editing `config.json` directly.
- One page, one Save button (not a Save per group).
- The "Einstellungen" tab sits on the RIGHT side of the screen, with a gear icon.
- The settings file is git-ignored; the VPS and the Mac each have their own.
- The list of changeable settings is the one below (Julius agreed to the list I proposed). Both the 12-month
  daylight buffer table and the flagger camera list are ON the page (2026-11-10).
- The save goes through a protected, root-owned wrapper ("safer", 2026-11-10), not through PHP writing the
  file itself.

## Changeable settings (the allowlist)

| Group | Keys | Range (my proposal, tune in review) |
|---|---|---|
| Video quality | `timelapse.crf` | whole number 18 to 35 |
| | `timelapse.daily_framerate`, `monthly_framerate`, `yearly_framerate` | whole number 1 to 60 |
| Cameras | `ignored_cameras` | list of camera names (a checkbox per camera, unticked = ignored) |
| | `flagger.cameras`, `flagger.retention_days` | camera names; whole number 1 to 365 |
| Daylight and windows | `daylight_buffer_minutes` | whole number 0 to 240 |
| | `automatic_daylight_buffer_minutes` (12 months) | whole number 0 to 240 each |
| | `interval_window.target_time`, `tolerance_minutes` | `HH:MM`; whole number 0 to 240 |
| | `min_coverage_days.monthly`, `yearly` | monthly 1 to 31, yearly 1 to 366 |
| Logs | `log_retention_days` | whole number 1 to 365 |

NOT changeable, on purpose: everything under `privacy` (which cameras are blurred, ignore boxes, detector
command) because it is a data-protection decision; `location`; `timelapse.ffmpeg_threads` and
`image_scan_stall_timeout_seconds` (a wrong value can overload the 2-core VPS or stall jobs).

## How it works

- **One source of truth for the allowlist.** A small Python module defines the allowed keys, types and ranges.
  `load_config()` uses it to merge `settings.json` over `config.json`; the writer uses the same module to
  validate a save. PHP does not repeat the rules.
- **Merge rule:** an allowed top-level key replaces the base value; the 12-month buffer map merges by month,
  so a file with one month changes only that month. Unknown or out-of-range keys in the file are ignored with
  a log warning, so a typo cannot break the night run. A missing or broken file means no overrides.
- **Save:** a wrapper (same pattern as `timelapse-web-rebuild`: root-owned script under `/usr/local/sbin/`,
  sudoers rule, installed by `./install.sh web_bridge`) receives the submitted values, validates them with the
  Python module, and writes `config/settings.json` atomically (temp file in the same folder, then rename,
  mode 0644 so the web server user can read it). The values travel as ONE JSON argument, because the PHP
  process runner closes stdin. Invalid input saves nothing and the page lists every error.
- **Stale page check:** the form carries the settings file's modification time as a hidden field. If the file
  changed since the page loaded, the save is refused with "Die Einstellungen wurden inzwischen geändert, bitte
  Seite neu laden". No file yet counts as time 0.
- **Web guards:** as on `camera.php`: session CSRF token compared with `hash_equals`, only `confirm = yes`
  accepted, every submitted value validated on the server, German messages. Access is the existing Basic Auth.
- **Log:** one line per save with the changed keys and old and new values, in a private log; no IP address,
  no user agent.
- **PHP readers:** `readProjectConfig()` (`web/src/video-library.php`) and `readHighlightsConfig()`
  (`web/src/highlights-library.php`) both read `config.json` directly today. They get one shared reader that
  applies the same overlay, so the pages show the values the jobs use. PHP repeats only the allowlisted KEY
  NAMES (no ranges); a test compares that list with the Python allowlist so the two cannot drift apart.
- **When it applies:** the next job that starts reads the new values; a running job is unaffected. The page
  says so, and says a new CRF changes only videos built afterwards, not existing ones.
- **Where the file lives:** `config/settings.json` on the VPS is the truth. The web UI writes it there. A
  missing file means no overrides, so a seed is optional. Julius prepares a starting file on the Mac and
  rsyncs it to the VPS ONCE, with `--no-perms --ignore-existing` (so it can never overwrite a saved file),
  after the `.gitignore` entry is pulled. After that it is never rsynced again (it would erase the
  colleagues' changes). Seed only the values that should differ from `config.json`: a key in
  `settings.json` overrides `config.json`, so a seed with every value would hide later edits of
  `config.json`. `./install.sh permissions` closes every file in `config/` except `config.json` to the web
  server user today, so it gets a second exception for `settings.json` (the pages must read it). A tracked `config/settings.example.json` shows the shape. `backup.sh` takes the file along
  so a new host gets it back; `./install.sh permissions` runs once after the seed so the wrapper's user can
  write it. The Mac may keep its own copy for local testing.

## UI

- Header: "Kameras" and "Highlights" stay at the left; "Einstellungen" with a gear icon is pushed to the
  far right, after the storage overview (my call). The gear is an inline SVG (no icon set, no CDN), marked
  `aria-hidden`, next to the visible word; the current page gets `aria-current="page"`.
- Page: groups as in mockup A, every field with a visible label and a unit, the default value shown beside the
  field, a visible focus state, a "last saved" line, a reset button (resets the form to the saved values).
- Cameras: a checkbox per camera, from `state/web-jobs/cameras.json` (what the nightly run lists from the
  box) PLUS the names already in `ignored_cameras`: that file leaves the ignored cameras out, so the union
  is every camera (my call; the web UI has no box access). Unticking a camera hides it from the camera list
  of the web UI at once (the pages read the merged config), and the page says so next to the list. A camera
  that is ticked again shows up in the web UI camera list after the next nightly camera-list refresh. The
  page refuses a save that would leave no camera ticked.
- BFSG/WCAG 2.2 AA: semantic fieldset/legend per group, labelled controls, error messages tied to their field,
  no colour-only state.

## Goals, non-goals, anti-goals

Goals: colleagues change the safe values themselves; a wrong value can never break the night run; one place
defines what is changeable.

Non-goals: roles or users beyond the existing Basic Auth, editing `privacy` or `location`, a history or undo
page, a per-camera override of the settings, applying a change to a running job.

Anti-goals: a way to change a setting that is not on the allowlist, however the request is crafted; a save
that half-applies; a settings file that makes `load_config()` raise.

## Build order (one task at a time: failing tests first, then Julius checks and commits)

1. Python allowlist module and the overlay in `load_config()` (tests: merge rule, ranges, unknown keys,
   missing and broken file).
2. One shared PHP reader for both libraries (structural PHP tests).
3. The writer and its wrapper: validation, atomic write, stale-page check, log line; `install.sh web_bridge`,
   `permissions`, `.gitignore`, `settings.example.json`, `backup.sh`.
4. The page and the header link (render a preview with fake data and look before handing over).
5. Docs: `docs/weboberflaeche.md`, `docs/konfiguration.md`, README only if it names the pages.

## Calls I made (Julius to check)

- The ranges in the table.
- The Python module as the only validator (PHP repeats no rules). The wrapper itself is Julius's decision; it
  costs one more wrapper to install (run `web_bridge` when no job runs).
- The camera list (video folders plus ignored names), and the far-right placement after the storage overview.
- The log line with old and new values.

## Open for Julius

Nothing open at the moment, apart from approving this design.
