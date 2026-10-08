"""Build historical calendar-year Yearly videos without the full-coverage check.

One-off backfill: same image scan, 0-byte filter, configured interval window and
five-images-per-day selection as the Yearly job, but a camera is encoded
whatever its coverage, so the results can be judged afterwards. Missing days
are logged and written to a summary CSV instead of skipping the camera.

Run from anywhere:
	.venv/bin/python3 scripts/yearly-backfill.py [--years 2023 2024] [--cameras A B] [--force]
"""

import argparse
import csv
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The video, log and camera paths in src/ are relative to the project root.
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.date_coverage import (  # noqa: E402
	format_date_ranges,
	get_latest_completed_date,
	get_missing_dates,
)
from src.images import find_interval_images_isolated, get_cameras  # noqa: E402
from src.interval_window import interval_window_from_config, resolve_target_seconds  # noqa: E402
from src.logger import RUN_ID, configure_file_logging, logger  # noqa: E402
from src.storage_filter import acquire_run_lock  # noqa: E402
from src.video import create_timelapse, get_video_path  # noqa: E402
from src.yearly_selection import select_yearly_images_isolated  # noqa: E402

DEFAULT_YEARS = [2026]
REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "yearly-coverage"


def parse_arguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--years", nargs="+", type=int, default=DEFAULT_YEARS)
	parser.add_argument(
		"--cameras",
		nargs="+",
		help="Only these cameras (default: every camera not in ignored_cameras).",
	)
	parser.add_argument(
		"--force",
		action="store_true",
		help="Rebuild videos that already exist instead of skipping them.",
	)

	return parser.parse_args()


# A calendar year, cut at the last completed day while that year is still running.
def get_year_window(year: int, yesterday: date) -> tuple[date, date] | None:
	start_date = date(year, 1, 1)
	end_date = min(date(year, 12, 31), yesterday)

	if end_date < start_date:
		return None

	return start_date, end_date


def build_year(
	camera: str,
	start_date: date,
	end_date: date,
	config: dict,
	force: bool,
) -> dict:
	total_days = (end_date - start_date).days + 1
	result = {
		"camera": camera,
		"year": start_date.year,
		"covered": 0,
		"total": total_days,
		"missing_ranges": "",
		"status": "",
		"video": "",
	}

	video_path = get_video_path(
		camera=camera,
		target_date=end_date,
		timelapse_type="yearly",
		manual_run=True,
	)

	if video_path.exists() and not force:
		logger.info(f"Video already exists - skipping: {video_path}")
		result.update(status="exists", video=str(video_path))

		return result

	stall_timeout_seconds = config["image_scan_stall_timeout_seconds"]

	window = interval_window_from_config(config)
	target_seconds_by_date = resolve_target_seconds(
		window=window,
		start_date=start_date,
		end_date=end_date,
		location=config["location"],
	)

	interval_images = find_interval_images_isolated(
		camera=camera,
		start_date=start_date,
		end_date=end_date,
		stall_timeout_seconds=stall_timeout_seconds,
		target_seconds_by_date=target_seconds_by_date,
		tolerance_minutes=window.tolerance_minutes,
	)

	missing_dates = get_missing_dates(
		images=interval_images,
		start_date=start_date,
		end_date=end_date,
	)
	covered_days = total_days - len(missing_dates)
	result.update(covered=covered_days, missing_ranges=format_date_ranges(missing_dates))

	if not interval_images:
		logger.warning(f"No valid Yearly images for {start_date.year} - skipping camera: {camera}")
		result["status"] = "no-images"

		return result

	# Logged at INFO on purpose: which days are missing is what gets judged later.
	logger.info(
		f"Coverage {start_date.year}: {covered_days} of {total_days} days | "
		f"missing: {result['missing_ranges']}"
	)

	yearly_images = select_yearly_images_isolated(
		camera=camera,
		images=interval_images,
		stall_timeout_seconds=stall_timeout_seconds,
		target_seconds_by_date=target_seconds_by_date,
	)

	if not yearly_images:
		logger.warning(f"No Yearly images selected for {start_date.year} - skipping: {camera}")
		result["status"] = "no-images"

		return result

	logger.info(f"Selected {len(yearly_images)} Yearly images")

	created_path = create_timelapse(
		camera=camera,
		target_date=end_date,
		images=yearly_images,
		timelapse_type="yearly",
		framerate=config["timelapse"]["yearly_framerate"],
		manual_run=True,
	)
	result.update(status="created", video=str(created_path))

	return result


def main() -> int:
	args = parse_arguments()
	config = load_config()

	configure_file_logging("yearly")

	yesterday = get_latest_completed_date(config["location"]["timezone"])

	ignored_cameras = set(config.get("ignored_cameras", []))
	cameras = args.cameras or [c for c in get_cameras() if c not in ignored_cameras]

	REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
	report_path = REPORT_DIRECTORY / f"backfill_{datetime.now():%Y-%m-%d_%H%M%S}.csv"
	fieldnames = ["camera", "year", "covered", "total", "missing_ranges", "status", "video"]

	logger.info("-" * 80)
	logger.info(
		f"Starting Yearly backfill | years={args.years} | cameras={', '.join(cameras)} | "
		f"force={args.force} | run_id={RUN_ID}"
	)

	with acquire_run_lock(), report_path.open("w", newline="") as report_file:
		writer = csv.DictWriter(report_file, fieldnames=fieldnames, delimiter=";")
		writer.writeheader()

		for camera in cameras:
			for year in args.years:
				window = get_year_window(year, yesterday)

				if window is None:
					continue

				start_date, end_date = window
				logger.info(f"Processing Yearly backfill {start_date} to {end_date}: {camera}")

				try:
					result = build_year(camera, start_date, end_date, config, args.force)

				except (OSError, TimeoutError, subprocess.CalledProcessError):
					# Operational errors only skip this camera/year, like the Yearly job.
					logger.exception(f"Failed Yearly backfill {year} for camera: {camera}")
					result = {"camera": camera, "year": year, "status": "failed"}

				writer.writerow(result)
				# Flush per row so a crash or reboot keeps the finished rows.
				report_file.flush()

	logger.info(f"Yearly backfill finished | report={report_path} | run_id={RUN_ID}")

	return 0


if __name__ == "__main__":
	sys.exit(main())
