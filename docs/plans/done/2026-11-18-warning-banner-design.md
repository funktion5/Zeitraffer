# Design: warnings banner in the web UI

Status: built 2026-11-18 (branch `feature/warning-banner`), final review fixed.

## Why

Julius wants to see at a glance, without reading logs, whether something needs him. Today the nightly
report, the job logs, the flagger log, the upload log and the blur watchdog each say something, in
different places. Over the last 7 nights about 20 kinds of warnings fired every night, almost all of
them permanent states (cameras without images, coverage gaps), so a banner that shows "everything" is
noise. Rule (Julius): **the banner shows only what he has to take care of.**

## Decisions (Julius, 2026-11-18)

- On every page of the web UI, always visible. With nothing to report it says so: `Nichts zu melden.`
- No "Gesehen" button: a message stays until the next check no longer finds it.
- Each night replaces the previous night's messages; privacy messages are current (every 5 minutes).
- One line per problem: what, which camera, plus a short German hint what to do and the handbook
  section; always the time of the last night run underneath.
- Look: green with ✓ when fine, orange with ⚠ when there are messages; never colour alone (BFSG).
  Everyone who opens the web UI sees the same banner.
- Approach A (below). Julius is not fond of another cron job, so the collector is a step at the end of
  the existing 02:00 line, not a new cron entry.

Sketch:

```
✓ Nichts zu melden.
  Letzter Nachtlauf: 18.11.2026, 02:00–02:55 Uhr

⚠ 2 Meldungen
• Strandterrassen: 856 Bildnamen nicht lesbar
  → neue Schreibweise? Handbuch „Unlesbare Dateinamen“
• Upload auf die Website fehlgeschlagen (1 Kamera)
  → Upload-Protokoll prüfen; die nächste Nacht lädt erneut hoch
  Letzter Nachtlauf: 18.11.2026, 02:00–02:55 Uhr
```

## Goals

The banner reports exactly these (Julius approved the list; "camera fell silent" was dropped):

| # | Message | Source and rule |
|---|---|---|
| 1 | Night run did not run | Web UI, live: `warnings.json` is missing, or after 06:00 its night is not today's. Collector: the newest `logs/nightly/<run>/` folder is not from this night (the wrapper stopped before making one: run lock held, wrong preset, no camera list): one message "Nachtlauf nicht gestartet", and rules 3, 4 and 6 are skipped, so last night's lines never come back. |
| 2 | Night run interrupted | Collector: `state/run-in-progress` still exists when it runs. Only the automatic production run sets it (web and manual runs pass `--jobs`/`--date`), so it is trustworthy. Shown as one line together with a `FAILED (run)` from rule 3, not twice. |
| 3 | A camera or the run FAILED | Collector: `FAILED` lines in this night's `report.txt` (camera name and reason). |
| 4 | Storage Box unreachable | Collector: `Failed to access camera storage` in this night's `main.out`. |
| 5 | Disk nearly full | Web UI, live: the storage ring's existing level `warn`/`critical` (`storageLevel()`). Every page that includes the header already computes `$storage`; when it is null (unreadable) there is no disk message. |
| 6 | Unreadable image names | Collector: the `WARNING: <n> image names cannot be read` lines in this night's `report.txt`. |
| 7 | Flagger failed | Collector: every `ERROR` line in this night's flagger log (`Flagger not started: …`, `[<camera>] failed: …`, `[<camera>] none of N images could be read`). In `src/flagger/run.py` ERROR is used only for these, so each is actionable. |
| 8a | Privacy: images unblurred for more than 10 minutes, right now | Web UI from the watchdog's status file: a camera with stale images. |
| 8b | Privacy: watchdog not running or cannot reach the box | Web UI: status file older than 15 minutes, or it records an error. |
| 8c | Privacy: `Blur gate: no confirmed image - skipping camera` | Collector: that line in this night's Daily log only. The Daily skips a camera without images before the gate, so there the line always means "images, but none confirmed"; the Monthly/Yearly gate can also fire on an empty window and is not read. |
| 8d | Privacy: detection model missing | Collector: a model file named in `config.json` does not exist (the blur detector's and the flagger's, both read from config). |
| 9 | Upload failed or did not run | Collector: this night's block of `logs/siteground-delivery.log` (see "Night marker" below) has `fehlgeschlagen=` above 0, `Mindestens eine Kamera ist fehlgeschlagen.` or the missing-login message; no block for this night means the upload did not run. A run that skips every file still writes its `Ergebnis:` lines, so it is not "did not run". |

