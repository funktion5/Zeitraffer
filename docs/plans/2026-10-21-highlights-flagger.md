# Highlights Flagger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone nightly program that finds animals and flying objects in the Daily images and writes a per-camera, per-day report folder (clean image copies plus `manifest.json`) for the future Highlights page.

**Architecture:** A new package `src/flagger/` with its own small YOLOX wrapper (copied plumbing, not imported from `src/privacy`), pure functions for grouping, report writing and cleanup, and a thin CLI. The detector is injected as a callable, so every test runs with a fake model.

**Tech Stack:** Python 3.13, numpy, opencv-python-headless, onnxruntime (all already in `requirements.txt`), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-21-highlights-flagger-design.md`. The web side is a separate plan: `docs/plans/2026-10-21-highlights-page.md`.

## Global Constraints

- No new dependency: `onnxruntime==1.30.0`, `numpy==2.5.3`, `opencv-python-headless==5.0.0.93` are already pinned.
- Code is tab-indented, 100 columns, double quotes (`ruff check .`, `ruff format --check .`); comments in English explain why. User-facing docs are German.
- The flagger only reads. It never writes to `/mnt/cameras` or the Storage Box. It writes only `videos/<camera>/highlights/<YYYY-MM-DD>/` and `logs/flagger/`, and takes the shared run lock `state/zeitraffer-run.lock`.
- Independent of the blur: no import from `src/privacy`, and no change to `src/privacy/`, `src/video.py`, `src/jobs/`, `src/main.py`. The only change to `src/logger.py` is adding `"flagger"` to `LogType` (Task 7).
- Starting thresholds: 0.30 for group `animal`, 0.30 for group `flying`. Tiles: whole frame plus the 4 overlapping tiles of 60 % size used by `src/privacy/detect.py`.
- Groups: `flying` = bird (14), airplane (4), kite (33); `animal` = cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe (15 to 23). Real aeroplanes are flagged.
- No cap on flagged images. Retention is `flagger.retention_days` (30, minimum 7), applied to every camera's `highlights` folders.
- `manifest.json`: schema 1, fields exactly as in the spec (including `taken_at`).
- CI has no model file and no FFmpeg: no CI test may need `models/` or `sandbox/`. No test touches `/mnt/cameras` or the network.
- Test environment: everything runs on the Pi itself with the project venv (`.venv`, Python 3.13), no Docker. Wherever this plan says `python -m pytest ...`, run `nice -n 19 .venv/bin/python -m pytest ...`, one test process at a time (Task 0 checks `php -v` and free memory first).
- Copied images always get a lowercase `.jpg` suffix (originals may end in `.JPG`, which `src/images.py` accepts); the page and its delete wrapper only accept lowercase.
- Commits are Julius's: never run `git commit` or `git push`. The work happens on the production Pi, so: never run production jobs (`src.main`, the blur job, the nightly wrapper), never edit the crontab or sudoers or install anything as root, read the cameras and the Storage Box only when Julius asks, run heavy commands with `nice -n 19`, and only one heavy process at a time (2 GB RAM; silent reboots from memory exhaustion are on record). Julius does not work during the nightly run. A "Commit" step means: stage the listed paths (`git add <paths>`, never `git add .`), write the message to `<scratchpad>/commit-<n>.txt`, and hand Julius `git commit -F <that file>`. One topic per commit. The message ends with the `Co-Authored-By` line of the model that did the work.

## Review Focus

Inputs the spec implies but no happy-path test covers; each has a test in the named task.

1. A corrupt or unreadable JPEG must be skipped, counted and logged, never abort the camera (Task 6).
2. A re-run of a day replaces that day's folder; a crash mid-write must leave the previous report intact and no temp folder behind (Task 4).
3. Cleanup boundary and guard: exactly 30 days old stays, 31 goes; names that are not plain dates, symlinks and other folders under `videos/<camera>/` are untouched (Task 5).
4. A tiny image (smaller than a tile) must not crash the letterbox (Task 3).
5. A day with nothing flagged still writes a manifest with `items: []` and the real `checked` count, and a camera with no images at all writes nothing (Task 6).

---

### Task 0: Check the Pi environment

**Files:** none changed.

- [ ] **Step 1:** The specs and plans are present in `docs/` (tracked; Julius pushes them once final); `.venv/bin/python --version` shows 3.13; `php -v` works (the web tests need it); `free -m` shows at least 1 GB available before heavy runs.
- [ ] **Step 2:** The Strandallee bird frame is in `sandbox/flagger-samples/` (gitignored; copy it there if it is elsewhere) and `models/object_detection_yolox_2022nov.onnx` exists.
- [ ] **Step 3:** `nice -n 19 .venv/bin/python -m pytest tests/config_test.py tests/web_php_test.py -q`. Expected: PASS. If `php` is missing, the web tests of the page plan cannot run: stop and tell Julius.

### Task 1: Settings and config section

**Files:**
- Create: `src/flagger/__init__.py` (empty), `src/flagger/settings.py`
- Modify: `config/config.json` (add `"flagger": {"cameras": [], "retention_days": 30}` next to `"privacy"`)
- Modify: `tests/config_test.py` (`assert_valid_config_structure` compares the root keys exactly, so add `"flagger"` to `EXPECTED_ROOT_KEYS`, plus a check like the one for `privacy`: `cameras` a list of unique strings, `retention_days` an int of at least 7)
- Test: `tests/flagger_settings_test.py`

**Interfaces:**
- Produces: `MIN_RETENTION_DAYS = 7`, `DEFAULT_RETENTION_DAYS = 30`, `@dataclass(frozen=True) class FlaggerSettings: cameras: tuple[str, ...]; retention_days: int`, `load_flagger_settings(config: dict) -> FlaggerSettings`.

- [ ] **Step 1: Write the failing tests** (`tests/flagger_settings_test.py`)

```python
def test_missing_section_means_no_cameras():
	assert load_flagger_settings({}) == FlaggerSettings(cameras=(), retention_days=30)


