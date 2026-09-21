import time
from collections.abc import Callable
from multiprocessing import Process, Queue
from queue import Empty
from typing import Any

# Give a worker process a short grace period before forcing termination.
WORKER_PROCESS_STOP_TIMEOUT_SECONDS = 1

# Immediate failure detection is not required while workers are active.
WORKER_POLL_INTERVAL_SECONDS = 5


# Stop a stalled worker and force-kill it only if termination is not enough.
def _stop_worker_process(
	process: Process,
) -> None:
	process.terminate()

	process.join(WORKER_PROCESS_STOP_TIMEOUT_SECONDS)

	if process.is_alive():
		process.kill()

		process.join(WORKER_PROCESS_STOP_TIMEOUT_SECONDS)


# Run a worker with an inactivity timeout that resets on progress.
def run_isolated_worker(
	camera: str,
	target: Callable[..., None],
	args: tuple[Any, ...],
	stall_timeout_seconds: float,
	operation_name: str,
) -> Any:
	result_queue = Queue()

	process = Process(
		target=target,
		args=(
			*args,
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
