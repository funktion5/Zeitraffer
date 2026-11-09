<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";


// Starts the upload of ONE camera's newest automatic videos through the root-owned trigger. Only
// the camera name reaches it: which files go is decided by the delivery script on the server
// (never by the browser), and where they go is its configuration. camera.php has already checked
// the camera and the confirmation; the trigger checks the camera again. Same return shape as
// startVideoJob() in job-runner.php.
function startPublishJob(string $camera): array
{
	$notStarted = static fn (string $message): array => [
		"started" => false,
		"jobId" => null,
		"message" => $message,
	];

	$runUser = projectRunUser();

	if ($runUser === null) {
		error_log("Publish wrapper not started: owner of the project folder could not be determined.");

		return $notStarted("Der Videoauftrag konnte nicht gestartet werden.");
	}

	$jobId = bin2hex(random_bytes(16));

	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		$runUser,
		"/usr/local/sbin/timelapse-web-publish",
		$jobId,
		$camera,
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

	error_log("Publish wrapper failed with exit code {$result["exitCode"]}: {$result["stderr"]}");

	return $notStarted("Der Videoauftrag wurde abgelehnt oder konnte nicht gestartet werden.");
}
