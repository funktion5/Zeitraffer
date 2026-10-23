<?php
/*
 * Plugin Name: Zeitraffer
 */
declare(strict_types=1);

defined( 'ABSPATH' ) || exit;

// Videos live in <uploads>/zeitraffer. Asking WordPress for the uploads location keeps
// this correct if a host relocates uploads or serves them from another URL.
// $create_dir = false: do not create month folders just by looking.
function tl_timelapse_videos_dir(): string {
  $uploads = wp_upload_dir(null, false);
  return $uploads["basedir"] . "/zeitraffer";
}

function tl_timelapse_videos_url(string $path): string {
  $uploads = wp_upload_dir(null, false);
  return $uploads["baseurl"] . "/zeitraffer/" . $path;
}


function tl_timelapse_get_cameras(): array {
  $paths = glob(tl_timelapse_videos_dir() . "/*", GLOB_ONLYDIR);
  $cameras = [];

  foreach((array) $paths as $path) {
    $folder = basename($path);

    // Skip cameras without any video, e.g. folders that only hold empty period folders.
    $has_video = false;
    foreach (["daily", "weekly", "monthly", "yearly"] as $period) {
      if (tl_timelapse_latest_video($folder, $period)) {
        $has_video = true;
        break;
      }
    }

    if (!$has_video) {
      continue;
    }

    // Same sanitizer as the ?camera= lookup, otherwise folders with spaces, dots or
    // umlauts get a slug that the lookup can never match.
    $cameras[sanitize_key($folder)] = $folder;
  }
  return $cameras;
}

function tl_timelapse_latest_video(string $folder, string $period): ?string {
  // glob() returns false on error, and rsort(false) is a fatal TypeError in PHP 8.
  $files = glob(tl_timelapse_videos_dir() . "/" . $folder . "/" . $period . "/*.mp4") ?: [];
  rsort($files);
  return $files[0] ?? null;
}

// End date of a video: the pipeline names files <camera>_<YYYY-MM-DD>.mp4 and that date is the last
// day the video covers. Other names fall back to the file's modification date.
function tl_timelapse_video_end_date(string $file): DateTimeImmutable {
  if (preg_match('/(\d{4}-\d{2}-\d{2})/', basename($file), $match)) {
    $date = DateTimeImmutable::createFromFormat('!Y-m-d', $match[1], wp_timezone());
    // createFromFormat rolls impossible dates over (13th month -> next year), so require
    // that the date formats back to the same text.
    if ($date && $date->format('Y-m-d') === $match[1]) {
      return $date;
    }
  }

  return (new DateTimeImmutable("@" . (int) filemtime($file)))->setTimezone(wp_timezone())->setTime(0, 0);
}

// Time span a video covers, as text for the heading. The windows follow the pipeline (README,
// "Timelapse-Typen"): daily = that day, weekly = 7 calendar days, monthly = 30 days, yearly = the
// calendar year up to the end date (365 or 366 days). All include the end date.
function tl_timelapse_video_span(string $file, string $period): string {
  $end = tl_timelapse_video_end_date($file);

  $start = match ($period) {
    "weekly" => $end->modify("-6 days"),
    "monthly" => $end->modify("-29 days"),
    "yearly" => $end->modify("+1 day")->modify("-1 year"),
    default => $end,
  };

  $format = fn(DateTimeImmutable $date): string => (string) wp_date(get_option("date_format"), $date->getTimestamp());

  if ($start == $end) {
    return $format($end);
  }

  return $format($start) . " bis " . $format($end);
}

// Text alternative for the video-only player (WCAG 1.2.1), as two paragraphs: the note that there
// is no sound, then the description from the camera entry. Independent of the period, so it never
// changes when a tab is switched.
function tl_timelapse_caption_html(string $description): string {
  $html = "<p>Zeitraffer ohne Ton</p>";

  if ($description !== "") {
    $html .= "<p>Beschreibung: " . esc_html($description) . "</p>";
  }

  return $html;
}

