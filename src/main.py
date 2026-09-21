import argparse
from datetime import date

from src.config import load_config
from src.images import get_cameras
from src.jobs.daily import run_daily_job
from src.jobs.manual import run_manual_job
from src.jobs.monthly import run_monthly_job
from src.jobs.weekly import run_weekly_job
from src.jobs.yearly import run_yearly_job
from src.logger import cleanup_old_logs, configure_file_logging, logger


# Parse optional command-line arguments for the timelapse job.
def parse_arguments():
	parser = argparse.ArgumentParser(
		description="Create timelapses for available cameras."
	)

	parser.add_argument(
		"--date",
		type=date.fromisoformat,
		help=(
			"Date to process in YYYY-MM-DD format. "
			"Providing a date creates a manual timelapse."
		),
	)

	parser.add_argument(
		"--cameras",
		nargs="+",
		help=(
			"Process only the specified cameras. Can only be used together with --date."
		),
	)

	return parser.parse_args()


# Coordinate the requested timelapse jobs.
def main():
	args = parse_arguments()

	if args.cameras and not args.date:
		raise ValueError("--cameras can only be used together with --date.")

	config = load_config()

	# Configure logging before camera discovery and filtering.
	log_type = "manual" if args.date else "daily"

	configure_file_logging(log_type)

	# Remove expired logs once at application startup.
	cleanup_old_logs(retention_days=config["log_retention_days"])

	# Camera storage must be available before any job can continue.
	try:
		available_cameras = get_cameras()

	except OSError:
		logger.exception("Failed to access camera storage.")
		raise

	# Remove globally ignored cameras before any job starts.
	ignored_cameras = set(
		config.get(
			"ignored_cameras",
			[],
		)
	)

	for camera in available_cameras:
		if camera in ignored_cameras:
			logger.info(f"Ignoring configured camera: {camera}")

	available_cameras = [
		camera for camera in available_cameras if camera not in ignored_cameras
	]

	# Manual runs are independent from the automatic workflow.
	if args.date:
		run_manual_job(
			config=config,
			available_cameras=available_cameras,
			target_date=args.date,
			requested_cameras=args.cameras,
			framerate=config["timelapse"]["manual_framerate"],
		)

		return

	# Automatic runs always create Daily videos first.
	run_daily_job(
		config=config,
		cameras=available_cameras,
		framerate=config["timelapse"]["daily_framerate"],
	)

	# Weekly videos depend on the updated Daily videos.
	configure_file_logging("weekly")

	run_weekly_job(
		config=config,
		cameras=available_cameras,
	)

	# Monthly uses the same updated camera source state.
	configure_file_logging("monthly")
	run_monthly_job(
		config=config,
		cameras=available_cameras,
		framerate=config["timelapse"]["monthly_framerate"],
	)

	# Yearly uses the same updated camera source state.
	configure_file_logging("yearly")

	run_yearly_job(
		config=config,
		cameras=available_cameras,
		framerate=config["timelapse"]["yearly_framerate"],
	)


if __name__ == "__main__":
	main()
