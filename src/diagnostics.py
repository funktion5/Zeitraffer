from src.image_worker import run_isolated_worker
from src.images import get_image_range
from src.logger import logger

IMAGE_RANGE_STALL_TIMEOUT_SECONDS = 10


def log_missing_images_diagnostic(
	camera: str,
) -> None:
	try:
		image_range = run_isolated_worker(
			camera=camera,
			target=get_image_range,
			kwargs={"camera": camera},
			stall_timeout_seconds=IMAGE_RANGE_STALL_TIMEOUT_SECONDS,
			operation_name="Image range diagnostic",
		)

	except TimeoutError:
		logger.warning(
			f"Image range diagnostic timed out for {camera} "
			f"after {IMAGE_RANGE_STALL_TIMEOUT_SECONDS} seconds without progress."
		)
		return

	# The diagnostic is best effort: a failed lookup must never fail the job.
	except (OSError, RuntimeError) as error:
		logger.warning(f"Could not determine available image range for {camera}: {error}")
		return

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
