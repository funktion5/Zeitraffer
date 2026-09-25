import argparse
from datetime import date

from src.config import load_config
from src.images import get_cameras
from src.jobs.daily import run_daily_job
from src.jobs.monthly import run_monthly_job
from src.jobs.weekly import run_weekly_job
from src.jobs.yearly import run_yearly_job
from src.logger import cleanup_old_logs, configure_file_logging, logger
from src.run_state import (
	mark_run_finished,
	mark_run_started,
)


# Parse optional command-line arguments for the timelapse job.
def parse_arguments():
	parser = argparse.ArgumentParser(description="Create timelapses for available cameras.")

	parser.add_argument(
		"--date",
		type=date.fromisoformat,
		help=("Alias for a historical Daily target date in YYYY-MM-DD format."),
	)

	parser.add_argument(
		"--cameras",
		nargs="+",
		help=(
			"Process specified cameras for Manual Daily or historical jobs. "
			"Historical Weekly requires exactly one camera."
		),
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

	parser.add_argument(
		"--daylight-buffer-minutes",
		type=int,
		choices=(30, 60, 90),
		help=(
			"Override the configured daylight buffer for this run only. "
			"Never persisted; config.json is unaffected."
		),
	)

	return parser.parse_args()


# Coordinate the requested timelapse jobs.
def main():
	args = parse_arguments()
	historical_weekly_run = bool(args.target_date and args.jobs and set(args.jobs) == {"weekly"})

	if args.date and args.jobs:
		raise ValueError("--date cannot be used together with --jobs.")

	if args.date and args.target_date:
		raise ValueError("--date cannot be used together with --target-date.")

	if args.target_date and not args.jobs:
		raise ValueError("--target-date can only be used together with --jobs.")

	if args.target_date and args.jobs and "weekly" in args.jobs and not historical_weekly_run:
		raise ValueError("Historical Weekly must be selected as the only job.")

	if historical_weekly_run and len(args.cameras or []) != 1:
		raise ValueError("Historical Weekly requires exactly one camera with --cameras.")

	if (
		args.daylight_buffer_minutes is not None
		and args.jobs
		and set(args.jobs) & {"monthly", "yearly"}
	):
		raise ValueError(
			"--daylight-buffer-minutes cannot be used with Monthly or Yearly; "
			"neither job type uses a daylight buffer."
		)

	if args.cameras and not args.date and not args.target_date:
		raise ValueError("--cameras can only be used with --date or --target-date.")
	config = load_config()

	if args.daylight_buffer_minutes is not None:
		config = {**config, "daylight_buffer_minutes": args.daylight_buffer_minutes}

	job_order = (
		"daily",
		"weekly",
		"monthly",
		"yearly",
	)

	selected_jobs = (
		["daily"]
		if args.date
		else [job for job in job_order if args.jobs is None or job in args.jobs]
	)
	# Configure logging before camera discovery and filtering.
	log_type = selected_jobs[0]

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

	# Historical jobs may process only explicitly requested cameras.
	if (args.date or args.target_date) and args.cameras:
		requested_cameras = list(dict.fromkeys(args.cameras))
		missing_cameras = [
			camera for camera in requested_cameras if camera not in available_cameras
		]

		if missing_cameras:
			missing_camera_names = ", ".join(missing_cameras)
			logger.error(f"Requested cameras not found: {missing_camera_names}")
			raise ValueError(f"Requested cameras not found: {missing_camera_names}")

		available_cameras = requested_cameras

	target_date = args.date or args.target_date
	automatic_production_run = args.date is None and args.jobs is None and args.target_date is None

	if automatic_production_run:
		mark_run_started()

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
				target_date=target_date,
				manual_run=target_date is not None,
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

	if automatic_production_run:
		mark_run_finished()


if __name__ == "__main__":
	main()
