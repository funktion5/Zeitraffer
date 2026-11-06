import importlib.util
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest

from src.config import PROJECT_ROOT

# The script's file name has a hyphen, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location(
	"backfill_windows", PROJECT_ROOT / "scripts" / "backfill-windows.py"
)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

SUMMARY = (
	"2026-11-06 14:22:27,963 | INFO | Monthly timelapse job finished for "
	"2026-07-08 to 2026-08-06 | created=1 | skipped=0 | failed={failed}\n"
)


# A clock that moves only when the chain sleeps or a fake window "takes time".
class FakeClock:
	def __init__(self, start: datetime):
		self.current = start
		self.slept: list[int] = []

	def now(self) -> datetime:
		return self.current

	def sleep(self, seconds: int) -> None:
		self.slept.append(seconds)
		self.current += timedelta(seconds=seconds)


# A run lock that is busy for the first busy_times attempts, like the night run or a web job.
def make_lock(busy_times: int = 0):
	state = {"busy": busy_times, "held": False, "attempts": 0}

	@contextmanager
	def acquire():
		state["attempts"] += 1

		if state["busy"] > 0:
			state["busy"] -= 1

			raise RuntimeError("Another timelapse run holds the lock")

		state["held"] = True

		try:
			yield

		finally:
			state["held"] = False

	return acquire, state


def ok_result() -> "backfill.WindowResult":
	return backfill.WindowResult(exit_code=0, failed=0)


# The window is the exact command the web UI runs for a manual Monthly of one camera.
def test_window_command_runs_the_manual_monthly_of_one_camera():
	assert backfill.window_command("python3", "SLSV", date(2026, 6, 7)) == [
		"python3",
		"-m",
		"src.main",
		"--jobs",
		"monthly",
		"--target-date",
		"2026-06-07",
		"--cameras",
		"SLSV",
	]


def test_parse_arguments_keeps_the_dates_in_the_given_order():
	args = backfill.parse_arguments(
		["--camera", "SLSV", "--dates", "2026-06-07", "2026-05-08", "2026-04-08"]
	)

	assert args.camera == "SLSV"
	assert args.dates == [date(2026, 6, 7), date(2026, 5, 8), date(2026, 4, 8)]


# No window starts at night: the night run holds the lock from 02:00. Windows are allowed from
# 05:00 to 22:59.
@pytest.mark.parametrize("hour, minute", [(5, 0), (12, 30), (22, 59)])
def test_seconds_until_allowed_is_zero_during_the_working_hours(hour, minute):
	assert backfill.seconds_until_allowed(datetime(2026, 11, 7, hour, minute)) == 0


@pytest.mark.parametrize(
	"now, expected",
	[
		(datetime(2026, 11, 6, 23, 0, 0), 6 * 3600),
		(datetime(2026, 11, 7, 2, 30, 0), 150 * 60),
		(datetime(2026, 11, 7, 4, 59, 59), 1),
	],
)
def test_seconds_until_allowed_waits_for_05_00_at_night(now, expected):
	assert backfill.seconds_until_allowed(now) == expected


# A camera error is caught and only logged, so the exit code alone says nothing: the job's own
# summary line carries the failed count.
def test_parse_failed_count_reads_the_summary_line():
	assert backfill.parse_failed_count(SUMMARY.format(failed=2)) == 2


def test_parse_failed_count_is_none_without_a_summary_line():
	assert backfill.parse_failed_count("2026-11-06 | INFO | something else\n") is None


@pytest.mark.parametrize(
	"result, expected",
	[
		(backfill.WindowResult(exit_code=0, failed=0), True),
		(backfill.WindowResult(exit_code=1, failed=0), False),
		(backfill.WindowResult(exit_code=0, failed=1), False),
		# No summary line means we cannot tell, so it does not count as good.
		(backfill.WindowResult(exit_code=0, failed=None), False),
	],
)
def test_window_succeeded_needs_exit_zero_and_no_failed_camera(result, expected):
	assert backfill.window_succeeded(result) is expected


def test_chain_runs_the_windows_in_the_given_order_and_holds_the_lock_only_while_one_runs():
	clock = FakeClock(datetime(2026, 11, 7, 9, 0))
	acquire, lock = make_lock()
	ran = []

	def run_window(target_date):
		ran.append((target_date, lock["held"]))

		return ok_result()

	results = backfill.run_chain(
		[date(2026, 6, 7), date(2026, 5, 8)],
		run_window=run_window,
		acquire_lock=acquire,
		now=clock.now,
		sleep=clock.sleep,
	)

	assert ran == [(date(2026, 6, 7), True), (date(2026, 5, 8), True)]
	assert lock["held"] is False
	assert results == [(date(2026, 6, 7), True), (date(2026, 5, 8), True)]


# Today's running window, the night run or a web job: wait five minutes and ask again.
def test_chain_waits_five_minutes_while_the_lock_is_busy():
	clock = FakeClock(datetime(2026, 11, 7, 9, 0))
	acquire, lock = make_lock(busy_times=2)
	ran = []

	def run_window(target_date):
		ran.append(target_date)

		return ok_result()

	backfill.run_chain(
		[date(2026, 6, 7)],
		run_window=run_window,
		acquire_lock=acquire,
		now=clock.now,
		sleep=clock.sleep,
	)

	assert clock.slept == [300, 300]
	assert lock["attempts"] == 3
	assert ran == [date(2026, 6, 7)]


