import argparse
from datetime import date, timedelta
from config import load_config
from solar import get_sun_times
from images import find_images, get_cameras


# Parses optional command-line arguments for the timelapse job.
def parse_arguments():
	parser = argparse.ArgumentParser(
		description="Create timelapses for all available cameras."
	)

	parser.add_argument(
		"--date",
		type=date.fromisoformat,
		help="Date to process in YYYY-MM-DD format. Defaults to yesterday."
	)

	return parser.parse_args()


# Runs the daily workflow for all cameras available on the camera mount.
def main():
	args = parse_arguments()
	config = load_config()

	# Use the requested date or default to yesterday for automated nightly runs.
	target_date = args.date or (date.today() - timedelta(days=1))
	location = config["location"]
	cameras = get_cameras()

	# Solar times are calculated once because all cameras share the same location.
	sunrise, sunset = get_sun_times(
		target_date=target_date,
		latitude=location["latitude"],
		longitude=location["longitude"],
		timezone=location["timezone"],
	)

	print(
		f"Date:    {target_date}\n"
		f"Sunrise: {sunrise}\n"
		f"Sunset:  {sunset}\n"
	)

	# Process every camera discovered dynamically on the mount.
	for camera in cameras:
		images = find_images(
			camera=camera,
			target_date=target_date,
			sunrise=sunrise,
			sunset=sunset,
		)

		# Skip cameras without images instead of interrupting the complete job.
		if not images:
			print(f"Camera: {camera}")
			print("Images: 0 - skipping")
			print()
			continue

		print(f"Camera: {camera}")
		print(f"Images: {len(images)}")
		print(f"First:  {images[0].name}")
		print(f"Last:   {images[-1].name}")

		print()


if __name__ == "__main__":
	main()