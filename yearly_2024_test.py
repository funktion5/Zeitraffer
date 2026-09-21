from datetime import date

from src.config import load_config
from src.images import find_interval_images_isolated
from src.logger import configure_file_logging, logger
from src.video import create_timelapse
from src.yearly_selection import select_unique_yearly_images

CAMERA = "Segelsport-Club-Suedenmeer"
START_DATE = date(
	2024,
	1,
	1,
)
END_DATE = date(
	2024,
	12,
	31,
)


def main() -> None:
	config = load_config()

	configure_file_logging("yearly")

	logger.info("-" * 80)

	logger.info(f"Starting fixed Yearly test for {CAMERA}: {START_DATE} to {END_DATE}")

	# Search and validate all images inside the configured daily time window.
	interval_images = find_interval_images_isolated(
		camera=CAMERA,
		start_date=START_DATE,
		end_date=END_DATE,
		stall_timeout_seconds=config["image_scan_stall_timeout_seconds"],
	)

	logger.info(f"Found {len(interval_images)} validated interval images")

	yearly_images = select_unique_yearly_images(
		interval_images,
		images_per_day=5,
	)

	if not yearly_images:
		logger.warning("No valid Yearly images available - test stopped.")

		return

	logger.info(f"Selected {len(yearly_images)} Yearly images")

	if len(yearly_images) < 366:
		logger.warning(
			"Yearly test will be created with "
			f"{len(yearly_images)} of "
			"366 possible daily frames."
		)

	video_path = create_timelapse(
		camera=CAMERA,
		target_date=END_DATE,
		images=yearly_images,
		timelapse_type="yearly",
		framerate=20,
	)

	logger.info(f"Fixed Yearly test finished: {video_path}")


if __name__ == "__main__":
	main()
