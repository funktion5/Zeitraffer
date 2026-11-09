<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";


// Starts a rebuild of the automatic videos of ONE camera through the root-owned trigger. Only the
// camera and the job names reach it, and camera.php has already checked both; the trigger checks
// them again. Same return shape as startVideoJob() in job-runner.php.
function startRebuildJob(string $camera, array $jobs): array
{
	$notStarted = static fn (string $message): array => [
		"started" => false,
		"jobId" => null,
		"message" => $message,
	];

	$runUser = projectRunUser();

	if ($runUser === null) {
		error_log("Rebuild wrapper not started: owner of the project folder could not be determined.");

		return $notStarted("Der Videoauftrag konnte nicht gestartet werden.");
	}

	$jobId = bin2hex(random_bytes(16));

	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		$runUser,
		"/usr/local/sbin/timelapse-web-rebuild",
		$jobId,
		$camera,
		...array_values($jobs),
	]);

	if ($result["exitCode"] === null) {
		return $notStarted("Der Videoauftrag konnte nicht gestartet werden.");
	}

	if ($result["exitCode"] === 0) {
		return [
			"started" => true,
			"jobId" => $jobId,
			"message" => $result["stdout"] !== "" ? $result["stdout"] : "Der Videoauftrag wurde angenommen.",
		];
	}

	// 75 is the wrapper's "run lock already held" code.
	if ($result["exitCode"] === 75) {
		return $notStarted("Es läuft bereits ein anderer Zeitraffer-Auftrag.");
	}

	error_log("Rebuild wrapper failed with exit code {$result["exitCode"]}: {$result["stderr"]}");

	return $notStarted("Der Videoauftrag wurde abgelehnt oder konnte nicht gestartet werden.");
}
