<?php

declare(strict_types=1);

// German display label for a job type; the identifier itself (used in
// form values, URLs, and the CLI) always stays the English lowercase form.
function translateJobLabel(string $job): string
{
	return match ($job) {
		"daily" => "Täglich",
		"weekly" => "Wöchentlich",
		"monthly" => "Monatlich",
		"yearly" => "Jährlich",
		default => $job,
	};
}

// The project folder, two levels above web/src/, so no install path is hardcoded.
function projectRoot(): string
{
	return dirname(__DIR__, 2);
}

// readProjectConfig() and its helpers: config.json with the saved web UI settings laid over it.
// Loaded here because they call projectRoot() above.
require_once __DIR__ . "/project-config.php";

// Only string names count; anything else in a camera list of the config is dropped.
function cameraNames(mixed $names): array
{
	if (!is_array($names)) {
		return [];
	}

	return array_values(
		array_filter(
			$names,
			fn($camera): bool => is_string($camera),
		),
	);
}

function getIgnoredCameras(): array
{
	return cameraNames(readProjectConfig()["ignored_cameras"] ?? []);
}

// The cameras whose frames a manual Daily, Monthly or Yearly blurs on the box before the video is
// built (privacy.blur_cameras), which makes the creation take longer.
function getBlurCameras(): array
{
	$privacy = readProjectConfig()["privacy"] ?? [];

	return cameraNames(is_array($privacy) ? ($privacy["blur_cameras"] ?? []) : []);
}

// The daylight buffer in minutes that a manual Daily or Weekly uses (daylight_buffer_minutes:
// config.json with the saved settings on top), or null when it is not a whole number from 0 to 240.
function getManualDaylightBuffer(): ?int
{
	$value = readProjectConfig()["daylight_buffer_minutes"] ?? null;

	return is_int($value) && $value >= 0 && $value <= 240 ? $value : null;
}

// The names end up in file paths, so only plain names pass: the pattern the Python side applies to
// the storage listing. It also keeps out ".", "..", hidden entries and "/". The D modifier stops
// "$" from accepting a trailing newline.
function isPlainCameraName(string $name): bool
{
	return preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*$/D', $name) === 1;
}

// The camera names come from state/web-jobs/cameras.json, which the nightly run writes
// (python3 -m src.camera_list): the web server user has no ssh key and never talks to the box.
// A missing or unusable file gives an empty list.
function findAvailableCameras(): array
{
	$listPath = projectRoot() . "/state/web-jobs/cameras.json";

	if (!is_file($listPath) || !is_readable($listPath)) {
		return [];
	}

	$content = file_get_contents($listPath);

	if ($content === false) {
		return [];
	}

	$list = json_decode($content, true);

	if (!is_array($list)) {
		return [];
	}

	$ignoredCameras = getIgnoredCameras();
	$cameras = [];

	foreach ($list as $entry) {
		if (!is_string($entry) || !isPlainCameraName($entry)) {
			continue;
		}

		if (in_array($entry, $ignoredCameras, true)) {
			continue;
		}

		$cameras[] = $entry;
	}

	natcasesort($cameras);

	return array_values($cameras);
}

// $runFolder "manual-runs" lists the historical videos, "" the automatic ones in
// videos/<camera>/<job>/. Only the four job folders are read, so highlights/ and manual-runs/
// never show up as jobs.
function findVideos(string $camera, string $runFolder): array
{
	$folderPath = $runFolder === "" ? "" : "/" . $runFolder;
	$videoRoot = projectRoot() . "/videos/" . $camera . $folderPath;

	if (!is_dir($videoRoot) || !is_readable($videoRoot)) {
		return [];
	}

	$allowedJobs = [
		"daily",
		"weekly",
		"monthly",
		"yearly",
	];

	$videos = [];

	foreach ($allowedJobs as $job) {
		$jobPath = $videoRoot . "/" . $job;

		if (!is_dir($jobPath) || !is_readable($jobPath)) {
			continue;
		}

		foreach (scandir($jobPath) as $filename) {
			// Hidden files include `.<name>.tmp.mp4` from a running encode, which must not be
			// played or deleted before the atomic rename.
			if (str_starts_with($filename, ".")) {
				continue;
			}

			if (strtolower(pathinfo($filename, PATHINFO_EXTENSION)) !== "mp4") {
				continue;
			}

			$filePath = $jobPath . "/" . $filename;

			if (!is_file($filePath) || is_link($filePath)) {
				continue;
			}

			$metadata = extractManualVideoMetadata($camera, $filename);

			$videos[$job][] = [
				"filename" => $filename,
				"date" => $metadata["date"],
				"bufferMinutes" => $metadata["bufferMinutes"],
				"window" => $metadata["window"],
				"url" => "/videos/"
					. rawurlencode($camera)
					. $folderPath
					. "/"
					. rawurlencode($job)
					. "/"
					. rawurlencode($filename),
			];
		}

		if (isset($videos[$job])) {
			usort(
				$videos[$job],
				fn(array $left, array $right): int => strcmp(
					($right["date"] ?? $right["filename"]) . ($right["bufferMinutes"] ?? "") . ($right["window"] ?? ""),
					($left["date"] ?? $left["filename"]) . ($left["bufferMinutes"] ?? "") . ($left["window"] ?? ""),
				),
			);
		}
	}

	return $videos;
}

