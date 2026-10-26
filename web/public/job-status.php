<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/json-response.php";


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

$statusRoot = getenv("TIMELAPSE_WEB_STATUS_ROOT")
	?: dirname(__DIR__, 2) . "/state/web-jobs";
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

	// The worker writes its PID within a second of the trigger's "running"; none after a minute
	// means it never got going (and the browser would keep the create button locked).
	} elseif (time() - (int) filemtime($statusFile) > 60) {
		$status = "failed";
	}
}

$payload = ["status" => $status];
$reasonFile = $statusRoot . "/" . $jobId . ".reason";

if ($status === "failed" && is_file($reasonFile) && is_readable($reasonFile)) {
	$reason = describeFailureReason((string) file_get_contents($reasonFile));

	if ($reason !== null) {
		$payload["reason"] = $reason;
	}
}

respondWithJson(200, $payload);
