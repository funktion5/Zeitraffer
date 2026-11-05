# Video status box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Videos" box on the edit screen of each Zeitraffer camera entry that shows the state of its four video folders, stores the newest file per period in the database, lets the players use that value, and lets an admin delete the files of a camera that is not published.

**Architecture:** Small `final` classes with static methods (the style of the f5-webcams plugin): the one "valid video" rule, the age status, stored values, a scanner (WP-Cron every 10 minutes plus a per-camera button), a meta box that renders the rows, and an actions class for scan and delete, which re-checks everything before it unlinks. A new filter hands the stored file to the f5-webcams player, whose lookup is tightened to the same rule. The existing procedural code of the plugin stays as it is.

**Tech Stack:** PHP 8.0-compatible object-oriented WordPress plugin code, WordPress post meta and cron APIs, an offline PHP harness for tests (see "Test method").

**Spec:** `docs/superpowers/specs/2026-11-03-video-status-page-design.md`

## Global Constraints

- PHP syntax that runs on 8.0 (the live version is unknown; the plugin header says 8.4), no new dependencies, no build step, no JavaScript: the box is plain server-rendered HTML with forms.
- Escape every output; every write has a nonce and a capability check; no raw SQL (post meta APIs only); path confinement for everything touching files; no `@` error suppression; nothing personal is stored (file names only).
- Decided by Julius: the new code is object-oriented in the style of the f5-webcams plugin: namespace `Zeitraffer`, `declare(strict_types=1)`, `final class` with static methods, 4-space indent, a `register()` method per class that adds its hooks, an `ABSPATH` guard, German texts. One class per file named `includes/class-<name>.php`, loaded by `require_once` from `plugin-timelapse.php`. The existing procedural `tl_timelapse_*` code is not converted; classes call its global functions (`tl_timelapse_videos_dir()`, `tl_timelapse_camera_entry()`) and constants (`TL_TIMELAPSE_POST_TYPE`, `TL_TIMELAPSE_FOLDER_META`); global classes need a leading backslash (`\WP_Post`, `\DateTimeImmutable`).
- The Zeitraffer plugin must keep working when f5-webcams is off, and f5-webcams when the Zeitraffer plugin is off.
- Julius commits; nothing is pushed; do not commit. Tests come first (red, then green).
- Periods: `daily`, `weekly`, `monthly`, `yearly`. Capability `edit_others_posts`. Post type `zeitraffer_camera`, folder meta `_zeitraffer_folder`.
- One "valid video" rule everywhere: a regular, non-empty, non-hidden `.mp4` that is not a symlink, directly in the period folder; newest by file name.
- Age comes from the date in the file name (`<folder>_<YYYY-MM-DD>`), not the modification time (mtime only for a name without a date). "Aktuell" when that date is yesterday or later in the site's timezone, else "Älter als 24 Stunden"; until 06:00 site time a file dated the day before yesterday still counts as "Aktuell". Other texts: "Kein Video", "Datei fehlt", "Datenbank veraltet".
- Stored meta per period: `_zeitraffer_video_<period>` = `["file" => name, "date" => "Y-m-d" or "", "checked" => unix time]`, written only when the file changes.

## Test method

No PHP test setup exists. Tests are checks in an offline harness: a PHP script that defines stand-ins for the WordPress functions, loads `frontend/zeitraffer/plugin-timelapse.php`, builds fake video folders, and runs a list of closures that return `true` or a failure message. The existing one is `harness-zeitraffer.php` (and `harness.php` for f5-webcams) in this session's scratchpad `.../scratchpad/harness/`; if it is gone, rebuild it from that pattern (stubs record hook registrations, meta writes and cron calls in globals). "Run" below means `php harness-zeitraffer.php` and, for f5, `php harness.php check`; a green run prints `all checks passed`. Checks call the classes as `\Zeitraffer\VideoFiles::newest_valid(...)`. Also run `php -l` on every touched file. Julius runs the Docker check at the end.

## Review Focus

1. A camera entry whose folder is missing, renamed or empty: no PHP warning, rows say "Kein Video" / "Ordner nicht gefunden", the scan clears stored values (Tasks 3, 5).
2. File names with spaces, umlauts, `#`, quotes or HTML: escaped in the box and the delete forms, and matched exactly by the delete (Tasks 5, 6).
3. A video name without a date (`final.mp4`) or with an impossible one: no warning, mtime fallback or "Kein Video" (Tasks 1, 2).
4. Timezone and DST edges around midnight and the 06:00 grace (server in UTC, site in Europe/Berlin) (Task 2).
5. A hostile or stale value: a filter value like `../x.mp4` in the player, a stored name whose file vanished, a file that disappears between listing and unlink (Tasks 4, 6, 7).