// The preview of what an upload would send: per period the newest automatic video, as [period =>
// filename] in the fixed order, only periods that have one. The delivery script decides what really
// goes (scripts/list-deliverable-videos.py); this mirrors its rules: only the four period folders
// directly under the camera folder, no symlinks, the newest BY FILE NAME among regular, non-empty,
// non-hidden lowercase *.mp4 files (as its glob). manual-runs/ is never looked at. ignored_cameras
// is already applied by findAvailableCameras().
function newestAutomaticVideos(string $camera): array
{
	$cameraPath = projectRoot() . "/videos/" . $camera;

	if (is_link($cameraPath) || !is_dir($cameraPath) || !is_readable($cameraPath)) {
		return [];
	}

	$newest = [];

	foreach (["daily", "weekly", "monthly", "yearly"] as $job) {
		$jobPath = $cameraPath . "/" . $job;

		if (is_link($jobPath) || !is_dir($jobPath) || !is_readable($jobPath)) {
			continue;
		}

		$validNames = [];

		foreach (scandir($jobPath) as $filename) {
			if (str_starts_with($filename, ".") || !str_ends_with($filename, ".mp4")) {
				continue;
			}

			$filePath = $jobPath . "/" . $filename;

			// A half-written video is hidden until its rename; an empty file is a failed render.
			if (is_link($filePath) || !is_file($filePath) || filesize($filePath) === 0) {
				continue;
			}

			$validNames[] = $filename;
		}

		if ($validNames !== []) {
			sort($validNames, SORT_STRING);
			$newest[$job] = end($validNames);
		}
	}

	return $newest;
}

// Extracts the ISO target date and, if present, the daylight buffer (in
// minutes) or the Monthly/Yearly interval window from a manual-run filename
// (`{camera}_{date}.mp4`, `{camera}_{date}_{buffer}min.mp4` or
// `{camera}_{date}_{HHMM|sunset}-{tolerance}min.mp4`). Everything comes back
// null if the filename doesn't match. Never guesses: an unexpected filename
// just falls back to sorting/displaying by the raw filename.
function extractManualVideoMetadata(string $camera, string $filename): array
{
	$noMetadata = [
		"date" => null,
		"bufferMinutes" => null,
		"window" => null,
	];

	$pattern = "/^"
		. preg_quote($camera, "/")
		. "_(\d{4}-\d{2}-\d{2})(?:_(\d+)min|_(\d{4}|sunset)-(\d+)min)?\.mp4$/";

	if (preg_match($pattern, $filename, $matches) !== 1 || !isValidIsoDate($matches[1])) {
		return $noMetadata;
	}

	$window = null;

	if (isset($matches[3]) && $matches[3] !== "") {
		$window = formatIntervalWindowLabel($matches[3], (int) $matches[4]);

		if ($window === null) {
			return $noMetadata;
		}
	}

	return [
		"date" => $matches[1],
		"bufferMinutes" => isset($matches[2]) && $matches[2] !== "" ? (int) $matches[2] : null,
		"window" => $window,
	];
}

// German label for a filename window part, e.g. "1830" -> "18:30 ±60 Min.".
// Returns null for an impossible time so the caller falls back to the filename.
function formatIntervalWindowLabel(string $target, int $toleranceMinutes): ?string
{
	if ($target === "sunset") {
		return "Sonnenuntergang ±{$toleranceMinutes} Min.";
	}

	$hour = (int) substr($target, 0, 2);
	$minute = (int) substr($target, 2, 2);

	if ($hour > 23 || $minute > 59) {
		return null;
	}

	return sprintf("%02d:%02d ±%d Min.", $hour, $minute, $toleranceMinutes);
}

function formatGermanDate(string $isoDate): string
{
	$parts = explode("-", $isoDate);

	return count($parts) === 3
		? "{$parts[2]}.{$parts[1]}.{$parts[0]}"
		: $isoDate;
}

