import contextlib
import csv
import importlib.util
from argparse import Namespace
from datetime import date
from pathlib import Path

from frame_source_fakes import RecordingFrameSource

import src.images as images_module
from src.config import PROJECT_ROOT
from src.image_worker import WorkerExitedError

# The script's file name has a hyphen, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location(
	"yearly_backfill", PROJECT_ROOT / "scripts" / "yearly-backfill.py"
)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

CONFIG = {
	"location": {"timezone": "Europe/Berlin"},
	"interval_window": {"target_time": "12:00", "tolerance_minutes": 90},
	"image_scan_stall_timeout_seconds": 10,
	"timelapse": {"yearly_framerate": 20},
	"ignored_cameras": [],
}


# Run main() for one camera with the scan, the selection, the video build and the lock replaced.
# find is called with the year and returns the images or raises. Returns the exit code, the ordered
# events of scan, selection, video build and release, and the rows of the CSV report.
def run_backfill(monkeypatch, tmp_path, find=None, release_errors=None, years=(2025, 2024)):
	events = []

	def fake_find_interval_images_isolated(camera, start_date, **kwargs):
		events.append(f"find:{start_date.year}")

		if find is not None:
			return find(start_date.year)

		return [Path(f"cam_{start_date:%y}-06-01_12-00-00-00.jpg")]

	def fake_select_yearly_images_isolated(camera, images, **kwargs):
		events.append("select")

		return images

	def fake_create_timelapse(camera, **kwargs):
		events.append("create")

		return Path(f"videos/{camera}/manual-runs/yearly/video.mp4")

	arguments = Namespace(years=list(years), cameras=["Cam"], force=True, blur_people=False)

	monkeypatch.setattr(backfill, "parse_arguments", lambda: arguments)
	monkeypatch.setattr(backfill, "load_config", lambda: CONFIG)
	monkeypatch.setattr(backfill, "configure_file_logging", lambda log_type: None)
	monkeypatch.setattr(backfill, "get_latest_completed_date", lambda timezone: date(2026, 10, 28))
	monkeypatch.setattr(backfill, "acquire_run_lock", lambda: contextlib.nullcontext())
	monkeypatch.setattr(backfill, "REPORT_DIRECTORY", tmp_path)
	monkeypatch.setattr(
		backfill,
		"find_interval_images_isolated",
		fake_find_interval_images_isolated,
	)
	monkeypatch.setattr(
		backfill,
		"select_yearly_images_isolated",
		fake_select_yearly_images_isolated,
	)
	monkeypatch.setattr(backfill, "create_timelapse", fake_create_timelapse)
	monkeypatch.setattr(
		images_module,
		"get_frame_source",
		lambda: RecordingFrameSource(events, release_errors),
	)

	code = backfill.main()

	report = next(tmp_path.glob("backfill_*.csv"))
	rows = list(csv.DictReader(report.open(newline=""), delimiter=";"))

	return code, events, rows


# The frames are unblurred and the video is built from them, so each camera and year releases them
# once the video is there, and the next year starts from an empty cache.
def test_every_year_releases_its_frames_after_its_video_is_built(monkeypatch, tmp_path):
	code, events, rows = run_backfill(monkeypatch, tmp_path)

	assert code == 0
	assert events == [
		"find:2025",
		"select",
		"create",
		"release:Cam",
		"find:2024",
		"select",
		"create",
		"release:Cam",
	]
	assert [row["status"] for row in rows] == ["created", "created"]


# A fetch error costs that year only, and whatever it fetched is removed.
def test_a_fetch_error_fails_that_year_and_the_other_year_still_runs(monkeypatch, tmp_path):
	def find(year):
		if year == 2025:
			raise OSError("rsync from the box failed")

		return [Path("cam_24-06-01_12-00-00-00.jpg")]

	code, events, rows = run_backfill(monkeypatch, tmp_path, find=find)

	assert code == 0
	assert events == [
		"find:2025",
		"release:Cam",
		"find:2024",
		"select",
		"create",
		"release:Cam",
	]
	assert [row["status"] for row in rows] == ["failed", "created"]


# A worker that dies is not an OSError, but it only costs that year.
def test_a_dead_worker_fails_that_year_and_the_other_year_still_runs(monkeypatch, tmp_path):
	def find(year):
		if year == 2025:
			raise WorkerExitedError("Interval image scan worker exited unexpectedly")

		return [Path("cam_24-06-01_12-00-00-00.jpg")]

	code, events, rows = run_backfill(monkeypatch, tmp_path, find=find)

	assert code == 0
	assert events[:2] == ["find:2025", "release:Cam"]
	assert [row["status"] for row in rows] == ["failed", "created"]


# Frames that could not be removed are unblurred leftovers: the video is fine, but the run says it
# was not clean.
def test_a_failed_release_makes_the_run_exit_with_one(monkeypatch, tmp_path):
	code, events, rows = run_backfill(
		monkeypatch,
		tmp_path,
		release_errors={"Cam": OSError("cannot remove the frame cache")},
	)

	assert code == 1
	assert events.count("release:Cam") == 2
	assert [row["status"] for row in rows] == ["created", "created"]