def test_reads_cameras_and_retention_and_collapses_duplicates():
	config = {"flagger": {"cameras": ["B", "A", "B"], "retention_days": 14}}
	assert load_flagger_settings(config) == FlaggerSettings(cameras=("B", "A"), retention_days=14)


def test_rejects_retention_below_a_week():
	with pytest.raises(ValueError, match="retention_days"):
		load_flagger_settings({"flagger": {"cameras": [], "retention_days": 6}})


@pytest.mark.parametrize("cameras", ["SLSV", ["SLSV", 3], None])
def test_rejects_malformed_camera_list(cameras):
	with pytest.raises(ValueError, match="cameras"):
		load_flagger_settings({"flagger": {"cameras": cameras}})


def test_repo_config_ships_an_empty_flagger_section():
	assert load_config()["flagger"] == {"cameras": [], "retention_days": 30}
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_settings_test.py -v` expects ImportError / FAIL.
- [ ] **Step 3: Implement `load_flagger_settings` in `src/flagger/settings.py`** and add the config section. An absent `retention_days` means 30; an absent `cameras` means empty.
- [ ] **Step 4: Run** `python -m pytest tests/flagger_settings_test.py tests/config_test.py -v`. Expected: PASS (without the `EXPECTED_ROOT_KEYS` change the config tests fail on the new key).
- [ ] **Step 5: Commit** (see Global Constraints): paths `src/flagger/__init__.py src/flagger/settings.py config/config.json tests/config_test.py tests/flagger_settings_test.py`, message `feat: add flagger settings and config section`.

### Task 2: Classes, groups and the flag decision

**Files:**
- Create: `src/flagger/groups.py`
- Test: `tests/flagger_groups_test.py`

**Interfaces:**
- Produces: `COCO_NAMES: tuple[str, ...]` (80 names, index = class id, names with `_` for spaces, e.g. `traffic_light`), `GROUP_BY_CLASS: dict[int, str]`, `THRESHOLDS: dict[str, float]` (`{"animal": 0.30, "flying": 0.30}`), `FLOOR: float` (the minimum threshold), `@dataclass(frozen=True) class Detection: class_id: int; score: float; box: tuple[float, float, float, float]` with properties `label -> str` and `group -> str`, and `best_flag(detections: list[Detection]) -> Detection | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_class_table():
	assert len(COCO_NAMES) == 80
	assert (COCO_NAMES[14], COCO_NAMES[4], COCO_NAMES[33], COCO_NAMES[16]) == (
		"bird",
		"airplane",
		"kite",
		"dog",
	)


def test_groups():
	assert {GROUP_BY_CLASS[c] for c in (14, 4, 33)} == {"flying"}
	assert {GROUP_BY_CLASS[c] for c in range(15, 24)} == {"animal"}
	assert 0 not in GROUP_BY_CLASS  # person is never flagged here


