<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";


function startVideoJob(
	string $job,
	string $targetDate,
	string $camera,
	?string $windowTime = null,
	?int $windowToleranceMinutes = null,
): array {
	$runUser = projectRunUser();

	if ($runUser === null) {
		error_log("Video wrapper not started: owner of the project folder could not be determined.");

		return [
			"started" => false,
			"jobId" => null,
			"message" => "Der Videoauftrag konnte nicht gestartet werden.",
		];
	}

	$jobId = bin2hex(random_bytes(16));

	$command = [
		"/usr/bin/sudo",
		"-n",
		"-u",
		$runUser,
		"/usr/local/sbin/timelapse-web-trigger",
		$jobId,
		$job,
		$targetDate,
		$camera,
	];

	// A Daily/Weekly gets no daylight buffer here: the job uses the saved setting. Monthly/Yearly
	// may add an interval window, both values or neither (the wrapper takes four arguments, or
	// six with a window).
	if ($windowTime !== null && $windowToleranceMinutes !== null) {
		$command[] = $windowTime;
		$command[] = (string) $windowToleranceMinutes;
	}

	$result = runPrivilegedCommand($command);

	if ($result["exitCode"] === null) {
		return [
			"started" => false,
			"jobId" => null,
			"message" => "Der Videoauftrag konnte nicht gestartet werden.",
		];
	}

	if ($result["exitCode"] === 0) {
		return [
			"started" => true,
			"jobId" => $jobId,
			"message" => $result["stdout"] !== "" ? $result["stdout"] : "Der Videoauftrag wurde angenommen.",
		];
	}

	if ($result["exitCode"] === 75) {
		return [
			"started" => false,
			"jobId" => null,
			"message" => "Es läuft bereits ein anderer Zeitraffer-Auftrag.",
		];
	}

	error_log("Video wrapper failed with exit code {$result["exitCode"]}: {$result["stderr"]}");

	return [
		"started" => false,
		"jobId" => null,
		"message" => "Der Videoauftrag wurde abgelehnt oder konnte nicht gestartet werden.",
	];
}