**This night.** The night is the collector's own start date. Night files count only if they belong to
it: the run folder's name (`YYYYMMDD-HHMMSS`) starts with that date; the job and flagger logs are
`logs/<job>/<date>.log`, read only from lines timestamped after the run folder's start (a web job
later the same day writes into the same files but after the collector has run).

**Night marker for the upload log.** The upload log has no timestamps (`[INFO] …` lines), and the web
UI's upload also writes into it. So the 02:00 cron line writes one line before the upload step,
`=== Nachtlauf <YYYY-MM-DD> ===`, into that log (our cron line, not the colleague's script). The
night's block is everything after the last marker of this night's date. The collector runs right
after the upload in the same line, so a later daytime upload cannot be mistaken for it.

**Time zone.** Python uses `config.json` `location.timezone`; the PHP banner reads the same value from
`config.json` (the existing config readers in `web/src/project-config.php`), never PHP's default.

## Non-goals

- Routine warnings (coverage gaps, empty, cut-off or duplicate images, the blur gate's known frames),
  cameras that stop delivering, a history of past messages, e-mail or push notifications.
- No change to the colleague's upload script; it is only read.

## Anti-goals (a failure even if it works)

- A green banner while something is broken: a missing or stale file must never read as "nothing to
  report" (rules 1 and 8b).
- The web server user reading private logs: `siteground-delivery.log` is mode 600 because of the FTP
  password and stays that way.
- Noise: a message that shows every day without anything to do.

## Approaches considered

- **A. Collector at the end of the night plus live values (chosen).** A Python step at the end of the
  02:00 cron line reads what the night left and writes one file; the watchdog writes its own status
  file every 5 minutes; the page only displays and adds the two live checks (missing night, disk).
  Logic in Python with tests, the page stays a display, private logs stay private.
- B. The page parses the logs on every load. Logic twice (PHP), slower pages, and the web user would
  need the private upload log. Not chosen.
- C. Every job writes its own messages into a shared file. Touches the Daily, blur, flagger, the
  colleague's upload script and the nightly wrapper; a forgotten job means a missing message. Not chosen.

## The parts

**Collector** (new Python module, run as the last step of the 02:00 line, appended with `;` like the
flagger; the same line also gets the night marker before the upload step; `./install.sh cron_hint`
prints the new line, Julius pastes it once). Reads the newest
`logs/nightly/<run>/report.txt` and `main.out`, the night's job and flagger logs, the last block of
the upload log, `state/run-in-progress` and the model path. Writes `state/web-jobs/warnings.json`
atomically and readable for the web (the pattern of `src/camera_list.py`: temp file, 0644, replace).
It always writes, also with zero messages, because the file's night date is what rule 1 checks.
All message and hint texts are German and made here, so the page only prints them.

```json
{
  "night": {"run": "20261118-020005", "started": "2026-11-18T02:00:05+01:00",
            "finished": "2026-11-18T02:55:12+01:00"},
  "messages": [
    {"camera": "Strandterrassen", "text": "856 Bildnamen nicht lesbar",
     "hint": "Neue Schreibweise? Handbuch „Unlesbare Dateinamen“"}
  ]
}
```

`camera` is `null` for a message about the whole run. "finished" is the collector's own time, which
is after the upload and the flagger.

**Watchdog** (`src/privacy/blur_watch.py`, already every 5 minutes, read-only on the box). After each
check it also writes `state/web-jobs/blur-watch.json`, same atomic pattern: the check time, the stale
count per camera, and an error text when the box could not be asked. Its log lines stay as they are.

**Banner** (new component in `web/src/components/`, included on every page right below the header,
where the "a job is running" notice is). Reads both files; adds rule 1 (missing night, threshold
06:00 local time: before that the previous night still counts, as the run may still be going), rule 5
(storage level) and rule 8b (status file older than 15 minutes). Styles follow the project's CSS
skill `zeitraffer-web-css` (tokens, focus, contrast). An unreadable or broken file counts as missing.

## Checks

- Python tests per source with fake files (each message, no message, missing file, a broken line).
- Watchdog test: status file written for stale, clean and error cases.
- PHP tests in the style of `tests/web/web_php_test.py`: the banner for "nothing", "messages", missing
  file, stale watchdog file, before and after 06:00.
- The Docker web setup (`docs/docker-web.md`) shows it with fake files before the merge.

## Left to the builder

- Module and function names, the exact German wording of each message, the exact parsing of each log
  (read the formats from the real files).
- How the banner looks within the CSS skill's tokens.
- Where the model path comes from (the same place the detector reads it).

## Open (Julius)

- Nothing at the moment.
