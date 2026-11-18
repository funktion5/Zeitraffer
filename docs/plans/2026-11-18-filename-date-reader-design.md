# Design: one general reader for date and time in image names

Status: approved by Julius 2026-11-18. Branch `feature/filename-date-reader`.

## Why

Strandterrassen names its images `Strandterrassen_20261117073004.jpg` (`_YYYYMMDDHHMMSS`). No pattern in
`extract_date` (`src/images.py`) reads that, so since about 2026-11-06 the camera has had Dailies and
Weeklies (they match the day as text) but never a Monthly or Yearly ("No valid ... images"), and the
flagger reads none of its images (ERROR in `logs/flagger/2026-11-18.log`). Nothing pointed at the cause.

Julius's wish: a new camera with an unseen name format **just works**, and **he is warned** when its
names cannot be read.

## Goals

- One reader for date and time, built from notation blocks, not from camera names.
- Every name that is readable today reads the same afterwards (proved on the real box, see Checks).
- Strandterrassen's names are read.
- A camera with unreadable names shows up as a WARNING in the nightly report and the log.

## Non-goals

- No date from the file's timestamp on the box: the blur job rewrites images in place, so it is not
  the capture time.
- No general date-parser library (`dateutil` fuzzy): new dependency, and it guesses in long digit runs.
- No per-camera format setting, no learned format in `state/`.
- The day pre-filter (`date_patterns`, text match of `%Y%m%d`, `%y%m%d`, `%y-%m-%d` in
  `find_images_for_dates` and `storage_filter.list_images_for_dates`) stays as it is.

## Anti-goals (a failure even if it works)

- A name read as the wrong date or time, silently. For blur cameras that is a privacy risk: the box
  writer's age limits decide by that time, and the pick-up publishes marked images only.
- Any change in what today's 17 box cameras or the NAS formats produce.

## Approaches considered

- **A. General reader from notation blocks (chosen by Julius).** Date, separator and time blocks are
  combined; whatever comes before and after (prefix, fraction, counter) does not matter. Needs a new
  block only for a really new notation (e.g. `2026.11.17`), and then the warning names the camera.
- B. Learn the format once per camera and store it in `state/`. More robust against ambiguous names,
  but a state file to back up and a relearn step when a camera changes format (BSV, Seerosenweg and
  Uferstrasse each have two formats). Not chosen.
- C. Add the Strandterrassen pattern by hand, plus the warning. Smallest, but the next new camera
  needs code again. Not chosen.

## The reader

**Blocks.** Every date block may be combined with every separator and every time block (a free
cross-product, 5 x 4 x 4 = 80 combinations), always date first:

| Date | Separator | Time |
|---|---|---|
| `YYYYMMDD` | none | `HHMMSS` |
| `YYMMDD` | `T` | `HHMM` |
| `YYYY-MM-DD` | `_` | `HH-MM-SS` |
| `YY-MM-DD` | `-` | `HHMMSScc` (two digits of hundredths, P/T legacy) |
| `YYYY_MMDD` (Cafe-am-Meer legacy, `promenade_`) | | |

**Rules:**

1. **Shape first.** A combination matches by shape only, and only as a whole: digits may not continue
   directly before or after it. A trailing fraction or counter after a non-digit (`-93`, `_00001`,
   `_01`) is ignored. Validity is judged afterwards.
2. **Valid parts.** A date part is valid when it is a real calendar date with a year from 2000 to 2099
   (`YY` means `20YY`). A fixed range, not "next year": the reader stays deterministic, and the
   signature stays `extract_date(name)`. A time part is valid when it is a real time of day.
3. **Full readings compete first.** A full reading is a match whose date AND time are both valid.
   - Exactly one distinct full reading: that is the name's date and time.
   - Two or more different full readings: date and time are both unreadable (no guess). Example: a
     14-digit run from the years 2001 to 2012 can be both `YYYYMMDDHHMMSS` and `YYMMDDHHMMSScc`.
   Matches with an invalid date never take part here, so `X_00_20261117073004.jpg` reads 07:30:04:
   the `YYMMDD`+`HHMMSScc` match of the same digits has the invalid date `2020-26-11` and is ignored.
4. **Fallback when there is no full reading.** The date is the valid date part of the matches, if they
   all agree; the time likewise. So `20250107T250110.jpg` keeps date 2025-01-07 and has no time, as
   today, and `20251340T101010.jpg` keeps the time 10:10:10, as today. Different valid parts in the
   fallback: that part is unreadable.