// [zeitraffer camera="<folder slug>" title="<display name>" description="<scene description>" heading="2"]
// camera: folder slug; falls back to ?camera= so the shared-page setup keeps working.
// title: shown instead of the folder name (page slugs and folders often differ).
// description: text alternative shown under the video.
// heading: level of the player's heading (2-6), to fit the surrounding page's heading structure.
function tl_timelapse_camera_shortcode(array|string $atts = []): string {
  $atts = shortcode_atts([
    "camera" => "",
    "title" => "",
    "description" => "",
    "heading" => "2",
  ], $atts, "zeitraffer");

  // The page title is the h1, so only 2-6 are valid; anything else falls back to 2.
  $level = in_array($atts["heading"], ["2", "3", "4", "5", "6"], true) ? $atts["heading"] : "2";


wp_enqueue_style(
  "zeitraffer",
  plugins_url("assets/style.css", __FILE__),
  [],
  filemtime(__DIR__ . "/assets/style.css")
);

// Last argument true: load in the footer, after the markup exists.
wp_enqueue_script(
  "zeitraffer",
  plugins_url("assets/script.js", __FILE__),
  [],
  filemtime(__DIR__ . "/assets/script.js"),
  true
);

$cameras = tl_timelapse_get_cameras();

if ($atts["camera"] !== "") {
  $slug = sanitize_key($atts["camera"]);
} else {
  $slug = isset($_GET["camera"]) ? sanitize_key(wp_unslash($_GET["camera"])) : "";
}

if (!isset($cameras[$slug])) {
  // Visitors see nothing. Editors get a hint, because a typo in the shortcode is the likely cause;
  // it lists folder names, so it must not be shown publicly.
  if ($slug !== "" && current_user_can("edit_pages")) {
    return "<p class='zeitraffer_notice'>" . esc_html("Zeitraffer: Kamera „" . $slug . "“ nicht gefunden. Verfügbar: " . implode(", ", array_keys($cameras)) . ".") . "</p>";
  }

  return "";
}

$entry = tl_timelapse_camera_entry($slug, "any");
$is_published = $entry && $entry->post_status === "publish";

// Only a published entry makes a camera public; a draft, a private or pending entry, or no entry at
// all hides it. Editors still see it, marked as unpublished, so a new camera can be tested on its
// real page.
if (!$is_published && !current_user_can("edit_others_posts")) {
  return "";
}

// $cameras[$slug] is the folder name (for the filesystem); $name is what visitors read.
// Shortcode attributes override the camera entry (Zeitraffer > Kameras), which overrides the defaults.
$name = $atts["title"] !== "" ? $atts["title"] : ($entry && $entry->post_title !== "" ? $entry->post_title : $cameras[$slug]);
$description = $atts["description"] !== "" ? $atts["description"] : ($entry ? trim($entry->post_excerpt) : "");


$html = "<div class='zeitraffer'>";

if (!$is_published) {
  $html .= "<p class='zeitraffer_notice'>" . esc_html("Diese Kamera ist nicht veröffentlicht und nur für Redakteure sichtbar (Zeitraffer → Alle Kameras).") . "</p>";
}

$periods = [
  "daily" => "Tag",
  "weekly" => "Woche",
  "monthly" => "Monat",
  "yearly" => "Jahr",
];

$period = isset($_GET["period"]) ? sanitize_key(wp_unslash($_GET["period"])) : "daily";

if (!isset($periods[$period])) {
  $period = "daily";
}

$video = tl_timelapse_latest_video($cameras[$slug], $period);

// The requested (or default) period may have no video; fall back to the first one that does.
if (!$video) {
  foreach (array_keys($periods) as $fallback) {
    $video = tl_timelapse_latest_video($cameras[$slug], $fallback);
    if ($video) {
      $period = $fallback;
      break;
    }
  }
}

// The page already names the camera (its h1), so the heading only says what this is and which period.
$heading = "Zeitraffer";

if ($video) {
  $heading .= ' &ndash; <span id="zeitraffer_date">' . esc_html(tl_timelapse_video_span($video, $period)) . '</span>';
}

$html .= "<h" . $level . ">" . $heading . "</h" . $level . ">";

if ($video) {
  $url = tl_timelapse_videos_url($cameras[$slug] . "/" . $period . "/" . basename($video));
  // Video-only content needs a text alternative (WCAG 1.2.1); aria-label is just a name.
  // playsinline keeps iOS from forcing the video fullscreen.
  $html .= '<video id="zeitraffer_video" controls playsinline preload="metadata" src="' . esc_url($url) . '" aria-label="' . esc_attr($name . " " . $periods[$period]) . '" aria-describedby="zeitraffer_caption"></video>';
  $html .= '<div id="zeitraffer_caption" class="zeitraffer_caption">' . tl_timelapse_caption_html($description) . '</div>';
}

$html .= "<nav class='zeitraffer_nav' aria-label='Zeitraum'>";

foreach ($periods as $key => $label) {
  $item = tl_timelapse_latest_video($cameras[$slug], $key);
  if (!$item) {
    continue;
  }

  $item_url = tl_timelapse_videos_url($cameras[$slug] . "/" . $key . "/" . basename($item));
  $item_span = tl_timelapse_video_span($item, $key);
  $link_url = add_query_arg("period", $key);
  $current = ($key === $period) ? " aria-current='true'" : "";

  // href keeps the tab working without JavaScript; data-* is read by assets/script.js.
  $html .= "<a href='" . esc_url($link_url) . "' data-src='" . esc_url($item_url) . "' data-label='" . esc_attr($name . " " . $label) . "' data-date='" . esc_attr($item_span) . "'" . $current . ">" . esc_html($label) . "</a>";
  }

  $html .= "</nav>";

  $html .= "</div>";


return $html;

}

