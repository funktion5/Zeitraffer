import time
from collections.abc import Callable
from multiprocessing import Process, Queue
from queue import Empty
from typing import Any

# Give a worker process a short grace period before forcing termination.
WORKER_PROCESS_STOP_TIMEOUT_SECONDS = 1

# Immediate failure detection is not required while workers are active.
WORKER_POLL_INTERVAL_SECONDS = 5

# Report progress at most once per second so large scans do not flood the queue.
PROGRESS_REPORT_INTERVAL_SECONDS = 1


# Stop a stalled worker and force-kill it only if termination is not enough.
def _stop_worker_process(
	process: Process,
) -> None:
	process.terminate()

	process.join(WORKER_PROCESS_STOP_TIMEOUT_SECONDS)

	if process.is_alive():
		process.kill()

		process.join(WORKER_PROCESS_STOP_TIMEOUT_SECONDS)


# Run the target inside the worker process and send its result back. The target
# receives a throttled progress_callback; expected filesystem errors are
# forwarded, anything else crashes the worker and surfaces as RuntimeError.
def _run_target(
	target: Callable[..., Any],
	kwargs: dict[str, Any],
	result_queue: Queue,
) -> None:
	last_progress_report = time.monotonic()

	def report_progress() -> None:
		nonlocal last_progress_report

		now = time.monotonic()

		if now - last_progress_report >= PROGRESS_REPORT_INTERVAL_SECONDS:
			result_queue.put(("progress", None))
			last_progress_report = now

	try:
		result_queue.put(("success", target(**kwargs, progress_callback=report_progress)))

	except OSError as error:
		result_queue.put(("error", str(error)))


# Run a worker with an inactivity timeout that resets on progress.
def run_isolated_worker(
	camera: str,
	target: Callable[..., Any],
	kwargs: dict[str, Any],
	stall_timeout_seconds: float,
	operation_name: str,
) -> Any:
	result_queue = Queue()

	process = Process(
		target=_run_target,
		args=(
			target,
			kwargs,
			result_queue,
		),
		daemon=True,
	)

	process.start()

	last_progress = time.monotonic()

	while True:
		remaining_time = stall_timeout_seconds - (time.monotonic() - last_progress)

		if remaining_time <= 0:
			_stop_worker_process(process)

			result_queue.close()

			raise TimeoutError(f"{operation_name} stalled for camera: {camera}")

		try:
			status, result = result_queue.get(
				timeout=min(
					WORKER_POLL_INTERVAL_SECONDS,
					remaining_time,
				)
			)

		except Empty:
			# A dead worker indicates an unexpected failure.
			if not process.is_alive():
				process.join()

				result_queue.close()

				raise RuntimeError(
					f"{operation_name} worker exited unexpectedly "
					f"for camera: {camera} "
					f"(exit code: {process.exitcode})"
				)

			continue

		if status == "progress":
			last_progress = time.monotonic()
			continue

		process.join(WORKER_PROCESS_STOP_TIMEOUT_SECONDS)

		if process.is_alive():
			_stop_worker_process(process)

		result_queue.close()

		if status == "error":
			raise OSError(result)

		return result