function formatBytes(float $bytes): string
{
	$units = ["B", "KB", "MB", "GB", "TB"];
	$unitIndex = 0;

	while ($bytes >= 1024 && $unitIndex < count($units) - 1) {
		$bytes /= 1024;
		$unitIndex++;
	}

	return number_format($bytes, 1) . " " . $units[$unitIndex];
}


// From these shares of the disk on, the header warns in words as well as in colour.
const STORAGE_WARN_PERCENT = 80.0;
const STORAGE_CRITICAL_PERCENT = 90.0;

// The folders the nightly run fills; "manual-runs" holds the videos made by hand.
const AUTOMATIC_VIDEO_FOLDERS = ["daily", "weekly", "monthly", "yearly"];

// Bytes of the regular files under a folder. Links are skipped so a link cannot count a file that
// lies elsewhere; a subfolder that cannot be read is left out.
function directoryBytes(string $directory): int
{
	if (!is_dir($directory) || !is_readable($directory)) {
		return 0;
	}

	$files = new RecursiveIteratorIterator(
		new RecursiveDirectoryIterator($directory, FilesystemIterator::SKIP_DOTS),
		RecursiveIteratorIterator::LEAVES_ONLY,
		RecursiveIteratorIterator::CATCH_GET_CHILD,
	);

	$bytes = 0;

	foreach ($files as $file) {
		if ($file->isFile() && !$file->isLink()) {
			$bytes += $file->getSize();
		}
	}

	return $bytes;
}

// Size of videos/ per camera, split into the automatic videos, the manual ones, the highlight
// pictures and the rest (anything else in the folder). Every camera folder counts, ignored cameras
// too: the disk is filled by what lies on it.
function getVideoStorage(): array
{
	$videoRoot = projectRoot() . "/videos";
	$storage = [
		"cameras" => [],
		"automatic" => 0,
		"manual" => 0,
		"highlights" => 0,
		"other" => 0,
		"total" => 0,
	];
	$entries = is_dir($videoRoot) ? scandir($videoRoot) : false;

	if ($entries === false) {
		return $storage;
	}

	foreach ($entries as $entry) {
		$directory = $videoRoot . "/" . $entry;

		if (!isPlainCameraName($entry) || is_link($directory) || !is_dir($directory)) {
			continue;
		}

		$automatic = 0;

		foreach (AUTOMATIC_VIDEO_FOLDERS as $folder) {
			$automatic += directoryBytes($directory . "/" . $folder);
		}

		$manual = directoryBytes($directory . "/manual-runs");
		$highlights = directoryBytes($directory . "/highlights");
		$total = directoryBytes($directory);
		$other = $total - $automatic - $manual - $highlights;

		$storage["cameras"][$entry] = [
			"automatic" => $automatic,
			"manual" => $manual,
			"highlights" => $highlights,
			"other" => $other,
			"total" => $total,
		];

		$storage["automatic"] += $automatic;
		$storage["manual"] += $manual;
		$storage["highlights"] += $highlights;
		$storage["other"] += $other;
		$storage["total"] += $total;
	}

	return $storage;
}

function storageLevel(float $usedPercent): string
{
	if ($usedPercent >= STORAGE_CRITICAL_PERCENT) {
		return "critical";
	}

	return $usedPercent >= STORAGE_WARN_PERCENT ? "warn" : "ok";
}

// The disk as five parts for the small donut: automatic videos, manual videos, highlight pictures,
// the rest of the used space (system, models, logs) and the free space. File sizes and disk figures
// are read at different moments, so the rest is clamped at 0 and the free part takes what is left.
function storageSegments(
	float $total,
	float $available,
	int $automatic,
	int $manual,
	int $highlights,
): array {
	$used = max(0.0, $total - $available);
	$other = max(0, (int) round($used) - $automatic - $manual - $highlights);
	$free = max(0, (int) round($total) - $automatic - $manual - $highlights - $other);

	$percentOf = static fn(int $bytes): float => $total > 0 ? round($bytes / $total * 100, 1) : 0.0;

	return [
		["key" => "automatic", "bytes" => $automatic, "percent" => $percentOf($automatic)],
		["key" => "manual", "bytes" => $manual, "percent" => $percentOf($manual)],
		["key" => "highlights", "bytes" => $highlights, "percent" => $percentOf($highlights)],
		["key" => "other", "bytes" => $other, "percent" => $percentOf($other)],
		["key" => "free", "bytes" => $free, "percent" => $percentOf($free)],
	];
}