## File Structure

- Create `frontend/zeitraffer/includes/class-video-files.php` (`VideoFiles`): the valid-file rule, file listing, date from name, folder for a slug.
- Create `.../includes/class-age-status.php` (`AgeStatus`): the status and age text.
- Create `.../includes/class-stored-videos.php` (`StoredVideos`): the stored meta, and the player filter.
- Create `.../includes/class-scanner.php` (`Scanner`): the scan and the cron schedule.
- Create `.../includes/class-status-box.php` (`StatusBox`): rows, badge, the meta box.
- Create `.../includes/class-video-actions.php` (`VideoActions`): scan button and delete.
- Modify `frontend/zeitraffer/plugin-timelapse.php`: `require_once` the classes, call the `register()` methods, the deactivation hook, `tl_timelapse_latest_video()` uses the rule.
- Modify `frontend/f5-webcams/includes/class-timelapse.php`: `latest_video()` asks the new filter first, tightened fallback. Modify `frontend/f5-webcams/TIMELAPSE-PLAYER-CHANGES.md`.
- Modify `docs/wordpress.md` (German): the box, the delete, the scan.

---

### Task 1: The valid-video rule and file listing

**Files:** Create `includes/class-video-files.php`; Modify `plugin-timelapse.php` (require; `tl_timelapse_latest_video`); Test: harness-zeitraffer.php.

**Interfaces:**
- Produces, in `final class Zeitraffer\VideoFiles`: `public const PERIODS = ["daily", "weekly", "monthly", "yearly"]`;
  `period_files(string $folder, string $period): array` (`list<string>` names of every regular `.mp4` directly in `<videos_dir>/<folder>/<period>/`, empty and hidden included, symlinks and nested folders excluded, sorted by name descending; `[]` when the folder is missing);
  `newest_valid(string $folder, string $period): ?string` (name, or null);
  `date_from_name(string $file): ?string` (`Y-m-d` from the first date in the name, null if none or impossible);
  `folder_for_slug(string $slug): ?string` (the folder name under `<videos_dir>` whose `sanitize_key(name)` equals the slug, any folder with or without videos, null if none or the slug is empty).
- Consumes: global `tl_timelapse_videos_dir()` (exists).

- [ ] **Step 1: Write the failing checks.** Fixture `Cam/daily/`: `Cam_2026-10-31.mp4` (1 byte), `Cam_2026-11-01.mp4` (0 bytes), `.Cam_2026-11-02.tmp.mp4` (1 byte), `Cam_2026-11-03.mp4` (symlink to a file outside), `notes.txt`, `old/Cam_2026-11-04.mp4`.
  - `newest valid skips empty, hidden, symlink, other types, nested`: `VideoFiles::newest_valid("Cam", "daily") === "Cam_2026-10-31.mp4"`.
  - `period files lists every regular mp4`: `VideoFiles::period_files("Cam", "daily") === ["Cam_2026-11-01.mp4", "Cam_2026-10-31.mp4", ".Cam_2026-11-02.tmp.mp4"]`; missing folder `=== []` (Review Focus 1).
  - `date from name`: `"Cam_2026-11-02.mp4"` -> `"2026-11-02"`; `"Cam_2026-13-45.mp4"`, `"final.mp4"` -> `null` (Review Focus 3).
  - `latest_video keeps its contract`: `tl_timelapse_latest_video("Cam", "daily")` ends with `/Cam/daily/Cam_2026-10-31.mp4`, and is null for an empty period (the camera list only needs truthiness).
  - `folder for slug`: `VideoFiles::folder_for_slug("cam") === "Cam"`; a folder that holds only empty files is still found (a draft camera must stay deletable); `"nope"` and `""` -> `null`.
- [ ] **Step 2: Run; expect these five to fail** (class undefined, `latest_video` still picks the 0-byte file).
- [ ] **Step 3: Implement** the class in `includes/class-video-files.php` (use `scandir`, `is_link`, `is_file`, `filesize`; a date is accepted only if `\DateTimeImmutable::createFromFormat("!Y-m-d")` formats back to the same text); make `tl_timelapse_latest_video()` return `<dir>/<folder>/<period>/<name>` from `VideoFiles::newest_valid()`; `require_once` the file in `plugin-timelapse.php`.
- [ ] **Step 4: Run; expect all checks green** (earlier ones included), `php -l` clean.

