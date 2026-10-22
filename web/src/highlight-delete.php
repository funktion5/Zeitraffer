<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";


function deleteHighlightImage(
	string $camera,
	string $date,
	string $filename,
): array {
	$runUser = projectRunUser();

	if ($runUser === null) {
		error_log("Highlight delete wrapper not started: owner of the project folder could not be determined.");

		return [
			"deleted" => false,
			"message" => "Das Bild konnte nicht gelöscht werden.",
		];
	}

	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		$runUser,
		"/usr/local/sbin/timelapse-web-delete-highlight",
		$camera,
		$date,
		$filename,
	]);

	if ($result["exitCode"] === 0) {
		return [
			"deleted" => true,
			"message" => $result["stdout"] !== "" ? $result["stdout"] : "Bild erfolgreich gelöscht.",
		];
	}

	if ($result["exitCode"] !== null) {
		error_log("Highlight delete wrapper failed with exit code {$result["exitCode"]}: {$result["stderr"]}");
	}

	return [
		"deleted" => false,
		"message" => "Das Bild konnte nicht gelöscht werden.",
	];
}