def test_strandallee_bird_is_flagged_as_the_airplane_guess():
	found = [Detection(14, 0.497, (716, 579, 814, 626)), Detection(4, 0.865, (716, 579, 814, 625))]
	best = best_flag(found)
	assert (best.label, best.group, best.score) == ("airplane", "flying", 0.865)


def test_below_threshold_and_foreign_classes_are_ignored():
	assert best_flag([Detection(16, 0.29, (0, 0, 1, 1)), Detection(0, 0.99, (0, 0, 1, 1))]) is None
	assert best_flag([]) is None
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_groups_test.py -v` expects FAIL.
- [ ] **Step 3: Implement** the module. `best_flag` returns the highest-scoring detection whose score is at least `THRESHOLDS[group]`; classes without a group are skipped.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `src/flagger/groups.py tests/flagger_groups_test.py`, message `feat: add flagger class groups and flag decision`.

### Task 3: YOLOX plumbing

**Files:**
- Create: `src/flagger/yolox.py`, `tests/flagger_fakes.py` (shared fakes, not collected)
- Test: `tests/flagger_yolox_test.py`

**Interfaces:**
- Consumes: `Detection`, `GROUP_BY_CLASS`, `FLOOR` from `src/flagger/groups.py`.
- Produces: `INPUT_SIZE = 640`, `Forward = Callable[[np.ndarray], np.ndarray]` (input blob `(1, 3, 640, 640)` float32, output `(8400, 85)`), `class OnnxForward` (`__init__(self, model_path: Path, threads: int = 4)`, `__call__(self, blob) -> np.ndarray`; imports `onnxruntime` inside `__init__` so importing the module needs only numpy and cv2), `detect_image(image: np.ndarray, forward: Forward, tiles: int = 2) -> list[Detection]` (boxes in full-image pixels; only classes in `GROUP_BY_CLASS`, score at least `FLOOR`; NMS per class at IoU 0.45 across the whole frame and all tiles), `detector_id(model_path: Path, tiles: int = 2) -> str` (format `<model stem without "object_detection_">-<first 8 hex of sha256 of the file>-ort-t<tiles>-animal0.3-flying0.3`).
- Fakes (`tests/flagger_fakes.py`): `class SequenceForward` taking `calls: list[list[tuple]]`, one list per forward call in order (whole frame first, then tiles top-left, top-right, bottom-left, bottom-right); each tuple is `(anchor_index, class_id, score)` or `(anchor_index, class_id, score, size_log)`. It returns a zero `(8400, 85)` array with, per tuple, objectness 1.0, the class score set, and `dets[i, 2:4] = size_log` (default 0.0, so the box edge equals the anchor's stride). Calls beyond the list return no detections.
- Anchor 2440 is stride 8, grid cell (40, 30), box centre (320, 240) in the 640 input (`index = 30*80 + 40`).

- [ ] **Step 1: Write the failing tests** (black images from `numpy.zeros`)

```python
def test_whole_frame_box_is_mapped_to_image_pixels():
	image = np.zeros((1080, 1920, 3), np.uint8)
	found = detect_image(image, SequenceForward([[(2440, 14, 0.5)]]), tiles=1)
	assert [(d.class_id, d.score) for d in found] == [(14, 0.5)]
	assert found[0].box == pytest.approx((948, 708, 972, 732), abs=0.5)


def test_tile_boxes_are_offset_into_the_full_frame():
	image = np.zeros((1080, 1920, 3), np.uint8)
	top_left = detect_image(image, SequenceForward([[], [(2440, 4, 0.8)]]))
	assert top_left[0].box == pytest.approx((568.8, 424.8, 583.2, 439.2), abs=0.5)
	bottom_right = detect_image(image, SequenceForward([[], [], [], [], [(2440, 4, 0.8)]]))
	assert bottom_right[0].box == pytest.approx((1336.8, 856.8, 1351.2, 871.2), abs=0.5)


def test_overlapping_boxes_of_one_class_keep_the_higher_score():
	big = math.log(4)
	forward = SequenceForward([[(2440, 14, 0.5, big), (2441, 14, 0.6, big)]])
	assert [d.score for d in detect_image(image, forward, tiles=1)] == [0.6]


