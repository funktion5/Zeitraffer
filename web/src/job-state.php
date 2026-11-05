<?php

declare(strict_types=1);


// The folder of the web jobs' status files; tests point it elsewhere with the environment variable.
function webStatusRoot(): string
{
	// __DIR__ is web/src, so the project root is two levels up.
	return getenv("TIMELAPSE_WEB_STATUS_ROOT") ?: dirname(__DIR__, 2) . "/state/web-jobs";
}


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


// A "running" status only means the worker hasn't reported a final result
// yet — it doesn't confirm the worker process is still alive. Cross-check
// against its recorded PID so a process killed outright (e.g. by a reboot)
// is reported as failed instead of leaving the client polling forever.
// Read-only: this is recomputed per request, never written back to the status file.
function resolveJobStatus(string $statusRoot, string $jobId, string $status): string
{
	if ($status !== "running") {
		return $status;
	}

	$pidFile = $statusRoot . "/" . $jobId . ".pid";

	if (is_file($pidFile) && is_readable($pidFile)) {
		$pid = trim((string) file_get_contents($pidFile));

		if (ctype_digit($pid) && !isWorkerPidAlive((int) $pid)) {
			return "failed";
		}

		return "running";
	}

	// The worker writes its PID within a second of the trigger's "running"; none after a minute
	// means it never got going (and the browser would keep the create button locked).
	if (time() - (int) filemtime($statusRoot . "/" . $jobId . ".status") > 60) {
		return "failed";
	}

	return "running";
}


// Whether any web job is running right now (the camera pages show a notice for it). Only files
// named like a job ID count: the folder also holds cameras.json and the like.
function hasRunningWebJob(string $statusRoot): bool
{
	foreach (glob($statusRoot . "/*.status") ?: [] as $statusFile) {
		$jobId = basename($statusFile, ".status");

		if (preg_match("/^[a-f0-9]{32}$/", $jobId) !== 1 || !is_readable($statusFile)) {
			continue;
		}

		$status = trim((string) file_get_contents($statusFile));

		if (resolveJobStatus($statusRoot, $jobId, $status) === "running") {
			return true;
		}
	}

	return false;
}
