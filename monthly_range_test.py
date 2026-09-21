from datetime import date

from src.config import load_config
from src.images import find_interval_images_isolated
from src.logger import configure_file_logging, logger
from src.video import create_timelapse

CAMERA = "Segelsport-Club-Suedenmeer"
START_DATE = date(
	2024,
	2,
	15,
)
END_DATE = date(
	2024,
	3,
	15,
)
FRAMERATE = 10


def main() -> None:
	config = load_config()

	configure_file_logging("monthly")

	logger.info("-" * 80)

	logger.info(f"Starting fixed Monthly test for {CAMERA}: {START_DATE} to {END_DATE}")

	monthly_images = find_interval_images_isolated(
		camera=CAMERA,
		start_date=START_DATE,
		end_date=END_DATE,
		stall_timeout_seconds=config["image_scan_stall_timeout_seconds"],
	)

	logger.info(f"Found {len(monthly_images)} validated Monthly images")

	if not monthly_images:
		logger.warning("No valid Monthly images available - test stopped.")
		return

	video_path = create_timelapse(
		camera=CAMERA,
		target_date=END_DATE,
		images=monthly_images,
		timelapse_type="monthly",
		framerate=FRAMERATE,
	)

	logger.info(f"Fixed Monthly test finished: {video_path}")


if __name__ == "__main__":
	main()