def test_classes_outside_the_groups_and_below_the_floor_are_dropped():
	assert detect_image(image, SequenceForward([[(2440, 0, 0.9), (2441, 14, 0.2)]]), tiles=1) == []


def test_image_smaller_than_a_tile_does_not_crash():
	assert detect_image(np.zeros((10, 10, 3), np.uint8), SequenceForward([])) == []


def test_detector_id_follows_model_bytes_and_tiles(
	tmp_path,
): ...  # two model files, different bytes -> different ids; "t2" in the id; tiles=1 -> "t1"
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_yolox_test.py -v` expects FAIL.
- [ ] **Step 3: Implement `src/flagger/yolox.py`.** Take the letterbox (pad value 114, `cv2.INTER_LINEAR`), the stride grid (8, 16, 32), the decode (`centres = (dets[:, :2] + grid) * strides`, `sizes = exp(dets[:, 2:4]) * strides`, `score = objectness * class score`) and the tile layout (60 % tiles, order top-left, top-right, bottom-left, bottom-right) from `src/privacy/detect.py` (`letterbox`, `make_grid`, `regions`, `detect_region`). Copy the logic; do not import from `src/privacy`. Use `cv2.dnn.NMSBoxes` per class.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `src/flagger/yolox.py tests/flagger_fakes.py tests/flagger_yolox_test.py`, message `feat: add flagger YOLOX wrapper`.

### Task 4: Report writer

**Files:**
- Create: `src/flagger/report.py`
- Test: `tests/flagger_report_test.py`

**Interfaces:**
- Consumes: `Detection` (Task 2).
- Produces: `HIGHLIGHTS_DIR = "highlights"`, `@dataclass(frozen=True) class FlaggedImage: path: Path; detection: Detection; taken_at: datetime; image_size: tuple[int, int]` (width, height), `build_manifest(camera: str, target_date: date, created: datetime, detector: str, checked: int, items: list[FlaggedImage]) -> dict`, `write_report(video_root: Path, camera: str, target_date: date, manifest: dict, items: list[FlaggedImage]) -> Path` (returns `video_root/<camera>/highlights/<YYYY-MM-DD>`).

- [ ] **Step 1: Write the failing tests** (`tmp_path` as `video_root`; images are small files `b"\xff\xd8x\xff\xd9"`)

```python
def test_manifest_matches_the_contract():
	manifest = build_manifest(
		"Strandallee", date(2026, 10, 20), created, "yolox-abcd1234-ort-t2", 143, [item]
	)
	assert manifest == {
		"schema": 1,
		"camera": "Strandallee",
		"date": "2026-10-20",
		"created": created.isoformat(),
		"detector": "yolox-abcd1234-ort-t2",
		"checked": 143,
		"items": [
			{
				"file": "strandallee-26-10-20_08-14-58-20.jpg",
				"taken_at": "2026-10-20T08:14:58+02:00",
				"group": "flying",
				"label": "airplane",
				"score": 0.865,
				"box": [716, 579, 814, 625],
				"image_size": [1920, 1080],
			}
		],
	}


def test_items_are_ordered_by_score_highest_first(): ...
def test_report_folder_holds_clean_copies_and_a_manifest(
	tmp_path,
): ...  # bytes equal, manifest parses, path as returned
def test_empty_report_still_writes_a_manifest(tmp_path): ...  # items [], checked kept, no jpgs
def test_rerun_replaces_the_day_and_leaves_other_days_alone(tmp_path): ...
def test_failure_while_copying_keeps_the_previous_report_and_leaves_no_temp(
	tmp_path, monkeypatch
): ...
```
The last test makes the second `shutil.copy2` raise `OSError` during a second write; it asserts the call raises `OSError`, the earlier day folder content is unchanged, and no entry other than the day folder exists in `highlights/`.

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_report_test.py -v` expects FAIL.
- [ ] **Step 3: Implement.** `box` values are rounded to ints, `score` to 4 decimals. Each copy is named after its original with the suffix lowercased (`X.JPG` becomes `X.jpg`), and `file` in the manifest is that name. `write_report` builds the folder as `highlights/.<date>.tmp`, then swaps: old folder renamed to `.<date>.old`, new one renamed into place, old removed. On any exception the temp folder is removed and the old report is restored or left in place. The leading dot keeps the web UI from listing temp folders.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `src/flagger/report.py tests/flagger_report_test.py`, message `feat: add flagger report writer`.

### Task 5: Cleanup of old reports

