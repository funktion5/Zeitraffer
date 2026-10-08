import os
import time

import pytest

import src.image_worker as image_worker_module
from src.image_worker import run_isolated_worker


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
