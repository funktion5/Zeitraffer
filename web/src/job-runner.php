<?php

declare(strict_types=1);


function startVideoJob(string $job, string $targetDate, string $camera): array
{
	$jobId = bin2hex(random_bytes(16));

	$command = [
		"/usr/bin/sudo",
		"-n",
		"-u",
		"zruser",
		"/usr/local/sbin/timelapse-web-trigger",
		$jobId,
		$job,
		$targetDate,
		$camera,
	];

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
			"started" => false,
			"jobId" => null,
			"message" => "The video job could not be started.",
		];
	}

	fclose($pipes[0]);
	$stdout = trim(stream_get_contents($pipes[1]));
	$stderr = trim(stream_get_contents($pipes[2]));
	fclose($pipes[1]);
	fclose($pipes[2]);

	$exitCode = proc_close($process);

	if ($exitCode === 0) {
		return [
			"started" => true,
			"jobId" => $jobId,
			"message" => $stdout !== "" ? $stdout : "The video job was accepted.",
		];
	}

	if ($exitCode === 75) {
		return [
			"started" => false,
			"jobId" => null,
			"message" => "Another timelapse job is already running.",
		];
	}

	error_log("Video wrapper failed with exit code {$exitCode}: {$stderr}");

	return [
		"started" => false,
		"jobId" => null,
		"message" => "The video job was rejected or could not be started.",
	];
}
