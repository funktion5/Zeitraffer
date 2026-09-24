<?php

declare(strict_types=1);


// Return one JSON response and stop endpoint processing.
function respondWithJson(int $statusCode, array $payload): never
{
	http_response_code($statusCode);
	header("Content-Type: application/json; charset=UTF-8");
	header("Cache-Control: no-store");

	echo json_encode(
		$payload,
		JSON_THROW_ON_ERROR,
	);

	exit;
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

$statusRoot = getenv("TIMELAPSE_WEB_STATUS_ROOT")
	?: "/home/zruser/timelapse/state/web-jobs";
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

respondWithJson(
	200,
	["status" => $status],
);
