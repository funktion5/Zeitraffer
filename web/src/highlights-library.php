<?php

declare(strict_types=1);

require_once __DIR__ . "/video-library.php";

// Reads the reports the flagger writes to videos/<camera>/highlights/<date>/ (manifest.json,
// schema 1, see docs/flagger.md). Everything in a report is treated as untrusted: a field with
// the wrong type drops its item, a broken report drops its day, nothing ever throws.

// German label for a COCO class the flagger reports; unknown labels pass through unchanged.
function translateHighlightLabel(string $label): string
{
	return match ($label) {
		"bird" => "Vogel",
		"airplane" => "Flugzeug",
		"kite" => "Drachen",
		"cat" => "Katze",
		"dog" => "Hund",
		"horse" => "Pferd",
		"sheep" => "Schaf",
		"cow" => "Kuh",
		"elephant" => "Elefant",
		"bear" => "Bär",
		"zebra" => "Zebra",
		"giraffe" => "Giraffe",
		default => $label,
	};
}

function parseHighlightsPeriod(mixed $value): string
{
	return in_array($value, ["1", "7", "30", "all"], true) ? $value : "7";
}

// First day still shown, as ISO date; null means no limit. The flagger reports a day during the
// following night, so "1" is yesterday.
function highlightsSinceDate(string $period, DateTimeImmutable $today): ?string
{
	if ($period === "all") {
		return null;
	}

	return $today->modify("-{$period} days")->format("Y-m-d");
}

function isValidHighlightCamera(string $camera): bool
{
	return $camera !== ""
		&& !str_contains($camera, "/")
		&& !str_starts_with($camera, ".")
		&& preg_match('/[\x00-\x1f\x7f]/', $camera) === 0;
}

// Same rule as the delete wrapper: lowercase .jpg, no leading dot, no path.
function isValidHighlightName(string $name): bool
{
	return preg_match('/^[A-Za-z0-9_-][A-Za-z0-9._-]*\.jpg$/', $name) === 1;
}

// The parsed config.json, or [] when it is missing or not a JSON object.
function readHighlightsConfig(): array
{
	$configPath = projectRoot() . "/config/config.json";

	if (!is_file($configPath) || !is_readable($configPath)) {
		return [];
	}

	$configContent = file_get_contents($configPath);
	$config = $configContent === false ? null : json_decode($configContent, true);

	return is_array($config) ? $config : [];
}

// Today in the cameras' timezone (config location.timezone): PHP itself runs in UTC, which
// would still show yesterday's date until 02:00 in summer.
function highlightsToday(): DateTimeImmutable
{
	$timezone = readHighlightsConfig()["location"]["timezone"] ?? null;

	// Checked up front instead of catching the constructor's exception: with Xdebug loaded
	// (as on the CI runner) that exception turns into an Error that catch (Exception) misses.
	$zone = in_array($timezone, DateTimeZone::listIdentifiers(), true)
		? new DateTimeZone($timezone)
		: null;

	return new DateTimeImmutable("today", $zone);
}

function getFlaggerCameras(): array
{
	$config = readHighlightsConfig();
	$cameras = is_array($config["flagger"] ?? null) ? $config["flagger"]["cameras"] ?? [] : [];

	if (!is_array($cameras)) {
		return [];
	}

	$valid = array_filter(
		$cameras,
		fn($camera): bool => is_string($camera) && isValidHighlightCamera($camera),
	);

	return array_values(array_unique($valid));
}

// Configured cameras plus any camera that still has reports, so highlights of a camera that
// was taken out of the config stay visible until the cleanup removes them.
function listHighlightCameras(): array
{
	$cameras = getFlaggerCameras();
	$videoRoot = projectRoot() . "/videos";

	if (is_dir($videoRoot) && is_readable($videoRoot)) {
		foreach (scandir($videoRoot) as $entry) {
			if (
				isValidHighlightCamera($entry)
				&& !in_array($entry, $cameras, true)
				&& is_dir($videoRoot . "/" . $entry . "/highlights")
			) {
				$cameras[] = $entry;
			}
		}
	}

	natcasesort($cameras);

	return array_values($cameras);
}

