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

    $cameras[strtolower($folder)] = $folder;
  }
  return $cameras;
}

function tl_timelapse_shortcode() {
  $html = "<ul>";

  foreach (tl_timelapse_get_cameras() as $slug => $folder) {
    $url = add_query_arg("camera", $slug, get_permalink(get_page_by_path("zeitraffer")));
    $html .= '<li><a href="' . esc_url($url) . '">' . esc_html($folder) . '</a></li>';
  }

  return $html . '</ul>';
}

function tl_timelapse_latest_video($folder, $period) {
  $files = glob(WP_CONTENT_DIR . "/zeitraffer-videos/" . $folder . "/" . $period . "/*.mp4");
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

if ($video) {
  $url = content_url("zeitraffer-videos/" . $cameras[$slug] . "/" . $period . "/" . basename($video));
  $html .= '<video id="zeitraffer_video" controls preload="metadata" src="' . esc_url($url) . '" aria-label="' . esc_attr($cameras[$slug] . " " . $periods[$period]) . '"></video>';
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
  $html .= "<a href='" . esc_url($link_url) . "' data-src='" . esc_url($item_url) . "' data-label='" . esc_attr($cameras[$slug] . " " . $label) . "'" . $current . ">" . esc_html($label) . "</a>";
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