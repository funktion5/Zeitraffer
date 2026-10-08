import argparse
from datetime import date

from src.config import load_config
from src.images import get_cameras, require_cameras
from src.interval_window import (
	IntervalWindow,
	interval_window_from_config,
	parse_window_time,
)
from src.jobs.daily import run_daily_job
from src.jobs.monthly import run_monthly_job
from src.jobs.weekly import run_weekly_job
from src.jobs.yearly import run_yearly_job
from src.logger import cleanup_old_logs, configure_file_logging, logger
from src.run_state import (
	mark_run_finished,
	mark_run_started,
)

# Fixed workflow order, regardless of the order given on the command line.
JOBS = ("daily", "weekly", "monthly", "yearly")


# argparse only turns ArgumentTypeError into a readable usage error.
def window_time_argument(value: str):
	try:
		return parse_window_time(value)

	except ValueError as error:
		raise argparse.ArgumentTypeError(str(error)) from None


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
		choices=JOBS,
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

	parser.add_argument(
		"--window-time",
		type=window_time_argument,
		help=(
			"Centre of the daily image window for historical Monthly/Yearly, "
			"as HH:MM or 'sunset' (that day's sunset). Defaults to config.json."
		),
	)

	parser.add_argument(
		"--window-tolerance-minutes",
		type=int,
		help=(
			"Minutes before and after the window centre for historical Monthly/Yearly. "
			"Defaults to config.json."
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

	window_override_requested = (
		args.window_time is not None or args.window_tolerance_minutes is not None
	)

	# Automatic runs must keep the configured window; only historical runs may move it.
	if window_override_requested and not args.target_date:
		raise ValueError(
			"--window-time and --window-tolerance-minutes can only be used with --target-date."
		)

	if window_override_requested and set(args.jobs) - {"monthly", "yearly"}:
		raise ValueError(
			"--window-time and --window-tolerance-minutes only apply to Monthly and Yearly."
		)

	config = load_config()

	if args.daylight_buffer_minutes is not None:
		config = {**config, "daylight_buffer_minutes": args.daylight_buffer_minutes}

	interval_window = None

	if window_override_requested:
		default_window = interval_window_from_config(config)

		# A flag left out falls back to its config value, never to a hardcoded one.
		interval_window = IntervalWindow(
			target=args.window_time if args.window_time is not None else default_window.target,
			tolerance_minutes=(
				args.window_tolerance_minutes
				if args.window_tolerance_minutes is not None
				else default_window.tolerance_minutes
			),
		)

	selected_jobs = (
		["daily"] if args.date else [job for job in JOBS if args.jobs is None or job in args.jobs]
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
		available_cameras = require_cameras(args.cameras, available_cameras)

	target_date = args.date or args.target_date
	automatic_production_run = args.date is None and args.jobs is None and args.target_date is None

	if automatic_production_run:
		mark_run_started()

	for job in selected_jobs:
		# The first job's log file was configured before camera discovery.
		if job != log_type:
			configure_file_logging(job)

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
				interval_window=interval_window,
			)

		elif job == "yearly":
			run_yearly_job(
				config=config,
				cameras=available_cameras,
				framerate=config["timelapse"]["yearly_framerate"],
				target_date=args.target_date,
				manual_run=args.target_date is not None,
				interval_window=interval_window,
			)

	if automatic_production_run:
		mark_run_finished()


if __name__ == "__main__":
	main()
