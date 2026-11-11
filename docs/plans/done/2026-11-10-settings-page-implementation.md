# Settings page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native, one task at a time)
> to implement this plan. Steps use checkbox (`- [ ]`) syntax. **Stop after every task** for Julius's check
> and git save: he runs pytest and ruff on the VPS, Claude runs neither; the hand-over is `git status
> --short`, the files to stage by name, and a message (no Co-Authored-By trailer).

**Goal:** A settings page in the web UI where colleagues change an allowlisted set of values, saved to
`config/settings.json` and laid over `config.json` by `load_config()`.

**Architecture:** One Python module owns the allowlist, the validation and the merge. `load_config()` merges
a validated `settings.json` over `config.json`. A root-owned wrapper (sudo, like `timelapse-web-rebuild`)
runs a Python writer that validates, stores only the differences from `config.json`, and writes atomically.
PHP reads the merged config through one shared reader and posts the form to the wrapper.

**Tech Stack:** Python 3.11-compatible (CI runs 3.13), plain PHP behind Apache, bash wrapper, pytest. No new
dependency.

**Spec:** `docs/plans/done/2026-11-10-settings-page.md`

## Global Constraints

- Code is tab-indented, 100 columns, double quotes (ruff); comments in English explain why; UI text German.
- Keep `src/` runnable on Python 3.11. No new Composer, npm or pip dependency.
- Plain-name camera pattern everywhere: `^[A-Za-z0-9][A-Za-z0-9._-]*$`.
- No local paths, account names, key names or logins in tracked files. No third-party requests; the gear is an
  inline SVG, no icon set.
- Every handler: session CSRF token compared with `hash_equals`, only `confirm = yes`, server-side validation.
- BFSG/WCAG 2.2 AA: fieldset/legend per group, labelled controls, errors tied to their field, visible focus.
- Allowlist (leaf key, rule). Nothing else is changeable; `privacy`, `location`, `timelapse.ffmpeg_threads`,
  `image_scan_stall_timeout_seconds` are not:
  `timelapse.crf` int 18-35; `timelapse.daily_framerate|monthly_framerate|yearly_framerate` int 1-60;
  `ignored_cameras` list of plain names; `flagger.cameras` list of plain names; `flagger.retention_days`
  int 1-365; `daylight_buffer_minutes` int 0-240; `automatic_daylight_buffer_minutes.1` to `.12` int 0-240;
  `interval_window.target_time` "HH:MM"; `interval_window.tolerance_minutes` int 0-240;
  `min_coverage_days.monthly` int 1-31; `min_coverage_days.yearly` int 1-366; `log_retention_days` int 1-365.
  Integers mean real JSON integers: not bool, not float, not a string.

## Review Focus

1. A `settings.json` on the machine running the tests (Julius's Mac) must never change a test result: Task 1.
2. A broken, non-object or wrongly typed `settings.json` must never make `load_config()` raise: Task 1.
3. A crafted save carrying a key outside the allowlist (`privacy.blur_cameras`, `location.timezone`) or a
   path-like camera name saves nothing: Tasks 2 and 6.
4. A save with every camera unticked is refused (the night run would process nothing): Task 6.
5. A save from a page loaded before another colleague saved is refused, and nothing half-applies: Tasks 2, 3.

---

### Task 1: Allowlist, validation, merge, and the overlay in `load_config()`

**Files:**
- Create: `src/settings.py`, `tests/settings_test.py`
- Modify: `src/config.py`, `config/config.json` (the `_note` key), `tests/config_test.py`, `tests/conftest.py`

**Interfaces:**
- Produces (`src/settings.py`):
  - `ALLOWED_KEYS: tuple[str, ...]`, dotted leaf paths exactly as the Global Constraints list them (month map
    expanded to `automatic_daylight_buffer_minutes.1` ... `.12`).
  - `validate_settings(raw: object) -> tuple[dict, list[str]]`: `raw` is a nested dict. Returns the clean
    nested dict (only allowlisted, valid leaves) and German error strings, one per rejected leaf, each starting
    with the dotted key (`"timelapse.crf: ..."`). A non-dict `raw` gives `({}, ["Ungültige Eingabe"])`.
    A key outside the allowlist is an error too ("nicht änderbar").
  - `merge_settings(base: dict, clean: dict) -> dict`: new dict, recursive for dicts (so one month of the
    month map changes only that month), lists and scalars replace. Does not mutate `base`.
  - `read_settings_file(path: Path) -> dict`: parsed object, or `{}` for a missing, unreadable, invalid or
    non-object file (a broken file logs one warning).
- Produces (`src/config.py`): `SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"`;
  `load_config()` returns `merge_settings(base, clean)` with `clean` from `validate_settings(
  read_settings_file(SETTINGS_PATH))`; dropped leaves are logged as warnings. `SETTINGS_PATH` is read at call
  time so tests can patch it.
- Produces (`config/config.json`), so an IT edit of `config.json` is not silently shadowed: JSON has no
  comments, so the FIRST key of the file is `"_note"`, a string: "Keys that can be changed on the web UI page
  Einstellungen are stored in config/settings.json, and a value there overrides this file. Change those keys
  on that page, not here. Which keys: docs/konfiguration.md." (Julius may reword; English like the code
  comments). The note is not in the allowlist, so a settings file can never override it.
