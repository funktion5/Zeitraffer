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

			$videos[$job][] = [
				"filename" => $filename,
				"date" => extractManualVideoDate($camera, $filename),
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
					$right["date"] ?? $right["filename"],
					$left["date"] ?? $left["filename"],
				),
			);
		}
	}

	return $videos;
}

// Extracts the ISO target date from a manual-run filename (`{camera}_{date}.mp4`),
// or null if the filename doesn't match that pattern. Never guesses: an
// unexpected filename just falls back to sorting/displaying by filename.
function extractManualVideoDate(string $camera, string $filename): ?string
{
	$prefix = $camera . "_";

	if (!str_starts_with($filename, $prefix) || !str_ends_with($filename, ".mp4")) {
		return null;
	}

	$datePart = substr($filename, strlen($prefix), -4);

	return isValidIsoDate($datePart) ? $datePart : null;
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