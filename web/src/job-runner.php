<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";


function startVideoJob(string $job, string $targetDate, string $camera, int $daylightBufferMinutes): array
{
	$jobId = bin2hex(random_bytes(16));

	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		"zruser",
		"/usr/local/sbin/timelapse-web-trigger",
		$jobId,
		$job,
		$targetDate,
		$camera,
		(string) $daylightBufferMinutes,
	]);

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
