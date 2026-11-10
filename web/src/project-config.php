<?php

declare(strict_types=1);

// Needs projectRoot() from video-library.php, which loads this file.

// The settings the web UI settings page may change, as dotted keys. config/settings.json lays these,
// and only these, over config/config.json. src/settings.py is the source of truth and a test
// compares the two lists, so they cannot drift apart. PHP checks no ranges: the writer validates
// every save.
const SETTINGS_ALLOWED_KEYS = [
	"timelapse.crf",
	"timelapse.daily_framerate",
	"timelapse.monthly_framerate",
	"timelapse.yearly_framerate",
	"ignored_cameras",
	"flagger.cameras",
	"flagger.retention_days",
	"daylight_buffer_minutes",
	"automatic_daylight_buffer_minutes.1",
	"automatic_daylight_buffer_minutes.2",
	"automatic_daylight_buffer_minutes.3",
	"automatic_daylight_buffer_minutes.4",
	"automatic_daylight_buffer_minutes.5",
	"automatic_daylight_buffer_minutes.6",
	"automatic_daylight_buffer_minutes.7",
	"automatic_daylight_buffer_minutes.8",
	"automatic_daylight_buffer_minutes.9",
	"automatic_daylight_buffer_minutes.10",
	"automatic_daylight_buffer_minutes.11",
	"automatic_daylight_buffer_minutes.12",
	"interval_window.target_time",
	"interval_window.tolerance_minutes",
	"min_coverage_days.monthly",
	"min_coverage_days.yearly",
	"log_retention_days",
];

// The privacy tab's own scope: its keys live in config/settings-privacy.json, so a save on one tab
// never touches the other tab's settings. The same rule as above: names only, and a test compares
// this list with the Python one.
const PRIVACY_SETTINGS_ALLOWED_KEYS = [
	"privacy.blur_cameras",
];

const SETTINGS_SCOPE_KEYS = [
	"general" => SETTINGS_ALLOWED_KEYS,
	"privacy" => PRIVACY_SETTINGS_ALLOWED_KEYS,
];

// A JSON file as an array. A missing, unreadable or broken file, or one that holds no array or
// object, gives an empty array.
function readJsonObjectFile(string $path): array
{
	if (!is_file($path) || !is_readable($path)) {
		return [];
	}

	$content = file_get_contents($path);

	if ($content === false) {
		return [];
	}

	$decoded = json_decode($content, true);

	return is_array($decoded) ? $decoded : [];
}

// The decoded config/config.json alone, without the saved settings. The settings page shows its
// values as the "Standard".
function readBaseConfig(): array
{
	return readJsonObjectFile(projectRoot() . "/config/config.json");
}

// The file of a settings scope: "general" is the Allgemein tab, "privacy" the Verpixelung tab.
function settingsFilePath(string $scope = "general"): string
{
	$name = match ($scope) {
		"general" => "settings.json",
		"privacy" => "settings-privacy.json",
		default => throw new InvalidArgumentException("Unknown settings scope."),
	};

	return projectRoot() . "/config/" . $name;
}

// The settings file's modification time in whole seconds, 0 when there is no file. The settings
// page hands it back on save, so a save from an outdated page can be refused. One time per scope:
// a save on one tab never makes the other tab's page out of date.
function readSettingsMtime(string $scope = "general"): int
{
	$path = settingsFilePath($scope);

	if (!is_file($path)) {
		return 0;
	}

	$mtime = filemtime($path);

	return $mtime === false ? 0 : $mtime;
}

// [found, value] for a dotted key of a nested array.
function settingsLeaf(array $source, string $dottedKey): array
{
	$node = $source;

	foreach (explode(".", $dottedKey) as $part) {
		if (!is_array($node) || !array_key_exists($part, $node)) {
			return [false, null];
		}

		$node = $node[$part];
	}

	return [true, $node];
}

function setSettingsLeaf(array &$target, string $dottedKey, mixed $value): void
{
	$parts = explode(".", $dottedKey);
	$last = array_pop($parts);
	$node = &$target;

	foreach ($parts as $part) {
		if (!isset($node[$part]) || !is_array($node[$part])) {
			$node[$part] = [];
		}

		$node = &$node[$part];
	}

	$node[$last] = $value;
}

// The config the jobs use: config/config.json with the allowlisted keys of config/settings.json laid
// over it. Every other key in the settings file is ignored, and so is a missing or broken file.
function readProjectConfig(): array
{
	$config = readBaseConfig();

	// Each file only applies the keys of its own scope.
	foreach (SETTINGS_SCOPE_KEYS as $scope => $keys) {
		$settings = readJsonObjectFile(settingsFilePath($scope));

		foreach ($keys as $key) {
			[$found, $value] = settingsLeaf($settings, $key);

			if ($found) {
				setSettingsLeaf($config, $key, $value);
			}
		}
	}

	return $config;
}