// ---- Camera entries (post type) -------------------------------------------------------------------
// One "Kamera" entry per camera folder holds the display name (title) and the scene description
// (excerpt), so texts are maintained in the admin and not in shortcodes. Entries are not public.

const TL_TIMELAPSE_POST_TYPE = "zeitraffer_camera";
// Leading underscore: protected meta, not shown or editable as a custom field.
const TL_TIMELAPSE_FOLDER_META = "_zeitraffer_folder";

function tl_timelapse_register_post_type(): void {
  register_post_type(TL_TIMELAPSE_POST_TYPE, [
    "labels" => [
      "name" => "Kameras",
      "singular_name" => "Kamera",
      "menu_name" => "Zeitraffer",
      "all_items" => "Alle Kameras",
      "edit_item" => "Kamera bearbeiten",
      "search_items" => "Kameras suchen",
      "not_found" => "Keine Kameras gefunden. „Kameras aus Ordnern anlegen“ erstellt sie.",
    ],
    "public" => false,
    "show_ui" => true,
    "menu_icon" => "dashicons-video-alt3",
    "supports" => ["title", "excerpt"],
    // Entries come from the folders only; one made by hand would have no folder.
    "capabilities" => ["create_posts" => "do_not_allow"],
    "map_meta_cap" => true,
  ]);
}
add_action("init", "tl_timelapse_register_post_type");

// Folder scans are repeated per list row otherwise; videos do not change within one request.
function tl_timelapse_cameras_cached(): array {
  static $cameras = null;

  if ($cameras === null) {
    $cameras = tl_timelapse_get_cameras();
  }

  return $cameras;
}

// The entry for a camera slug, or null. $status "any" also finds drafts, so the sync never duplicates.
function tl_timelapse_camera_entry(string $slug, string $status = "publish"): ?WP_Post {
  $posts = get_posts([
    "post_type" => TL_TIMELAPSE_POST_TYPE,
    "post_status" => $status,
    "meta_key" => TL_TIMELAPSE_FOLDER_META,
    "meta_value" => $slug,
    "numberposts" => 1,
    "no_found_rows" => true,
  ]);

  return $posts[0] ?? null;
}

function tl_timelapse_add_meta_box(): void {
  add_meta_box("zeitraffer_folder", "Zeitraffer", "tl_timelapse_render_meta_box", TL_TIMELAPSE_POST_TYPE, "side");
}
add_action("add_meta_boxes", "tl_timelapse_add_meta_box");

// Read-only: nothing here is saved, so there is no form handler to protect.
function tl_timelapse_render_meta_box(WP_Post $post): void {
  $slug = (string) get_post_meta($post->ID, TL_TIMELAPSE_FOLDER_META, true);

  echo "<p><strong>Ordner:</strong> " . esc_html($slug) . "</p>";
  echo "<p>Shortcode: <code>" . esc_html('[zeitraffer camera="' . $slug . '"]') . "</code></p>";

  if (!isset(tl_timelapse_cameras_cached()[$slug])) {
    echo "<p><strong>Ordner nicht gefunden.</strong> Umbenannt oder gelöscht?</p>";
  }

  echo "<p>Titel = Anzeigename auf der Seite. Auszug = Beschreibung des Videos (Textalternative).</p>";
  echo "<p>Nur veröffentlichte Kameras sind für Besucher sichtbar. Entwürfe sehen nur Redakteure.</p>";
}

