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
	parser = argparse.ArgumentParser(description="Create timelapses for available cameras.")

	parser.add_argument(
		"--date",
		type=date.fromisoformat,
		help=("Date to process in YYYY-MM-DD format. Providing a date creates a manual timelapse."),
	)

	parser.add_argument(
		"--cameras",
		nargs="+",
		help=("Process only the specified cameras. Can only be used together with --date."),
	)

	parser.add_argument(
		"--jobs",
		nargs="+",
		choices=(
			"daily",
			"weekly",
			"monthly",
			"yearly",
		),
		help=(
			"Run only the specified automatic jobs. "
			"Jobs always execute in their defined workflow order."
		),
	)

	parser.add_argument(
		"--target-date",
		type=date.fromisoformat,
		help=(
			"Use an explicit end date for selected automatic jobs. "
			"Can only be used together with --jobs."
		),
	)

	return parser.parse_args()


# Coordinate the requested timelapse jobs.
def main():
	args = parse_arguments()

	if args.date and args.jobs:
		raise ValueError("--date cannot be used together with --jobs.")

	if args.date and args.target_date:
		raise ValueError("--date cannot be used together with --target-date.")

	if args.target_date and not args.jobs:
		raise ValueError("--target-date can only be used together with --jobs.")

	if args.cameras and not args.date:
		raise ValueError("--cameras can only be used together with --date.")
	config = load_config()

	job_order = (
		"daily",
		"weekly",
		"monthly",
		"yearly",
	)

	selected_jobs = [job for job in job_order if args.jobs is None or job in args.jobs]
	# Configure logging before camera discovery and filtering.
	log_type = "manual" if args.date else selected_jobs[0]

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

	available_cameras = [camera for camera in available_cameras if camera not in ignored_cameras]

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

	first_job = True

	for job in selected_jobs:
		if not first_job:
			configure_file_logging(job)

		first_job = False

		if job == "daily":
			run_daily_job(
				config=config,
				cameras=available_cameras,
				framerate=config["timelapse"]["daily_framerate"],
				target_date=args.target_date,
				manual_run=args.target_date is not None,
			)

		elif job == "weekly":
			run_weekly_job(
				config=config,
				cameras=available_cameras,
				target_date=args.target_date,
				manual_run=args.target_date is not None,
			)

		elif job == "monthly":
			run_monthly_job(
				config=config,
				cameras=available_cameras,
				framerate=config["timelapse"]["monthly_framerate"],
				target_date=args.target_date,
				manual_run=args.target_date is not None,
			)

		elif job == "yearly":
			run_yearly_job(
				config=config,
				cameras=available_cameras,
				framerate=config["timelapse"]["yearly_framerate"],
				target_date=args.target_date,
				manual_run=args.target_date is not None,
			)


if __name__ == "__main__":
	main()
