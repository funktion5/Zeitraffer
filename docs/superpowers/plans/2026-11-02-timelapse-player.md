# Zeitraffer Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One timelapse player, with its own control bar, joined tab strip and a look that inherits the site, in both the Zeitraffer plugin and the f5-webcams plugin.

**Architecture:** The Zeitraffer plugin's `assets/script.js` and `assets/style.css` are the master; the f5 plugin carries byte-identical copies. Both PHP renderers print one shared markup contract. The script builds the control bar on top of `<video controls>` and removes the native controls only after the bar exists and the browser supports CSS nesting. The two helpers that are easy to get wrong (time text, frame step) are pure functions with Node tests; everything else is checked by hand in Docker.

**Tech Stack:** PHP (WordPress plugins), vanilla JavaScript, modern CSS with native nesting, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-02-timelapse-player-design.md`

## Global Constraints

- No `var` in JavaScript: `const` and `let` only. No libraries, no build step, no CDN, nothing stored in the browser.
- Modern CSS: custom properties, native nesting where it reads cleaner (note: native nesting cannot concatenate a suffix like `&-name`, so nest descendant selectors), `aspect-ratio`, `gap`, `:focus-visible`.
- Shared JS and CSS use the master's style: tabs, double quotes, no spaces inside parentheses.
- f5 PHP must run on PHP 8.0+: no 8.4-only syntax (for example no `new Foo()->bar()`).
- Frame rates: daily 10, weekly 10, monthly 20, yearly 20 fps (config `timelapse.daily_framerate`, `monthly_framerate`, `yearly_framerate`; weekly uses the daily rate, see `src/jobs/weekly.py`). Constants are commented as depending on the pipeline config.
- No hard-coded pixel sizes in CSS: sizes follow the font (`rem`, `em`), layout comes from flex, grid and margins, hairlines are `thin`, and any size shared by several controls is one custom property (`--timelapse-target-size: 2.75rem`, which is 44 px at the default font size). Media query breakpoints are in `rem`.
- Speeds: 0.5x, 1x, 2x only. Touch targets at least `--timelapse-target-size`. Accent: `--timelapse-accent` default `#1f2937` with white text, to be pointed at an Avada variable later.
- Visitor text is German with formal "Sie"; error text: "Das Video konnte nicht geladen werden. Bitte laden Sie die Seite neu oder versuchen Sie es später noch einmal."
- English identifiers; "zeitraffer" as a name becomes "timelapse". Stay as they are: shortcode tag `[zeitraffer]`, post type slug, meta key `_zeitraffer_folder`, admin action and nonce `zeitraffer_sync`, the folders `uploads/zeitraffer/` and the plugin folders.
- Keep it small (YAGNI): no test scaffolding beyond `tests/frontend/player.test.js`; the PHP markup is checked with a throwaway offline replay script (scratchpad, not committed). CI does not run Node, so `node --test` runs locally unless Julius adds a CI step.
- `src/` is not touched. f5 edits only in the files listed in the spec's "Files" section. f5's `CLAUDE.md` and `README.md` are not edited.
- **Hand-over after every task** (Julius commits; Claude runs no pytest, ruff or git-state commands): offline checks only (`php -l`, `node --check`, `node --test`, the offline replay), write a message file to the scratchpad, run `git status --short` and name any file not part of the task, give the Docker check steps one per block, then stop for Julius's check and commit. No Claude trailer in commit messages.

## Review Focus

- Metadata not loaded yet, so the duration is `NaN` or `Infinity`: no "NaN" in the time text or scrubber (Task 1 tests, Task 4 init on `loadedmetadata`).
- A tab switch while playing at 2x or with loop on: the new video keeps speed and loop and starts paused (Task 6).
- Arrow keys and Space on a focused scrubber or button keep their native behaviour; frame step and play/pause by key only when the viewport itself has focus (Task 5).
- Fullscreen: the bar is inside the fullscreen element, the label updates, and no button appears where fullscreen is unsupported (Task 6).
- Forced-colors and reduced-motion: controls stay visible when `text-shadow` is dropped, and nothing animates (Task 4).

## Shared markup contract

Root `div.timelapse` containing, in order: optional `p.timelapse-notice`; `h2.timelapse-heading` with `span.timelapse-date[aria-live=polite]`; `nav.timelapse-tabs[aria-label=Zeitraum]` with links carrying `data-src`, `data-label`, `data-date`, `data-fps`, and `aria-current=true` on the active one; `div.timelapse-viewport` holding `video.timelapse-video[controls playsinline preload=metadata aria-describedby]`; `div.timelapse-caption` with a unique id (`timelapse-caption-<n>`, a per-request counter). The script finds everything by class inside its own root. The bar (built by JS, appended to the viewport) uses `timelapse-bar`, `timelapse-seek` (range input), `timelapse-time`, `timelapse-play`, `timelapse-step-back`, `timelapse-step-forward`, `timelapse-speeds` (buttons `timelapse-speed[data-speed]`), `timelapse-loop`, `timelapse-fullscreen`, and `timelapse-error` (`role=alert`).