function tl_timelapse_list_columns(array $columns): array {
  $columns["zeitraffer_folder"] = "Ordner";
  return $columns;
}
add_filter("manage_" . TL_TIMELAPSE_POST_TYPE . "_posts_columns", "tl_timelapse_list_columns");

function tl_timelapse_list_column_content(string $column, int $post_id): void {
  if ($column !== "zeitraffer_folder") {
    return;
  }

  $slug = (string) get_post_meta($post_id, TL_TIMELAPSE_FOLDER_META, true);
  echo esc_html($slug);

  if (!isset(tl_timelapse_cameras_cached()[$slug])) {
    echo " &ndash; " . esc_html("Ordner nicht gefunden");
  }
}
add_action("manage_" . TL_TIMELAPSE_POST_TYPE . "_posts_custom_column", "tl_timelapse_list_column_content", 10, 2);

// Button above the camera list. A POST with a nonce, handled below; not run automatically.
function tl_timelapse_sync_form(): void {
  $screen = get_current_screen();

  if (!$screen || $screen->id !== "edit-" . TL_TIMELAPSE_POST_TYPE || !current_user_can("edit_others_posts")) {
    return;
  }

  if (isset($_GET["zeitraffer_synced"])) {
    $count = absint($_GET["zeitraffer_synced"]);
    echo '<div class="notice notice-success is-dismissible"><p>' . esc_html($count . " Kamera(s) als Entwurf angelegt. Sie werden erst mit „Veröffentlichen“ sichtbar.") . '</p></div>';
  }

  echo '<form method="post" action="' . esc_url(admin_url("admin-post.php")) . '">';
  echo '<input type="hidden" name="action" value="zeitraffer_sync">';
  wp_nonce_field("zeitraffer_sync");
  echo '<p><button type="submit" class="button button-primary">Kameras aus Ordnern anlegen</button> ';
  echo esc_html("Legt für jeden Ordner ohne Eintrag eine Kamera als Entwurf an. Vorhandene bleiben unverändert.") . '</p>';
  echo '</form>';
}
add_action("admin_notices", "tl_timelapse_sync_form");

function tl_timelapse_handle_sync(): void {
  if (!current_user_can("edit_others_posts")) {
    wp_die("Keine Berechtigung.", "", ["response" => 403]);
  }

  check_admin_referer("zeitraffer_sync");

  $created = 0;

  foreach (tl_timelapse_get_cameras() as $slug => $folder) {
    if (tl_timelapse_camera_entry((string) $slug, "any")) {
      continue;
    }

    // Draft: a new camera stays hidden until someone has tested it and publishes the entry.
    $id = wp_insert_post([
      "post_type" => TL_TIMELAPSE_POST_TYPE,
      "post_status" => "draft",
      "post_title" => $folder,
      "meta_input" => [TL_TIMELAPSE_FOLDER_META => $slug],
    ], true);

    if (!is_wp_error($id)) {
      $created++;
    }
  }

  wp_safe_redirect(add_query_arg([
    "post_type" => TL_TIMELAPSE_POST_TYPE,
    "zeitraffer_synced" => $created,
  ], admin_url("edit.php")));
  exit;
}
add_action("admin_post_zeitraffer_sync", "tl_timelapse_handle_sync");

// Player under the image of [f5_webcams_last]. The folder name of the webcam the image shows is
// the video folder, so the player follows the image without its own "latest webcam" lookup.
// Unpublished or video-less cameras render nothing, as with the shortcode.
function tl_timelapse_after_webcam(string $foldername, string $heading_tag): void {
  // A webcam without a timelapse folder is normal; skip it quietly, without the editor's
  // "camera not found" notice the shortcode would print under the image.
  if (!isset(tl_timelapse_cameras_cached()[sanitize_key($foldername)])) {
    return;
  }

  // One level below the webcam's heading (h4 -> h5), at most h6.
  $level = min(6, (int) substr($heading_tag, 1) + 1);

  // The shortcode escapes its own output.
  echo tl_timelapse_camera_shortcode([ // phpcs:ignore WordPress.Security.EscapeOutput
    "camera" => $foldername,
    "heading" => (string) $level,
  ]);
}
add_action("f5_webcams_after_webcam", "tl_timelapse_after_webcam", 10, 2);

add_shortcode(
  "zeitraffer",
  "tl_timelapse_camera_shortcode"
);