- Consumes: none.

- [ ] **Step 1: Isolate tests from a real settings file.** In `tests/conftest.py` add an autouse fixture that
  monkeypatches `src.config.SETTINGS_PATH` to `tmp_path / "no-settings.json"` (nonexistent). Add to
  `tests/settings_test.py`: `test_tests_never_read_a_real_settings_file` asserting that file does not exist.
- [ ] **Step 2: Write the failing tests** in `tests/settings_test.py`:
  - `test_allowed_keys_lists_every_leaf`: contains `timelapse.crf`, `automatic_daylight_buffer_minutes.11`,
    `min_coverage_days.yearly`; contains nothing starting with `privacy` or `location`; 12 month keys.
  - `test_validate_accepts_each_key_at_both_bounds` (parametrized key, low, high from the constraints).
  - `test_validate_rejects_out_of_range_and_wrong_types`: crf 17, 36, `True`, `"28"`, `28.0` each give one
    error starting with `"timelapse.crf"` and `clean == {}`.
  - `test_validate_rejects_keys_outside_the_allowlist`: `{"privacy": {"blur_cameras": []}}`,
    `{"location": {"timezone": "UTC"}}`, `{"timelapse": {"ffmpeg_threads": 8}}` each leave `clean == {}`
    and one error naming the dotted key.
  - `test_validate_rejects_bad_camera_names`: `["../x"]`, `["a/b"]`, `[""]`, `".hidden"`, `"Alpha"` (not a list).
  - `test_validate_checks_the_midday_time`: `"12:00"` and `"00:00"` pass; `"24:00"`, `"12:60"`, `"1200"`, `""` fail.
  - `test_merge_replaces_leaves_and_merges_the_month_map`: base with all 12 months, clean
    `{"automatic_daylight_buffer_minutes": {"11": 45}}` changes only `"11"`; a list in clean replaces the
    base list; `base` is unchanged afterwards.
  - `test_read_settings_file_ignores_missing_broken_and_non_object_files`: missing, `"{not json"`, `"[1]"` all `{}`.
  - `test_load_config_applies_valid_values_and_drops_invalid_ones`: patched file
    `{"timelapse": {"crf": 30, "ffmpeg_threads": 99}, "log_retention_days": "x"}` gives crf 30,
    `ffmpeg_threads` and `log_retention_days` equal to `config.json`'s.
  - `test_load_config_without_a_settings_file_equals_config_json`.
  - In `tests/config_test.py`: add `"_note"` to `EXPECTED_ROOT_KEYS`, and
    `test_config_json_starts_with_the_settings_note`: the first key of the parsed file is `_note`, a string
    that mentions `settings.json` and `Einstellungen`.
- [ ] **Step 3: Run `python -m pytest tests/settings_test.py` (Julius, on the VPS).** Expected: FAIL, `src.settings`
  not found.
- [ ] **Step 4: Implement `src/settings.py` and the `src/config.py` change.** One rule table keyed by dotted leaf
  (a small frozen dataclass for int ranges, plus a list-of-names and a time-of-day rule); the same table
  builds `ALLOWED_KEYS`. Check what `src/logger.py` imports first: if it imports `src.config`, use the
  standard `logging` module in `settings.py` instead, to avoid an import cycle.