**Files:**
- Modify: `src/flagger/report.py`
- Test: `tests/flagger_cleanup_test.py`

**Interfaces:**
- Produces: `cleanup_old_reports(video_root: Path, today: date, retention_days: int) -> list[Path]`, returns the removed day folders.

- [ ] **Step 1: Write the failing tests** (today 2026-10-21, `retention_days=30`, so the cutoff is 2026-09-21)

```python
def test_boundary_30_days_old_stays_31_goes(tmp_path):
	# make highlights/2026-09-20, 2026-09-21, 2026-10-20 for camera "A"
	assert removed == [tmp_path / "A" / "highlights" / "2026-09-20"]


def test_every_camera_is_cleaned_not_only_configured_ones(tmp_path): ...
def test_only_plain_date_folders_inside_highlights_are_touched(tmp_path): ...
```
The third test creates and asserts untouched: `2026-09-20-keep`, `notes`, `2026-13-45`, `.2026-09-01.tmp`, a file named `2026-09-01`, a symlink named `2026-09-02` pointing at a folder outside (neither the link nor its target removed), and `A/manual-runs/yearly/old.mp4` and `A/daily/` content.

```python
def test_missing_video_root_is_fine(tmp_path):
	assert cleanup_old_reports(tmp_path / "nope", today, 30) == []


def test_a_failing_removal_is_logged_not_raised(
	tmp_path, monkeypatch
): ...  # shutil.rmtree raises OSError; no exception, [] returned for that folder
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_cleanup_test.py -v` expects FAIL.
- [ ] **Step 3: Implement.** Look only at directories directly under `video_root/*/highlights/` whose names fully match `\d{4}-\d{2}-\d{2}`, are real directories (not symlinks) and parse as a valid date older than `today - timedelta(days=retention_days)`. Log removals at debug level and failures at warning level.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `src/flagger/report.py tests/flagger_cleanup_test.py`, message `feat: add flagger report cleanup`.

### Task 6: Scanning one camera and running all cameras

**Files:**
- Create: `src/flagger/run.py`
- Test: `tests/flagger_run_test.py`

**Interfaces:**
- Consumes: `detect_image`, `Forward`, `detector_id` (Task 3), `best_flag`, `Detection` (Task 2), `FlaggedImage`, `build_manifest`, `write_report` (Task 4); existing `find_daily_images_isolated`, `image_moment` (`src/images.py`), `get_sun_times` (`src/solar.py`), `automatic_daylight_buffer_for` (`src/config.py`).
- Produces: `@dataclass(frozen=True) class ImageScan: flagged: list[FlaggedImage]; checked: int; failed: int`, `scan_images(images: list[Path], forward: Forward, timezone: str, tiles: int = 2) -> ImageScan`, `select_daily_images(config: dict, camera: str, target_date: date) -> list[Path]`, `run_cameras(config: dict, cameras: Sequence[str], target_date: date, forward: Forward, video_root: Path, detector: str, now: datetime) -> int` (0, or 1 if any camera failed).

- [ ] **Step 1: Write the failing tests** (images written with `cv2.imwrite` into `tmp_path`, names like `cam-26-10-20_08-14-58-20.jpg`; fake forward from Task 3)

```python
def test_scan_flags_and_counts(tmp_path):
	scan = scan_images([good, corrupt, unparseable], forward_flagging_everything, "Europe/Berlin")
	assert (len(scan.flagged), scan.checked, scan.failed) == (1, 1, 2)
	assert scan.flagged[0].taken_at.isoformat() == "2026-10-20T08:14:58+02:00"
	assert scan.flagged[0].image_size == (64, 48)
```
`good` is a readable image, `corrupt` holds `b"not a jpeg"`, `unparseable` is a readable image named `weird.jpg`. `checked` counts images that were analysed; `failed` counts unreadable images and names `image_moment` cannot parse; both failures are logged and skipped.

