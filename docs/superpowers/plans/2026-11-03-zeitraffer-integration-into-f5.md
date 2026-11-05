# Zeitraffer Plugin Integration into f5-webcams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native, one task at a time; Julius says "go" after each hand-over). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Move everything of the Zeitraffer plugin (camera post type, "Videos" box, scanner, delete actions, stored videos) into the f5-webcams plugin, so the Zeitraffer plugin can retire and the player reads the stored file directly.

**Architecture:** The camera post type gets its own file `includes/class-timelapse-post-type.php` (`TimelapsePostType`), next to the untouched `PostType` of the `webcams` type. The six status classes move to f5 `includes/` unchanged except namespace and constants. The four `f5_webcams_*` filters that bridged the two plugins become direct method calls. All classes are `final`, static, no constructor, like the rest of f5.

**Tech Stack:** PHP 8.4, WordPress 6.5+, the two offline harnesses (`harness-zeitraffer.php`, `harness.php`).

**Spec:** `docs/superpowers/specs/2026-11-03-video-status-page-design.md` (the feature) and the status plan `docs/superpowers/plans/2026-11-03-video-status-page.md` (Tasks 1-6, built). New decisions of 2026-11-03, evening (colleague's green light, via Julius): full integration, Zeitraffer plugin retires, own file for the post type class, English file names (`class-timelapse-post-type.php`).

## Progress (updated 2026-11-03, evening)

Tasks 1-4 complete and checked by Julius in Docker (uncommitted). Open: Julius's answer on deleting `frontend/zeitraffer/` (needs a harness retarget first), then Task 5. Ledger and harnesses: `memory/status-page-artifacts/` (see memory note `project-timelapse-status-page`).

## Global Constraints

- Julius commits himself. **No commit, no push, no stash, no pytest/ruff** by Claude. Offline checks only: `php -l`, the two harnesses, `node --test tests/frontend/player.test.js`.
- f5 files that may be edited: `f5-webcams.php` (inserted lines, plus the rename of the two shortcode lines), `includes/class-timelapse.php`, `includes/class-zeitraffer-shortcode.php` (renamed to `class-timelapse-shortcode.php` in Task 3), `assets/css/f5-webcams.css` (only the comment that names the shortcode file), `TIMELAPSE-PLAYER-CHANGES.md`, plus the new files. The other modified files in the f5 working copy (CLAUDE.md, class-cron, class-formatting, class-template-loader, check-webcams, class-stale-webcam-alert, README.md, `*.min.css`) are older copies of the colleague's work: never touch, never stage. f5's own CLAUDE.md and README are not edited; a suggested paragraph goes to Julius instead.
- Slug `zeitraffer_camera`, meta keys `_zeitraffer_folder` and `_zeitraffer_video_<period>`, cron hook `zeitraffer_scan` and schedule `zeitraffer_10min` stay **identical**, so existing entries, stored values and the scheduled event carry over.
- Style of f5: `declare(strict_types=1)`, `namespace F5\Webcams`, ABSPATH guard, 4 spaces, one class per file, `final` + static, German admin texts as plain strings (admin only, not wrapped in `__()`).
- No new dependency. No third-party request. Delete rules of `VideoActions` do not change (not published, `edit_others_posts`, name must equal a listed regular `.mp4`, realpath in folder, no symlink).
- Zeitraffer plugin and the new f5 code must not both register the type in Docker: Tasks 1-3 only add and load classes (nothing registers a hook); **Task 4 is the switch**.
- Deleting `frontend/zeitraffer/` needs Julius's explicit yes (global rule); until then it stays, deactivated.
- Harness commands (HARNESS = `<memory-ordner>/status-page-artifacts`):
  `export PATH="$HOME/.config/herd-lite/bin:$PATH"; cd "$HARNESS" && php harness-zeitraffer.php` (expect `all checks passed`, today 52 checks) and `php harness.php check` (today 32 checks, plus the 10 baseline dumps in `baseline/`, byte-identical).
- Ledger: `$HARNESS/ledger-integration.md`, first line `# SDD ledger — plan: docs/superpowers/plans/2026-11-03-zeitraffer-integration-into-f5.md`; one completion line per task, rulings as `Ruling: ... — why — cost if wrong`.

## Review Focus

Failure modes the tasks' main tests do not cover; each has a check in the task named:

1. A webcam or folder whose name has capitals or dots (`Hafen.Nord`): the entry lookup by `sanitize_key(foldername)` and the player's stored-file lookup must agree (Task 3).
2. A stored file that is gone, empty, a symlink, hidden or has a path in its name: the player must fall back to the newest valid file, never fail and never reach outside the folder (Task 3).
3. Existing entries after the move: same slug, same meta keys, same hook and schedule names; the scheduled event is not duplicated (Task 1, 2, 4).
4. A webcam without any camera entry: visitors see no player, editors see it with the note. This is a behaviour change for f5 alone (it showed every player before the bridge existed); the post type is now always part of f5 (Task 3).
5. Both plugins active at once: duplicate boxes and two scans. Not testable offline; the order "deactivate Zeitraffer, then update f5" goes into the hand-over and the docs (Task 4, 5).
6. Baseline: `latest_video` becomes stricter than `glob('*.mp4')` (empty file, symlink). Any baseline difference must be explained and ruled, not accepted silently (Task 3).

---

### Task 1: `TimelapsePostType` and `VideoFiles` in f5

**Files:**
- Create: `frontend/f5-webcams/includes/class-timelapse-post-type.php`, `frontend/f5-webcams/includes/class-video-files.php`
- Modify: `$HARNESS/harness-zeitraffer.php` (loads the f5 copies of what has moved; references `\Zeitraffer\VideoFiles` become `\F5\Webcams\VideoFiles`)
- Not modified: `f5-webcams.php`, the Zeitraffer plugin (still complete and working)

**Interfaces:**
- Consumes: the current procedural code in `frontend/zeitraffer/plugin-timelapse.php` (copy its behaviour, not its names) and `Zeitraffer\VideoFiles`.
- Produces:
  - `VideoFiles` (copy, namespace `F5\Webcams`) plus `public static function base_dir(): string` (`<uploads>/zeitraffer`, no trailing slash; replaces `tl_timelapse_videos_dir()`) and `public static function cameras(): array<string,string>` (slug => folder, only folders with a valid video in at least one period; replaces `tl_timelapse_get_cameras()`). Every use of `\tl_timelapse_videos_dir()` inside the class becomes `self::base_dir()`.
  - `TimelapsePostType` with `public const SLUG = 'zeitraffer_camera'`, `public const FOLDER_META = '_zeitraffer_folder'`; `register(): void` (adds the hooks: `init` -> `register_type`, `add_meta_boxes`, the two list-column filters, `admin_notices`, `admin_post_zeitraffer_sync`); `register_type(): void`; `entry_for_slug(string $slug, string $status = 'publish'): ?\WP_Post`; `is_published(string $foldername): bool`; `is_visible(string $foldername): bool` (published, or `current_user_can('edit_others_posts')`); `notice(string $foldername): string`; `texts(string $foldername): array{title: string, description: string}`. The labels are the ones of today ("Zeitraffer", "Zeitraffers", "Alle Zeitraffers", button "Zeitraffer aus Ordnern anlegen").

- [ ] **Step 1: Write the failing checks** in the harness, with the references switched: `VideoFiles` checks of the status plan's Task 1 now name `\F5\Webcams\VideoFiles`; new checks: `VideoFiles::base_dir()` is `<uploads>/zeitraffer`; `cameras()` skips a folder with only an empty video and keys by `sanitize_key`; `TimelapsePostType::SLUG` and `FOLDER_META` equal the literal strings above; `entry_for_slug('hafen.nord')` finds an entry whose meta holds the sanitized slug and respects `$status`; `is_visible` true for a published entry, false for a draft and for no entry, true for a draft when `current_user_can` is true; `notice` is `''` for a published camera and the editor text of today for the others; `texts` returns title and trimmed excerpt, nothing for no entry; the register_type call receives the labels above (record the `register_post_type` args in the stub).
- [ ] **Step 2: Run** `php harness-zeitraffer.php`. Expected: FAIL (class `F5\Webcams\TimelapsePostType` not found).
- [ ] **Step 3: Create `class-video-files.php`** as a copy of the Zeitraffer class with the namespace changed and the two additions above.
- [ ] **Step 4: Create `class-timelapse-post-type.php`**: move, not rewrite, the code of `plugin-timelapse.php` lines for the type, entry lookup, side meta box, list column, sync form and handler (nonce + `edit_others_posts` unchanged), and the three bridge functions' bodies as `is_visible`, `notice`, `texts`. The class docblock says: the private camera post type, one entry per video folder; visibility, texts and notes come from here; the `webcams` registration stays in `PostType`.
- [ ] **Step 5: Run** both harnesses and `php -l` on the two new files. Expected: all checks passed, 32 checks of `harness.php` unchanged.
- [ ] **Step 6: Ledger line, then stop** for Julius's look. Nothing is wired in yet; Docker is unchanged.

---

### Task 2: The five status classes into f5

**Files:**
- Create: `frontend/f5-webcams/includes/class-age-status.php`, `class-stored-videos.php`, `class-scanner.php`, `class-status-box.php`, `class-video-actions.php`
- Modify: `$HARNESS/harness-zeitraffer.php` (one class at a time: its checks switch to `\F5\Webcams\X`; the old plugin file is no longer loaded when the last class has moved)

**Interfaces:**
- Consumes: Task 1; the existing classes in `frontend/zeitraffer/includes/`.
- Produces: the same public methods as today in namespace `F5\Webcams`. Changes inside: `TL_TIMELAPSE_POST_TYPE` -> `TimelapsePostType::SLUG`, `TL_TIMELAPSE_FOLDER_META` -> `TimelapsePostType::FOLDER_META`, `\tl_timelapse_videos_dir()` -> `VideoFiles::base_dir()`, `\tl_timelapse_camera_entry($slug, 'any')` -> `TimelapsePostType::entry_for_slug($slug, 'any')`. `StoredVideos::register()` and `player_video()` (the filter) are **not** copied: the filter is gone. `StoredVideos` gets `public static function file_for(string $foldername, string $period): ?string` (the validated stored file name or null; the logic of `player_video()` without the `$file` fallback argument).

- [ ] **Step 1: Switch the references** of one class at a time in the harness (`\Zeitraffer\AgeStatus` -> `\F5\Webcams\AgeStatus`, and so on) and add the new checks: `StoredVideos::file_for` returns the stored name for a valid file, null for a missing file, an empty file, a symlink, a hidden name, a name with `/` or `\`, a name not ending in `.mp4`, a period outside the four, and null when there is no entry or no value. The checks named `the plugin answers f5_webcams_timelapse_*` and the like are removed with the filters in Task 3, not here.
- [ ] **Step 2: Run** `php harness-zeitraffer.php`. Expected: FAIL (class not found).
- [ ] **Step 3: Copy the five files**, change namespace and constants as listed, replace `player_video()` by `file_for()`, delete `StoredVideos::register()`. Nothing else changes; the security checks of `VideoActions` stay word for word.
- [ ] **Step 4: Run** both harnesses and `php -l` on the five files. Expected: all 52 old checks (plus the new ones) pass against the f5 copies; the mutant run (`PLUGIN_FILE` replaced by a copy without the listing/dir/symlink check in `VideoActions::remove`) still fails the hostile-request check; adapt the mutant to the f5 path.
- [ ] **Step 5: Ledger line, then stop.**

---

### Task 3: The player uses the entries directly (replaces the old Task 7)

**Files:**
- Modify: `frontend/f5-webcams/includes/class-timelapse.php`, `frontend/f5-webcams/includes/class-zeitraffer-shortcode.php` (renamed, see below), `frontend/f5-webcams/f5-webcams.php` (insert the seven `require_once` lines before `class-timelapse.php`, and rename the two existing shortcode lines; no hook is registered yet), `$HARNESS/harness.php`
- Rename (Julius's call, English names): `includes/class-zeitraffer-shortcode.php` -> `includes/class-timelapse-shortcode.php`, class `ZeitrafferShortcode` -> `TimelapseShortcode`. The shortcode tag `[zeitraffer]` and its attributes do not change, so existing pages keep working. Every reference is renamed with it: `f5-webcams.php` (line 51 `require_once`, line 90 `::register()`), the comment in the player section of `assets/css/f5-webcams.css`, `TIMELAPSE-PLAYER-CHANGES.md`, `docs/wordpress.md`, and the `\F5\Webcams\ZeitrafferShortcode` calls in `harness.php`. A check in the harness asserts that the class `ZeitrafferShortcode` no longer exists and the tag `zeitraffer` is still registered.

**Interfaces:**
- Consumes: `TimelapsePostType::is_visible/notice/texts`, `StoredVideos::file_for`, `VideoFiles::newest_valid/folder_for_slug/base_dir`. The classes must be loaded as soon as `Timelapse` calls them, because Docker mounts the f5 folder live: loading a class registers nothing, so the Zeitraffer plugin still owns the type, box and scan until Task 4.
- Produces: `Timelapse::latest_video(string $foldername, string $period): ?string` keeps its signature and returns the same absolute path. Order: empty folder or period outside `periods()` -> null; folder confined with `PathValidator::resolve_within_base` (as today); `StoredVideos::file_for($foldername, $period)` when it names a valid file -> that path; else `VideoFiles::newest_valid(...)` -> that path; else null. `Timelapse::folder_for_slug()` delegates to `VideoFiles::folder_for_slug()`; `Timelapse::base_dir()` delegates to `VideoFiles::base_dir()`. `Timelapse::camera_texts()` is removed; `render()` and `ZeitrafferShortcode::render()` call `TimelapsePostType::is_visible()`, `notice()` and `texts()`. The filters `f5_webcams_show_timelapse`, `f5_webcams_timelapse_notice`, `f5_webcams_timelapse_texts` and the never-applied `f5_webcams_timelapse_video` are gone; the docblocks that describe them go with them.

- [ ] **Step 1: Write the failing checks** in `harness.php` (stubs added: `get_posts`, `get_post_meta`, `get_post_status`, `current_user_can`, `WP_Post`, a scenario helper that puts a published entry with empty excerpt into the stub store): (a) all 10 baseline scenarios render byte-identical HTML when the camera has a published entry with no title and no excerpt; (b) a camera without an entry renders `''` for a visitor and the player with the editor note when `current_user_can` is true; (c) a draft entry behaves the same as no entry for a visitor; (d) a stored file that is not the newest is the one the player uses; (e) stored file deleted, emptied, replaced by a symlink, named `../x.mp4`, hidden: the player uses the newest valid file; (f) the folder `Hafen.Nord` with the entry slug that the real `sanitize_key('Hafen.Nord')` gives, stored file found; (g) the webcam page falls back to the entry's excerpt as description when the webcam has none; the shortcode attributes still win over the entry's texts; (h) `latest_video` returns null for `''`, for `'../x'` and for an unknown period.
- [ ] **Step 2: Run** `php harness.php check`. Expected: FAIL on (b)-(g); (a) shows whether the baseline survives.
- [ ] **Step 3: Implement** the changes above in the two files. Keep the markup of `render_player()` untouched.
- [ ] **Step 4: Run** `php harness.php check` and `php harness-zeitraffer.php`, then `harness.php dump <scenario>` for all 10 and diff against `baseline/`. Expected: all green, 0 differences. Every difference is ledgered as a ruling (expected only where a baseline scenario holds an empty or symlinked mp4).
- [ ] **Step 5: `php -l`** on both files, then `node --test tests/frontend/player.test.js` (8 pass). Update `TIMELAPSE-PLAYER-CHANGES.md`: the filter list becomes "none; visibility, note and texts come from the camera entries of this plugin", and describe the stored-file rule.
- [ ] **Step 6: Ledger line, then stop.** Docker keeps working with the Zeitraffer plugin still active: f5 now reads the same slug and meta the old plugin writes, and the new classes only sit loaded. Julius may reload a webcam page and a `[zeitraffer]` page to see that nothing changed.

---

### Task 4: The switch (wiring, deactivation, retirement)

**Files:**
- Modify: `frontend/f5-webcams/f5-webcams.php` (insert lines only, no other line touched)
- Modify: `$HARNESS/harness.php` or `harness-zeitraffer.php` (a wiring check, below)
- Later, only with Julius's yes: delete `frontend/zeitraffer/`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: in `f5-webcams.php` (the `require_once` lines are already there from Task 3) `TimelapsePostType::register(); StatusBox::register(); VideoActions::register(); Scanner::register();` next to the other `::register()` calls; `register_deactivation_hook(F5_WEBCAMS_PLUGIN_FILE, [Scanner::class, 'unschedule']);` as a second hook next to the `Cron` one (`Cron` is not edited).

- [ ] **Step 1: Write the failing check** (offline wiring): load `f5-webcams.php` in the f5 harness (or a small copy of its require/register block) and assert the recorded calls contain the four registrations and the deactivation callback `Scanner::unschedule`, and that no call registers a hook named `f5_webcams_show_timelapse`, `_notice`, `_texts` or `_video`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Insert the lines.** `php -l f5-webcams.php`.
- [ ] **Step 4: Run** both harnesses and the baseline diff again. Expected: green, 0 differences.
- [ ] **Step 5: Hand-over for Julius, in this order, one command per block, labelled:** (1) make the zip of `frontend/` if not done; (2) in Docker, **deactivate the Zeitraffer plugin first**, then reload; (3) the checklist of the status plan's Docker check (list unchanged, box with four rows, "Jetzt prüfen", draft -> delete part, delete one/all, published shows none), plus: the type and its entries are still there with the same labels, the sync button works, a webcam page and `[zeitraffer camera="..."]` show the player, a camera set to Entwurf is hidden for a logged-out visitor, the scan still runs (`Jetzt prüfen`, then the wp-cron event `zeitraffer_scan` exists once, not twice).
- [ ] **Step 6: Ledger line, then stop.** After Julius's "works": ask once whether `frontend/zeitraffer/` may be deleted; do not delete without that answer.

---

### Task 5: Docs, memory, final verification and review

**Files:**
- Modify: `docs/wordpress.md`, `README.md` (the paragraph), `frontend/f5-webcams/TIMELAPSE-PLAYER-CHANGES.md` (if Task 3 left anything), memory notes.

- [ ] **Step 1: Rewrite `docs/wordpress.md`** for one plugin: install (only F5 Webcams), the rollout order (deactivate "Zeitraffer", update F5 Webcams, then remove the old plugin), where the post type, box, scanner and player live (file list), the removed filters, the unchanged slug/meta/cron names. German, like the rest. Update the README paragraph. Hand Julius a suggested paragraph for f5's CLAUDE.md "Structure" list (not edited by me).
- [ ] **Step 2: Run everything:** both harnesses, `php -l` on every touched PHP file, the 10 baseline diffs, `node --test tests/frontend/player.test.js`, `git status --short` in both repos with every file not part of this work named.
- [ ] **Step 3: Final whole-branch review** by a fresh reviewer (Agent, most capable model) with this plan's Review Focus verbatim and the ledger's `Ruling:` lines; re-grade the findings; Critical and Important get one fix pass, each with a check that failed first; minors go to the ledger.
- [ ] **Step 4: Update memory** (`project-timelapse-status-page.md`, `project-timelapse-wordpress-plugin.md`, `MEMORY.md`), mark the spec "built", and send Julius the final message with "Rulings I made" and "Deferred minors". No commit.