### Task 2: Age status

**Files:** Create `includes/class-age-status.php`; Modify `plugin-timelapse.php` (require); Test: harness-zeitraffer.php.

**Interfaces:**
- Produces, in `final class Zeitraffer\AgeStatus`: `for_video(?string $date, ?int $mtime, \DateTimeImmutable $now): array` returning `["state" => "current"|"old"|"none", "label" => string, "days" => ?int]`; `text(?int $days): string` ("heute" for 0, "gestern" for 1, "vor N Tagen", "" for null).
- Rule: compute in the timezone of `$now` (callers pass `wp_timezone()`). Expected date = yesterday; before 06:00 it is the day before yesterday. `$date >= expected` -> current "Aktuell"; else old "Älter als 24 Stunden" with `days` = whole days from `$date` to today. No `$date` but an `$mtime`: use its date in that timezone. Neither: none "Kein Video", days null.

- [ ] **Step 1: Write the failing checks** (`now` in Europe/Berlin unless noted):
  - `now 2026-11-03 10:00`: date `2026-11-02` -> current; `2026-11-01` -> old, days 2.
  - `now 2026-11-03 05:59`: `2026-11-01` -> current; at `06:00` -> old.
  - DST end (Berlin, 2026-10-25): `now 2026-10-25 01:30`, date `2026-10-23` -> current; `now 2026-10-26 07:00`, date `2026-10-24` -> old (Review Focus 4).
  - UTC server vs site: instant `2026-11-02 23:30 UTC` converted to Berlin (00:30 on the 3rd), date `2026-11-01` -> current (grace); the same instant left in UTC, date `2026-11-01` -> old (the function must follow the timezone it is given).
  - mtime fallback: date null, mtime of 2026-11-02 12:00 Berlin -> current; both null -> `state "none"`, label "Kein Video" (Review Focus 3).
  - `text`: 0 "heute", 1 "gestern", 3 "vor 3 Tagen", null "".
- [ ] **Step 2: Run; expect failures** (class undefined).
- [ ] **Step 3: Implement** the class; `\DateTimeImmutable` date arithmetic, no manual seconds math (DST); require the file.
- [ ] **Step 4: Run; expect green.**

### Task 3: Stored values, scan, schedule

**Files:** Create `includes/class-stored-videos.php`, `includes/class-scanner.php`; Modify `plugin-timelapse.php` (require, `Scanner::register()`, `register_deactivation_hook(__FILE__, [\Zeitraffer\Scanner::class, "unschedule"])`); Test: harness-zeitraffer.php (add stubs `get_post_meta`, `update_post_meta`, `delete_post_meta`, `wp_next_scheduled`, `wp_schedule_event`, `wp_clear_scheduled_hook`, `register_deactivation_hook`, recording calls; `get_posts` returns a fixture list and records its args).

**Interfaces:**
- Produces, in `final class Zeitraffer\StoredVideos`: `meta_key(string $period): string` (`"_zeitraffer_video_" . $period`); `get(int $post_id, string $period): ?array` (`["file","date","checked"]` or null); `save(int $post_id, string $period, string $file, string $date): void` (writes only if `file` or `date` differ from the stored value; `checked` = now); `clear(int $post_id, string $period): void` (deletes only if something is stored).
- Produces, in `final class Zeitraffer\Scanner`: `public const HOOK = "zeitraffer_scan"`, `public const SCHEDULE = "zeitraffer_10min"`; `scan_camera(\WP_Post $entry): array` (period => `["file" => string, "date" => string]` or null; updates the stored values); `scan_all(): void`; `add_interval(array $schedules): array`; `ensure_scheduled(): void`; `unschedule(): void`; `register(): void` (adds `cron_schedules`, `init` -> `ensure_scheduled`, and `HOOK` -> `scan_all`).
- Consumes: `VideoFiles::newest_valid`, `VideoFiles::date_from_name`, `VideoFiles::folder_for_slug` (Task 1), global `TL_TIMELAPSE_FOLDER_META`.
- Note: the entry stores the sanitized slug; the real folder comes from `VideoFiles::folder_for_slug()` (not from `tl_timelapse_get_cameras()`, which hides folders without a valid video). A slug with no folder means "folder missing". Tasks 4, 5 and 6 use the same lookup.

