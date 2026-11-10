<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";

// The two settings files, one per tab: the scope names the file on the host, so nothing else may
// reach the wrapper.
const SETTINGS_SCOPES = ["general", "privacy"];

const SETTINGS_SAVE_FAILED_MESSAGE = "Die Einstellungen konnten nicht gespeichert werden.";
const SETTINGS_INVALID_MESSAGE = "Die Eingaben sind ungültig.";

// The one JSON line the settings writer prints, or null when the output is not a JSON object with
// a text "status".
function decodeSettingsReply(string $stdout): ?array
{
	$reply = json_decode($stdout, true);

	return is_array($reply) && is_string($reply["status"] ?? null) ? $reply : null;
}

// Saves the values of the settings page through the root-owned wrapper. The values travel as ONE
// JSON argument next to the modification time of the settings file the page was loaded with; the
// wrapper and the writer behind it validate everything again, so nothing here is trusted either way.
// Returns ["status" => "saved" | "invalid" | "stale" | "failed", "errors" => string[], "mtime" => int].
// A failure's details go to the server log only, never into the result.
function saveSettings(array $values, int $loadedMtime, string $scope = "general"): array
{
	$failed = static fn(): array => [
		"status" => "failed",
		"errors" => [SETTINGS_SAVE_FAILED_MESSAGE],
		"mtime" => $loadedMtime,
	];

	if (!in_array($scope, SETTINGS_SCOPES, true)) {
		error_log("Settings wrapper not started: unknown scope.");

		return $failed();
	}

	$runUser = projectRunUser();

	if ($runUser === null) {
		error_log("Settings wrapper not started: owner of the project folder could not be determined.");

		return $failed();
	}

	$json = json_encode($values);

	if ($json === false) {
		error_log("Settings wrapper not started: the values could not be encoded as JSON.");

		return $failed();
	}

	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		$runUser,
		"/usr/local/sbin/timelapse-web-settings",
		$scope,
		(string) $loadedMtime,
		$json,
	]);

	if ($result["exitCode"] === null) {
		return $failed();
	}

	$reply = decodeSettingsReply($result["stdout"]);
	$status = $reply["status"] ?? null;
	$mtime = is_int($reply["mtime"] ?? null) ? $reply["mtime"] : $loadedMtime;

	// 0 saved, 65 invalid values, 73 the file changed since the page loaded (see the wrapper). A
	// reply that does not belong to its exit code is treated like any other failure.
	if ($result["exitCode"] === 0 && $status === "saved") {
		return ["status" => "saved", "errors" => [], "mtime" => $mtime];
	}

	if ($result["exitCode"] === 73 && $status === "stale") {
		return ["status" => "stale", "errors" => [], "mtime" => $mtime];
	}

	if ($result["exitCode"] === 65 && $status === "invalid") {
		$errors = array_values(
			array_filter(is_array($reply["errors"] ?? null) ? $reply["errors"] : [], is_string(...)),
		);

		return [
			"status" => "invalid",
			"errors" => $errors === [] ? [SETTINGS_INVALID_MESSAGE] : $errors,
			"mtime" => $mtime,
		];
	}

	error_log("Settings wrapper failed with exit code {$result["exitCode"]}: {$result["stderr"]}");

	return $failed();
}
