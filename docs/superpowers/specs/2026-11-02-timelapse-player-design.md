# Zeitraffer player: custom controls, tabs and look

Status: design, not built. Written on 2026-11-02 after a conversation with Julius; where a line says
"decided" it is his decision, where it says "my call" it is a default he can overrule.

## Intent

Today the Zeitraffer videos (last 24 hours, 7 days, 30 days, year) of a webcam are shown with the
browser's own `<video controls>` bar and a row of plain text links above it. It works, but it looks
foreign next to the company site (Avada), and a timelapse needs more than play and pause: people want
to slow it down to spot a bird or a boat, step through it one frame at a time, and loop it.

The goal is one player that looks like it belongs to the site, inherits the site's fonts and colours,
and has controls that suit a timelapse.

## Where it lives: two players

The same videos are shown in two places, and both get the new player.

- **Shortcode player**: the Zeitraffer plugin, `frontend/zeitraffer/` (`plugin-timelapse.php`,
  `assets/style.css`, `assets/script.js`), used with `[zeitraffer]` and by the editors' camera setup.
- **Webcam page player**: the f5-webcams plugin, `frontend/f5-webcams/` (`includes/class-timelapse.php`,
  `assets/js/timelapse.js`, `assets/css/timelapse.css`). It is a separate repository of a colleague, who
  merges Julius's changes by hand using `frontend/f5-webcams/TIMELAPSE-PLAYER-CHANGES.md`.

Each plugin must keep working without the other.

## Goals

- Both players look and behave the same, from one CSS file and one JavaScript file kept identical in
  both plugins.
- A control bar of our own, replacing the browser's: a scrubber with the time at its right end, a big
  play/pause button on the left, frame step back and forward in the middle, and speed (0.5x, 1x, 2x),
  loop and fullscreen on the right.
- The period tabs as a joined strip that fits the site.
- A short message when a video cannot be loaded.
- In the webcam page player, the webcam's live image as the video's poster (an experiment, see below).

## Non-goals

- Clock times on the scrubber ("14:35 Uhr"), a burned-in timestamp, hover thumbnails on the scrubber, or
  a "gestern / vorgestern" day picker. They need pipeline changes in `src/`, which stays untouched.
- Autoplay, saving a viewer's choices, a faster speed than 2x, picture-in-picture, download buttons.
- Renaming folders, such as `uploads/zeitraffer/` or the plugin folders.
- Changing Avada or its settings.

## Anti-goals (a failure even if everything technically works)

- Controls that cannot be read on a bright (noon sky) or a dark (dusk) frame.
- A player that does not play when JavaScript is off or the browser is old: the native controls must
  stay as the fallback.
- A second player on the same page breaking the first.
- Anything stored in the visitor's browser (consent under section 25 TDDDG would be needed).

## Decided

- **Overlay bar.** The bar sits over the lower edge of the picture, always visible, with no background
  block behind it. The controls are white with a soft dark halo (a thin dark glow around icons, text and
  the scrubber), not floating buttons.
- **Layout.** Top row: the scrubber, time at its right end. Below: play/pause big on the left, frame
  back and forward in the middle, speed / loop / fullscreen on the right.
- **Tabs.** A joined strip of four parts, the active part filled. They stay real links that work without
  JavaScript.
- **Both players, two identical copies.** The CSS and JS are the same file in both plugins. The Zeitraffer
  plugin's copy is the master; the f5 copy carries a comment "copied from the Zeitraffer plugin, change it
  there first", and a `diff` of the two must come out empty. For that, both PHP renderers use one shared
  set of element names (f5 currently uses `f5-webcams-timelapse-...`, the plugin `zeitraffer_...`).
- **Inherit the site.** The CSS inherits `font` and `color` from the theme and uses `currentColor` for
  borders and dividers. There is one accent setting (a CSS custom property) at the top of the file for the
  filled active tab, starting as a dark neutral with white text. Once Avada's own variable names are known
  it points at the matching variable. No Avada classes in our markup.
- **Modern CSS.** Custom properties, native nesting where it reads cleaner, `aspect-ratio`, `gap`,
  `:focus-visible`. No preprocessor and no build step.
- **JavaScript.** `const` and `let`, never `var`. No libraries.
- **Frame step needs the frame rate.** The player holds the pipeline's rates as constants per period:
  daily 10, weekly 10 (it uses the daily rate), monthly 20, yearly 20 frames per second. They come from
  `timelapse.daily_framerate`, `monthly_framerate` and `yearly_framerate` in `config/config.json`. They
  must be commented where they are defined, and documented in `docs/wordpress.md`, as depending on the
  pipeline config.
- **Poster.** The live webcam image as the poster, webcam page player only. Julius: "okayish, I would try
  that out", so it is an experiment that must be easy to remove.
- **Error message.** A short message when the video fails to load.
- **Cache-busting in f5.** The two player files in f5 use their file modification time as the version,
  as the Zeitraffer plugin already does, so nobody has to bump `F5_WEBCAMS_VERSION`. This needs one more
  edit in f5's `includes/class-assets.php`.
