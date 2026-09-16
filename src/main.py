import argparse
from datetime import date, timedelta

from src.config import load_config
from src.images import find_images, get_cameras, get_image_range
from src.logger import logger
from src.solar import get_sun_times
from src.video import create_timelapse


# Parse optional command-line arguments for the timelapse job.
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Create timelapses for all available cameras."
    )

    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Date to process in YYYY-MM-DD format. Defaults to yesterday.",
    )

    return parser.parse_args()


# Log additional camera information when no images were found for the target date.
def log_missing_images_diagnostic(camera: str) -> None:
    image_range = get_image_range(camera)

    if image_range.total_files == 0:
        logger.warning("No image files available.")
        return

    if image_range.recognized_files == 0:
        logger.warning(
            "Image files exist, but their filename format is unsupported."
        )
        logger.warning(
            f"Unrecognized files: {image_range.unrecognized_files}"
        )
        return

    logger.warning(
        f"Available image range: "
        f"{image_range.earliest_date} - {image_range.latest_date}"
    )

    if image_range.unrecognized_files > 0:
        logger.warning(
            f"{image_range.unrecognized_files} files use "
            "an unsupported filename format."
        )


# Run the daily workflow for all cameras available on the camera mount.
def main():
    args = parse_arguments()
    config = load_config()

    # Use the requested date or default to yesterday for automated nightly runs.
    target_date = args.date or (date.today() - timedelta(days=1))

    logger.info(f"Starting daily timelapse job for {target_date}")

    location = config["location"]
    daylight_buffer_minutes = config["daylight_buffer_minutes"]

    logger.info(
        f"Daylight buffer: {daylight_buffer_minutes} minutes"
    )

    cameras = get_cameras()

    # Calculate solar times once because all cameras share the same location.
    sunrise, sunset = get_sun_times(
        target_date=target_date,
        latitude=location["latitude"],
        longitude=location["longitude"],
        timezone=location["timezone"],
    )

    logger.info(f"Sunrise: {sunrise}")
    logger.info(f"Sunset: {sunset}")

    # Process every camera discovered dynamically on the mount.
    for camera in cameras:
        logger.info(f"Processing camera: {camera}")

        images = find_images(
            camera=camera,
            target_date=target_date,
            sunrise=sunrise,
            sunset=sunset,
            daylight_buffer_minutes=daylight_buffer_minutes,
        )

        # Skip cameras without images instead of interrupting the complete job.
        if not images:
            logger.warning("Found 0 images - skipping camera.")
            log_missing_images_diagnostic(camera)
            continue

        logger.info(f"Found {len(images)} images")
        logger.debug(f"First image: {images[0].name}")
        logger.debug(f"Last image: {images[-1].name}")

        video_path = create_timelapse(
            camera=camera,
            target_date=target_date,
            images=images,
        )

        logger.info(f"Finished processing camera: {camera}")
        logger.debug(f"Video path: {video_path}")

    logger.info(f"Daily timelapse job finished for {target_date}")


if __name__ == "__main__":
    main()