## File Structure

- `frontend/zeitraffer/assets/script.js`, `assets/style.css`: master player. `plugin-timelapse.php`: shortcode renderer.
- `frontend/f5-webcams/assets/js/timelapse.js`, `assets/css/timelapse.css`: identical copies. `includes/class-timelapse.php`, `includes/class-assets.php`, `TIMELAPSE-PLAYER-CHANGES.md`.
- `tests/frontend/player.test.js`: the only committed test.
- `docs/wordpress.md` (German).

---

### Task 1: Time and frame-step helpers with Node tests

**Files:**
- Create: `tests/frontend/player.test.js`
- Modify: `frontend/zeitraffer/assets/script.js` (add helpers and a guarded export; the existing tab switching keeps working)

**Interfaces:**
- Produces, exported via `module.exports` when `module` exists: `formatTime(seconds: number): string`, `valueText(current: number, duration: number): string`, `stepTime(current: number, direction: 1 | -1, fps: number, duration: number): number`.

- [ ] **Step 1: Write the failing tests** in `tests/frontend/player.test.js` (`node:test`, `node:assert`, an `approx(a, b)` helper with 1e-9 tolerance): `formatTime` gives "0:00" for 0, "0:07" for 7.4, "1:01" for 61, "59:59" for 3599.9, and "0:00" for `NaN`, `Infinity` and -1; `valueText(7, 12)` is "0:07 von 0:12" and `valueText(NaN, NaN)` is "0:00 von 0:00"; `stepTime` targets the middle of a frame: `(0, 1, 10, 12)` is 0.15, `(0.15, 1, 10, 12)` is 0.25, `(0.25, -1, 10, 12)` is 0.15, `(0.3, 1, 20, 12)` is 0.375, clamped to `[0.5/fps, duration - 0.5/fps]` so `(0, -1, 10, 12)` is 0.05 and `(11.95, 1, 10, 12)` is 11.95, and an invalid fps (0, `NaN`) returns `current` unchanged.
- [ ] **Step 2: Run** `node --test tests/frontend/player.test.js`. Expected: FAIL (the exports do not exist).
- [ ] **Step 3: Implement** the helpers in `script.js` as top-level `const` functions; `stepTime` uses `Math.floor(current * fps + 1e-6)` as the frame index and returns `(index + direction + 0.5) / fps`, clamped. Guard the export with `typeof module !== "undefined" && module.exports`, and wrap the existing DOM code so it only runs when `document` exists.
- [ ] **Step 4: Run** the tests. Expected: PASS. Run `node --check frontend/zeitraffer/assets/script.js`.
- [ ] **Step 5: Hand over** (see Global Constraints). Julius checks that the shortcode page in Docker still switches tabs, then commits.

### Task 2: Shared names and frame-rate data (Zeitraffer plugin)

**Files:**
- Modify: `frontend/zeitraffer/plugin-timelapse.php`, `frontend/zeitraffer/assets/style.css`, `frontend/zeitraffer/assets/script.js` (selectors only)

**Interfaces:**
- Produces: the Shared markup contract (above); `const TL_TIMELAPSE_FRAME_RATES = ["daily" => 10, "weekly" => 10, "monthly" => 20, "yearly" => 20]` with its comment.

- [ ] **Step 1: Write a throwaway offline replay** in the scratchpad (not committed): load `plugin-timelapse.php` with stand-ins for the WordPress functions it calls and a fixture of fake `.mp4` files for the four periods, render the shortcode, and print: the class and id lists, each tab's `data-fps`, whether the video has `controls`, and the caption ids of two renders. Run it. Expected: it shows the old `zeitraffer_...` names and no `data-fps`.
- [ ] **Step 2: Implement** the rename in `plugin-timelapse.php` per the contract, add `data-fps` to the tab links from `TL_TIMELAPSE_FRAME_RATES`, add the viewport wrapper and the per-request caption id counter, and rename the internal identifiers (script and style handle, meta box id, list column key, the `zeitraffer_synced` query argument). Leave the names listed as staying in Global Constraints. The comment on the constant says the rates must match `timelapse.*_framerate` in `config/config.json` and that weekly uses the daily rate.
- [ ] **Step 3: Update the selectors** in `style.css` and `script.js` to the new classes; behaviour unchanged.
- [ ] **Step 4: Verify.** The replay shows the contract names, no "zeitraffer" in any class or id, `data-fps` 10, 10, 20, 20, `controls` present, two different caption ids, and a title with `<img onerror>` escaped. `php -l`, `node --check`. Hand over; Julius checks the tabs in Docker.

