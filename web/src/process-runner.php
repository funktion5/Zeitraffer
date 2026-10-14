<?php

declare(strict_types=1);


// The wrappers run as the account that owns the project folder (two levels above web/src/), so
// the account name is not hardcoded. Null when it cannot be determined or would be root: the
// caller then refuses instead of guessing.
function projectRunUser(): ?string
{
	$owner = fileowner(dirname(__DIR__, 2));

	if ($owner === false || $owner === 0) {
		return null;
	}

	$entry = posix_getpwuid($owner);

	return $entry === false ? null : $entry["name"];
}

// Shared by the video-trigger and video-delete wrappers so the sudo/proc_open
// handling only needs to be correct in one place.
function runPrivilegedCommand(array $command): array
{
	$descriptors = [
		0 => ["pipe", "r"],
		1 => ["pipe", "w"],
		2 => ["pipe", "w"],
	];

	$process = proc_open(
		$command,
		$descriptors,
		$pipes,
		null,
		null,
		["bypass_shell" => true],
	);

	if (!is_resource($process)) {
		return [
			"exitCode" => null,
			"stdout" => "",
			"stderr" => "",
		];
	}

	fclose($pipes[0]);

	$stdout = trim(stream_get_contents($pipes[1]));
	$stderr = trim(stream_get_contents($pipes[2]));

	fclose($pipes[1]);
	fclose($pipes[2]);

	$exitCode = proc_close($process);

	return [
		"exitCode" => $exitCode,
		"stdout" => $stdout,
		"stderr" => $stderr,
	];
}