// Days with a valid report, newest first; items keep the manifest order (highest score first).
function findHighlightDays(string $camera, ?string $sinceIso): array
{
	if (!isValidHighlightCamera($camera)) {
		return [];
	}

	$highlightsRoot = projectRoot() . "/videos/" . $camera . "/highlights";

	if (!is_dir($highlightsRoot) || !is_readable($highlightsRoot)) {
		return [];
	}

	$days = [];

	foreach (scandir($highlightsRoot) as $date) {
		// Also skips the flagger's hidden ".<date>.tmp" work folders.
		if (!isValidIsoDate($date) || ($sinceIso !== null && $date < $sinceIso)) {
			continue;
		}

		$dayPath = $highlightsRoot . "/" . $date;

		if (is_link($dayPath) || !is_dir($dayPath)) {
			continue;
		}

		$day = readHighlightDay($camera, $date, $dayPath);

		if ($day !== null) {
			$days[] = $day;
		}
	}

	usort($days, fn(array $left, array $right): int => strcmp($right["date"], $left["date"]));

	return $days;
}

function readHighlightDay(string $camera, string $date, string $dayPath): ?array
{
	$manifestPath = $dayPath . "/manifest.json";

	if (is_link($manifestPath) || !is_file($manifestPath) || !is_readable($manifestPath)) {
		return null;
	}

	$content = file_get_contents($manifestPath);
	$manifest = $content === false ? null : json_decode($content, true);

	if (
		!is_array($manifest)
		|| ($manifest["schema"] ?? null) !== 1
		|| !is_int($manifest["checked"] ?? null)
		|| $manifest["checked"] < 0
		|| !is_array($manifest["items"] ?? null)
		|| !array_is_list($manifest["items"])
	) {
		return null;
	}

	$items = [];

	foreach ($manifest["items"] as $entry) {
		$item = is_array($entry) ? parseHighlightItem($entry) : null;

		// The page never lists a file that is not there, so a delete needs no manifest rewrite.
		if ($item === null) {
			continue;
		}

		$imagePath = $dayPath . "/" . $item["file"];

		if (is_link($imagePath) || !is_file($imagePath)) {
			continue;
		}

		$items[] = [
			"file" => $item["file"],
			"url" => "/videos/"
				. rawurlencode($camera)
				. "/highlights/"
				. $date
				. "/"
				. rawurlencode($item["file"]),
			...array_diff_key($item, ["file" => true]),
		];
	}

	return [
		"date" => $date,
		"checked" => $manifest["checked"],
		"items" => $items,
	];
}

function parseHighlightItem(array $entry): ?array
{
	$file = $entry["file"] ?? null;
	$takenAt = $entry["taken_at"] ?? null;
	$group = $entry["group"] ?? null;
	$label = $entry["label"] ?? null;
	$score = $entry["score"] ?? null;
	$box = $entry["box"] ?? null;
	$imageSize = $entry["image_size"] ?? null;

	if (
		!is_string($file)
		|| !isValidHighlightName($file)
		|| !is_string($takenAt)
		|| preg_match('/^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):([0-5]\d)/', $takenAt, $time) !== 1
		|| !in_array($group, ["animal", "flying"], true)
		|| !is_string($label)
		|| $label === ""
		|| !(is_int($score) || is_float($score))
		|| $score < 0
		|| $score > 1
		|| !isIntList($box, 4)
		|| !isIntList($imageSize, 2)
		|| $imageSize[0] <= 0
		|| $imageSize[1] <= 0
	) {
		return null;
	}

	return [
		"file" => $file,
		"time" => "{$time[1]}:{$time[2]}",
		"group" => $group,
		"label" => $label,
		"score" => (float) $score,
		"box" => $box,
		"imageSize" => $imageSize,
	];
}

function isIntList(mixed $value, int $length): bool
{
	return is_array($value)
		&& array_is_list($value)
		&& count($value) === $length
		&& array_filter($value, "is_int") === $value;
}

// A delete is only allowed for an image the page would list right now.
function isListedHighlight(string $camera, mixed $date, mixed $file): bool
{
	if (!is_string($date) || !isValidIsoDate($date) || !is_string($file)) {
		return false;
	}

	foreach (findHighlightDays($camera, $date) as $day) {
		if ($day["date"] !== $date) {
			continue;
		}

		foreach ($day["items"] as $item) {
			if ($item["file"] === $file) {
				return true;
			}
		}
	}

	return false;
}

function highlightsPageUrl(string $period, string $camera, bool $deleted = false): string
{
	$query = array_filter(
		[
			"days" => $period,
			"camera" => $camera,
			"deleted" => $deleted ? "1" : "",
		],
		fn(string $value): bool => $value !== "",
	);

	return "/highlights.php?" . http_build_query($query, "", "&", PHP_QUERY_RFC3986);
}
