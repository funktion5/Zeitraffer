"""Run several Monthly windows of one camera one after another, unattended.

Helper for the blur backfill. Every window is the command the web UI runs for a manual Monthly:
it blurs the window's frames on the Storage Box first and builds the video in manual-runs/. The
chain takes the shared run lock for one window at a time and waits while it is busy (a web job,
the night run), starts no window between 23:00 and 05:00, and goes on with the next window after
a failure. The exit code is 1 if any window failed, so the log shows which ones.

Run from anywhere; nohup keeps it alive after the ssh session ends:
	nohup .venv/bin/python3 scripts/backfill-windows.py --camera SLSV \
		--dates 2026-06-07 2026-05-08 > /dev/null 2>&1 &
"""

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The video, log and camera paths in src/ are relative to the project root.
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.image_worker import exit_on_sigterm  # noqa: E402
from src.logger import RUN_ID, configure_file_logging, logger  # noqa: E402
from src.storage_filter import acquire_run_lock  # noqa: E402

# The night run holds the lock from 02:00; a window takes about two hours at most, so none is
# started after 23:00 and the chain sleeps until 05:00, when the night run is long done.
STOP_HOUR = 23
RESUME_HOUR = 5
LOCK_RETRY_SECONDS = 300

SUMMARY_PATTERN = re.compile(r"timelapse job finished .*failed=(\d+)")


@dataclass(frozen=True)
class WindowResult:
	exit_code: int
	# The failed count of the job's summary line; None when no such line was found.
	failed: int | None


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--camera", required=True)
	parser.add_argument(
		"--dates",
		nargs="+",
		required=True,
		type=date.fromisoformat,
		help="The last day (Zieldatum) of every window, in the order they should run.",
	)

	return parser.parse_args(argv)


def window_command(python: str, camera: str, target_date: date) -> list[str]:
	return [
		python,
		"-m",
		"src.main",
		"--jobs",
		"monthly",
		"--target-date",
		target_date.isoformat(),
		"--cameras",
		camera,
	]


# A camera error is caught and only logged by the job, so its exit code is not enough: the
# summary line carries the failed count.
def parse_failed_count(output: str) -> int | None:
	counts = SUMMARY_PATTERN.findall(output)

	return int(counts[-1]) if counts else None


def window_succeeded(result: WindowResult) -> bool:
	return result.exit_code == 0 and result.failed == 0


def seconds_until_allowed(now: datetime) -> int:
	if RESUME_HOUR <= now.hour < STOP_HOUR:
		return 0

	resume = now.replace(hour=RESUME_HOUR, minute=0, second=0, microsecond=0)

	if now.hour >= STOP_HOUR:
		resume += timedelta(days=1)

	return int((resume - now).total_seconds())


def start_window(camera: str, target_date: date) -> WindowResult:
	# Without a local camera folder the frames come from the Storage Box; a nohup shell may not
	# name its ssh alias, so give the same default as the web worker.
	environment = os.environ.copy()
	environment.setdefault("TIMELAPSE_STORAGE_BOX", "storagebox")

	completed = subprocess.run(
		window_command(sys.executable, camera, target_date),
		cwd=PROJECT_ROOT,
		env=environment,
		stdin=subprocess.DEVNULL,
		stdout=subprocess.DEVNULL,
		stderr=subprocess.PIPE,
		text=True,
		errors="replace",
		check=False,
	)

	return WindowResult(
		exit_code=completed.returncode,
		failed=parse_failed_count(completed.stderr),
	)


# Returns (window, succeeded) in the order the windows ran. The lock is held only while one
# window runs, so the night run and the web UI can take it between two windows.
def run_chain(
	dates: list[date],
	*,
	run_window: Callable[[date], WindowResult],
	acquire_lock: Callable[[], AbstractContextManager[None]],
	now: Callable[[], datetime],
	sleep: Callable[[int], None],
) -> list[tuple[date, bool]]:
	results: list[tuple[date, bool]] = []

	for target_date in dates:
		result = None

		while result is None:
			wait = seconds_until_allowed(now())

			if wait:
				logger.info(
					f"Window {target_date}: paused for {wait} s "
					f"(no windows {STOP_HOUR}:00 - {RESUME_HOUR:02d}:00)"
				)
				sleep(wait)

				continue

			with ExitStack() as stack:
				# Only taking the lock may fail with this error; an error inside the window must
				# not be mistaken for a busy lock.
				try:
					stack.enter_context(acquire_lock())

				except RuntimeError:
					logger.info(f"Run lock is busy, trying again in {LOCK_RETRY_SECONDS} s")
					sleep(LOCK_RETRY_SECONDS)

					continue

				logger.info(f"Starting window {target_date}")
				result = run_window(target_date)

		succeeded = window_succeeded(result)
		logger.info(
			f"Window {target_date} {'finished' if succeeded else 'FAILED'} | "
			f"exit_code={result.exit_code} | failed={result.failed}"
		)
		results.append((target_date, succeeded))

	return results


def main(argv: list[str] | None = None) -> int:
	args = parse_arguments(argv)

	# The windows are Monthly jobs, so the chain logs into the same file as the web jobs.
	configure_file_logging("monthly")

	logger.info("-" * 80)
	logger.info(
		f"Starting window chain | camera={args.camera} | "
		f"windows={', '.join(d.isoformat() for d in args.dates)} | run_id={RUN_ID}"
	)

	results = run_chain(
		args.dates,
		run_window=lambda target_date: start_window(args.camera, target_date),
		acquire_lock=acquire_run_lock,
		now=datetime.now,
		sleep=time.sleep,
	)

	failed = [target_date.isoformat() for target_date, succeeded in results if not succeeded]
	logger.info(
		f"Window chain finished | ok={len(results) - len(failed)} | "
		f"failed={', '.join(failed) if failed else 'none'}"
	)

	return 1 if failed else 0


if __name__ == "__main__":
	exit_on_sigterm()
	sys.exit(main())