- **English identifiers.** Variables, functions, constants, CSS classes and ids, JavaScript names and
  script handles are in English; where the word "zeitraffer" is used as a name, it becomes "timelapse".
  The Zeitraffer plugin is new and not live, so there are no existing class names to stay compatible
  with. No folder is renamed (not `uploads/zeitraffer/`, not the plugin folders).

## My calls (Julius can overrule)

1. **The bar is built by JavaScript on top of `<video controls>`.** `controls` is removed only once the
   script has built the bar, and only if the browser supports CSS nesting (`CSS.supports('selector(&)')`).
   Otherwise the native controls stay.
2. **Scoped per player.** The script finds each player by a class and works inside it, so several players
   on one page do not clash (the old ids made that a known limit).
3. **Speed.** 0.5x, 1x and 2x only. The chosen speed survives a tab switch (a reload of the video resets
   it otherwise) and is kept only while the page is open.
4. **Keyboard, only while the player has focus.** Space plays and pauses, the left and right arrows step
   one frame (and pause first).
5. **Time label.** Plain video time, such as 0:07 / 0:12.
6. **Phone.** The three speeds collapse into one button that cycles through them, and the tabs become a
   2x2 block of the same joined parts.
7. **Error text.** "Das Video konnte nicht geladen werden. Bitte laden Sie die Seite neu oder versuchen Sie
   es später noch einmal." (formal "Sie", as it is public text).
8. **Touch targets** at least 44 px (WCAG 2.2 AA only requires 24 px).
9. **One code style for the shared JS and CSS.** The two plugins use different styles today (the Zeitraffer
   plugin: tabs, double quotes, no spaces inside parentheses; f5: tabs, single quotes, spaces inside
   parentheses). Identical files need one, so the master's style wins.
10. **Testing without a new dependency.** Pure helper functions (time formatting, frame step maths) are
    kept apart so Node's built-in `node --test` can run them; the rest is checked in the Docker site.
11. **Stored and public names stay.** The English renaming covers identifiers in the code. The shortcode
    tag `[zeitraffer]`, the post type slug, the meta key and the admin action names are stored or public
    names, not variables, so they are left as they are. Julius said "only variables and such"; if he wants
    them renamed too, the local test site's camera entries must be recreated.
12. **Frame rates are authoritative as constants.** The oldest and newest videos of three cameras on the
    VPS (BSV-Steinhude, SLSV, Uferstrasse) all match 10 / 10 / 20 / 20 fps. Older videos built earlier may
    differ, so the comment next to the constants says so.
13. **Two players on one page:** only the first player updates the address with `?period=`, so they never
    overwrite each other.
14. **Poster.** It is the same live image URL the webcam page already shows publicly. After a tab switch it
    shows again until the video plays; the builder may refine that.
15. **Small details left to the builder:** fullscreen where the browser does not support it (for example
    on iPhone, hide the button), and a guard against the script starting twice.

## Constraints

- Everything self-hosted: no CDN, no third-party request, no new dependency, no build step.
- Accessibility (BFSG, WCAG 2.2 AA): every control keyboard-operable with a German text label and a visible
  focus outline (Avada resets `:focus-visible`), the loop toggle announces its state, a speed change is
  announced, sufficient contrast on bright and dark frames, `prefers-reduced-motion` and forced-colors
  respected, usable at 320 px width.
- The f5 PHP must run on PHP 8.0 and newer (no 8.4-only syntax): the live PHP version is not known.
- `src/` (the pipeline) is not touched.
- The f5 plugin belongs to a colleague. Edits there are limited to the files in "Files" below, which
  Julius approves by approving this design; the plugin's own `CLAUDE.md` and `README.md` are not edited.
- German text for visitors; code comments in English, explaining why.

## Files

Zeitraffer plugin (`frontend/zeitraffer/`): `plugin-timelapse.php` (shared element names, frame-rate data,
tab markup), `assets/style.css`, `assets/script.js`. Documentation in `docs/wordpress.md`.

f5-webcams (`frontend/f5-webcams/`): `includes/class-timelapse.php` (shared element names, frame-rate
data, poster), `includes/class-assets.php` (file modification time as the version of the two player
files), `assets/js/timelapse.js` and `assets/css/timelapse.css` (identical copies of the master),
`TIMELAPSE-PLAYER-CHANGES.md` (updated for the colleague).

## Acceptance

- Both players show the same bar, tabs and look, and `diff` of the two JS files and of the two CSS files
  is empty.
- With JavaScript off, the native controls and the tab links still work.
- A broken video address shows the error message instead of a black box.
- Julius checks the controls on real bright and dark frames and the halo is readable on both.
- A keyboard-only pass through every control, and a 320 px wide screen, work.
- Two players on one page work independently.
- The frame-rate constants carry the comment and are documented.

## Open, not blocking

- Avada's variable names for the accent colour: read them on the live page (browser developer tools, the
  `<html>` element, variables starting with `--`). Until then the accent keeps its neutral default.
- The f5 colleague has not seen this yet; the change notes need updating once it is built.

## Left to the builder

Class and element names, the exact markup of the bar, how the scrubber is built (for example a range
input with a readable value text), how the tabs wrap on a phone, how the poster experiment is switched
off, the order of the steps and the test approach.
