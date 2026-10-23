# Blur Catch-up Before the Nightly Run — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before the 02:00 timelapse run, blur every daytime image of the blur cameras from the
last 48 h that the box blur job has not handled yet, so the Daily is built from blurred images.

**Architecture:** No new module. The existing box blur job (`src/privacy/blur_box.py`) already
lists today plus two days back, skips images with a final status and processes the rest newest
first through the only box writer (`src/privacy/box_writer.py`). Two changes make it a catch-up:
the writer's image age limit goes from 24 h to 48 h, and a `--catch-up` flag removes the 40 s
per-camera time budget. Cron runs it inside the run lock right before `src.main`.

**Tech Stack:** Python 3.13, pytest, ruff (tabs, line length 100), cron + `flock`.

**Spec:** [2026-10-23-blur-daily-gate.md](2026-10-23-blur-daily-gate.md) (Part 1 and the 48 h
decision). The Daily gate (Part 2) is **out of scope** for this plan.

## Execution notes (2026-10-23)

- Tasks 1 and 2 built; final review found that `math.inf` removes the only bound on a round:
  a stalled box (120 s fetch timeout per image) could hold the run lock for hours. Changed to
  `CATCH_UP_BUDGET_SECONDS = 45 * 60` per camera (two summer days of SLSV ~288 x 8 s fit).
  Read "no time budget" / `math.inf` below as this constant.
- Accepted, not changed: an image from two days back that fails in the catch-up drops out of the
  next night's listing without a `refused` line; it was too old to blur anyway and its failure
  is already logged as an error that night.
- Task 3 Step 2 (daytime first run): `refused` > 0 is expected for images from two days back
  that are already older than 48 h at that time.

## Global Constraints

- Julius 2026-10-23: "all i want for now is the blur check for the last 48 hours that runs before the timelapse job"; expected: two days blurred the first night, one day each night after, until the live blur job (every minute) goes live.
- Age limit exactly 48 h (`timedelta(hours=48)`); no further edge-case handling (Julius: "48 h is enough and thats it").
- `box_writer.py` stays the only module that writes to the box; `src.main` and `src.video` never import `src.privacy.blur_box`.
- The catch-up must never stop the timelapse run: it is chained with `;`, not `&&`.
- Tabs for indentation, line length 100, comments explain why (CLAUDE.md conventions).
- Doc text German, identifiers English.
- Claude never commits to `main` and never edits the crontab: those steps are handed to Julius as commands.
- README summary and docs/<topic>.md are kept in sync.

## Review Focus

1. A day-old image that the live job missed (26 h old) must now be blurred, not refused — pinned in Task 1 (`test_yesterdays_missed_image_is_caught_up`).
2. Images older than 48 h must still be refused and logged, never silently dropped — pinned in Task 1 (updated refusal tests).
3. A catch-up with many open images must not stop after the first one — pinned in Task 2 (`test_catch_up_has_no_time_budget`, `test_unlimited_budget_processes_every_open_image`).
4. The normal round (without `--catch-up`) keeps its 40 s budget — pinned in Task 2 (`test_normal_round_keeps_the_time_budget`).
5. A failing catch-up must still let the timelapse run start — not testable in pytest; checked in Task 3 Step 4 (`;` between the two commands).

---

### Task 1: Writer age limit 48 h

**Files:**
- Modify: `src/privacy/box_writer.py:42-43`
- Modify: `tests/privacy_box_writer_test.py:539-550`
- Modify: `tests/privacy_blur_box_test.py:326-336` and `:650-653`
- Modify: `docs/verpixelung-box.md` (lines 195, 241, 280-282, 322)

**Interfaces:**
- Consumes: nothing new.
- Produces: `box_writer.DEFAULT_MAX_IMAGE_AGE == timedelta(hours=48)`.

- [ ] **Step 1: Add the failing test for a missed image from yesterday**

In `tests/privacy_blur_box_test.py`, directly after `test_image_outside_the_window_is_refused_once_and_recorded`, add:

```python
def test_yesterdays_missed_image_is_caught_up(setup: Setup, monkeypatch) -> None:
	# 26 h old: outside the old 24 h window, inside 48 h, so a catch-up round still blurs it.
	name = "20260614T120000.jpg"
	image = setup.upload(name, age_seconds=26 * 3600)
	monkeypatch.setenv("FAKE_PEOPLE", name)

	assert setup.run().blurred == 1
	assert image.read_bytes() == blurred_bytes(name)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/privacy_blur_box_test.py::test_yesterdays_missed_image_is_caught_up -v`
Expected: FAIL (`assert 0 == 1`; the image is refused as older than 24 h).

- [ ] **Step 3: Raise the limit**

