# Filename Date Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One general reader for date and time in image names (built from notation blocks), so new
camera formats like Strandterrassen's just work, plus a nightly warning when a camera's names cannot
be read.

**Architecture:** `extract_date` and `extract_time` in `src/images.py` keep their signatures and become
thin wrappers around one cached reader that tries every block combination and applies the design's
validity, competition and fallback rules. The Daily's listing loop counts unreadable names and logs
one WARNING per camera; the nightly wrapper copies that line into `report.txt`.

**Tech Stack:** Python 3.13 (runnable on 3.11), `re`, `functools.lru_cache`, bash (nightly wrapper),
pytest.

**Spec:** `docs/plans/done/2026-11-18-filename-date-reader-design.md`

## Global Constraints

- No new dependency. Signatures stay `extract_date(filename: str) -> date | None` and
  `extract_time(filename: str) -> tuple[int, int, int] | None`.
- Year range 2000 to 2099; `YY` means `20YY`.
- A combination matches only as a whole: no digit directly before or after it.
- Full readings (date AND time valid) compete first; two different full readings: both unreadable.
  Fallback without a full reading: date and time each from the valid parts, only if they agree.
- The warning never fails a camera or the night.
- Project rules: Claude runs no pytest (Julius runs it in Docker, `docs/docker-web.md`); one task at a
  time, tests first, then stop for Julius's check and commit; `ruff format` + `ruff check` on the
  edited files only. Comments: 1-2 lines of why. German for docs.

## Review Focus

1. Upper-case extension (`camera_260101_130000.JPG`): read like `.jpg`. Test in Task 1.
2. Two different date-time shapes in one name (`cam_20261117073004_20261118120000.jpg`): both
   unreadable, never the first one. Test in Task 1.
3. Leap days: `20240229T120000` valid, `20250229T120000` no date. Test in Task 1.
4. Year boundaries: `20000101T000000` read, `21000101T000000` no date, `00-01-01_00-00-00` read as
   2000-01-01. Test in Task 1.
5. A name the Daily's day pre-filter keeps although its date is unreadable must still be counted as
   unreadable by the warning. Test in Task 3.

---

### Task 1: The general reader

**Files:**
- Modify: `src/images.py:129-253` (`extract_date`, `extract_time`; `image_moment` unchanged)
- Test: `tests/images_test.py`
- Test (examples only): `tests/privacy/privacy_blur_box_test.py:463,577`, `tests/storage_filter_test.py:339`

**Interfaces:**
- Produces: `extract_date(filename: str) -> date | None` and
  `extract_time(filename: str) -> tuple[int, int, int] | None`, same as today; both call one private
  `_read_name(filename: str) -> tuple[date | None, tuple[int, int, int] | None]` wrapped in
  `functools.lru_cache(maxsize=8192)` (callers usually ask for date and time of the same name in a row).