- [ ] **Step 5: Run the settings tests and the whole suite (Julius).** Expected: PASS, nothing else red (the
  existing `config_test.py` still reads the real `config.json`).
- [ ] **Step 6: Hand over.** `git status --short`, stage `src/settings.py src/config.py config/config.json
  tests/settings_test.py tests/conftest.py tests/config_test.py`, suggested message "feat: allowlisted settings
  overlay for load_config, with a note in config.json".

### Task 2: The writer (`src/settings_save.py`)

**Files:**
- Create: `src/settings_save.py`, `tests/settings_save_test.py`

**Interfaces:**
- Consumes (Task 1): `validate_settings`, `merge_settings`, `read_settings_file`, `SETTINGS_PATH`,
  `CONFIG_PATH`, `load_config`.
- Produces:
  - `@dataclass(frozen=True) class SaveResult: status: str; errors: tuple[str, ...]; mtime: int`. `status` is
    `"saved"`, `"invalid"` or `"stale"`; `mtime` is the settings file's modification time in whole seconds
    after the call, 0 when the file does not exist.
  - `save_settings(submitted: object, expected_mtime: int, *, config_path: Path | None = None,
    settings_path: Path | None = None, log_path: Path | None = None) -> SaveResult`. `None` means the module
    constant, read at call time. `submitted` is the complete nested dict of the form's values.
  - `main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int`: reads one JSON document from
    stdin and `--expected-mtime <int>`, prints one JSON line `{"status", "errors", "mtime"}` to stdout. Exit
    codes: 0 saved, 65 invalid (including unparsable JSON, "Ungültige Eingabe"), 73 stale.
  - `SETTINGS_LOG_PATH = PROJECT_ROOT / "logs" / "settings.log"`.

Behaviour the tests pin: validate first, then compare `expected_mtime` with `int(st_mtime)` of the settings
file (0 if missing); store ONLY the leaves that differ from `config.json` (so a value set back to the base
value disappears from the file, and the file stays minimal; lists compared as sorted lists and stored sorted);
write to a temp file in the same folder, `chmod 0o644` (the web server user reads it), `os.replace`; any
failure leaves the old file and no temp file. One log line per save to `settings.log`, created mode 0o600:
timestamp plus the changed keys as `key: old -> new`, no IP, no user agent.

- [ ] **Step 1: Write the failing tests** in `tests/settings_save_test.py` (each with a tmp `config.json` copy
  and tmp settings and log paths):
  - `test_save_stores_only_values_that_differ_from_config_json`: submit every allowed leaf at its base value
    except crf 30 and a list change; the file parses to exactly `{"timelapse": {"crf": 30}, ...}` for those.
  - `test_saving_the_base_value_again_removes_the_override`: file `{"timelapse": {"crf": 30}}`, submit crf 28
    (the base) gives file content `{}`.
  - `test_invalid_values_save_nothing`: crf 99 gives status `invalid`, the file's bytes unchanged, the error
    names `timelapse.crf`.
  - `test_keys_outside_the_allowlist_save_nothing`: add `privacy.blur_cameras` and, separately,
    `location.timezone`: status `invalid`, bytes unchanged.
  - `test_path_like_camera_names_save_nothing`: `ignored_cameras: ["../etc"]`.
  - `test_a_stale_page_is_refused`: file exists with mtime T, `expected_mtime = T - 5` gives `stale`, bytes
    unchanged; `expected_mtime = 0` with no file saves.
  - `test_saved_file_is_world_readable_and_leaves_no_temp_file`: mode 0o644, folder lists only the file.
  - `test_a_failing_rename_keeps_the_old_file`: patch `os.replace` to raise `OSError`; old bytes intact, no
    temp file left, the error propagates.
  - `test_log_line_names_changed_keys_with_old_and_new_values`: contains `timelapse.crf`, `28`, `30`; file
    mode 0o600; contains nothing else about the request.
  - `test_main_exit_codes_and_json_output`: stdin StringIO for saved (0), invalid values (65), unparsable JSON
    (65), stale (73); stdout is one JSON line with the three fields.