5. `extract_date(name)` and `extract_time(name)` keep their names, signatures and return values, so
   none of the about 20 callers (jobs, blur, flagger, storage filter, `nas/`, `extras/`) changes.
6. **Speed.** The Monthly and Yearly already read every name of a camera (SKM-Mardorf: about 228,000).
   The new reader must not make that noticeably slower (measured old vs new on that list, see Checks).
   How, for example by first splitting a name into digit runs and separators, is left to the builder.

Coverage check against today: every one of the 22 name shapes on the box and every shape in the tests
is one combination of the table (Reolink `_00_YYYYMMDDHHMMSS`, BSV `bsv_steinhude_YYYYMMDDHHMM` and
`_YYMMDDHHMM`, `promenade_YYYY_MMDD_HHMMSS_01`, P/T `[A-Za-z]YYMMDDHHMMSScc`, `YYYYMMDDTHHMMSS`,
`_YYMMDD_HHMMSS`, `YY-MM-DD_HH-MM-SS-cc[_NNNNN]`). Strandterrassen is `YYYYMMDD` + none + `HHMMSS`.

**Intended behaviour changes.** Widening is the point: any name whose shape is a combination of the
table is read. Examples:

- `Strandterrassen_20261117073004.jpg` is read.
- `IMG20260615-120000.jpg`, `cam_20260615_120000.jpg` (phone style), `cam_2026-06-15_12-00-00.jpg`,
  `x_260615-120000.jpg` and 12-digit `YYYYMMDDHHMM` runs are read.
- `a_20260101T1000.jpg` gets the time 10:00 (today: date only). No test asserts its time.
- A dashed time no longer needs the trailing `-cc` (`_12-00-00.jpg` is read).
- Tests that use `IMG20260615-120000.jpg` as their "unreadable" example (`privacy_blur_box_test`,
  `storage_filter_test`) get a name that stays unreadable under the new rules (for example
  `IMG2026.06.15.jpg`); the assertion stays the same.

Narrowing, accepted: a part that today is found inside a longer digit run or without its partner no
longer counts, because rule 1 wants a whole date-and-time shape. Examples: a date-only name such as
`cam_260615_x.jpg` and a time-only name such as `fooT101010.jpg`. Callers already treat such names as
unreadable where it matters (the blur refuses a name without a time, the day pre-filter keeps an
unreadable name for the caller to refuse), and the box comparison proves that no real name is hit.

## The warning

The Daily lists every camera's names each night anyway (`find_images_for_dates` loops over the whole
listing). In that same loop it counts names (`.jpg`, any case) whose date **or** time cannot be read:
both are needed for a Monthly, a Yearly and the flagger. The extra `extract_time` per name is part of
the speed measurement. On 2026-11-18 every name on the box except Strandterrassen's was fully
readable, so the warning starts silent and no old file keeps it going. If the count is above zero: one log line per camera at
WARNING, `[<camera>] <n> of <total> image names cannot be read, e.g. <name>`, and the nightly report
(`scripts/timelapse-nightly-staged`, `report.txt`) shows `   WARNING: <n> image names cannot be read`
under that camera. It does **not** fail the camera or the night: the videos may still be fine.

Web UI note on the camera page: see Open.

## Checks

- Tests first: one test per row of the coverage list above (real example names), the full-reading
  rule with the Reolink and P/T names, the ambiguity rule, the fallback (`T250110`, `20251340T`), the
  year range, each widening example, and Strandterrassen.
- Speed: old and new reader over SKM-Mardorf's name list (about 228,000), timed; Julius runs it.
- Read-only comparison on the VPS before the switch: old and new `extract_date`/`extract_time` over
  every name of every camera on the box; the result must be zero differences except Strandterrassen.
  Julius runs it (it lists about 1.4 million names; the shape listing on 2026-11-18 took a few minutes).
- Docker pytest and ruff, then VPS pytest after the pull, as usual.

## Left to the builder

- How the blocks are written in code (one small table, compiled once), as long as the rules hold.
- Where in the Daily the count is taken and how the wrapper picks the line up for `report.txt`.

## Web UI: a later, separate feature

Julius, 2026-11-18: warnings go into a file, and the web UI shows a banner with the current warnings,
refreshed each night. That is its own feature (own branch, own design), after this one: the night run
rewrites a small warnings file, and a banner at the top of every page (`header.php`, where the "a job
is running" notice is) shows last night's warnings. Which warnings it collects (unreadable names,
failed cameras, cameras without images, blur watchdog) and the file's fields are decided there. This
feature only writes the log line and the `report.txt` line.
