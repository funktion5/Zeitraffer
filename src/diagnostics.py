from multiprocessing import Process, Queue
from queue import Empty

from src.images import get_image_range
from src.logger import logger

IMAGE_RANGE_TIMEOUT_SECONDS = 10
IMAGE_RANGE_PROCESS_STOP_TIMEOUT_SECONDS = 1


def _get_image_range_worker(
	camera: str,
	result_queue: Queue,
) -> None:
	try:
		image_range = get_image_range(camera)

		result_queue.put(
			(
				"success",
				image_range,
			)
		)

	except OSError as error:
		result_queue.put(
			(
				"error",
				str(error),
			)
		)


def _stop_diagnostic_process(
	process: Process,
) -> None:
	process.terminate()
	process.join(IMAGE_RANGE_PROCESS_STOP_TIMEOUT_SECONDS)

	if process.is_alive():
		process.kill()
		process.join(IMAGE_RANGE_PROCESS_STOP_TIMEOUT_SECONDS)


def log_missing_images_diagnostic(
	camera: str,
) -> None:
	result_queue = Queue()

	process = Process(
		target=_get_image_range_worker,
		args=(
			camera,
			result_queue,
		),
		daemon=True,
	)

	process.start()
	process.join(IMAGE_RANGE_TIMEOUT_SECONDS)

	if process.is_alive():
		_stop_diagnostic_process(process)

		logger.warning(
			f"Image range diagnostic timed out for {camera} "
			f"after {IMAGE_RANGE_TIMEOUT_SECONDS} seconds."
		)

		result_queue.close()
		return

	try:
		status, result = result_queue.get(timeout=1)

	except Empty:
		logger.warning(f"Image range diagnostic failed for {camera}.")

		result_queue.close()
		return

	result_queue.close()

	if status == "error":
		logger.warning(f"Could not determine available image range for {camera}: {result}")
		return

	image_range = result

	if image_range.earliest_date is None or image_range.latest_date is None:
		logger.warning("No recognized image files available.")

	else:
		logger.warning(
			f"Available image range: {image_range.earliest_date} - {image_range.latest_date}"
		)

	if image_range.unrecognized_files > 0:
		logger.warning(
			f"{image_range.unrecognized_files} files use an unsupported filename format."
		)