- [ ] **Step 2: Run `python -m pytest tests/settings_save_test.py` (Julius).** Expected: FAIL, module not found.
- [ ] **Step 3: Implement `src/settings_save.py`.** Model the atomic write on `write_camera_list` in
  `src/camera_list.py` (mkstemp, chmod, replace, cleanup in `except BaseException`).
- [ ] **Step 4: Run the new tests and the suite (Julius).** Expected: PASS.
- [ ] **Step 5: Hand over.** Stage `src/settings_save.py tests/settings_save_test.py`, message "feat: settings
  writer with differences only, stale check and log line".

### Task 3: The protected wrapper, install steps, ignore rule, example, backup

**Files:**
- Create: `scripts/web/timelapse-web-settings`, `config/settings.example.json`,
  `tests/web/web_settings_wrapper_test.py`
- Modify: `install.sh` (`step_web_bridge`, `step_permissions`), `.gitignore`, `backup.sh`,
  `tests/backup_test.py` (and the existing install tests where they list the wrappers: grep the tests for
  `timelapse-web-rebuild` and extend the same assertions).

**Interfaces:**
- Consumes (Task 2): `python -m src.settings_save --expected-mtime N`, JSON on stdin, exit codes 0/65/73.
- Produces: `/usr/local/sbin/timelapse-web-settings <expected-mtime> <json>`. Synchronous (no background
  worker, no run lock: the write is atomic). It validates its own arguments: exactly two, the first only digits
  (max 12), the second at most 8192 bytes; otherwise exit 64. It pipes the JSON to the Python writer as the run
  user (env overrides `TIMELAPSE_PROJECT_ROOT` and `TIMELAPSE_WEB_PYTHON`, like the rebuild wrapper), prints the
  writer's stdout and returns its exit code.

- [ ] **Step 1: Write the failing wrapper tests** in `tests/web/web_settings_wrapper_test.py`, in the style of
  `web_rebuild_test.py` (a fake python script via `TIMELAPSE_WEB_PYTHON` that records its argv and stdin):
  - `test_wrapper_passes_the_json_on_stdin_and_the_mtime_as_an_option`: fake sees `-m src.settings_save
    --expected-mtime 123` and exactly the JSON on stdin.
  - `test_wrapper_rejects_bad_arguments`: no arguments, three arguments, `abc`, `-1`, `12 3` as mtime, and a
    9000-byte JSON each exit 64 and never start the fake.
  - `test_wrapper_returns_the_writers_exit_code_and_output`: fake exits 65 / 73 with a JSON line; the wrapper
    returns the same code and prints the line.
- [ ] **Step 2: Run them (Julius).** Expected: FAIL, wrapper missing.
- [ ] **Step 3: Write the wrapper** with `set -euo pipefail`, modelled on `timelapse-web-rebuild` (project root
  via `getent`, usage text, exit 64 for bad arguments).
- [ ] **Step 4: `install.sh`.** `step_web_bridge`: one `sudo install -m 755 -o root -g root` line for the new
  wrapper and one sudoers line `www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-settings *`.
  `step_permissions`: the `find config ... ! -name config.json` line also excludes `settings.json`, and after
  `chmod o=r config/config.json` add a guarded `[[ -f config/settings.json ]] && chmod o=r config/settings.json`.
- [ ] **Step 5: `.gitignore`** gets `config/settings.json`. **`config/settings.example.json`** is tracked and
  holds `{"timelapse": {"crf": 28}}` (the base value, harmless if copied). **`backup.sh`** copies
  `config/settings.json` when it exists, read-only on the host, and `tests/backup_test.py` gets a test that a
  present file comes along and a missing one is not an error.
- [ ] **Step 6: Run the new tests, the install and backup tests, and `bash -n` on the changed shell files
  (Julius).** Expected: PASS.
- [ ] **Step 7: Hand over.** Tell Julius that `./install.sh web_bridge` and `./install.sh permissions` run on the
  VPS when no job runs, and that a one-time seed is `rsync --no-perms --ignore-existing` of his prepared file.
  Stage the files by name; message "feat: settings wrapper, install steps, ignore rule, backup".

### Task 4: One PHP config reader with the overlay

**Files:**
- Create: `web/src/project-config.php`, `tests/web/web_settings_reader_test.py`
- Modify: `web/src/video-library.php`, `web/src/highlights-library.php`