### Task 3: Tab strip and viewport CSS

**Files:**
- Modify: `frontend/zeitraffer/assets/style.css`

**Interfaces:**
- Consumes: the Shared markup contract. Produces: `--timelapse-accent`, `--timelapse-on-accent` on `.timelapse`.

- [ ] **Step 1: Rewrite the CSS** with native nesting under `.timelapse`. `font: inherit; color: inherit`; the tabs as one joined strip (`display: flex`, a `currentColor` border, divided parts, `min-block-size: 44px`), the active part (`[aria-current]`) filled with the accent and bold, a visible `:focus-visible` outline; under `30rem` the strip becomes a 2x2 grid. `.timelapse-viewport` is `position: relative` with the video at 16:9 and full width; calm styles for caption and notice.
- [ ] **Step 2: Verify offline:** the file uses no suffix nesting and every `var(--...)` is defined. No unit test exists for CSS. Hand over; Julius checks the shortcode page at about 1200 px and 320 px, with the active tab visible without colour.

### Task 4: Control bar core

**Files:**
- Modify: `frontend/zeitraffer/assets/script.js`, `frontend/zeitraffer/assets/style.css`

**Interfaces:**
- Consumes: Task 1 helpers. Produces: `initPlayer(root: HTMLElement): void`, a `LABELS` object holding every German string, and the bar markup from the contract (play, seek, time).

- [ ] **Step 1: Implement** `initPlayer`: return early (native controls stay) if `!CSS.supports("selector(&)")`; build the bar (buttons are `<button type="button">` with German `aria-label` from `LABELS` and inline SVG icons marked `aria-hidden`); set the scrubber's `max` on `loadedmetadata` and `durationchange`; on `timeupdate` update the range value, `.timelapse-time` ("0:07 / 0:12" via `formatTime`) and `aria-valuetext` via `valueText`; toggle the play button's label and state on `play` and `pause`; clicking the picture toggles play; remove the `controls` attribute only after the bar is built. Boot: `document.querySelectorAll(".timelapse").forEach(initPlayer)`. A tab click replaces the source as before and resets the bar's time display.
- [ ] **Step 2: Bar CSS.** Overlay at the lower edge of the viewport, no background, grid `1fr auto 1fr` for the second row, the scrubber and time on the first row; white controls with a dark halo (`text-shadow`, `filter: drop-shadow` for the icons, a dark outline on the scrubber track); the play button larger than the others; every control at least 44 px; under `@media (forced-colors: active)` give controls a visible border; nothing animates.
- [ ] **Step 3: Verify offline:** `node --check`, `node --test tests/frontend/*.test.js`. Hand over; Julius checks in Docker: the bar appears, play/pause, mouse and keyboard scrubbing, the time text, no "NaN" before the video loads, the native controls come back with JavaScript disabled, and the halo on a bright and a dark frame.

### Task 5: Frame step and keyboard

**Files:**
- Modify: `frontend/zeitraffer/assets/script.js`, `frontend/zeitraffer/assets/style.css`

- [ ] **Step 1: Wire the buttons.** The step buttons call `video.pause()` and set `video.currentTime = stepTime(video.currentTime, direction, fps, video.duration)`; `fps` is `Number(...)` of the active tab link's `data-fps`, and if it is not greater than 0 both step buttons get `hidden`.
- [ ] **Step 2: Keyboard.** The viewport gets `tabindex="0"`, `role="group"` and a German `aria-label`. A `keydown` handler acts only when `event.target` is the viewport itself: Space toggles play, ArrowLeft and ArrowRight step one frame, all with `preventDefault`. Events from the scrubber or buttons are ignored, so their native behaviour stays.
- [ ] **Step 3: Verify and hand over.** `node --check`. Julius checks: stepping moves exactly one frame at 10 and at 20 fps, arrows on the scrubber still scrub, Space on a button does not double-trigger.

### Task 6: Speed, loop, fullscreen, error, address sync

**Files:**
- Modify: `frontend/zeitraffer/assets/script.js`, `frontend/zeitraffer/assets/style.css`

