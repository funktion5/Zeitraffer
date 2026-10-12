<?php
/*
 * Plugin Name: Zeitraffer
 */
defined( 'ABSPATH' ) || exit; 


function tl_timelapse_get_cameras() {
  $paths = glob(WP_CONTENT_DIR . "/zeitraffer-videos/*", GLOB_ONLYDIR);
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

// URL of the page that holds the [zeitraffer] shortcode.
function tl_timelapse_camera_page_url() {
  // Filterable, so a renamed page needs no code change.
  $page = get_page_by_path(apply_filters("zeitraffer_camera_page_slug", "zeitraffer"));

  if (!$page) {
    // Page missing or renamed: link to the current page instead of a broken URL.
    return get_permalink();
  }

  // With WPML, return the translation in the current language; without it the ID is unchanged.
  $page_id = apply_filters("wpml_object_id", $page->ID, "page", true);

  return get_permalink($page_id);
}

function tl_timelapse_shortcode() {
  $cameras = tl_timelapse_get_cameras();

  // An empty <ul> is invalid markup and tells screen reader users nothing.
  if (!$cameras) {
    return "<p>" . esc_html("Derzeit sind keine Zeitraffer-Videos verfügbar.") . "</p>";
  }

  $html = "<ul>";
  $page_url = tl_timelapse_camera_page_url();

  foreach ($cameras as $slug => $folder) {
    $url = add_query_arg("camera", $slug, $page_url);
    $html .= '<li><a href="' . esc_url($url) . '">' . esc_html($folder) . '</a></li>';
  }

  return $html . '</ul>';
}

function tl_timelapse_latest_video($folder, $period) {
  // glob() returns false on error, and rsort(false) is a fatal TypeError in PHP 8.
  $files = glob(WP_CONTENT_DIR . "/zeitraffer-videos/" . $folder . "/" . $period . "/*.mp4") ?: [];
  rsort($files);
  return $files[0] ?? null;
}

function tl_timelapse_camera_shortcode() {


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

$slug = isset($_GET["camera"]) ? sanitize_key(wp_unslash($_GET["camera"])) : "";

if (!isset($cameras[$slug]))
  return "";


$html = "<div class='zeitraffer'><h2>" . esc_html($cameras[$slug]) . "</h2>";

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

if ($video) {
  $url = content_url("zeitraffer-videos/" . $cameras[$slug] . "/" . $period . "/" . basename($video));
  $caption = "Zeitraffer ohne Ton: " . $cameras[$slug] . ", " . $periods[$period];
  // Video-only content needs a text alternative (WCAG 1.2.1); aria-label is just a name.
  // playsinline keeps iOS from forcing the video fullscreen.
  // The wrapper carries the loading skeleton: a <video> cannot take pseudo-elements.
  $html .= '<div class="zeitraffer_player"><video id="zeitraffer_video" controls playsinline preload="metadata" src="' . esc_url($url) . '" aria-label="' . esc_attr($cameras[$slug] . " " . $periods[$period]) . '" aria-describedby="zeitraffer_caption"></video></div>';
  $html .= '<p id="zeitraffer_caption" class="zeitraffer_caption">' . esc_html($caption) . '</p>';
}

$html .= "<nav class='zeitraffer_nav' aria-label='Zeitraum'>";

foreach ($periods as $key => $label) {
  $item = tl_timelapse_latest_video($cameras[$slug], $key);
  if (!$item) {
    continue;
  }

  $item_url = content_url("zeitraffer-videos/" . $cameras[$slug] . "/" . $key . "/" . basename($item));
  $link_url = add_query_arg("period", $key);
  $current = ($key === $period) ? " aria-current='true'" : "";

  // href keeps the tab working without JavaScript; data-* is read by assets/script.js.
  $html .= "<a href='" . esc_url($link_url) . "' data-src='" . esc_url($item_url) . "' data-label='" . esc_attr($cameras[$slug] . " " . $label) . "' data-caption='" . esc_attr("Zeitraffer ohne Ton: " . $cameras[$slug] . ", " . $label) . "'" . $current . ">" . esc_html($label) . "</a>";
  }

  $html .= "</nav>";

  $html .= "</div>";


return $html;

}

add_shortcode(
  "tl",
  "tl_timelapse_shortcode"
);

add_shortcode(
  "zeitraffer",
  "tl_timelapse_camera_shortcode"
);