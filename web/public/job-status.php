<?php

declare(strict_types=1);


// Whether /proc/<pid> both exists and still looks like our own worker script,
// guarding against a stale PID having since been reused by an unrelated process.
function isWorkerPidAlive(int $pid): bool
{
	$cmdlinePath = "/proc/{$pid}/cmdline";

	if (!is_readable($cmdlinePath)) {
		return false;
	}

	$cmdline = file_get_contents($cmdlinePath);

	return $cmdline !== false && str_contains($cmdline, "timelapse-web-worker");
}


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

// A "running" status only means the worker hasn't reported a final result
// yet — it doesn't confirm the worker process is still alive. Cross-check
// against its recorded PID so a process killed outright (e.g. by a reboot)
// is reported as failed instead of leaving the client polling forever.
// job-status.php stays read-only: this is recomputed per request, never
// written back to the status file.
if ($status === "running") {
	$pidFile = $statusRoot . "/" . $jobId . ".pid";

	if (is_file($pidFile) && is_readable($pidFile)) {
		$pid = trim((string) file_get_contents($pidFile));

		if (ctype_digit($pid) && !isWorkerPidAlive((int) $pid)) {
			$status = "failed";
		}
	}
}

respondWithJson(
	200,
	["status" => $status],
);
