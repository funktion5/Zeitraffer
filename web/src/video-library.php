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

function getIgnoredCameras(): array
{
	$configPath = "/home/zruser/timelapse/config/config.json";

	if (!is_file($configPath) || !is_readable($configPath)) {
		return [];
	}

	$configContent = file_get_contents($configPath);

	if ($configContent === false) {
		return [];
	}

	$config = json_decode($configContent, true);

	if (!is_array($config)) {
		return [];
	}

	$ignoredCameras = $config["ignored_cameras"] ?? [];

	if (!is_array($ignoredCameras)) {
		return [];
	}

	return array_values(
		array_filter(
			$ignoredCameras,
			fn($camera): bool => is_string($camera),
		),
	);
}

function findAvailableCameras(): array
{
	$cameraRoot = "/mnt/cameras";
	$ignoredCameras = getIgnoredCameras();

	if (!is_dir($cameraRoot) || !is_readable($cameraRoot)) {
		return [];
	}

	$cameras = [];

	foreach (scandir($cameraRoot) as $entry) {
		if ($entry === "." || $entry === "..") {
			continue;
		}

		if (str_starts_with($entry, ".")) {
			continue;
		}

		if (in_array($entry, $ignoredCameras, true)) {
			continue;
		}

		$cameraPath = $cameraRoot . "/" . $entry;

		if (is_dir($cameraPath)) {
			$cameras[] = $entry;
		}
	}

	natcasesort($cameras);

	return array_values($cameras);
}

function findManualVideos(string $camera): array
{
	$manualRoot = "/home/zruser/timelapse/videos/"
		. $camera
		. "/manual-runs";

	if (!is_dir($manualRoot) || !is_readable($manualRoot)) {
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
		$jobPath = $manualRoot . "/" . $job;

		if (!is_dir($jobPath) || !is_readable($jobPath)) {
			continue;
		}

		foreach (scandir($jobPath) as $filename) {
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
				"url" => "/videos/"
					. rawurlencode($camera)
					. "/manual-runs/"
					. rawurlencode($job)
					. "/"
					. rawurlencode($filename),
			];
		}

		if (isset($videos[$job])) {
			usort(
				$videos[$job],
				fn(array $left, array $right): int => strcmp(
					($right["date"] ?? $right["filename"]) . ($right["bufferMinutes"] ?? ""),
					($left["date"] ?? $left["filename"]) . ($left["bufferMinutes"] ?? ""),
				),
			);
		}
	}

	return $videos;
}

// Extracts the ISO target date and, if present, the daylight buffer (in
// minutes) from a manual-run filename (`{camera}_{date}.mp4` or
// `{camera}_{date}_{buffer}min.mp4`). Both come back null if the filename
// doesn't match either pattern. Never guesses: an unexpected filename just
// falls back to sorting/displaying by the raw filename.
function extractManualVideoMetadata(string $camera, string $filename): array
{
	$pattern = "/^" . preg_quote($camera, "/") . "_(\d{4}-\d{2}-\d{2})(?:_(\d+)min)?\.mp4$/";

	if (preg_match($pattern, $filename, $matches) !== 1 || !isValidIsoDate($matches[1])) {
		return [
			"date" => null,
			"bufferMinutes" => null,
		];
	}

	return [
		"date" => $matches[1],
		"bufferMinutes" => isset($matches[2]) && $matches[2] !== "" ? (int) $matches[2] : null,
	];
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
	$videoRoot = "/home/zruser/timelapse/videos";

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