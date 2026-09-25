<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";


function deleteManualVideo(
	string $camera,
	string $job,
	string $filename,
): array {
	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		"zruser",
		"/usr/local/sbin/timelapse-web-delete",
		$camera,
		$job,
		$filename,
	]);

	if ($result["exitCode"] === 0) {
		return [
			"deleted" => true,
			"message" => $result["stdout"] !== "" ? $result["stdout"] : "Video erfolgreich gelöscht.",
		];
	}

	if ($result["exitCode"] !== null) {
		error_log("Video delete wrapper failed with exit code {$result["exitCode"]}: {$result["stderr"]}");
	}

	return [
		"deleted" => false,
		"message" => "Das Video konnte nicht gelöscht werden.",
	];
}