- [ ] **Step 1: Speed.** Each `.timelapse-speed[data-speed]` (0.5, 1, 2) sets `video.playbackRate` and `video.defaultPlaybackRate` and updates `aria-pressed` on the group; a tab switch keeps the speed because the new video loads with the default rate. On narrow screens the three buttons simply shrink and wrap.
- [ ] **Step 2: Loop** sets `video.loop` with `aria-pressed`; a tab switch keeps it.
- [ ] **Step 3: Fullscreen** requests fullscreen on the viewport (so the bar stays inside), flips the label between enter and exit on `fullscreenchange`, and sets `hidden` on the button when `requestFullscreen` is missing.
- [ ] **Step 4: Error.** A `video` `error` event shows `.timelapse-error` (`role="alert"`) with `LABELS.error`; a new source clears it.
- [ ] **Step 5: Address sync and start guard.** `history.replaceState` runs only for the first `.timelapse` on the page; `initPlayer` sets `root.dataset.timelapseReady` and returns if it is already set.
- [ ] **Step 6: Verify and hand over.** `node --check`. Julius checks: speeds and loop; a tab switch at 2x with loop on (still 2x and loop, starts paused); fullscreen with the bar usable; renaming one video file in Docker shows the message instead of a black box; two shortcodes on one page work independently and only the first changes the address.

### Task 7: f5 markup and frame-rate data

**Files:**
- Modify: `frontend/f5-webcams/includes/class-timelapse.php`

**Interfaces:**
- Produces: `Timelapse::FRAME_RATES` (same values and comment as the plugin constant); `Timelapse::render(int $post_id, string $foldername, string $title): string` keeps its signature and both filters.

- [ ] **Step 1: Run the offline replay** (the f5 version of the Task 2 script, in the scratchpad) against the f5 class. Expected: it still shows `f5-webcams-timelapse-*` names and no `data-fps`.
- [ ] **Step 2: Implement** the contract names, the viewport wrapper, `data-fps` per tab from `FRAME_RATES`, and the per-request caption id counter.
- [ ] **Step 3: Verify.** The replay prints the same class set as the Zeitraffer plugin's; `php -l`; no PHP 8.1+ only syntax. Hand over (the f5 files are committed in the f5 repository, mixed with the colleague's pending changes, so name the files).

### Task 8: f5 assets, cache-busting, change notes

**Files:**
- Modify: `frontend/zeitraffer/assets/script.js`, `frontend/zeitraffer/assets/style.css` (header comment), `frontend/f5-webcams/assets/js/timelapse.js`, `frontend/f5-webcams/assets/css/timelapse.css`, `frontend/f5-webcams/includes/class-assets.php`, `frontend/f5-webcams/TIMELAPSE-PLAYER-CHANGES.md`

- [ ] **Step 1: Add the header comment** to both master files: the master lives in `frontend/zeitraffer/assets/`, is copied word for word to `frontend/f5-webcams/assets/js/timelapse.js` and `css/timelapse.css`, change it there first.
- [ ] **Step 2: Copy** the two master files over the f5 files, then run `diff frontend/zeitraffer/assets/script.js frontend/f5-webcams/assets/js/timelapse.js` and the same for the CSS pair. Expected: no output.
- [ ] **Step 3: Cache-busting.** In `class-assets.php` the two player handles use `filemtime()` of their file as the version, falling back to `F5_WEBCAMS_VERSION` if it returns false.
- [ ] **Step 4: Rewrite** `TIMELAPSE-PLAYER-CHANGES.md` (short, for a lazy developer): the new names, `data-fps`, the unchanged filters, the modification-time version, and the rule that the two asset files are copies of the Zeitraffer plugin's master, with the two `diff` commands.
- [ ] **Step 5: Verify.** `php -l`, `node --check`, `node --test tests/frontend/*.test.js`. Hand over; Julius checks the f5 webcam page in Docker.

### Task 9: Documentation and acceptance

**Files:**
- Modify: `docs/wordpress.md`

- [ ] **Step 1: Add a German section** `## Player: Bedienung und Bildrate` before `## Täglicher Betrieb`: the controls, the keyboard (Space, left and right arrow, only with focus on the player), the fallback to the native controls, the accent setting `--timelapse-accent`, the master-copy rule between the two plugins with the two `diff` commands, and the frame rates as constants that must match `timelapse.*_framerate` in `config/config.json` (weekly uses the daily rate).
- [ ] **Step 2: Acceptance pass for Julius** (nothing to code): both players look and behave the same; JavaScript off leaves native controls and tab links working; a broken video address shows the message; the halo is readable on real bright and dark frames; a keyboard-only pass and a 320 px screen work; two players on one page are independent; the constants are commented and documented.

### Task 10 (optional): Poster experiment in f5

**Files:**
- Modify: `frontend/f5-webcams/includes/class-timelapse.php`

- [ ] **Step 1: Add one clearly marked block:** a private `poster_url(int $post_id, string $foldername): string` that repeats the template's own lookup (sanitized `lastimage`, `PathValidator` against `uploads/webcams/`, `is_file`), and print the `poster` attribute on the video only when the URL is non-empty. This keeps `templates/single-webcams.php` untouched.
- [ ] **Step 2: Verify and hand over.** `php -l`; the offline replay shows `poster` only when a live image exists. Julius judges it in Docker and removes the block if he does not like it.
