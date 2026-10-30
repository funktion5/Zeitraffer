import shutil
from datetime import date
from pathlib import Path

import src.flagger.report as report
from src.flagger.report import cleanup_old_reports

TODAY = date(2026, 10, 21)


def day_folder(video_root: Path, camera: str, name: str) -> Path:
	folder = video_root / camera / "highlights" / name
	folder.mkdir(parents=True)
	(folder / "manifest.json").write_text("{}", encoding="utf-8")
	return folder


def test_boundary_30_days_old_stays_31_goes(tmp_path):
	gone = day_folder(tmp_path, "A", "2026-09-20")
	kept = [day_folder(tmp_path, "A", "2026-09-21"), day_folder(tmp_path, "A", "2026-10-20")]

	removed = cleanup_old_reports(tmp_path, TODAY, 30)

	assert removed == [gone]
	assert not gone.exists()
	assert all(folder.is_dir() for folder in kept)


def test_every_camera_is_cleaned_not_only_configured_ones(tmp_path):
	old = [day_folder(tmp_path, "A", "2026-08-01"), day_folder(tmp_path, "B", "2026-08-02")]

	removed = cleanup_old_reports(tmp_path, TODAY, 30)

	assert sorted(removed) == sorted(old)
	assert not any(folder.exists() for folder in old)


def test_only_plain_date_folders_inside_highlights_are_touched(tmp_path):
	highlights = tmp_path / "A" / "highlights"
	untouched = [
		day_folder(tmp_path, "A", "2026-09-20-keep"),
		day_folder(tmp_path, "A", "notes"),
		day_folder(tmp_path, "A", "2026-13-45"),
		day_folder(tmp_path, "A", ".2026-09-01.old"),
		day_folder(tmp_path, "A", ".2026-09-01.tmp.x"),
	]
	plain_file = highlights / "2026-09-01"
	plain_file.write_text("x", encoding="utf-8")
	outside = tmp_path / "outside"
	outside.mkdir()
	(outside / "keep.jpg").write_bytes(b"x")
	link = highlights / "2026-09-02"
	link.symlink_to(outside, target_is_directory=True)
	video = tmp_path / "A" / "manual-runs" / "yearly" / "old.mp4"
	video.parent.mkdir(parents=True)
	video.write_bytes(b"x")
	daily = tmp_path / "A" / "daily" / "A_2026-01-01.mp4"
	daily.parent.mkdir(parents=True)
	daily.write_bytes(b"x")

	assert cleanup_old_reports(tmp_path, TODAY, 30) == []

	assert all(folder.is_dir() for folder in untouched)
	assert plain_file.is_file()
	assert link.is_symlink() and (outside / "keep.jpg").is_file()
	assert video.is_file() and daily.is_file()


def test_retention_setting_moves_the_cutoff(tmp_path):
	week_old = day_folder(tmp_path, "A", "2026-10-13")

	assert cleanup_old_reports(tmp_path, TODAY, 30) == []
	assert cleanup_old_reports(tmp_path, TODAY, 7) == [week_old]


def test_missing_video_root_is_fine(tmp_path):
	assert cleanup_old_reports(tmp_path / "nope", TODAY, 30) == []


def test_a_failing_removal_is_logged_not_raised(tmp_path, monkeypatch):
	stuck = day_folder(tmp_path, "A", "2026-08-01")
	gone = day_folder(tmp_path, "B", "2026-08-01")
	real_rmtree = shutil.rmtree

	def failing_rmtree(path, *args, **kwargs):
		if Path(path) == stuck:
			raise OSError("busy")
		return real_rmtree(path, *args, **kwargs)

	monkeypatch.setattr(report.shutil, "rmtree", failing_rmtree)

	assert cleanup_old_reports(tmp_path, TODAY, 30) == [gone]
	assert stuck.is_dir()


def test_a_symlinked_highlights_folder_is_not_followed(tmp_path):
	elsewhere = tmp_path / "elsewhere"
	old = elsewhere / "2026-08-01"
	old.mkdir(parents=True)
	camera = tmp_path / "videos" / "A"
	camera.mkdir(parents=True)
	(camera / "highlights").symlink_to(elsewhere, target_is_directory=True)

	assert cleanup_old_reports(tmp_path / "videos", TODAY, 30) == []
	assert old.is_dir()


def test_old_work_folders_left_by_a_crash_are_removed(tmp_path):
	stale = day_folder(tmp_path, "A", ".2026-08-01.tmp")
	recent = day_folder(tmp_path, "A", ".2026-10-20.tmp")

	assert cleanup_old_reports(tmp_path, TODAY, 30) == [stale]
	assert recent.is_dir()
