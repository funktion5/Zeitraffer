# Frames over ssh: dropping the mount, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every job and tool reads camera frames over ssh and rsync instead of the `/mnt/cameras` mount, one small feature at a time.

**Architecture:** A `FrameSource` interface in a new `src/frame_source.py` sits behind the functions of `src/images.py` that today call `scandir` on `CAMERA_ROOT`. A local implementation keeps today's behaviour; an ssh implementation lists names over ssh and fetches the frames a job would open into a cache folder with rsync. The jobs stay as they are; each is switched over and checked on its own. The mount is removed last.

**Tech Stack:** Python 3.11+ (3.13 in CI and on the VPS), pytest, ruff, `ssh` and `rsync` (already used), PHP and bash for the web trio.

**Spec:** `docs/superpowers/specs/2026-10-27-ssh-frames-design.md` (read it first; this plan only adds the decisions it leaves open).

## Global Constraints

- One task is one feature. Never start the next task before the user says so.
- Work on `main`; the user commits every task with `git commit -F`, no Claude trailer, one topic per commit.
- Python 3.11 and 3.13; tabs, 100 columns, double quotes; `ruff check .` and `ruff format --check .` stay green.
- CI has no FFmpeg: run pytest with `ffmpeg` and `ffprobe` hidden before handing a task over.
- Tests never touch the real box: fakes for `StorageBox.run`, `subprocess.run` and `time.sleep`.
- No new dependency. No secrets, host names, account names or key file names in tracked files; the box is the ssh alias in `TIMELAPSE_STORAGE_BOX`.
- The Pi keeps running its own old checkout, so the local source stays the default until Task 28.
- `www-data` has no ssh key: PHP never talks to the box.
- Frames are unblurred: no fetched copy may outlive its camera in a job, also not after an error.
- `src/frame_source.py` must not import `src.images` or `src.storage_filter` at module level (circular imports); import `list_camera_files` lazily inside the method.

## Review Focus

Failure modes the spec implies that no task's happy path covers, most likely first. Each has a test in the task named in brackets.

1. The cache root must survive a worker started with the `spawn` method (macOS, future Python defaults), not only `fork`: the choice travels in the environment. [Task 10]
2. A frame listed on the box vanishes before rsync runs (rsync exit 23/24): the camera fails; it is never built from fewer frames. [Task 11]
3. File names with spaces or other odd characters survive listing and fetching. [Tasks 9, 11]
4. The box is unreachable or ssh would prompt (`BatchMode=yes`): the camera counts as failed, the others still run, the job exits non-zero. [Tasks 11, 14]
5. After an error in the video build or a stalled worker, no fetched frames are left behind. [Tasks 12, 14]
6. Several `localize` calls for one camera inside one job: manual Weekly runs one worker per day, and a later call must never remove frames an earlier call fetched. [Task 11]
7. The cache root must exist, with `TIMELAPSE_FRAME_CACHE` exported, before the first worker process starts. A root created inside a worker never reaches the parent, so the parent's `release` would find nothing and unblurred frames stay on disk. [Task 10]

## Task protocol (applies to every task)

1. Write the failing tests listed in the task; run them and see them fail for the stated reason.
2. Implement only the signatures listed in the task.
3. Run the full suite with `ffmpeg`/`ffprobe` hidden, plus `ruff check .` and `ruff format --check .`: all green. The existing tests of the touched functions must pass unchanged.
4. Stop and report: files changed, test counts, anything surprising. If the task has a hand check, give the user the commands.
5. The user checks, commits, and says go for the next task. A fresh reviewer reads the diff at the end of each phase, or earlier if the user asks.

---

## Phase A: the seam, local only (no behaviour change)

### Task 1: `FrameSource` with a local implementation

**Files:** Create `src/frame_source.py`, `tests/frame_source_test.py`; Modify `src/images.py` (add `get_frame_source`).