- [ ] **Step 1: Write the failing tests** in `tests/images_test.py`. Keep the three existing
  `test_extract_*` tests unchanged (they pin today's behaviour). Add:

```python
def test_strandterrassen_names_are_read():
	assert extract_date("Strandterrassen_20261117073004.jpg") == date(2026, 11, 17)
	assert extract_time("Strandterrassen_20261117073004.jpg") == (7, 30, 4)


# Widening is intended: any name shaped like date + separator + time.
@pytest.mark.parametrize(
	("name", "expected_date", "expected_time"),
	[
		("IMG20260615-120000.jpg", date(2026, 6, 15), (12, 0, 0)),
		("cam_20260615_120000.jpg", date(2026, 6, 15), (12, 0, 0)),
		("cam_2026-06-15_12-00-00.jpg", date(2026, 6, 15), (12, 0, 0)),
		("x_260615-120000.jpg", date(2026, 6, 15), (12, 0, 0)),
		("cam_202606151200.jpg", date(2026, 6, 15), (12, 0, 0)),
		("a_20260101T1000.jpg", date(2026, 1, 1), (10, 0, 0)),
		("cam_26-06-15_12-00-00.jpg", date(2026, 6, 15), (12, 0, 0)),
		("camera_260101_130000.JPG", date(2026, 1, 1), (13, 0, 0)),
	],
)
def test_widened_shapes_are_read(name, expected_date, expected_time):
	assert extract_date(name) == expected_date
	assert extract_time(name) == expected_time


# Only full readings compete: the invalid-date reading of the same digits must not spoil the time.
@pytest.mark.parametrize(
	("name", "expected_time"),
	[
		("sam-Reolink_00_20261117073004.jpg", (7, 30, 4)),
		("T26061512000011.jpg", (12, 0, 0)),
	],
)
def test_a_reading_with_an_invalid_date_does_not_compete(name, expected_time):
	assert extract_time(name) == expected_time


def test_two_different_full_readings_are_unreadable():
	# 2001-2012 digit runs read both as YYYYMMDDHHMMSS and YYMMDDHHMMSScc.
	assert extract_date("P20120512000001.jpg") is None
	assert extract_time("P20120512000001.jpg") is None
	assert extract_date("cam_20261117073004_20261118120000.jpg") is None
	assert extract_time("cam_20261117073004_20261118120000.jpg") is None


def test_fallback_keeps_the_valid_part():
	assert extract_date("20250107T250110.jpg") == date(2025, 1, 7)
	assert extract_time("20250107T250110.jpg") is None
	assert extract_date("20251340T101010.jpg") is None
	assert extract_time("20251340T101010.jpg") == (10, 10, 10)


def test_a_part_without_its_partner_is_not_read():
	assert extract_date("cam_260615_x.jpg") is None
	assert extract_time("fooT101010.jpg") is None


def test_leap_days_and_year_bounds():
	assert extract_date("20240229T120000.jpg") == date(2024, 2, 29)
	assert extract_date("20250229T120000.jpg") is None
	assert extract_date("20000101T000000.jpg") == date(2000, 1, 1)
	assert extract_date("21000101T000000.jpg") is None
	assert extract_date("00-01-01_00-00-00.jpg") == date(2000, 1, 1)
```

  Change the three test examples whose "unreadable" name becomes readable, keeping each assertion:
  - `privacy_blur_box_test.py:463` (`test_image_without_readable_time_is_refused`): `cam_260615_x.jpg`
    becomes `cam_20260615T250000.jpg` (date readable, hour 25), so the test still means "dated name
    without a readable time".
  - `privacy_blur_box_test.py:577` (`test_unreadable_name_is_refused_and_logged_not_dropped`):
    `IMG20260615-120000.jpg` becomes `IMG20260615.jpg` (matches the day text, no date-time shape).
  - `storage_filter_test.py:339`: `IMG20250110-120000.jpg` becomes `IMG20250110.jpg`, same reason.

- [ ] **Step 2: Julius runs the new tests and sees them fail**

Run (Mac, `docker/zeitraffer-web`): `docker compose exec -u zeitraffer web bash -c "cd ~/timelapse && .venv/bin/python3 -m pytest tests/images_test.py -q"`
Expected: the new tests FAIL (Strandterrassen date `None`, widened shapes `None`, ...); the three
existing `test_extract_*` tests PASS.

- [ ] **Step 3: Implement `_read_name`, `extract_date`, `extract_time` in `src/images.py`**

Blocks as in the design (date: `YYYYMMDD`, `YYMMDD`, `YYYY-MM-DD`, `YY-MM-DD`, `YYYY_MMDD`; separator:
none, `T`, `_`, `-`; time: `HHMMSS`, `HHMM`, `HH-MM-SS`, `HHMMSScc`), every combination compiled once
at import as `(?<!\d)(?=(<date><sep><time>)(?!\d))` with named groups, so overlapping matches at every
position are found. Rules 2 to 4 of the design decide the result:

```
full = {(d, t) for each match if d valid and t valid}
if len(full) == 1: return the one
if len(full) > 1: return (None, None)
dates = {d for each match if d valid}; times = {t for each match if t valid}
return (the date if len(dates) == 1 else None, the time if len(times) == 1 else None)
```

The old pattern lists go. Update the comment above `image_moment` ("unknown formats are never
guessed" stays true: ambiguous names are unreadable). Keep it fast: if the 80 compiled patterns per
name turn out slow in Task 2, first skip names without a digit run of 6 or more, then consider
splitting into digit runs; the plan does not fix the method.

- [ ] **Step 4: Julius runs the image, blur and storage tests**

Run: `docker compose exec -u zeitraffer web bash -c "cd ~/timelapse && .venv/bin/python3 -m pytest tests/images_test.py tests/privacy/privacy_blur_box_test.py tests/storage_filter_test.py -q"`
Expected: all PASS. Then the full suite: `... -m pytest -q`, all PASS (one skip, the flagger
acceptance test).

- [ ] **Step 5: ruff, then Julius saves**

Run: `.venv/bin/ruff format src/images.py tests/images_test.py tests/privacy/privacy_blur_box_test.py tests/storage_filter_test.py` and `.venv/bin/ruff check` on the same files. Expected: clean.
Julius stages these four files and commits, e.g. `feat: read image dates and times from notation blocks`.

### Task 2: Proof on the real box (read-only, no code change in the repo)

**Files:**
- Create: `local/compare_name_reader.py` (git-ignored `local/`, never committed)

**Interfaces:**
- Consumes: `extract_date`, `extract_time` from the VPS checkout (`main`, old reader) and from
  `git show origin/feature/filename-date-reader:src/images.py` (new reader, loaded by path into a
  module named `new_images`; the VPS checkout is not switched).

- [ ] **Step 1: Write the script.** It needs `TIMELAPSE_STORAGE_BOX=storagebox
  TIMELAPSE_FRAME_SOURCE=ssh`. For every camera from `get_frame_source().list_cameras()` and every
  `.jpg` name (any case) from `list_names(camera)`: compare old and new `(extract_date, extract_time)`.
  Print per camera `names`, `differences` and up to 3 example differences (`name: old -> new`), then
  the time both readers took over SKM-Mardorf's names (`time.perf_counter`, each reader's cache
  cleared first). Read-only: no writes anywhere.

- [ ] **Step 2: Julius pushes the branch, then runs it on the VPS from the Mac**

Run (Mac, repo): `ssh zeitraffer 'cd ~/timelapse && git fetch && git show origin/feature/filename-date-reader:src/images.py > /tmp/new_images.py && TIMELAPSE_STORAGE_BOX=storagebox TIMELAPSE_FRAME_SOURCE=ssh .venv/bin/python3 -' < local/compare_name_reader.py`
Expected: `differences 0` for every camera except Strandterrassen (854+ names: old `None` -> new date
and time); new SKM-Mardorf time at most twice the old one. Anything else: stop and bring it back
into the design before Task 3.

### Task 3: Count unreadable names in the Daily

**Files:**
- Modify: `src/images.py` (`find_images_for_dates`, `_find_daily_images_worker`)
- Test: `tests/images_test.py`

**Interfaces:**
- Produces: `find_images_for_dates(camera, target_dates, progress_callback=None, report_unreadable: bool = False)`;
  with `report_unreadable=True` it logs, after the loop and only when the count is above 0:
  `[<camera>] <n> of <total> image names cannot be read, e.g. <first unreadable name>` at WARNING
  (`total` = all `.jpg` names, any case; unreadable = `extract_date` or `extract_time` is `None`).
  `_find_daily_images_worker` passes `report_unreadable=True`; no other caller changes.

- [ ] **Step 1: Write the failing tests** (use the existing `FakeFrameSource` and `caplog`):
  - `test_daily_listing_warns_about_unreadable_names`: names `["Cam_20261117073004.jpg",
    "IMG20261117.jpg", "photo.jpg", "notes.txt"]`, target 2026-11-17, `report_unreadable=True`:
    exactly one WARNING containing `[Test-Camera] 2 of 3 image names cannot be read, e.g. IMG20261117.jpg`;
    the result for 2026-11-17 still holds both 20261117 names (Review Focus 5: the pre-filter keeps
    `IMG20261117.jpg`, and it is still counted).
  - `test_listing_without_the_flag_logs_no_unreadable_warning`: same names, default flag: no record
    containing `cannot be read`.
  - `test_a_fully_readable_listing_logs_no_warning`: only readable names, flag on: no such record.

- [ ] **Step 2: Julius runs them and sees the first one fail.**
  Run: `... -m pytest tests/images_test.py -q -k "unreadable or fully_readable"`. Expected: first FAILS
  (unexpected keyword `report_unreadable`), the others FAIL the same way.

- [ ] **Step 3: Implement** the parameter and the count inside the existing loop (no second listing),
  and pass `report_unreadable=True` in `_find_daily_images_worker`.

- [ ] **Step 4: Julius runs `tests/images_test.py` and the full suite.** Expected: all PASS.

- [ ] **Step 5: ruff on `src/images.py` and `tests/images_test.py`; Julius commits**, e.g.
  `feat: warn when a camera's image names cannot be read`.

### Task 4: The line in the nightly report, and the docs

**Files:**
- Modify: `scripts/timelapse-nightly-staged` (camera loop, about line 207-226)
- Test: `tests/scripts/nightly_staged_test.py`
- Modify (docs, German): `docs/architektur.md:78-85,428`, `docs/handbuch.md:424-428,1088`

**Interfaces:**
- Consumes: the WARNING line format from Task 3.

- [ ] **Step 1: Write the failing test** `test_unreadable_names_are_reported_without_failing_the_camera`:
  `project.main_lines(summary("Daily"), "2026-11-18 02:00:10,000 | WARNING | [Bravo Cam] 7 of 900 image names cannot be read, e.g. x.jpg", summary("Weekly"), summary("Monthly"), summary("Yearly"))`;
  assert `result.returncode == 0`, `"   WARNING: 7 image names cannot be read" in report`, the line
  stands after `== Bravo Cam` and before the next `==`, no WARNING under Alpha, `"Cameras: 2, failed: 0" in report`.

- [ ] **Step 2: Julius runs it and sees it fail.**
  Run: `... -m pytest tests/scripts/nightly_staged_test.py -q -k unreadable`. Expected: FAIL, no WARNING line.

- [ ] **Step 3: Implement** in the camera loop, after the ok/FAILED line: `grep -F -- "| WARNING | [${camera}] "`
  on `$main_out`, take the number from the first line with `image names cannot be read`, and
  `note "   WARNING: <n> image names cannot be read"`. It sets no `CAMERA_PROBLEMS`.

- [ ] **Step 4: Docs.** `architektur.md`: the reader reads from notation blocks (table in short), an
  ambiguous name is unreadable, not guessed. `handbuch.md` "Eine Kamera hat keine Bilder" (line 424 ff.)
  and the message table (line 1088): the new WARNING and report line, and what to do: look at the
  example name; a really new notation needs a new block in `src/images.py`.

- [ ] **Step 5: Julius runs the full suite in Docker; ruff on any edited Python file.** Expected: all
  PASS. Julius commits, e.g. `feat: show unreadable image names in the nightly report`, merges when he
  calls the feature done, then pulls on the VPS when no job runs (`src/` changes; no `web_bridge`).
  The first night after: Strandterrassen gets a flagger result and no WARNING line.
