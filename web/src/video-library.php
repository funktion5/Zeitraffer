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

// The decoded config/config.json. A missing, unreadable or broken file gives an empty array.
function readProjectConfig(): array
{
	$configPath = projectRoot() . "/config/config.json";

	if (!is_file($configPath) || !is_readable($configPath)) {
		return [];
	}

	$configContent = file_get_contents($configPath);

	if ($configContent === false) {
		return [];
	}

	$config = json_decode($configContent, true);

	return is_array($config) ? $config : [];
}

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

// The camera names come from state/web-jobs/cameras.json, which the nightly run writes
// (python3 -m src.camera_list): the web server user has no ssh key and the storage is not mounted
// on this host. A missing or unusable file gives an empty list.
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
		// The names end up in file paths, so only plain names pass: the pattern the Python side
		// applies to the storage listing. It also keeps out ".", "..", hidden entries and "/".
		// The D modifier stops "$" from accepting a trailing newline.
		if (!is_string($entry) || preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*$/D', $entry) !== 1) {
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
// goes (scripts/list-deliverable-videos.py); this mirrors its rules so the page shows the same
// list: only the four period folders directly under the camera folder, no symlinks, and in them
// the newest BY FILE NAME among the regular, non-empty, non-hidden *.mp4 files (".mp4" in lower
// case only, as its glob). Test renders in manual-runs/ and the like are never looked at. The
// camera folder's own ignored_cameras rule is already applied by findAvailableCameras().
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

	return [
		"total" => formatBytes($total),
		"used" => formatBytes($used),
		"available" => formatBytes($available),
		"usedPercent" => round($usedPercent, 1),
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