**Interfaces, produced for all later tasks:**
```python
class FrameFetchError(OSError): ...

class FrameSource(Protocol):
	def list_cameras(self) -> list[str]: ...
	def list_names(self, camera: str) -> Iterable[str]: ...  # may stream: ticks follow the names
	def path_for(self, camera: str, name: str) -> Path: ...
	def localize(
		self, camera: str, paths: list[Path], progress_callback: Callable[[], None] | None = None
	) -> None: ...  # make the files exist locally; raises FrameFetchError
	def release(self, camera: str) -> None: ...  # drop fetched copies of one camera

@dataclass(frozen=True)
class LocalFrameSource:  # implements FrameSource
	root: Path

def get_frame_source() -> FrameSource  # in src/images.py; returns LocalFrameSource(CAMERA_ROOT)
```

Tests: `test_local_list_cameras_returns_sorted_visible_directories` (a hidden folder and a plain file are excluded), `test_local_list_names_returns_every_entry_name`, `test_local_path_for_joins_root_camera_and_name`, `test_local_localize_and_release_change_nothing`, `test_get_frame_source_follows_a_patched_camera_root` (monkeypatch `src.images.CAMERA_ROOT`, as the existing tests do).

Implement: `list_cameras` mirrors today's `get_cameras`; `list_names` is `os.scandir` names; `localize` and `release` do nothing. `get_frame_source` builds a new `LocalFrameSource(CAMERA_ROOT)` on every call so patched roots keep working.

### Task 2: `get_cameras` through the source

**Files:** Modify `src/images.py` (`get_cameras`); Test `tests/images_test.py`.

Test: `test_get_cameras_uses_the_frame_source` (monkeypatch `src.images.get_frame_source` to a fake returning `["A", "B"]`; assert `get_cameras() == ["A", "B"]`). Implement: `return sorted(get_frame_source().list_cameras())`.

### Task 3: `find_images_for_dates` through the source

**Files:** Modify `src/images.py`; Test `tests/images_test.py`.

Test: `test_find_images_for_dates_uses_names_and_paths_from_the_source` (fake source with names `["a_20260101T1000.jpg", "b.JPG", "c.txt"]`; assert only `.jpg` names matching the date patterns are returned, as `fake.path_for(camera, name)` values, and the progress callback runs once per name). Implement: iterate `source.list_names(camera)` instead of `os.scandir`; build paths with `source.path_for`.

### Task 4: `get_image_range` through the source

Same pattern. Test: `test_get_image_range_reads_names_from_the_source` (earliest, latest and `unrecognized_files` computed from fake names).

### Task 5: `find_interval_images` through the source

Same pattern. Test: `test_find_interval_images_reads_names_from_the_source` (window and tolerance applied to fake names; result sorted by date and time, as `path_for` paths).

### Task 6: Daily worker calls `localize`

**Files:** Modify `src/images.py` (`_find_daily_images_worker`); Test `tests/images_test.py`.

Test: `test_daily_worker_localizes_previous_day_and_selected_frames_before_filtering` (recording fake source and a monkeypatched `filter_empty_images` that asserts `localize` already ran; the localized list is all frames of the previous day plus only the daylight-selected frames of the target day; `progress_callback` is passed through). Implement: call `get_frame_source().localize(camera, previous_images + current_images, progress_callback)` before the first `filter_empty_images`.

### Task 7: `_find_images_worker` calls `localize`

Same pattern (this feeds manual Weekly). Test: `test_images_worker_localizes_selected_frames_before_filtering`; localized list equals the daylight-selected frames.

### Task 8: `_find_interval_images_worker` calls `localize`