In `src/privacy/box_writer.py` replace

```python
# Covers every daytime image of the current day. Night images never get here.
DEFAULT_MAX_IMAGE_AGE = timedelta(hours=24)
```

with

```python
# Two days, so the catch-up before the nightly run still reaches yesterday's earliest daytime
# images after a missed day or a morning restart. Night images never get here.
DEFAULT_MAX_IMAGE_AGE = timedelta(hours=48)
```

- [ ] **Step 4: Move the existing boundary tests to 48 h**

`tests/privacy_blur_box_test.py`, test `test_image_outside_the_window_is_refused_once_and_recorded`: change

```python
	name = "20260614T120000.jpg"
	image = setup.upload(name, age_seconds=26 * 3600)
```

to

```python
	name = "20260613T130000.jpg"
	image = setup.upload(name, age_seconds=49 * 3600)
```

Same file, test `test_image_leaving_the_window_during_detection_is_refused_after_it`: change the comment and clock to

```python
	# The clock passes 48 h between the pre-check and the backup.
	setup.upload(DAY_WITH_PERSON)
	times = iter([NOW, NOW + timedelta(hours=48)])
```

`tests/privacy_box_writer_test.py` (`NOW` is 2026-10-15 13:00): change the two age tests to

```python
def test_old_image_is_refused_without_contact(writer: BoxWriter, box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused, match="older than"):
		writer.backup(CAMERA, "20261013T125900.jpg", "0" * 64)

	assert box.calls == []


def test_image_just_inside_the_age_limit_is_accepted(writer: BoxWriter, box: FakeBox) -> None:
	_add_image(box, "20261013T130100.jpg")

	writer.backup(CAMERA, "20261013T130100.jpg", _current_hash(box, CAMERA, "20261013T130100.jpg"))
```

`test_image_two_days_back_is_refused_and_logged` (50 h old) stays as it is and must still pass.

- [ ] **Step 5: Run the privacy tests**

Run: `.venv/bin/python3 -m pytest tests/privacy_blur_box_test.py tests/privacy_box_writer_test.py -v`
Expected: all PASS.

- [ ] **Step 6: Update docs/verpixelung-box.md**

- Line 195: `(das Bild ist inzwischen älter als 24 Stunden)` -> `(das Bild ist inzwischen älter als 48 Stunden)`.
- Line 241: `höchstens 24 Stunden alt` -> `höchstens 48 Stunden alt`.
- Lines 280-282, replace the bullet with:

~~~markdown
- **Ausfall bis zwei Tage:** Die Liste reicht bis vorgestern zurück. Verpasste Tagbilder der
  letzten 48 Stunden werden nachgeholt, das neueste zuerst. Ältere werden als `refused`
  vermerkt und als Fehler geloggt, nie still übergangen.
~~~

- Line 322: `älter als 24 Stunden` -> `älter als 48 Stunden`.

- [ ] **Step 7: Lint and hand over the commit**

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check .`
Expected: no findings. Then give Julius:

```bash
git add src/privacy/box_writer.py tests/privacy_box_writer_test.py tests/privacy_blur_box_test.py docs/verpixelung-box.md
git commit -m "blur: let the box writer reach images up to 48 h old"
```

---

### Task 2: `--catch-up` flag without time budget

**Files:**
- Modify: `src/privacy/blur_box.py` (imports, `parse_arguments` at :405-423, the `process_box_camera(...)` call in `main` at :497-508)
- Modify: `tests/privacy_blur_box_test.py` (imports, module-level dicts, `rounds` fixture `record_round`, new tests)
- Modify: `docs/verpixelung-box.md` (option table around line 93)

**Interfaces:**
- Consumes: `process_box_camera(..., time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS, ...)` (exists).
- Produces: CLI flag `--catch-up` (bool, `args.catch_up`); `main` passes `time_budget_seconds=math.inf` when set, else `DEFAULT_TIME_BUDGET_SECONDS`.

- [ ] **Step 1: Let the `rounds` fixture record the budget**

In `tests/privacy_blur_box_test.py`, next to `rules_seen: dict[str, object] = {}` (top of the file) add

```python
budgets_seen: dict[str, object] = {}
```

and in the fixture `rounds` change `record_round` to

```python
	def record_round(writer, storage_box, camera, *args, rules=None, **options):
		calls.append((camera, sorted(writer.allowed_cameras)))
		rules_seen[camera] = rules
		budgets_seen[camera] = options.get("time_budget_seconds")

		return blur_box.BoxRoundSummary()