- [ ] **Step 1: Write the failing checks.**
  - `scan stores the newest valid file per period`: entry with slug `cam`, daily and weekly present -> `update_post_meta` called for `_zeitraffer_video_daily` with `["file" => "Cam_2026-11-02.mp4", "date" => "2026-11-02", "checked" => <int>]`, and the return value has `daily`/`weekly` set, `monthly`/`yearly` null.
  - `scan writes nothing when nothing changed`: a second scan with identical files -> zero `update_post_meta`/`delete_post_meta` calls.
  - `scan updates when the newest file changes`, and `scan deletes the meta when a video is gone`.
  - `scan of a missing folder clears all four values and warns about nothing` (Review Focus 1).
  - `scan_all covers drafts but not the trash`: `get_posts` args contain post_type `zeitraffer_camera` and a `post_status` list with `draft` and `publish` and without `trash`; every returned entry is scanned.
  - `schedule`: `Scanner::ensure_scheduled()` calls `wp_schedule_event` once with recurrence `zeitraffer_10min` and the hook `zeitraffer_scan` when `wp_next_scheduled` is false, and not at all when it is true; `Scanner::add_interval([])["zeitraffer_10min"]["interval"] === 600`; after loading the plugin, `add_action("zeitraffer_scan", [Scanner::class, "scan_all"])`, `add_action("init", ...ensure_scheduled)`, the `cron_schedules` filter and `register_deactivation_hook(<plugin file>, [Scanner::class, "unschedule"])` are recorded.
- [ ] **Step 2: Run; expect failures** (classes undefined).
- [ ] **Step 3: Implement** both classes, each with the `ABSPATH` guard; `Scanner::scan_camera()` finds the folder with `folder_for_slug($entry's slug meta)`; require both files and call `Scanner::register()` in `plugin-timelapse.php`.
- [ ] **Step 4: Run; expect green; `php -l`.**

### Task 4: The player filter

**Files:** Modify `includes/class-stored-videos.php`; Modify `plugin-timelapse.php` (`StoredVideos::register()`); Test: harness-zeitraffer.php.

**Interfaces:**
- Produces, in `StoredVideos`: `player_video(string $file, string $foldername, string $period): string`, and `register(): void` which adds `add_filter("f5_webcams_timelapse_video", [self::class, "player_video"], 10, 3)`. `player_video` returns the stored file name for the entry of that folder and period if the stored name is a plain name (no slash, ends in `.mp4`) and the file passes the valid rule on disk; otherwise it returns `$file` unchanged (the default `""`).

- [ ] **Step 1: Write the failing checks:** stored valid -> returns the name; stored but the file was deleted -> returns the input; no entry for the folder -> input; period not in the list -> input; stored name `../x.mp4` or `a/b.mp4` (tampered meta) -> input (Review Focus 5); the filter is registered with priority 10 and 3 arguments.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement** using `tl_timelapse_camera_entry(sanitize_key($foldername), "any")` and `StoredVideos::get()`; the folder name for the disk check comes from `VideoFiles::folder_for_slug()`, as in the scan.
- [ ] **Step 4: Run; expect green.**

### Task 5: The status box (display)

**Files:** Create `includes/class-status-box.php`; Modify `plugin-timelapse.php` (require, `StatusBox::register()`); Modify `docs/wordpress.md` (German section "Videos im Kameraeintrag"); Test: harness-zeitraffer.php (stubs `get_post_status`, `wp_nonce_field` returning `<nonce>`, `esc_html`, `esc_attr`, `esc_url`, `admin_url`, `wp_timezone`, `add_meta_box`).

**Interfaces:**
- Produces, in `final class Zeitraffer\StatusBox`: `rows(\WP_Post $entry, \DateTimeImmutable $now): array` (four rows in period order, each `["period","path","disk" => ?string,"stored" => ?string,"status" => <AgeStatus array>,"note" => ""|"Datenbank veraltet"|"Datei fehlt"]`; `path` is the folder path, `disk` the newest valid file name, status from `AgeStatus::for_video` of the disk file);
  `render(\WP_Post $post): void` (echoes); `badge(array $status, string $note): string`; `register(): void` which adds `add_meta_box("timelapse_videos", "Videos", [self::class, "render"], TL_TIMELAPSE_POST_TYPE, "normal", "default")` on `add_meta_boxes`.
