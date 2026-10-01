# TODO — Custom time window (`--from` / `--to`)

Status: planned 2026-10-01, not started. Implement after the current interim task.

## Decisions (agreed with Julius, 2026-10-01)

- Missing days are never a reason to skip: encode what exists, log the gaps.
- Hard cap: 21 days inclusive (`to - from + 1 <= 21`).
- New `--framerate` CLI flag (per run, never persisted). Web toggle for it comes later.
- Web UI gets a "Benutzerdefiniert" job option with from/to date fields.
- No lock in `main.py`; the web wrapper already takes `state/zeitraffer-run.lock`.

## Open questions (answer before starting)

1. Does the 21-day cap apply to every selection style, or only daylight selection?
2. Is a `--style daily|monthly|yearly` switch still wanted? With a 21-day cap, daylight
   selection (as Daily/Weekly) is the natural fit; midday/5-per-day selection mostly matters
   for long windows. Plan below assumes daylight selection only, no `--style`.
3. `--framerate` for custom runs only, or for every manual/historical run? Plan: custom only
   now, widen when the web toggle lands. Allowed range? Plan: 1-60.
4. Filename: always include `_<fps>fps`, or only when it differs from the default? Plan: always
   (variants stay unambiguous).
5. May `--to` be today (incomplete day)? Plan: match whatever `--target-date` accepts.

## Behaviour

```
.venv/bin/python3 -m src.main --from 2025-06-01 --to 2025-06-14 --cameras SLSV \
	[--framerate 15] [--daylight-buffer-minutes 60]
```

- `--from` / `--to` (dest `from_date` / `to_date`): both required together, `from <= to`,
  span <= 21 days. Mutually exclusive with `--date`, `--jobs`, `--target-date`.
- `--cameras` required (one or more).
- Frame selection: Weekly's daylight selection per day (sunrise/sunset + buffer), sorted by
  time, then the cross-day duplicate filter. Buffer from config, `--daylight-buffer-minutes`
  overrides.
- Framerate: `daily_framerate` (10) unless `--framerate` is given.
- No run-in-progress marker, no retention, log type `custom` (`logs/custom/`).
- Output: `videos/<camera>/manual-runs/custom/<camera>_<from>_<to>_<buffer>min_<fps>fps.mp4`,
  written via the usual `.tmp.mp4` + atomic replace.
- Missing days: logged as ranges (`format_date_ranges`) plus "N of M days available", then
  encoded anyway. A camera with zero images is skipped with a warning (nothing to encode).
- Per-camera `OSError` / `TimeoutError` / `CalledProcessError` caught, later cameras continue.

## Steps

### Python

- [ ] `src/jobs/weekly.py`: generalise `collect_weekly_images` into a range-based helper
      (`start_date`, `end_date`); Weekly keeps calling it with its 7-day window. No behaviour
      change for Weekly.
- [ ] `src/video.py`: `TimelapseType` gains `"custom"`; `get_video_path` / `create_timelapse`
      / `create_image_timelapse` / `create_temp_directory` accept an optional start date and
      framerate suffix for custom. Existing call sites unchanged.
- [ ] `src/jobs/custom.py`: `run_custom_job(config, cameras, start_date, end_date, framerate)`
      with the summary line `created/skipped/failed | run_id` like the other jobs.
- [ ] `src/main.py`: `--from`, `--to`, `--framerate` plus validation; dispatch to
      `run_custom_job`; `configure_file_logging("custom")`. Check `src/logger.py` accepts the
      new log type.
- [ ] Tests: `tests/custom_test.py` (gaps encoded not skipped, zero images skipped, cap,
      output path, framerate and buffer passthrough), `tests/main_test.py` (every invalid flag
      combination), `tests/video_test.py` (custom path), Weekly tests green after refactor.

### Web (wrapper install is a live-system change — ask first)

- [ ] `scripts/timelapse-web-trigger`: job `custom` takes `<from> <to>` instead of one target
      date; validate both dates, order and 21-day cap in bash too (PHP is not the only
      caller). Buffer required for custom.
- [ ] `scripts/timelapse-web-worker`: build `--from --to --cameras --daylight-buffer-minutes`.
- [ ] `scripts/timelapse-web-delete`: allow job `custom`.
- [ ] `web/src/job-runner.php`: custom variant of `startVideoJob` (argument array via
      `proc_open`, no shell string).
- [ ] `web/public/camera.php`: radio "Benutzerdefiniert"; fieldset with two labelled
      `type="date"` inputs (Von / Bis), shown only for custom; daylight buffer fieldset also
      shown for custom. Server-side validation (CSRF, ISO dates, order, cap, buffer) with
      German messages. Same keyboard/focus/label handling as the existing fieldsets.
- [ ] `web/src/video-library.php`: label `custom` => "Benutzerdefiniert", add to the manual
      job list; `extractManualVideoMetadata` learns the custom filename pattern (display
      "01.06.2025 – 14.06.2025"); unknown names still fall back to the raw filename.
- [ ] Web tests (`tests/web_status*_test.py`) for the new wrapper arguments.
- [ ] Re-install wrappers with `sudo install` (README "Wrapper installieren") — ask first.
- [ ] `migrate.sh verify` afterwards (www-data must read `videos/*/manual-runs/custom/`).

### Docs

- [ ] README: section "Benutzerdefinierter Zeitraum" under "CLI und Job-Auswahl", invalid
      combinations, "Historische Ausgaben" path, web "Aktueller Funktionsumfang",
      "Timelapse-Typen".
- [ ] CLAUDE.md: CLI line and `src/jobs/custom.py` in Structure.

### Later (separate change)

- [ ] Web framerate toggle wired to `--framerate`.

## Verification

- `ruff format . && ruff check . && pytest` green (pre-existing `images.py` format diff aside).
- One short CLI run for one camera — Julius runs it in the terminal.
- Web: start a custom job, status updates, video shows in the library, delete works.