```

Add `import math` to the imports at the top of the test file (after `import json`).

- [ ] **Step 2: Write the failing tests**

Add after `test_round_is_skipped_while_another_blur_round_runs`:

```python
def test_catch_up_has_no_time_budget(rounds) -> None:
	budgets_seen.clear()

	assert blur_box.main(["--all-blur-cameras", "--catch-up"]) == 0
	assert budgets_seen == {CAMERA: math.inf, "Other": math.inf}


def test_normal_round_keeps_the_time_budget(rounds) -> None:
	budgets_seen.clear()

	assert blur_box.main(["--all-blur-cameras"]) == 0
	assert set(budgets_seen.values()) == {blur_box.DEFAULT_TIME_BUDGET_SECONDS}


def test_unlimited_budget_processes_every_open_image(setup: Setup, monkeypatch) -> None:
	names = ["20260615T110000.jpg", "20260615T120000.jpg", "20260615T130000.jpg"]
	monkeypatch.setenv("FAKE_PEOPLE", ",".join(names))

	for name in names:
		setup.upload(name)

	summary = setup.run(time_budget_seconds=math.inf)

	assert (summary.blurred, summary.postponed) == (3, 0)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/privacy_blur_box_test.py -k "budget" -v`
Expected: `test_catch_up_has_no_time_budget` FAILS with `SystemExit: 2` (unknown argument);
`test_normal_round_keeps_the_time_budget` FAILS (`{None} != {40}`);
`test_unlimited_budget_processes_every_open_image` already PASSES (the loop handles `inf`) and
stays as a guard; `test_time_budget_postpones_the_rest_newest_first` still PASSES.

- [ ] **Step 4: Implement the flag**

In `src/privacy/blur_box.py`, add `import math` to the standard-library imports. In
`parse_arguments`, before `return parser.parse_args(argv)`, add

```python
	parser.add_argument(
		"--catch-up",
		action="store_true",
		help="No time budget per camera: handle every open image of the listed days "
		"(run before the nightly timelapse run).",
	)
```

In `main`, in the `process_box_camera(...)` call, change

```python
					args.settle_seconds,
					rules=rules,
				)
```

to

```python
					args.settle_seconds,
					# The catch-up runs before the nightly videos, when no fresh upload waits.
					time_budget_seconds=math.inf if args.catch_up else DEFAULT_TIME_BUDGET_SECONDS,
					rules=rules,
				)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python3 -m pytest tests/privacy_blur_box_test.py -v`
Expected: all PASS.

- [ ] **Step 6: Document the option**

In `docs/verpixelung-box.md`, option table, add after the `--all-blur-cameras` row:

~~~markdown
| `--catch-up` | ohne 40-Sekunden-Grenze: alle offenen Tagbilder der Liste (bis 48 Stunden alt) in einem Lauf; läuft nachts vor dem Zeitraffer-Lauf |
~~~

- [ ] **Step 7: Lint and hand over the commit**

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check .`
Expected: no findings. Then give Julius:

```bash
git add src/privacy/blur_box.py tests/privacy_blur_box_test.py docs/verpixelung-box.md
git commit -m "blur: add --catch-up, a round without the time budget"
```

---

### Task 3: First run, nightly cron, docs

**Files:**
- Modify: crontab (Julius runs the commands; Claude never edits it)
- Modify: `docs/betrieb.md` (sections "Nächtlicher Produktionslauf" and "Wiederanlauf nach Neustart"), `docs/verpixelung-box.md` (Stand, Cron block), `docs/handbuch.md:35`, `README.md` (Verpixelung summary, "Noch offen")
- Modify: `docs/plans/2026-10-23-blur-daily-gate.md` (Status line)

**Interfaces:**
- Consumes: `python3 -m src.privacy.blur_box --all-blur-cameras --catch-up` (Task 2).
- Produces: nightly order catch-up -> `src.main` -> flagger; `@reboot` recovery: catch-up -> `src.main`.

- [ ] **Step 1: Full test suite and lint**

Run: `.venv/bin/python3 -m pytest -q && .venv/bin/ruff format --check . && .venv/bin/ruff check .`
Expected: all tests pass, no findings.

- [ ] **Step 2: First real run by hand (Julius, terminal, before the cron change)**

This is the first write into production camera folders (`Scheunenviertel`, `SLSV`; SLSV added
to `privacy.blur_cameras` by Julius on 2026-10-23) on the box. Julius runs it while watching, with
VS Code disconnected (detector + VS Code caused the 10-15 reset):

```bash
cd ~/timelapse && .venv/bin/python3 -m src.privacy.blur_box --cameras Scheunenviertel SLSV --catch-up; echo "exit $?"; tail -n 5 logs/privacy/$(date +%F).log
```

