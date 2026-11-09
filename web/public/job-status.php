<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/json-response.php";
require_once __DIR__ . "/../src/job-state.php";


// German text for the known reasons a historical run ends without a video (the worker keeps
// src.main's last warning). Anything else gives null: log text never reaches the browser.
function describeFailureReason(string $warning): ?string
{
	if (preg_match('/coverage too low: (\d+) of (\d+) days available \(minimum (\d+)\)/', $warning, $match) === 1) {
		return "Zu wenige Tage mit Bildern im Zeitfenster: {$match[1]} von {$match[2]} (mindestens {$match[3]}).";
	}

	if (preg_match('/Weekly image coverage incomplete: (\d+) of 7 days/', $warning, $match) === 1) {
		return "Nur an {$match[1]} von 7 Tagen gibt es Bilder; Wöchentlich braucht alle 7.";
	}

	if (str_contains($warning, "Found 0 images")) {
		return "Für diesen Tag wurden keine Bilder gefunden.";
	}

	if (preg_match('/No valid \w+ images available/', $warning) === 1) {
		return "Im gewählten Zeitraum gibt es keine verwendbaren Bilder.";
	}

	// The blur of a blur camera's frames on the box did not finish, so no video was built.
	if (preg_match('/Blur not finished: (\d+) of (\d+) not blurred yet/', $warning, $match) === 1) {
		return "Von {$match[2]} Bildern sind {$match[1]} noch nicht verpixelt, deshalb wurde kein Video erstellt. "
			. "Bitte den Auftrag noch einmal starten.";
	}

	if (str_contains($warning, "Blur not finished: another blur run holds the lock")) {
		return "Gerade läuft eine andere Verpixelung. Bitte später noch einmal versuchen.";
	}

	return null;
}


if ($_SERVER["REQUEST_METHOD"] !== "GET") {
	respondWithJson(
		405,
		["error" => "Method not allowed."],
	);
}

$jobId = $_GET["id"] ?? null;

if (!is_string($jobId) || preg_match("/^[a-f0-9]{32}$/", $jobId) !== 1) {
	respondWithJson(
		400,
		["error" => "Invalid job ID."],
	);
}

$statusRoot = webStatusRoot();
$statusFile = $statusRoot . "/" . $jobId . ".status";

if (!is_file($statusFile) || !is_readable($statusFile)) {
	respondWithJson(
		404,
		["error" => "Job status not found."],
	);
}

$status = trim((string) file_get_contents($statusFile));
$allowedStatuses = [
	"running",
	"completed",
	"failed",
];

if (!in_array($status, $allowedStatuses, true)) {
	respondWithJson(
		500,
		["error" => "Invalid stored job status."],
	);
}

// "running" in the file only means no final result yet: job-state.php checks that the worker is
// still alive. This endpoint stays read-only; nothing is written back to the status file.
$status = resolveJobStatus($statusRoot, $jobId, $status);

$payload = ["status" => $status];
$reasonFile = $statusRoot . "/" . $jobId . ".reason";

if ($status === "failed" && is_file($reasonFile) && is_readable($reasonFile)) {
	$reason = describeFailureReason((string) file_get_contents($reasonFile));

	if ($reason !== null) {
		$payload["reason"] = $reason;
	}
}

// A rebuild leaves one line per finished job; the page shows them under the final message.
$results = readJobResults($statusRoot, $jobId);

if ($results !== []) {
	$payload["results"] = $results;
}

respondWithJson(200, $payload);