- `badge` returns `<strong style="color:#xxxxxx">label</strong>` (label escaped, colour through `esc_attr`), in the colours of the webcam check page (`check-webcams.php`): "Aktuell" green `#00a32a`; "Datenbank veraltet" yellow `#dba617`; "Älter als 24 Stunden", "Kein Video" and "Datei fehlt" red `#d63638`. "Datei fehlt" replaces the row's status; "Datenbank veraltet" is shown as an extra yellow badge next to it.
- Column headings, as on the webcam check page: "Zeitraum", "Ordner", "Neueste erkannte Datei", "Stand Datenbank", "Alter", "Status".
- No form inside the box: a meta box sits inside the post edit form and forms cannot nest. The box prints buttons with `form="zeitraffer-videos"`, `formmethod="post"`, `formaction=<admin-post.php?action=zeitraffer_scan|zeitraffer_delete>` and `name="item"` with the value `scan`, `all` or `<period>|<file name>`. One standalone form `<form id="zeitraffer-videos">` with hidden `post_id` and `wp_nonce_field(StatusBox::NONCE_ACTION)` (`zeitraffer_video_actions`) is printed by `StatusBox::print_actions_form()` on `admin_footer`, only on the edit screen of a camera entry. A checkbox `name="confirm"` (also `form="zeitraffer-videos"`) is the confirmation, since the page uses no JavaScript. (Ruling made during Task 5.)

- [ ] **Step 1: Write the failing checks.**
  - rows: disk and stored equal -> `note ""`; disk newer than stored -> `"Datenbank veraltet"`; stored names a file not on disk -> `"Datei fehlt"`; nothing anywhere -> status label `"Kein Video"`; missing folder -> four rows, no warning (Review Focus 1).
  - render, published entry (`get_post_status` = `publish`): output contains the four period names and the folder paths, the "Jetzt prüfen" form, and contains neither `Löschen` nor `zeitraffer_delete`.
  - render, draft entry: lists every `.mp4` of the four folders (the previous file, an empty one and a hidden one included), one delete form per file with hidden `period` and `file` inputs, one "Alle Dateien löschen" form, and a note naming `ignored_cameras`.
  - escaping: a file named `a "b" <i>&.mp4` appears escaped in text and in every attribute (Review Focus 2); the missing-folder case prints "Ordner nicht gefunden".
  - render shows the result of a delete: with `$_GET["zeitraffer_deleted"] = "3"` the output contains `3 Datei(en) gelöscht` (value passed through `absint`).
  - headings and badges: the output contains the six column headings listed above; `badge()` gives `#00a32a` for current, `#d63638` for old and for none, `#dba617` for the note "Datenbank veraltet"; a label with `<b>` in it comes out escaped.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement** the class; resolve the real folder with `VideoFiles::folder_for_slug()` (Task 1); the displayed status is always the disk file's; require the file and call `StatusBox::register()`.
- [ ] **Step 4: Run; expect green; `php -l`.** Add the German doc section (what the box shows, when the delete part appears: only after saving the camera as a draft, the `ignored_cameras` note).

### Task 6: Scan button and delete

**Files:** Create `includes/class-video-actions.php`; Modify `plugin-timelapse.php` (require, `VideoActions::register()`); Modify `docs/wordpress.md`; Test: harness-zeitraffer.php (real temp folders; stubs `current_user_can`, `check_admin_referer`, `wp_die` throwing, `wp_safe_redirect`, `get_edit_post_link`).

**Interfaces:**
- Produces, in `final class Zeitraffer\VideoActions`:
  `may_delete(?\WP_Post $entry): bool` (entry exists, post type `zeitraffer_camera`, status re-read with `get_post_status($entry->ID)` is not `publish`, `current_user_can("edit_others_posts")`);
  `delete_files(\WP_Post $entry, ?string $period, ?string $file): array` returning `["deleted" => int, "skipped" => int]`: with a period and a name it removes that one file, with both null every regular `.mp4` of the four folders; it checks `may_delete`, accepts a period only from `VideoFiles::PERIODS`, accepts a name only if it equals one returned by `VideoFiles::period_files()` for that period, requires `realpath` of the file inside `<videos_dir>/<folder>/<period>/`, skips symlinks, treats an already missing file as skipped (no warning), and ends with `Scanner::scan_camera($entry)`;
  `handle_scan(): void` and `handle_delete(): void`: thin handlers (capability, `check_admin_referer(StatusBox::NONCE_ACTION)`, read `post_id` and `item` from the request; `item` is `scan`, `all` or `<period>|<file name>`, split at the first `|`; the delete handler also requires `confirm=1` and does nothing without it; call the function, `wp_safe_redirect` to the edit screen with `zeitraffer_deleted=<n>`, `exit`); `register(): void` adds them on `admin_post_zeitraffer_scan` and `admin_post_zeitraffer_delete`. Because the target travels as one `item` value, a small pure function `parse_item(string $item): ?array` (`["period" => ?string, "file" => ?string]`, null for anything else) is tested directly.