**Interfaces:**
- Produces (`web/src/project-config.php`): `const SETTINGS_ALLOWED_KEYS = [...]` (the dotted leaf names only,
  no ranges); `readBaseConfig(): array` (config.json only, `[]` when missing or broken, as today);
  `readProjectConfig(): array` (the base with `config/settings.json` laid over for the allowlisted keys only,
  month map merged by month, lists replaced; a missing or broken settings file means the base);
  `readSettingsMtime(): int` (whole seconds, 0 when the file does not exist).
- Consumes: Task 1's key list (checked by a test).

- [ ] **Step 1: Write the failing tests** in `tests/web/web_settings_reader_test.py`, running PHP through the
  helper style of `web_php_test.py` against a temp project root:
  - `test_overlay_changes_allowlisted_keys_only`: settings with `timelapse.crf`, `ignored_cameras`,
    `privacy.blur_cameras` gives the first two changed, privacy unchanged.
  - `test_month_map_merges_by_month`.
  - `test_missing_and_broken_settings_file_give_the_base`.
  - `test_php_key_list_equals_the_python_allowlist`: the PHP constant, read via `php -r` json output, equals
    `list(src.settings.ALLOWED_KEYS)` (the drift guard).
  - `test_both_libraries_use_the_shared_reader`: `readHighlightsConfig()` and `getIgnoredCameras()` reflect a
    settings override.
- [ ] **Step 2: Run them (Julius).** Expected: FAIL.
- [ ] **Step 3: Implement.** Move `readProjectConfig()` out of `video-library.php` into the new file;
  `readHighlightsConfig()` becomes `return readProjectConfig();`; both libraries `require_once` the new file.
  Keep the existing function names and return shapes so no caller changes.
- [ ] **Step 4: Run the new tests and the existing PHP web tests (Julius).** Expected: PASS.
- [ ] **Step 5: Hand over.** Stage the four files, message "feat: shared PHP config reader with the settings overlay".

### Task 5: The save runner

**Files:**
- Create: `web/src/settings-runner.php`
- Modify: `tests/web/web_settings_reader_test.py` (or a new `tests/web/web_settings_runner_test.py`)

**Interfaces:**
- Consumes: `runPrivilegedCommand()` and `projectRunUser()` from `web/src/process-runner.php`; the wrapper
  from Task 3.
- Produces: `saveSettings(array $values, int $loadedMtime): array` returning
  `["status" => "saved"|"invalid"|"stale"|"failed", "errors" => string[], "mtime" => int]`. It runs
  `/usr/bin/sudo -n -u <runUser> /usr/local/sbin/timelapse-web-settings <loadedMtime> <json>` where `<json>`
  is `json_encode($values)`; exit 0 maps to `saved`, 65 to `invalid` (errors decoded from the wrapper's JSON
  line), 73 to `stale`, anything else to `failed` with a logged `error_log` line and a generic German message.

- [ ] **Step 1: Failing tests.** sudo cannot be faked, so test through a seam: `saveSettings()` takes the
  command from a function `settingsWrapperCommand(int $mtime, string $json): array` that the test can
  override (read `web_rebuild_test.py` and follow how it reaches `startRebuildJob`). Cases: each exit code
  above, an unparsable wrapper reply is `failed`, and the JSON argument is exactly `json_encode($values)`.
- [ ] **Step 2: Run (Julius).** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Hand over.** Stage by name, message "feat: PHP runner for the settings wrapper".

### Task 6: The page and the header link

**Files:**
- Create: `web/public/settings.php`, `tests/web/web_settings_page_test.py`
- Modify: `web/src/components/header.php`, `web/public/style.css`

**Interfaces:**
- Consumes: `readProjectConfig()`, `readBaseConfig()`, `readSettingsMtime()` (Task 4), `saveSettings()`
  (Task 5), the camera list file `state/web-jobs/cameras.json`.
- Produces: `/settings.php`. GET renders the form with the effective values and, beside each field, the
  `config.json` value as "Standard". POST needs `csrf_token` (as `camera.php`), `confirm = yes` (the Save
  button is `<button name="confirm" value="yes">`) and hidden `loaded_mtime`.

Rules the tests pin:
- The handler reads ONLY a fixed map of known field names to dotted keys, never iterating `$_POST`. Integers
  are sent as ints when the text is all digits, otherwise as the raw string (so the writer rejects them).