Same pattern (this feeds Monthly and Yearly; Yearly's lazy hashing then reads cached files). Test: `test_interval_worker_localizes_all_candidates_before_filtering`; localized list equals the candidates from `find_interval_images`.

**Phase A checkpoint:** a fresh reviewer reads Tasks 1 to 8; local behaviour is identical, the existing test suite passes unchanged.

---

## Phase B: the ssh source

### Task 9: `SshFrameSource` listing

**Files:** Modify `src/frame_source.py`; Test `tests/frame_source_test.py`.

**Interfaces:** `class SshFrameSource` with `__init__(self, box, cache_root: Path)`, where `box` is any object with `remote`, `base_directory`, `camera_directory(camera)` and `run(command, timeout_seconds)` (the `StorageBox` shape; do not import it). Implements `list_cameras`, `list_names`, `path_for` (`cache_root / camera / name`).

Tests (fake box returning canned `ls -l` output): `test_ssh_list_cameras_returns_directories_only`, `test_ssh_list_names_returns_regular_files`, `test_ssh_list_names_keeps_names_with_spaces`, `test_ssh_listing_failure_is_an_oserror`, `test_ssh_listing_timeout_is_a_timeouterror`, `test_ssh_path_for_points_into_the_cache`, `test_ssh_unsafe_names_from_the_box_are_refused` (security: a name with `/`, a control character, `..` or a leading `-` raises `FrameFetchError`, for file names, for camera names, and in `path_for`), `test_ssh_listing_timeout_is_below_the_configured_stall_timeout` (reads `image_scan_stall_timeout_seconds` from `config/config.json`). **Unsafe names (Phase A review, approved):** names come from a remote system and end up in local paths and the rsync file list; a file name with a newline can also fake a second `ls -l` line. They are refused loudly, never cleaned up. Implement: camera listing as `list_box_cameras` in `scripts/stage-frames.py` does it; names via a lazy `from src.storage_filter import list_camera_files` (keys of its result). Leave `stage-frames.py` untouched until Task 31. **Stall timeout (Phase A review):** the listing runs inside an isolated worker, which is killed after `image_scan_stall_timeout_seconds` (60 s) without a progress tick, and one `ls -l` over ssh sends no ticks. The listing timeout passed to `box.run` must stay below that value, so the real error is raised before the worker timeout hides it; pick the number here and test it. **Number: `NAME_LISTING_TIMEOUT_SECONDS = 45`** in `src/frame_source.py` (the existing `LISTING_TIMEOUT_SECONDS` in `src/storage_filter.py` is 60, equal to the stall timeout, so it is not used here). To pass its own timeout without touching `src/storage_filter.py`, the source runs `ls -l` itself and lazily imports only `parse_ls_output` from there (a small deviation from "keys of `list_camera_files`").

### Task 10: choosing the source and the cache root

**Files:** Modify `src/images.py` (`get_frame_source`), `src/frame_source.py` (cache helper), `README.md` (one line for `TIMELAPSE_FRAME_SOURCE` in the environment variable table); Test `tests/frame_source_test.py`.

**Interfaces:** `get_frame_source()` reads `TIMELAPSE_FRAME_SOURCE`: unset or `local` gives `LocalFrameSource`; `ssh` gives `SshFrameSource(get_storage_box(), cache_root)` (lazy import of `get_storage_box`); anything else raises `ValueError` naming the allowed values. `cache_root` is `<PROJECT_ROOT>/temp/frame-cache/<unique suffix>`, chosen on first use and exported as `TIMELAPSE_FRAME_CACHE`; later calls and child processes reuse that variable. **Ruling (Task 10):** choosing the path does not touch the disk, so a run that only lists (the camera-list job, a failed run) leaves no empty folders behind. The folder with its marker file `.frame-cache` is created by `create_frame_cache(root)` (mode `0700`), which `SshFrameSource.localize` calls in Task 11.

Tests: `test_unset_or_local_gives_the_local_source`, `test_ssh_gives_an_ssh_source_with_the_box_from_the_environment`, `test_unknown_value_is_rejected`, `test_cache_root_is_created_once_with_a_marker`, `test_spawned_child_process_sees_the_same_cache_root` (Review Focus 1: use `multiprocessing.get_context("spawn")`), `test_a_worker_that_is_the_first_caller_does_not_create_its_own_root` (Review Focus 7).

The parent creates the root: every `*_isolated` function in `src/images.py` calls `get_frame_source()` before it starts its worker, and each entry point that reads frames (`src/main.py`, `scripts/yearly-backfill.py`, `nas/helpers/storagebox_fill.py`, the flagger) does so before any job work, so the variable is exported before a worker forks or spawns. These entry points do not all call `get_cameras()` in the parent.

**Owner-only cache (approved):** the cache root is created with mode `0700` (`mkdir(mode=0o700)`), so only the login user can read it whatever `temp/` or the umask allow. The frames in it are unblurred and show people (GDPR), and the Python jobs' default `umask 0002` makes new files world-readable, so the parent folder is the only other barrier. Test `test_cache_root_is_owner_only`: with `umask 0002`, `stat.S_IMODE(root.stat().st_mode) == 0o700`.

### Task 11: `localize` fetches with rsync

**Files:** Modify `src/frame_source.py`; Test `tests/frame_source_test.py`.

**Interfaces:** `SshFrameSource.localize(camera, paths, progress_callback=None) -> None`. Constants `FETCH_BATCH_SIZE = 500`, `FETCH_RETRY_WAIT_SECONDS = (30, 120)`, `RSYNC_IDLE_TIMEOUT_SECONDS = 300`, `RSYNC_TOTAL_TIMEOUT_SECONDS = 3600`.

Behaviour: first `create_frame_cache(self.cache_root)` (Task 10: mode `0700` plus the marker); then fetch the file names of `paths` that are not already in the cache, in batches, with the same rsync command as `copy_camera` in `scripts/stage-frames.py` (`-t --from0 --files-from=- --timeout=...`, ssh with `BatchMode=yes` and `StrictHostKeyChecking=yes`); call `progress_callback` after every batch so the stall timeout of the isolated worker does not fire; never delete a file this call did not fetch (manual Weekly runs one worker, and so one `localize`, per day, and all seven days must still be there at the end; cleanup is `release`'s job); retry on `OSError` with the waits above; after the last failure remove the camera's cache folder and raise `FrameFetchError`.

Tests (fake `subprocess.run` and `time.sleep`): `test_fetch_runs_rsync_with_nul_separated_names`, `test_fetch_keeps_names_with_spaces_intact`, `test_fetch_splits_1200_names_into_three_batches_and_reports_progress_each_time`, `test_failed_fetch_is_retried_with_the_configured_waits`, `test_exhausted_retries_remove_the_camera_cache_and_raise_frame_fetch_error`, `test_rsync_vanished_files_exit_code_23_fails_the_camera` (Review Focus 2), `test_a_later_call_keeps_the_files_of_an_earlier_call` (Review Focus 6: two `localize` calls for one camera with different paths, both sets present afterwards).

### Task 12: `release` and guarded cleanup

**Files:** Modify `src/frame_source.py`; Test `tests/frame_source_test.py`.

**Interfaces:** `SshFrameSource.release(camera) -> None` and `release_all() -> None` remove `cache_root/camera` or the whole cache root, but only when `cache_root` carries the `.frame-cache` marker and resolves strictly inside `<PROJECT_ROOT>/temp`; unsafe camera names (containing `/`, `.` or `..`) raise `ValueError`.

Tests: `test_release_removes_only_the_named_camera_folder`, `test_release_all_removes_the_cache_root`, `test_release_refuses_a_cache_root_without_the_marker`, `test_release_refuses_a_root_outside_temp`, `test_release_refuses_unsafe_camera_names`, `test_release_ignores_a_missing_folder` (Review Focus 5).

### Task 13: equivalence of the two sources

**Files:** Test `tests/frame_source_equivalence_test.py` (new).

Test (parametrised over `find_images_for_dates`, `find_interval_images`, `get_image_range`, `get_cameras`): build a temporary local camera folder with names in all supported date formats plus non-jpg files and odd names; give a fake box the same names as `ls -l` output; assert the local and ssh sources return the same sorted names. This is the spec's equivalence check.

**Phase B checkpoint:** a fresh reviewer reads Tasks 9 to 13.

---

## Phase C: the jobs, one per task

Each job task has the same shape: add a `finally` that calls `get_frame_source().release(camera)` around the per-camera work; make a listing or fetch error count as `failed` (not `skipped`) while the other cameras continue; keep "0 frames" as `skipped`. `FrameFetchError` is an `OSError`, which the jobs already catch as an operational error.

### Task 14: Daily

**Files:** Modify `src/jobs/daily.py`; Test `tests/daily_test.py`.

Tests: `test_fetch_error_counts_as_failed_and_other_cameras_still_run` (Review Focus 4), `test_zero_frames_is_skipped_not_failed`, `test_release_runs_after_success`, `test_release_runs_when_the_video_build_raises` (Review Focus 5).

**Hand check (the user):** on the VPS, no staging, no mount:
`TIMELAPSE_FRAME_SOURCE=ssh TIMELAPSE_STORAGE_BOX=<alias> .venv/bin/python3 -m src.main --jobs daily --target-date <date> --cameras <camera>`. The video must match the Pi's for the same day, and `temp/frame-cache` must be empty afterwards.

### Task 15: manual Weekly

**Files:** Modify `src/jobs/weekly.py` (`collect_weekly_images` and its caller); Test `tests/weekly_test.py`. Same four tests as Task 14 for the weekly path. Hand check: `--jobs weekly --target-date <date> --cameras <camera>` as above.

### Task 16: Monthly

**Files:** Modify `src/jobs/monthly.py`; Test `tests/monthly_test.py`. Same four tests. Hand check: `--jobs monthly`.

### Task 17: Yearly

**Files:** Modify `src/jobs/yearly.py`; Test `tests/yearly_test.py`. Same four tests, plus `test_yearly_selection_reads_the_fetched_files` (the candidate set is localized once; `select_yearly_images_isolated` runs on cached paths). Hand check: `--jobs yearly` for one camera and a short range.

### Task 18: highlights flagger

**Files:** Modify `src/flagger/run.py`; Test `tests/flagger_run_test.py`. Tests: release after each camera, also after a detector error; fetch error marks that camera failed and the others still run. The flagger still takes the run lock itself, which now conflicts with nothing because no wrapper stages around it. Hand check: `python3 -m src.flagger.run --cameras <camera> --target-date <date>` with the two variables set.

### Task 19: CLI camera discovery and `--blur-people`

**Files:** Modify `src/main.py` only if it still reads the mount; Test `tests/main_test.py`. Tests: `test_main_discovers_cameras_through_the_frame_source`; `test_blur_people_runs_on_localized_frames` (anonymize receives the cached paths). Hand check: one Daily with `--blur-people`.

**Phase C checkpoint:** a fresh reviewer reads Tasks 14 to 19.

---

## Phase D: web and nightly

### Task 20: camera list file

**Files:** Create `src/camera_list.py`, `tests/camera_list_test.py`.

**Interfaces:** `write_camera_list(destination: Path, cameras: list[str]) -> None` (atomic write: temp file, then rename; JSON list; mode 644) and `python3 -m src.camera_list` writing `state/web-jobs/cameras.json` from `get_frame_source().list_cameras()` minus `ignored_cameras`. Tests: `test_write_is_atomic_and_readable`, `test_ignored_cameras_are_left_out`, `test_a_failed_listing_keeps_the_old_file`.

### Task 21: web video library reads the list

**Files:** Modify `web/src/video-library.php` (`findAvailableCameras`); Test `tests/web_php_test.py`. Replace the `/mnt/cameras` scan with reading `state/web-jobs/cameras.json`; a missing or invalid file gives an empty list. Tests: `camera list comes from the file`, `a missing file gives no cameras`.

### Task 22: web trigger checks the list

**Files:** Modify `scripts/timelapse-web-trigger`; Test `tests/web_status_test.py` or a new `tests/web_trigger_test.py` following the existing wrapper tests. The `-d ${CAMERA_ROOT}/${CAMERA}` check becomes membership in `cameras.json`; exit code 66 stays for an unknown camera. Tests: known camera passes, unknown camera exits 66.

### Task 23: web worker uses the ssh source

**Files:** Modify `scripts/timelapse-web-worker`; Test existing worker tests. Export `TIMELAPSE_FRAME_SOURCE=ssh` and `TIMELAPSE_STORAGE_BOX=${TIMELAPSE_STORAGE_BOX:-storagebox}` before `src.main` (sudo clears the environment). Test: the command environment contains both. Hand check: start one job from the web UI and watch it complete.

### Task 24: nightly wrapper without staging

**Files:** Modify `scripts/timelapse-nightly-staged`, `tests/nightly_staged_test.py`. The wrapper stops calling `stage-frames.py` and `--clean-only`, and stops exporting `TIMELAPSE_CAMERA_ROOT` (the staging folder); it keeps the lock, the per-camera loop, the verification and the report, and writes `cameras.json` through `python3 -m src.camera_list`. Tests: no staging call; the camera list is written; failure of one camera still gives exit 1. Hand check: one full nightly run on the VPS, report read by the user.

**Phase D checkpoint:** a fresh reviewer reads Tasks 20 to 24. Then `wp-security-reviewer` (read-only, Opus) reviews the one place where web input reaches a privileged path: camera-name handling in `timelapse-web-trigger` (no argument or command injection, exit 66 for an unknown name and nothing else), the `sudo` environment in `timelapse-web-worker`, `cameras.json` handling and file modes, and the rule that `www-data` never holds an ssh key or talks to the box. Its findings are fixed before the user pushes Phase D (approved by the user 2026-10-28).

---

## Phase E: tools

### Task 25: yearly backfill

**Files:** Modify `scripts/yearly-backfill.py`. It calls `find_interval_images_isolated`, so it follows the source; add `release` per camera and test with the existing backfill tests. Hand check: one camera, short range.

### Task 26: NAS helpers

**Files:** Modify `nas/helpers/storagebox_fill.py` (drop the `/mnt/cameras` assertion; it reads through the source) and check `nas/nas-extract.py` and `render_letterbox.py`, which use a local folder through `TIMELAPSE_CAMERA_ROOT` and keep working with the local source. Test: `test_local_source_still_reads_a_nas_folder` in `tests/frame_source_test.py`.

### Task 27: blur jobs and storage filter (verification first)

**Files:** none unless the check finds a mount dependency; then Modify `src/storage_filter.py` (report paths no longer built from `CAMERA_ROOT`) with `tests/storage_filter_test.py`. Hand check on the VPS: `blur_box --cameras <camera>` on a test camera and `scripts/storage-filter-all` in report mode, both with the ssh alias only.

**Phase E checkpoint:** a fresh reviewer reads Tasks 25 to 27.

---

## Phase F: the mount goes

### Task 28: flip the default

**Files:** Modify `src/images.py`, `src/frame_source.py`; Test `tests/frame_source_test.py`. Unset `TIMELAPSE_FRAME_SOURCE`: ssh when `TIMELAPSE_STORAGE_BOX` is set; otherwise the local source requires an explicit `TIMELAPSE_CAMERA_ROOT`. Remove `DEFAULT_CAMERA_ROOT` and the `/mnt/cameras` default. Tests: the three cases; no variable at all gives a clear error naming both variables (not an empty camera list).

### Task 29: remove the mount

**Files:** Delete `systemd/cameras-sshfs.service`, `scripts/cameras-sshfs-preflight`, `config/mount.env.example`; Modify `src/storage_filter.py` (`get_storage_box` loses the `/proc/mounts` fallback) and its tests. The user confirms the deletions before they run, per the project rules (list first, hand over a script).

### Task 30: docs and installer text

**Files:** Modify `Dockerfile` (the `/mnt/cameras` mount point), `compose.yaml` and `docker/entrypoint.sh` (the mount option and entry script), `migrate.sh` (Pi-only: mark it historical or drop its mount steps), `README.md` (SSHFS section out, frame-source section in), `docs/handbuch.md`, `docs/werkzeuge.md` (staging section), `docs/vps.md` (known gaps shrink), `docs/architektur.md`, `install.sh` (`cron_hint` text: no staging, flagger line). Test: `grep -rn "mnt/cameras\|sshfs" . --exclude-dir=.git --exclude-dir=frontend` returns only historical notes the user keeps.

### Task 31: retire `stage-frames.py`

**Files:** Delete `scripts/stage-frames.py` and `tests/stage_frames_test.py` after confirmation, or keep a thin tool if the user wants it. Update `docs/plans/web-server-nightly-run.md` status.

**Phase F checkpoint:** a fresh reviewer reads Tasks 28 to 31; the user does the final end-to-end check (nightly run plus one web job).

---

## Self-review

- **Spec coverage:** goals, non-goals and anti-goals map to Tasks 1 to 31: every job (14 to 19), tools and NAS (25 to 27), web (20 to 24), mount removal (28 to 30), the equivalence check (13), failure meaning (11, 14), cleanup (12, 14), fetch scope (6 to 8, 17), opt-in switch (10, 28). Blur jobs are verification only because they are already mount-free (27).
- **Types:** `localize(camera, paths, progress_callback)`, `release(camera)`, `path_for(camera, name)`, `FrameFetchError` are used with identical signatures in Tasks 6 to 8, 11, 12 and 14 to 18.
- **Proportion:** tasks carry signatures, test names and the values the spec pins; bodies are left to the implementer.
