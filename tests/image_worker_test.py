import time

import pytest

import src.image_worker as image_worker_module
from src.image_worker import run_isolated_worker


# Return a successful worker result through the shared queue contract.
def successful_worker(
	value,
	result_queue,
):
	result_queue.put(
		(
			"success",
			value,
		)
	)


# Return an expected operational error through the shared queue contract.
def failing_worker(
	message,
	result_queue,
):
	result_queue.put(
		(
			"error",
			message,
		)
	)


# Report progress before returning a successful result.
def progressing_worker(
	delay_seconds,
	value,
	result_queue,
):
	time.sleep(delay_seconds)

	result_queue.put(
		(
			"progress",
			None,
		)
	)

	time.sleep(delay_seconds)

	result_queue.put(
		(
			"success",
			value,
		)
	)


# Keep the worker alive without reporting progress.
def stalled_worker(
	sleep_seconds,
	result_queue,
):
	time.sleep(sleep_seconds)


# Exit without publishing a result.
def exiting_worker(
	result_queue,
):
	return


# A successful worker result must be returned to the caller.
def test_run_isolated_worker_returns_success_result():
	result = run_isolated_worker(
		camera="Test-Camera",
		target=successful_worker,
		args=("expected-result",),
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
			args=("storage unavailable",),
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
			args=(1,),
			stall_timeout_seconds=0.1,
			operation_name="Test operation",
		)


# Progress messages must reset the inactivity timeout.
def test_run_isolated_worker_resets_timeout_on_progress():
	result = run_isolated_worker(
		camera="Test-Camera",
		target=progressing_worker,
		args=(
			0.08,
			"expected-result",
		),
		stall_timeout_seconds=0.12,
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
			args=(),
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