```python
def test_tiny_image_is_scanned_without_error(tmp_path): ...  # 10x10 jpg, checked 1, failed 0
def test_select_daily_images_uses_the_daily_jobs_rules(monkeypatch):
	# monkeypatch src.flagger.run.find_daily_images_isolated to capture kwargs
	# config = {"location": {...Berlin, lat/lon...}, "automatic_daylight_buffer_minutes": {"10": 75, ...}, "image_scan_stall_timeout_seconds": 60}
	assert (
		captured["previous_date"] == date(2026, 10, 19)
		and captured["daylight_buffer_minutes"] == 75
	)
	assert captured["stall_timeout_seconds"] == 60 and captured["sunrise"] < captured["sunset"]


def test_a_day_without_flags_writes_an_empty_manifest(
	tmp_path, monkeypatch
): ...  # items [], checked == number of images
def test_a_camera_without_images_writes_nothing(
	tmp_path, monkeypatch
): ...  # no folder, exit 0, warning logged
def test_one_failing_camera_does_not_stop_the_others(
	tmp_path, monkeypatch
): ...  # first raises OSError in selection, second reports; exit 1
def test_summary_line_per_camera(
	tmp_path, monkeypatch, caplog
): ...  # "[Strandallee] checked=2 flagged=1 failed=0" in caplog.text
```
`run_cameras` tests monkeypatch `select_daily_images` to return prepared paths.

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_run_test.py -v` expects FAIL.
- [ ] **Step 3: Implement** the three functions. Read images with `cv2.imread(str(path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)`. One `FlaggedImage` per image: the result of `best_flag` on that image's detections. `run_cameras` catches `OSError` and `TimeoutError` per camera (as the Daily job does), logs one line per camera `[<camera>] checked=N flagged=M failed=F`, writes the manifest through `build_manifest` and `write_report` with `created=now`.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `src/flagger/run.py tests/flagger_run_test.py`, message `feat: add flagger camera scan and run`.

### Task 7: Command line, lock and test mode

**Files:**
- Modify: `src/flagger/run.py` (add `parse_arguments`, `make_forward`, `main`, `if __name__ == "__main__": sys.exit(main())`)
- Modify: `src/logger.py` (add `"flagger"` to `LogType`, nothing else)
- Test: `tests/flagger_main_test.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5, 6; `acquire_run_lock` and `RUN_LOCK_PATH` from `src/storage_filter.py` (context manager, raises `RuntimeError` when held); `get_cameras`, `require_cameras` from `src/images.py`; `get_latest_completed_date(timezone)` from `src/date_coverage.py`.
- Produces: `LOCK_PATH = RUN_LOCK_PATH` (the shared `state/zeitraffer-run.lock`, so the flagger never runs alongside the nightly encodes, a web job or the storage filter; tests monkeypatch it), `DEFAULT_MODEL = PROJECT_ROOT / "models" / "object_detection_yolox_2022nov.onnx"`, `parse_arguments(argv: list[str] | None = None) -> argparse.Namespace` with `--cameras A B`, `--target-date YYYY-MM-DD`, `--model PATH`, `--images DIR`, `--out DIR`, `--camera NAME` (test mode label, default `adhoc`); `--images` requires `--out` and excludes `--cameras`; `make_forward(model_path: Path) -> Forward` (the seam tests monkeypatch); `main(argv: list[str] | None = None) -> int`. Run as `python3 -m src.flagger.run`.

- [ ] **Step 1: Write the failing tests** (monkeypatch `LOCK_PATH` to `tmp_path`, `make_forward` to a fake, `load_config` to a small dict)

```python
def test_empty_camera_list_does_nothing(...):          # main([]) == 0, make_forward raises if called, log says no cameras configured
def test_unknown_or_ignored_camera_stops_before_reading(...):   # get_cameras patched; "Nope" and an ignored one -> return 1, make_forward not called
def test_held_lock_skips_the_run(...):                  # flock held by the test -> returns 0, "Skipped" logged, nothing scanned
def test_images_mode_writes_a_report_without_config_or_cleanup(...):
	# folder with "A_26-10-20_08-14-58-20.jpg" and "B_26-10-20_09-14-58-20.JPG"; the copy of B is "B_26-10-20_09-14-58-20.jpg"
	# main(["--images", str(src), "--out", str(out), "--target-date", "2026-10-20"]) == 0
	# out/adhoc/highlights/2026-10-20/manifest.json exists; cleanup_old_reports is monkeypatched to raise and is not called
def test_nightly_mode_cleans_up_after_the_cameras(...):  # cleanup called once with today and the configured retention_days
def test_parse_rejects_images_without_out_and_with_cameras(): ...   # SystemExit
```

- [ ] **Step 2: Run to verify failure:** `python -m pytest tests/flagger_main_test.py -v` expects FAIL.
- [ ] **Step 3: Implement `main`.** Nightly mode: `configure_file_logging("flagger")`, load the config and settings, camera list from `--cameras` or `settings.cameras`; empty means log "no cameras configured" and return 0; validate against `get_cameras()` minus `ignored_cameras` (return 1 on any problem); take `acquire_run_lock(LOCK_PATH)` (a `RuntimeError` logs "Skipped: ..." and returns 0); target date from `--target-date` or `get_latest_completed_date(timezone)`; then `run_cameras` with `forward=make_forward(model)`, `detector=detector_id(model)`, `video_root=Path("videos")` and `now` in the configured timezone, then `cleanup_old_reports(Path("videos"), today, settings.retention_days)` (a failure there never changes the exit code). Test mode: list `*.jpg` case-insensitively in `--images`, `scan_images`, write with `video_root=--out`, camera `--camera`, date `--target-date` or today, no config cameras, no lock, no cleanup.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** paths `src/flagger/run.py src/logger.py tests/flagger_main_test.py`, message `feat: add flagger command line`.

### Task 8: Acceptance test on real data

**Files:**
- Test: `tests/flagger_acceptance_test.py`

**Interfaces:**
- Consumes: `OnnxForward`, `detect_image`, `best_flag`.

- [ ] **Step 1: Write the test.** Skip with a clear reason when `models/object_detection_yolox_2022nov.onnx` or `sandbox/flagger-samples/strandallee-26-10-20_08-14-58-20.jpg` is missing (CI, fresh clones).

```python
def test_strandallee_bird_is_flagged():
	image = cv2.imread(str(SAMPLE), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
	best = best_flag(detect_image(image, OnnxForward(MODEL)))
	assert best is not None and best.group == "flying" and best.score >= 0.30
	assert iou(best.box, (716, 579, 814, 625)) > 0.5
```
`iou` is a small helper in the test file.

- [ ] **Step 2: Run:** `python -m pytest tests/flagger_acceptance_test.py -v`. Expected: PASS where the model and sample exist (Mac, Pi), SKIPPED in CI.
- [ ] **Step 3: Commit:** paths `tests/flagger_acceptance_test.py`, message `test: add flagger acceptance test for the bird sample`.

### Task 9: Documentation

**Files:**
- Create: `docs/flagger.md` (German, like the other `docs/<feature>.md`)
- Modify: `README.md` (short sections only, details stay in `docs/flagger.md`)

- [ ] **Step 1: Write `docs/flagger.md`:** purpose, the `flagger` config section, the two ways to run it (`python3 -m src.flagger.run` nightly, `--images ... --out ...` for tests), the output folder and `manifest.json` fields, groups and thresholds, the 30-day cleanup, the test commands, and the cron line from the spec, marked "geplant, nicht eingerichtet". The web page gets its section from the page plan.
- [ ] **Step 1b: README:** the `flagger` key in "Konfiguration", the chained cron line in "Zeitplanung mit Cron" (marked "geplant, nicht eingerichtet"), and a short "Highlights-Flagger" section (what it does, how to run it, link to `docs/flagger.md`).
- [ ] **Step 2: Verify** every command in the document against `parse_arguments`: run `python3 -m src.flagger.run --help` and compare.
- [ ] **Step 3: Commit:** paths `docs/flagger.md README.md`, message `docs: describe the highlights flagger`.

### Task 10: Whole-project verification and hand-over

- [ ] **Step 1:** `ruff check .` and `ruff format --check .` pass.
- [ ] **Step 2:** `python -m pytest` passes with `ffmpeg` and `ffprobe` hidden from `PATH` (CI has neither).
- [ ] **Step 3:** Confirm `git status` shows only the intended paths and `git diff --stat` touches none of `src/privacy/`, `src/video.py`, `src/jobs/`, `src/main.py`, and `src/logger.py` only by the one `LogType` line.
- [ ] **Step 4:** Hand Julius the commit commands (one `git commit -F` per commit), plus the final checks on the Pi: `.venv/bin/python -m pytest tests/flagger_*_test.py`; the acceptance test with the sample copied to `sandbox/flagger-samples/`; a test-mode run `.venv/bin/python3 -m src.flagger.run --images sandbox/flagger-samples --out /tmp/flagger-out --target-date 2026-10-20`; one nightly-mode run for one chosen camera (`--cameras <name> --target-date <date>`) after adding it to `flagger.cameras`; timing per image and per night noted from the log; the cron line from the spec for Julius to add when he decides to.