# A window that ends after 23:00 must not be followed by another one before 05:00.
def test_chain_pauses_after_23_00_and_goes_on_at_05_00():
	clock = FakeClock(datetime(2026, 11, 6, 22, 50))
	acquire, _ = make_lock()
	ran_at = []

	def run_window(target_date):
		ran_at.append(clock.current)
		clock.current += timedelta(minutes=30)

		return ok_result()

	backfill.run_chain(
		[date(2026, 6, 7), date(2026, 5, 8)],
		run_window=run_window,
		acquire_lock=acquire,
		now=clock.now,
		sleep=clock.sleep,
	)

	assert ran_at == [datetime(2026, 11, 6, 22, 50), datetime(2026, 11, 7, 5, 0)]
	# From 23:20 to 05:00 the next morning.
	assert clock.slept == [20400]


# If the night run is still going at 05:00, the lock check holds the chain back.
def test_chain_keeps_waiting_when_the_night_run_overruns_05_00():
	clock = FakeClock(datetime(2026, 11, 7, 3, 0))
	acquire, lock = make_lock(busy_times=3)
	ran_at = []

	def run_window(target_date):
		ran_at.append(clock.current)

		return ok_result()

	backfill.run_chain(
		[date(2026, 6, 7)],
		run_window=run_window,
		acquire_lock=acquire,
		now=clock.now,
		sleep=clock.sleep,
	)

	# 03:00 is not allowed: sleep to 05:00 first, then three busy attempts of five minutes each.
	assert clock.slept == [7200, 300, 300, 300]
	assert ran_at == [datetime(2026, 11, 7, 5, 15)]


# One bad window must not stop the others; the result list says which one failed.
def test_chain_goes_on_after_a_failed_window_and_reports_it():
	clock = FakeClock(datetime(2026, 11, 7, 9, 0))
	acquire, _ = make_lock()
	outcomes = {
		date(2026, 6, 7): backfill.WindowResult(exit_code=0, failed=0),
		date(2026, 5, 8): backfill.WindowResult(exit_code=1, failed=None),
		date(2026, 4, 8): backfill.WindowResult(exit_code=0, failed=1),
		date(2026, 3, 9): backfill.WindowResult(exit_code=0, failed=0),
	}
	ran = []

	def run_window(target_date):
		ran.append(target_date)

		return outcomes[target_date]

	results = backfill.run_chain(
		list(outcomes),
		run_window=run_window,
		acquire_lock=acquire,
		now=clock.now,
		sleep=clock.sleep,
	)

	assert ran == list(outcomes)
	assert results == [
		(date(2026, 6, 7), True),
		(date(2026, 5, 8), False),
		(date(2026, 4, 8), False),
		(date(2026, 3, 9), True),
	]


# The frames come from the Storage Box under its default ssh alias, like the web worker's.
def test_start_window_runs_the_command_with_the_default_storage_box_and_reads_the_summary(
	monkeypatch,
):
	monkeypatch.delenv("TIMELAPSE_STORAGE_BOX", raising=False)
	calls = []

	def fake_run(command, **kwargs):
		calls.append((command, kwargs))

		return subprocess.CompletedProcess(
			command, returncode=0, stdout="", stderr=SUMMARY.format(failed=0)
		)

	monkeypatch.setattr(backfill.subprocess, "run", fake_run)

	result = backfill.start_window("SLSV", date(2026, 6, 7))

	command, kwargs = calls[0]

	assert command == backfill.window_command(sys.executable, "SLSV", date(2026, 6, 7))
	assert kwargs["cwd"] == PROJECT_ROOT
	assert kwargs["env"]["TIMELAPSE_STORAGE_BOX"] == "storagebox"
	assert result == backfill.WindowResult(exit_code=0, failed=0)


def test_start_window_keeps_a_storage_box_that_is_already_set(monkeypatch):
	monkeypatch.setenv("TIMELAPSE_STORAGE_BOX", "otherbox")
	calls = []

	def fake_run(command, **kwargs):
		calls.append(kwargs)

		return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="")

	monkeypatch.setattr(backfill.subprocess, "run", fake_run)

	result = backfill.start_window("SLSV", date(2026, 6, 7))

	assert calls[0]["env"]["TIMELAPSE_STORAGE_BOX"] == "otherbox"
	assert result == backfill.WindowResult(exit_code=1, failed=None)


# The exit code tells the person who looks at the log (or cron mail) whether all windows were good.
@pytest.mark.parametrize(
	"results, expected",
	[
		([(date(2026, 6, 7), True), (date(2026, 5, 8), True)], 0),
		([(date(2026, 6, 7), True), (date(2026, 5, 8), False)], 1),
	],
)
def test_main_returns_one_when_a_window_failed(monkeypatch, results, expected):
	monkeypatch.setattr(backfill, "configure_file_logging", lambda *_: None)
	monkeypatch.setattr(backfill, "run_chain", lambda dates, **kwargs: results)

	assert backfill.main(["--camera", "SLSV", "--dates", "2026-06-07", "2026-05-08"]) == expected