- Known cameras = names in `cameras.json` plus `ignored_cameras`. A ticked name outside that set is refused.
  Ticked cameras are processed, unticked become `ignored_cameras`. No camera ticked is refused with a German
  message. Flagger cameras are the ticked subset of the known cameras.
- A `stale` result shows "Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden". `invalid`
  lists every error next to the page's form; `failed` shows the generic message. `saved` shows
  "Gespeichert. Gilt ab dem nächsten Auftrag; neue Videos nutzen die neue Qualität, bestehende bleiben
  unverändert." and reloads the values.
- Header: "Kameras" and "Highlights" stay left; "Einstellungen" with an inline SVG gear (`aria-hidden="true"`,
  visible text beside it) is pushed to the far right after the storage overview (`margin-left: auto`), and
  carries `aria-current="page"` on its own page.
- Markup: one `<form method="post">`, a `<fieldset>` with `<legend>` per group (Videoqualität, Kameras,
  Tageslicht und Zeitfenster, Flagger, Protokolle), every control with a `<label for>`, a 12-month table for
  the automatic buffer, units in the labels, a "Zuletzt gespeichert" line from the file's mtime, a reset
  button (`type="reset"`), the Save bar at the bottom, a note beside the camera list that unticked cameras
  disappear from the camera list of the web UI at once.

- [ ] **Step 1: Failing tests** in `tests/web/web_settings_page_test.py`, following `web_camera_page_test.py`:
  - `test_post_without_a_valid_csrf_token_is_rejected_and_nothing_is_saved`.
  - `test_post_without_confirm_yes_is_rejected` (`on`, `true`, missing).
  - `test_an_unticked_everything_save_is_refused`.
  - `test_a_ticked_camera_outside_the_known_set_is_refused`.
  - `test_unknown_post_fields_are_never_forwarded` (a posted `privacy[blur_cameras]` never reaches the runner).
  - `test_stale_invalid_failed_and_saved_show_their_messages`.
  - `test_every_field_has_a_label_and_every_group_a_legend`.
  - `test_the_nav_link_has_a_gear_and_aria_current_on_its_page` and `test_the_gear_svg_is_aria_hidden`.
- [ ] **Step 2: Run (Julius).** Expected: FAIL.
- [ ] **Step 3: Implement** `settings.php`, the header link and the CSS (the existing custom properties only:
  `--color-primary`, `--color-surface`, ... no new colours). Read `camera.php` lines 40-110 for the session and
  CSRF setup, and `style.css` for the form and button rules before writing.
- [ ] **Step 4: Run the page tests and the whole suite (Julius).** Expected: PASS.
- [ ] **Step 5: Render before hand-over.** Start `php -S` with fake data and a fake runner, screenshot the page
  in headless Chrome at desktop and phone width, and look: gear at the far right, groups, the 12-month table,
  error and success states, keyboard focus (memory `feedback-render-ui-before-handover`).
- [ ] **Step 6: Hand over.** Stage by name, message "feat: settings page and header link".

### Task 7: Docs

**Files:**
- Modify: `docs/weboberflaeche.md`, `docs/konfiguration.md`

- [ ] **Step 1:** `docs/weboberflaeche.md`: a section "Einstellungen" (what the page changes, what it does not,
  when a change applies, that unticking a camera hides it at once, the stale-page message). German, plain.
- [ ] **Step 2:** `docs/konfiguration.md`: a section on `config/settings.json` (the allowlist, that only
  differences are stored, that `config.json` stays the base, the one-time seed with
  `rsync --no-perms --ignore-existing`, `./install.sh permissions` afterwards, never rsync it again). Put the
  rule for IT at the top of the section: for a key on the allowlist, change it on the settings page or in
  `settings.json`, because a value there wins over `config.json`; `config.json` holds the default for such a
  key. The same sentence is the `_note` at the top of `config.json`.
- [ ] **Step 3:** run the project's link check over the two files; no local paths, account names or logins.
- [ ] **Step 4: Hand over.** Stage the two docs, message "docs: settings page and settings.json". Julius moves
  the design and this plan to `docs/plans/done/` himself, and I save a project memory and update CLAUDE.md
  "Current focus" only when he asks.
