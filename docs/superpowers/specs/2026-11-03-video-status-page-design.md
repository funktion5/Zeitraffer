# Video status page: see what is on the website, and clean up

Status: built (2026-11-03) and merged into the f5-webcams plugin (2026-11-04, see the integration plan). Written on 2026-11-03 after a conversation with Julius; where a line says
"decided" it is his decision (or his colleague's request that he accepted), where it says "my call" it is a
default he can overrule.

## Intent

The Zeitraffer videos reach the website by a copy from the VPS (not built yet, see "Context"). When
something goes wrong (a camera stops, a night is skipped, a transfer fails), the people who run the
website have no way to see it: they have to look into folders. They already have this for the live webcam
images: the admin page "Webcams > Status prüfen" (`frontend/f5-webcams/lib/check-webcams.php`) lists
every webcam with its folder, newest file, the file stored in the database, its age and a status. The
colleague who maintains that plugin asked for the same for the Zeitraffer videos, so they can maintain
the site without asking Julius.

A second need comes from the same colleague: when a camera is set to draft, its videos must be
deletable from the admin, so that nobody can reach them by their plain URL.

## Context (what exists)

- **Videos on the website:** `<uploads>/zeitraffer/<folder>/<period>/<folder>_<YYYY-MM-DD>.mp4`, period
  `daily`, `weekly`, `monthly` or `yearly`. The pipeline on the VPS rebuilds all four types for every
  camera every night at 02:00 (daily = yesterday; a camera with too many missing days skips monthly and
  yearly that night). The copy to the website is planned as a push from the VPS right after the nightly
  run, sending only the newest valid file per camera and period; the website keeps the newest and the
  previous file. A camera on the pipeline's `ignored_cameras` list gets no videos at all.
- **Zeitraffer plugin** (`frontend/zeitraffer/plugin-timelapse.php`, Julius's, procedural, functions
  `tl_timelapse_*`, German UI texts, 2-space indent, double quotes): a camera entry post type
  `zeitraffer_camera` (not public, status draft or publish, one entry per video folder, title and excerpt
  = display name and scene text, protected meta `_zeitraffer_folder` = `sanitize_key(folder)`), a sync
  button that creates draft entries from the folders, and three filters answering the f5-webcams plugin
  (`f5_webcams_show_timelapse`, `f5_webcams_timelapse_notice`, `f5_webcams_timelapse_texts`). Helpers
  that exist: `tl_timelapse_get_cameras()`, `tl_timelapse_latest_video()`, `tl_timelapse_camera_entry()`,
  `tl_timelapse_videos_dir()`.
- **f5-webcams plugin** (`frontend/f5-webcams/`, a colleague's separate repository): the player
  (`includes/class-timelapse.php`, `render_player()`) and the `[zeitraffer]` shortcode. It finds the
  newest video itself with `Timelapse::latest_video($foldername, $period)` (a `glob`, newest by file
  name, folder confined by `PathValidator`).
- **The model for the page:** `check-webcams.php`: an admin submenu page, a sortable table, status
  badges (ok, warning, error), a "run now" button protected by a nonce, capability `manage_options`.

## Goals

- A box "Videos" on the edit screen of every camera entry (Zeitraffer > Alle Kameras > the camera, where
  the description field is and where the camera is set to draft). It lists, for each of the camera's
  four periods: the folder path, the newest video on disk, the value stored in the database, how old the
  video is, and a status text ("Aktuell", "Älter als ...", "Kein Video"). Decided by Julius, who looked
  at the existing camera list and the edit screen and wants it exactly there.
- The values are stored in the WordPress database by a scan, and the players use the stored value (see
  "Decisions"). Decided: the colleague wants the "file in the database" like the webcam page has.
- For a camera whose entry is not published, the box lists its files with delete buttons. Decided.
- Everything in the box is German, escaped, and safe to use (see "Constraints").

## Non-goals

- **The camera list stays exactly as it is** (columns Titel, Datum, Ordner, and the "Kameras aus Ordnern
  anlegen" button): no status column and no separate overview page across all cameras. Decided by Julius.
- No ACF fields (see "Decisions"), no REST route or token (the push job could trigger the scan later;
  not now), no change to the pipeline or the VPS, no playing of videos in the admin, no automatic
  deletion, no deletion of a published camera's files, no per-period thresholds.

## Anti-goals

- A delete button that can remove anything but `.mp4` files in the four period folders of one camera.
- A status box that says "Aktuell" while the player would show nothing, or the other way round.
- A slower public site: the scan runs in the background and from the admin screen, never because a
  visitor loads a page.

## Decisions

Decided by Julius (and the colleague's requests he accepted):

- **Two plugins stay.** The status box, the scan and the delete tool live in the Zeitraffer plugin. The
  player and shortcode stay in f5-webcams. Everything f5-webcams needs from the Zeitraffer plugin goes
  through filters.
- **Stored values, read by the players** ("option B"): a scan stores the newest file per camera and
  period in the database; the box compares it with what is on disk; the players use the stored file and
  fall back to looking in the folder when the value is missing or the file is gone.
- **Draft cameras:** the box shows their files and lets an admin delete them, so nobody can open them by
  URL. Julius knows the push can bring files back unless the camera is also on the pipeline's
  `ignored_cameras`; the box should say so.
- **Where it sits:** in the camera's edit screen, in the main column under the description field, as a
  meta box registered for the existing post type `zeitraffer_camera`. The camera list is not touched.

My calls (Julius can overrule):

- **Storage is plain post meta on the camera entry, not ACF.** ACF only defines and displays fields; the
  webcam values are post meta underneath. The camera entries have no ACF field group, and adding fields
  would change the live field group (the colleague's) with eight fields per camera and make the plugin
  depend on ACF. Protected meta (leading underscore) like `_zeitraffer_folder`: one meta key per period,
  `_zeitraffer_video_<period>`, holding `file` (name only), `date` (the day in the file name, `Y-m-d`, or
  empty) and `checked` (Unix time of the scan). The meta is written only when the file changes, so a scan
  that finds nothing new causes no database writes.
- **The scan** runs by WP-Cron every 10 minutes (self-healing schedule, cleared on deactivation, the
  pattern of f5's `Cron` class) and by a "Jetzt prüfen" button in the box (POST, nonce, capability; it
  scans that one camera). The scheduled scan covers every camera entry, drafts included. "Newest" means the newest by file name among regular,
  non-empty, non-hidden `.mp4` files that are not symlinks, directly in the period folder (the same rule
  as the VPS delivery list). **One rule everywhere:** the scan, the status page, the Zeitraffer plugin's
  `tl_timelapse_latest_video()` and the player's fallback in f5 (`Timelapse::latest_video()`) all use it,
  so the page never calls a video current that the player would not show, or the reverse. Today both
  lookups are a plain `glob` that would also take a 0-byte file or a symlink; they are tightened as part
  of this work. If the folder or the video is gone, the stored value for that period is removed.
- **Age comes from the date in the file name, not from the file's modification time.** The webcam
  status page already does the same for images (`Formatting::capture_age_seconds()` says why: a
  transfer refreshes the modification time, so a stuck camera would look fresh). Every video is named
  `<folder>_<YYYY-MM-DD>` with the last day it covers, and all four types are rebuilt nightly, so one
  rule fits all: "Aktuell" when that date is yesterday or later (in the site's timezone), "Älter als 24
  Stunden" (and the age in days) when it is earlier. Until 06:00 site time a file dated the day before
  yesterday still counts as "Aktuell", because the nightly run and the push are not through yet. "Kein
  Video" when there is none, "Datei fehlt" when the database names a file that is not on disk. The
  modification time is only the fallback for a name without a date. A period that legitimately was
  skipped (too many missing days) will show as old; that is information, not an error.
- **Layout of the box:** a table with one row per period (daily, weekly, monthly, yearly), columns:
  period, folder path, newest file on disk, stored value, age, status. Below it the "Jetzt prüfen"
  button. For a camera whose **saved** status is not published, the box also lists every `.mp4` of the
  four folders with a "Löschen" button each and one "Alle Dateien löschen" button, and a note that the
  push brings the files back unless the camera is on `ignored_cameras`. The delete part therefore
  appears only after the camera has been saved as a draft; the server checks the saved status again
  before it deletes (see "Delete"). A folder that has videos but no camera entry has no edit screen; the
  existing sync button creates its entry.
- **Capability:** `edit_others_posts` for the box and the scan, as the existing sync button; the delete
  needs the same plus the camera being not published.
- **Delete covers every `.mp4` in the four period folders, not just the newest.** The website keeps the
  newest and the previous file, and a leftover previous file would still be reachable by its URL. For a
  camera whose entry is not published the box therefore lists all of its files, read from the disk, not
  only the stored value. A delete is a POST with a nonce and a confirmation, for one file or for "all
  files of this camera". The browser sends the camera, the period and a bare file name; it never sends
  a path. The server re-checks everything: the entry is not published, it lists the period folder
  itself and accepts the name only if it matches a file found there exactly, the file is a regular
  `.mp4` and not a symlink, and the folder is inside `<uploads>/zeitraffer/<folder>/<period>/`. Then it
  deletes and re-scans that camera, which clears the stored value if no file is left.
- **How the players read the stored value:** a new filter from the Zeitraffer plugin
  (`f5_webcams_timelapse_video`, folder and period in, file name out). In f5, `Timelapse::latest_video()`
  asks it first and checks that the named file exists inside the confined folder; otherwise it keeps its
  tightened lookup (see above). This is a small change in the colleague's class, so it comes last. It is
  made directly in the f5 working copy on Julius's branch, as the earlier steps were, and Julius hands it
  over; until the colleague has it, the Zeitraffer side degrades silently: the page works and the stored
  value is only informational.
- **The player can lag behind the disk, and that is accepted.** After the nightly push the player keeps
  showing the previous video until the next scan, normally within ten minutes (WP-Cron runs when
  visitors load pages, so on a quiet site it can take longer). The box shows both the file on disk and
  the stored one; when they differ it says so ("Datenbank veraltet") and the "Jetzt prüfen" button
  fixes it. The status text and the age are always those of the file on disk. A later trigger
  from the push job (a token route like f5's `/run` for images) would shorten the lag; not now.

## Constraints

- PHP syntax that runs on 8.0 (the live version is unknown; the plugin header says 8.4), no new
  dependencies, no build step, no JavaScript: the box is plain server-rendered HTML with forms.
- Escape every output; every write has a nonce and a capability check; no raw SQL (post meta APIs only);
  path confinement for everything touching files; no `@` error suppression; nothing personal is stored
  (file names only).
- Follow the plugin's style (procedural `tl_timelapse_*` functions, German texts). New code may go into
  new files that the plugin file requires.
- The Zeitraffer plugin must keep working when f5-webcams is off, and f5-webcams when the Zeitraffer
  plugin is off (then the players show for every camera with videos, as today).
- Julius commits; nothing is pushed. Tests come first (see "How it is checked").

## How it is checked

No PHP test setup exists. The method used in the last steps: an offline harness (a PHP script that loads
the real plugin file with simple stand-ins for the WordPress functions and fake video folders, test first,
red then green), plus Julius's check in the Docker WordPress. The harness is a scratch file; whether it
moves into the repository is Julius's call.

## Left to the builder

File layout inside the plugin, function names, the exact German wording of labels and notices, column
widths, how the delete confirmation looks, how to split the work into steps, and how to stub WordPress in
the harness.

## If the camera post type is changed later

Julius may want to change how the cameras are kept (the post type `zeitraffer_camera`). Everything that
depends on it is in one file, `frontend/zeitraffer/plugin-timelapse.php`, as of 2026-11-03:

- the post type: `TL_TIMELAPSE_POST_TYPE`, `tl_timelapse_register_post_type()`; the meta key
  `TL_TIMELAPSE_FOLDER_META` (`_zeitraffer_folder` = `sanitize_key(folder)`);
- the lookup every other part uses: `tl_timelapse_camera_entry($slug, $status)`;
- the camera list: the "Ordner" column (`tl_timelapse_list_columns()`, `tl_timelapse_list_column_content()`)
  and the sync button and handler (`tl_timelapse_sync_form()`, `tl_timelapse_handle_sync()`, which creates
  draft entries from the video folders);
- the side box "Zeitraffer" on the edit screen (`tl_timelapse_add_meta_box()`,
  `tl_timelapse_render_meta_box()`), and, once built, the "Videos" box, the scan and the stored meta
  `_zeitraffer_video_<period>`;
- the filters that answer the f5-webcams plugin: `f5_webcams_show_timelapse`,
  `f5_webcams_timelapse_notice`, `f5_webcams_timelapse_texts` and, once built, `f5_webcams_timelapse_video`.

The f5-webcams plugin knows nothing about the post type, only the filters. Replacing the post type means
re-pointing `tl_timelapse_camera_entry()` and the box, and keeping the filters' contract. One alternative
was mentioned: since every video camera is also a webcam post (the folder names match), a field on the
`webcams` post could replace the entries; that touches the colleague's ACF field group and was not chosen.