// The disk as one part per camera for the big donut on the settings pages: the biggest cameras
// first (at most $maxCameras), the smaller ones lumped together (a lump of one camera is shown by
// name instead), then the rest of the used space and the free space. The parts add up to the whole disk; parts without bytes are left out.
function storageCameraParts(array $segments, array $videoStorage, int $maxCameras = 6): array
{
	$bytesOf = array_column($segments, "bytes", "key");
	$total = (int) array_sum($bytesOf);

	$cameras = array_filter(
		array_map(static fn(array $camera): int => $camera["total"], $videoStorage["cameras"]),
		static fn(int $bytes): bool => $bytes > 0,
	);
	$names = array_keys($cameras);
	usort($names, static fn($a, $b): int => $cameras[$b] <=> $cameras[$a] ?: strcmp((string) $a, (string) $b));

	$parts = [];

	if (count($names) === $maxCameras + 1) {
		$maxCameras++;
	}

	foreach (array_slice($names, 0, $maxCameras) as $index => $name) {
		$parts[] = [
			"kind" => "camera",
			"label" => (string) $name,
			"bytes" => $cameras[$name],
			"color" => "var(--chart-" . ($index + 1) . ")",
		];
	}

	$rest = array_slice($names, $maxCameras);

	if ($rest !== []) {
		$parts[] = [
			"kind" => "more",
			"label" => "Weitere Kameras (" . count($rest) . ")",
			"bytes" => array_sum(array_map(static fn($name): int => $cameras[$name], $rest)),
			"color" => "var(--chart-7)",
		];
	}

	// File sizes and disk figures are read at different moments: the rest is clamped at 0 and the
	// free part takes what is left, so the parts always add up to the disk.
	$shown = (int) array_sum(array_column($parts, "bytes"));
	$other = max(0, $total - (int) ($bytesOf["free"] ?? 0) - $shown);
	$free = max(0, $total - $shown - $other);

	$parts[] = [
		"kind" => "other",
		"label" => "Sonstiges (System, Modelle, Logs)",
		"bytes" => $other,
		"color" => "var(--color-border-light)",
	];
	$parts[] = ["kind" => "free", "label" => "Frei", "bytes" => $free, "color" => "var(--color-surface-light)"];

	$parts = array_values(array_filter($parts, static fn(array $part): bool => $part["bytes"] > 0));

	return array_map(
		static fn(array $part): array => $part + [
			"percent" => $total > 0 ? round($part["bytes"] / $total * 100, 1) : 0.0,
		],
		$parts,
	);
}

// The parts that are videos (the cameras and the lumped rest), each as a share of all videos: for
// the donut of the videos only.
function storageVideoParts(array $parts): array
{
	$videos = array_values(array_filter(
		$parts,
		static fn(array $part): bool => in_array($part["kind"], ["camera", "more"], true),
	));
	$total = array_sum(array_column($videos, "bytes"));

	return array_map(
		static fn(array $part): array => $part + [
			"videoPercent" => $total > 0 ? round($part["bytes"] / $total * 100, 1) : 0.0,
		],
		$videos,
	);
}

// The arcs of one donut: a circle of pathLength 100, so a dash length is a percent. $of names what the
// percent is a share of ("des Speichers", "der Videos"): the two donuts have different bases.
function storageArcs(array $parts, string $percentKey, string $of): array
{
	$arcs = [];
	$start = 0.0;

	foreach ($parts as $part) {
		$percent = (float) $part[$percentKey];
		$arcs[] = [
			"color" => $part["color"],
			"percent" => $percent,
			"start" => round($start, 1),
			"tip" => $part["label"] . ": " . formatBytes($part["bytes"])
				. " (" . number_format($percent, 1) . " % " . $of . ")",
		];
		$start += $percent;
	}

	return $arcs;
}

function getStorageUsage(): ?array
{
	$videoRoot = projectRoot() . "/videos";

	$total = disk_total_space($videoRoot);
	$available = disk_free_space($videoRoot);

	if ($total === false || $available === false) {
		return null;
	}

	$used = $total - $available;

	$usedPercent = $total > 0
		? ($used / $total) * 100
		: 0;

	$videos = getVideoStorage();

	return [
		"total" => formatBytes($total),
		"used" => formatBytes($used),
		"available" => formatBytes($available),
		"usedPercent" => round($usedPercent, 1),
		"level" => storageLevel($usedPercent),
		"videos" => formatBytes($videos["automatic"] + $videos["manual"]),
		"segments" => storageSegments(
			$total,
			$available,
			$videos["automatic"],
			$videos["manual"],
			$videos["highlights"],
		),
	];
}

function isValidIsoDate(string $value): bool
{
	$date = DateTimeImmutable::createFromFormat(
		"!Y-m-d",
		$value,
	);

	return $date !== false
		&& $date->format("Y-m-d") === $value;
}