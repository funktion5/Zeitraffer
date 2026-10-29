import os
import signal
import threading
import time
from pathlib import Path

import pytest

import src.image_worker as image_worker_module
from src.image_worker import exit_on_sigterm, run_isolated_worker


# Return a successful worker result.
def successful_worker(
	value,
	progress_callback,
):
	return value


# Raise an expected operational error inside the worker.
def failing_worker(
	message,
	progress_callback,
):
	raise OSError(message)


# Report progress several times before returning a successful result.
def progressing_worker(
	delay_seconds,
	steps,
	value,
	progress_callback,
):
	for _ in range(steps):
		time.sleep(delay_seconds)

		progress_callback()

	return value


# Keep the worker alive without reporting progress.
def stalled_worker(
	sleep_seconds,
	progress_callback,
):
	time.sleep(sleep_seconds)


# Exit without publishing a result.
def exiting_worker(
	progress_callback,
):
	os._exit(1)


# A successful worker result must be returned to the caller.
def test_run_isolated_worker_returns_success_result():
	result = run_isolated_worker(
		camera="Test-Camera",
		target=successful_worker,
		kwargs={"value": "expected-result"},
		stall_timeout_seconds=1,
		operation_name="Test operation",
	)

	assert result == "expected-result"


# A worker-reported operational error must be exposed as OSError.
def test_run_isolated_worker_raises_oserror_for_worker_error():
	with pytest.raises(
		OSError,
		match="storage unavailable",
	):
		run_isolated_worker(
			camera="Test-Camera",
			target=failing_worker,
			kwargs={"message": "storage unavailable"},
			stall_timeout_seconds=1,
			operation_name="Test operation",
		)


# A worker that stops making progress must be terminated after the inactivity timeout.
def test_run_isolated_worker_raises_timeout_for_stalled_worker():
	with pytest.raises(
		TimeoutError,
		match="Test operation stalled for camera: Test-Camera",
	):
		run_isolated_worker(
			camera="Test-Camera",
			target=stalled_worker,
			kwargs={"sleep_seconds": 1},
			stall_timeout_seconds=0.1,
			operation_name="Test operation",
		)


# Progress messages must reset the inactivity timeout. The total runtime (5 x 0.1 s) exceeds the
# timeout, so only the reset lets it pass; each step leaves 0.3 s slack for process startup and a
# busy machine.
def test_run_isolated_worker_resets_timeout_on_progress(
	monkeypatch,
):
	# The forked worker inherits this, so every progress call reaches the parent.
	monkeypatch.setattr(image_worker_module, "PROGRESS_REPORT_INTERVAL_SECONDS", 0)

	result = run_isolated_worker(
		camera="Test-Camera",
		target=progressing_worker,
		kwargs={
			"delay_seconds": 0.1,
			"steps": 5,
			"value": "expected-result",
		},
		stall_timeout_seconds=0.4,
		operation_name="Test operation",
	)

	assert result == "expected-result"


# A worker that exits without returning a queue result must be treated as unexpected failure.
def test_run_isolated_worker_raises_runtime_error_for_unexpected_worker_exit(
	monkeypatch,
):
	monkeypatch.setattr(
		image_worker_module,
		"WORKER_POLL_INTERVAL_SECONDS",
		0.01,
	)

	with pytest.raises(
		RuntimeError,
		match="Test operation worker exited unexpectedly for camera: Test-Camera",
	):
		run_isolated_worker(
			camera="Test-Camera",
			target=exiting_worker,
			kwargs={},
			stall_timeout_seconds=1,
			operation_name="Test operation",
		)


# Stopping a worker must first request termination.
def test_stop_worker_process_terminates_worker():
	class FakeProcess:
		def __init__(self):
			self.terminate_called = False
			self.kill_called = False
			self.join_calls = []

		def terminate(self):
			self.terminate_called = True

		def join(
			self,
			timeout=None,
		):
			self.join_calls.append(timeout)

		def is_alive(self):
			return False

		def kill(self):
			self.kill_called = True

	process = FakeProcess()

	image_worker_module._stop_worker_process(process)

	assert process.terminate_called is True
	assert process.kill_called is False
	assert process.join_calls == [
		image_worker_module.WORKER_PROCESS_STOP_TIMEOUT_SECONDS,
	]