- [ ] **Step 1: Write the failing checks** (draft entry, folder `Cam` with `daily`: `Cam_2026-11-02.mp4`, `Cam_2026-11-01.mp4`, `.x.tmp.mp4` (empty), `notes.txt`; `weekly`: one file; a symlink `Cam_2026-11-03.mp4` pointing to a file outside):
  - one named file is deleted, all others stay.
  - all (null, null): every regular `.mp4` of the four folders gone including the empty and the hidden one; `notes.txt`, the symlink target outside and the folder itself stay; the stored meta is cleared by the re-scan.
  - refused for a published entry (`get_post_status` = `publish`) and for a user without the capability: `deleted === 0`, files intact.
  - refused and nothing outside touched for: period `../..`, `weekly/../daily`, name `../outside.mp4`, `a/b.mp4`, a name that is in no listing, the symlink name (Review Focus 2, 5).
  - a file removed between listing and unlink (delete the same name twice in a row): the second call counts it as skipped, no warning (Review Focus 5).
  - a name with `#`, spaces and an umlaut is deleted by exact match (Review Focus 2).
  - hooks: `admin_post_zeitraffer_scan` and `admin_post_zeitraffer_delete` are registered.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement** the class; never take a path from the request, only the camera id, the period and a bare name.
- [ ] **Step 4: Run; expect green; `php -l`.** Extend the German doc section: the delete rules and that the push brings files back unless the camera is on `ignored_cameras`.

### Task 7: The f5-webcams lookup

**Files:** Modify `frontend/f5-webcams/includes/class-timelapse.php` (`latest_video()`); Modify `frontend/f5-webcams/TIMELAPSE-PLAYER-CHANGES.md`; Test: the f5 `harness.php` (add checks; the earlier 32 must stay green and the 10 baseline scenarios byte-identical).

**Interfaces:**
- `Timelapse::latest_video(string $foldername, string $period): ?string` keeps its signature (absolute path or null). It first applies `apply_filters("f5_webcams_timelapse_video", "", $foldername, $period)`; the value is used only if it is a non-empty string equal to its own `basename`, ends in `.mp4`, and the file in the confined folder is a regular, non-empty, non-symlink file. Otherwise the fallback runs: newest by name among regular, non-empty, non-symlink `.mp4` (hidden files are skipped by `glob`).

- [ ] **Step 1: Write the failing checks:** filter returns a valid existing name -> that file (even if a newer file is on disk: the stored value wins); returns a name that does not exist -> fallback newest; returns `../x.mp4`, `a/b.mp4`, `x.txt` or a non-string -> fallback (Review Focus 5); fallback skips a 0-byte newest file and a symlink newest file; no listener -> unchanged behaviour (baseline scenarios identical).
- [ ] **Step 2: Run; expect the new checks to fail.**
- [ ] **Step 3: Implement** in `latest_video()`; keep `PathValidator` confinement for the folder. Add the filter and the stricter fallback to `TIMELAPSE-PLAYER-CHANGES.md` (the filters list and "Behaviour").
- [ ] **Step 4: Run both f5 checks and the baseline dumps; expect green and identical; `php -l`.** Edited in the f5 working copy only; Julius hands it over.

### Task 8: Hand-over

**Files:** Modify the spec's status line to "built"; update memory `project-timelapse-status-page.md`.

- [ ] **Step 1: Run everything once:** both harnesses, `php -l` on all touched PHP files, the 10 f5 baseline dumps, `node --test tests/frontend/player.test.js`.
- [ ] **Step 2: List what changed** with `git status --short` in both repos, name files that are not part of this work, and give Julius this Docker check: the camera list is unchanged; open a camera: the box shows four rows; "Jetzt prüfen" updates it; set the camera to draft and save: the delete part appears; delete one file and then all (check the folder); a published camera shows no delete part; a webcam page and the shortcode show the stored video; with the Zeitraffer plugin deactivated the player still works.
- [ ] **Step 3: Update the spec status and the memory note.** Do not commit.