Expected: one summary line per camera, e.g. `[SLSV] blurred=N clean=M night=K settling=0 refused=0 failed=0 postponed=0`;
about 2 x 48 (Scheunenviertel) + 2 x 71 (SLSV) daytime images at ~8 s each (estimate ~30 min).
Julius checks one blurred image per camera before Step 3.

- [ ] **Step 3: Install the cron lines (Julius)**

Dry-run on 2026-10-23 against the live crontab: exactly the `0 2` and `@reboot` lines change.

```bash
B=~/crontab-backup-$(date +%F_%H%M).txt; crontab -l > "$B" && crontab -l | sed 's#\(-c '"'"'cd /home/zruser/timelapse \)&& \(/home/zruser/timelapse/.venv/bin/python3 -m src\.main'"'"'\)#\1\&\& /home/zruser/timelapse/.venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras --catch-up; \2#' > ~/crontab-new.txt && diff "$B" ~/crontab-new.txt
```

Expected diff: two lines; inside each `flock -c '...'` the catch-up now comes first, followed by
`; ... -m src.main`. The flagger part of the `0 2` line is unchanged. Then:

```bash
crontab ~/crontab-new.txt && crontab -l | grep -v '^#' | grep .
```

- [ ] **Step 4: Check the order and the separator**

Run: `crontab -l | grep -c "blur_box --all-blur-cameras --catch-up; "`
Expected: `2`. The `;` means a failed catch-up still starts the timelapse run.

- [ ] **Step 5: Docs**

`docs/betrieb.md`, section "Nächtlicher Produktionslauf": replace the intro sentence and cron block with

~~~markdown
Die installierte Crontab verpixelt zuerst die offenen Bilder der letzten 48 Stunden
([Verpixelung auf der Storage Box](verpixelung-box.md)), startet dann den vollständigen Workflow
und danach den [Highlights-Flagger](#highlights-flagger), täglich um 02:00 Uhr:

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras --catch-up; <projektpfad>/.venv/bin/python3 -m src.main'; cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.flagger.run
```

Schlägt das Nachholen fehl, startet der Zeitraffer-Lauf trotzdem (`;`, nicht `&&`).
~~~

Section "Wiederanlauf nach Neustart": in the `@reboot` line, insert
`<projektpfad>/.venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras --catch-up; ` directly
before `<projektpfad>/.venv/bin/python3 -m src.main` inside `-c '...'`.

`docs/verpixelung-box.md`:
- "Stand" paragraph: replace `Der Cron-Eintrag ist noch nicht eingerichtet.` with
  `Seit dem <Datum> verpixelt Cron jede Nacht vor dem Zeitraffer-Lauf die offenen Bilder der letzten 48 Stunden (--catch-up); die Runde jede Minute ist noch nicht eingerichtet.`
- After the planned `* * * * *` cron block add:
  `Bis dahin verpixelt nur das nächtliche Nachholen: in der ersten Nacht zwei Tage, danach jede Nacht den Vortag. Bis zum Lauf um 02:00 holt die Website unverpixelte Bilder ab.`

`docs/handbuch.md:35`: replace the row with
`| Verpixelung auf der Storage Box | nachts vor dem Zeitraffer-Lauf (Nachholen der letzten 48 h); die Runde jede Minute noch nicht in Cron | Cron |`

`README.md`:
- Verpixelung bullet "Direkt auf dem Online-Speicher": replace `Er ist gebaut und getestet, läuft aber noch nicht im Dauerbetrieb.` with
  `Er läuft jede Nacht vor den Videos und verpixelt die Bilder der letzten zwei Tage; die laufende Verpixelung neuer Bilder ist noch nicht im Dauerbetrieb.`
- "Noch offen": `- Verpixelung jede Nacht automatisch starten` -> `- Verpixelung neuer Bilder laufend (jede Minute) starten`.

`docs/plans/2026-10-23-blur-daily-gate.md`, after the Status line add:
`Part 1 (catch-up) built 2026-10-<dd>, see [2026-10-23-blur-catch-up.md](2026-10-23-blur-catch-up.md); Part 2 (gate) still not started.`

- [ ] **Step 6: Hand over the commit**

```bash
git add config/config.json docs/betrieb.md docs/verpixelung-box.md docs/handbuch.md README.md docs/plans/2026-10-23-blur-daily-gate.md docs/plans/2026-10-23-blur-catch-up.md
git commit -m "blur: SLSV joins the blur cameras; the catch-up runs before the nightly timelapse run"
```

- [ ] **Step 7: Next morning**

Run: `grep -E "\] blurred=|Refused|Round aborted" logs/privacy/$(date +%F).log`
Expected: one summary line per blur camera with `failed=0`; `logs/daily/$(date +%F).log` starts
after the last summary line.