# A worker that survives terminate must be force-killed.
def test_stop_worker_process_kills_worker_when_terminate_is_not_enough():
	class FakeProcess:
		def __init__(self):
			self.terminate_called = False
			self.kill_called = False
			self.join_calls = []
			self.alive_checks = 0

		def terminate(self):
			self.terminate_called = True

		def join(
			self,
			timeout=None,
		):
			self.join_calls.append(timeout)

		def is_alive(self):
			self.alive_checks += 1

			return self.alive_checks == 1

		def kill(self):
			self.kill_called = True

	process = FakeProcess()

	image_worker_module._stop_worker_process(process)

	assert process.terminate_called is True
	assert process.kill_called is True
	assert process.join_calls == [
		image_worker_module.WORKER_PROCESS_STOP_TIMEOUT_SECONDS,
		image_worker_module.WORKER_PROCESS_STOP_TIMEOUT_SECONDS,
	]


# Progress must be rate-limited so large scans do not flood the queue.
def test_run_target_limits_progress_reports(
	monkeypatch,
):
	class RecordingQueue:
		def __init__(self):
			self.messages = []

		def put(self, message):
			self.messages.append(message)

	def chatty_target(progress_callback):
		for _ in range(3):
			progress_callback()

		return "done"

	monotonic_values = iter([0, 0.2, 1.1, 1.2])

	monkeypatch.setattr(
		image_worker_module.time,
		"monotonic",
		lambda: next(monotonic_values),
	)

	result_queue = RecordingQueue()

	image_worker_module._run_target(chatty_target, {}, result_queue)

	assert result_queue.messages == [
		("progress", None),
		("success", "done"),
	]


# Leave a marker from a finally block, as a worker does to stop a child process it started.
def cleanup_worker(
	marker_path,
	progress_callback,
):
	try:
		time.sleep(10)

	finally:
		Path(marker_path).write_text("cleaned up")


# The parent stops a stalled worker with SIGTERM. The worker must turn that into a normal exit, so
# its cleanup code runs and a child process it started (rsync) is stopped with it instead of being
# left behind to write into a folder that has already been cleaned up.
def test_a_stopped_worker_runs_its_cleanup_code(tmp_path):
	marker = tmp_path / "marker"

	with pytest.raises(TimeoutError):
		run_isolated_worker(
			camera="Test-Camera",
			target=cleanup_worker,
			kwargs={"marker_path": str(marker)},
			stall_timeout_seconds=1,
			operation_name="Test operation",
		)

	assert marker.read_text() == "cleaned up"


# Report the worker's process id, then block as a worker does while rsync fetches frames.
def blocked_worker(
	pid_path,
	progress_callback,
):
	Path(pid_path).write_text(str(os.getpid()))
	time.sleep(30)


# A stop signal reaches only the parent. The job's finally block removes the fetched frames as
# soon as the exception has left run_isolated_worker, so the worker (and the rsync it started) must
# already be stopped by then, or it would write into the folder that was just removed.
def test_a_stop_signal_stops_the_worker_before_the_exception_leaves(tmp_path):
	pid_file = tmp_path / "pid"
	previous_handler = signal.getsignal(signal.SIGTERM)

	# Wait until the worker is really blocked, then stop the parent as `kill <pid>` would.
	def stop_the_parent_when_the_worker_runs():
		while not pid_file.exists():
			time.sleep(0.05)

		time.sleep(0.2)
		os.kill(os.getpid(), signal.SIGTERM)

	exit_on_sigterm()
	threading.Thread(target=stop_the_parent_when_the_worker_runs, daemon=True).start()

	try:
		with pytest.raises(SystemExit):
			run_isolated_worker(
				camera="Test-Camera",
				target=blocked_worker,
				kwargs={"pid_path": str(pid_file)},
				stall_timeout_seconds=60,
				operation_name="Test operation",
			)

		# Signal 0 only probes: a stopped and collected worker has no process any more.
		with pytest.raises(ProcessLookupError):
			os.kill(int(pid_file.read_text()), 0)

	finally:
		signal.signal(signal.SIGTERM, previous_handler)


# The job entry points install the same handler: a stop signal must unwind the running job, so the
# finally block that removes the fetched frames runs, instead of the process dying on the spot.
def test_exit_on_sigterm_turns_sigterm_into_system_exit():
	previous_handler = signal.getsignal(signal.SIGTERM)

	try:
		exit_on_sigterm()

		with pytest.raises(SystemExit):
			signal.raise_signal(signal.SIGTERM)

	finally:
		signal.signal(signal.SIGTERM, previous_handler)
