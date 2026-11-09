import importlib.util
import os

import pytest

from src.config import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "list-deliverable-videos.py"


# The script's file name has a hyphen, so it cannot be imported by name. Loaded per test, so a
# missing script fails each test with its path instead of breaking the collection of the file.
@pytest.fixture
def script():
	spec = importlib.util.spec_from_file_location("list_deliverable_videos", SCRIPT_PATH)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	return module


def make_video(root, relative, size=1):
	path = root / relative
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"x" * size)

	return path


# One file per camera and period is all the website shows; the newest wins, by file name, like the
# WordPress plugin's latest_video(). A bug that lists every file would copy the whole history.
def test_only_the_newest_file_of_each_period_is_listed(script, tmp_path):
	for period in ("daily", "weekly", "monthly", "yearly"):
		make_video(tmp_path, f"Cam/{period}/Cam_2026-10-30.mp4")
		make_video(tmp_path, f"Cam/{period}/Cam_2026-11-01.mp4")
		make_video(tmp_path, f"Cam/{period}/Cam_2026-10-31.mp4")

	assert script.list_deliverable_videos(tmp_path, set()) == [
		"Cam/daily/Cam_2026-11-01.mp4",
		"Cam/monthly/Cam_2026-11-01.mp4",
		"Cam/weekly/Cam_2026-11-01.mp4",
		"Cam/yearly/Cam_2026-11-01.mp4",
	]


# A rebuilt or copied older video gets a fresh modification time but keeps its date in the name.
def test_newest_is_chosen_by_file_name_not_by_modification_time(script, tmp_path):
	newer_name = make_video(tmp_path, "Cam/daily/Cam_2026-11-01.mp4")
	older_name = make_video(tmp_path, "Cam/daily/Cam_2026-10-31.mp4")

	os.utime(newer_name, (1_000_000, 1_000_000))
	os.utime(older_name, (2_000_000, 2_000_000))

	assert script.list_deliverable_videos(tmp_path, set()) == ["Cam/daily/Cam_2026-11-01.mp4"]


# A camera that is a day behind must still deliver its own newest video.
def test_each_camera_is_chosen_on_its_own(script, tmp_path):
	make_video(tmp_path, "Zeta/daily/Zeta_2026-10-30.mp4")
	make_video(tmp_path, "Zeta/daily/Zeta_2026-10-29.mp4")
	make_video(tmp_path, "Alpha/daily/Alpha_2026-11-01.mp4")

	assert script.list_deliverable_videos(tmp_path, set()) == [
		"Alpha/daily/Alpha_2026-11-01.mp4",
		"Zeta/daily/Zeta_2026-10-30.mp4",
	]


# A failed render must not block the older good video from being the one on offer.
def test_a_newer_empty_file_loses_to_the_older_valid_one(script, tmp_path):
	make_video(tmp_path, "Cam/daily/Cam_2026-10-31.mp4")
	make_video(tmp_path, "Cam/daily/Cam_2026-11-01.mp4", size=0)

	assert script.list_deliverable_videos(tmp_path, set()) == ["Cam/daily/Cam_2026-10-31.mp4"]


# The encoder writes ".<name>.tmp.mp4" and renames it when done. A hidden name sorts before a
# normal one, so only a folder where it is the sole candidate shows whether it is filtered.
def test_a_hidden_temporary_file_is_never_listed(script, tmp_path):
	make_video(tmp_path, "Cam/daily/.Cam_2026-11-01.tmp.mp4")

	assert script.list_deliverable_videos(tmp_path, set()) == []


def test_a_symlinked_file_is_skipped_for_the_older_regular_one(script, tmp_path):
	outside = make_video(tmp_path / "outside", "secret.mp4")
	videos = tmp_path / "videos"

	make_video(videos, "Cam/daily/Cam_2026-10-31.mp4")
	(videos / "Cam" / "daily" / "Cam_2026-11-01.mp4").symlink_to(outside)

	assert script.list_deliverable_videos(videos, set()) == ["Cam/daily/Cam_2026-10-31.mp4"]


def test_a_symlinked_period_folder_is_not_followed(script, tmp_path):
	make_video(tmp_path / "outside", "Cam_2026-11-01.mp4")
	videos = tmp_path / "videos"

	(videos / "Cam").mkdir(parents=True)
	(videos / "Cam" / "daily").symlink_to(tmp_path / "outside", target_is_directory=True)

	assert script.list_deliverable_videos(videos, set()) == []


# The ignore list stops new builds only; the old videos of such a camera stay on disk.
def test_an_ignored_camera_is_skipped_although_it_has_videos(script, tmp_path):
	make_video(tmp_path, "Cam/daily/Cam_2026-11-01.mp4")
	make_video(tmp_path, "Hafenstrasse/daily/Hafenstrasse_2026-11-01.mp4")

	assert script.list_deliverable_videos(tmp_path, {"Hafenstrasse"}) == [
		"Cam/daily/Cam_2026-11-01.mp4"
	]


# The videos folder also holds test renders, highlight images, macOS and pytest leftovers. Each
# offender has a newer name than the valid video, so a leak would change the result.
@pytest.mark.parametrize(
	"offender",
	[
		"Cam/manual-runs/daily/Cam_2026-11-01_90min.mp4",
		"Cam/highlights/2026-11-01/clip.mp4",
		"Cam/alltime/Cam_2026-11-01.mp4",
		"Cam/daily/old/Cam_2026-11-01.mp4",
		"Cam/Cam_2026-11-01.mp4",
		"Cam_2026-11-01.mp4",
		"Cam/daily/Cam_2026-11-01.jpg",
		"Cam/daily/.DS_Store",
		"Cam/.DS_Store",
		"Cam/.pytest_cache/Cam_2026-11-01.mp4",
	],
)
def test_nothing_outside_the_four_period_folders_is_listed(script, tmp_path, offender):
	make_video(tmp_path, "Cam/daily/Cam_2026-10-31.mp4")
	make_video(tmp_path, offender)

	assert script.list_deliverable_videos(tmp_path, set()) == ["Cam/daily/Cam_2026-10-31.mp4"]


def test_a_period_without_a_valid_video_gives_no_entry(script, tmp_path):
	make_video(tmp_path, "Cam/daily/Cam_2026-11-01.mp4")
	(tmp_path / "Cam" / "monthly").mkdir()
	make_video(tmp_path, "Empty/daily/Empty_2026-11-01.mp4", size=0)

	assert script.list_deliverable_videos(tmp_path, set()) == ["Cam/daily/Cam_2026-11-01.mp4"]


# The job reads this output, so it is one relative path per line and nothing else. The ignore list
# comes from the config, not from an argument.
def test_main_prints_one_relative_path_per_line(script, tmp_path, monkeypatch, capsys):
	make_video(tmp_path, "Cam/daily/Cam_2026-11-01.mp4")
	make_video(tmp_path, "Hafenstrasse/daily/Hafenstrasse_2026-11-01.mp4")
	monkeypatch.setattr(script, "VIDEO_ROOT", tmp_path)
	monkeypatch.setattr(script, "load_config", lambda: {"ignored_cameras": ["Hafenstrasse"]})

	assert script.main() == 0
	assert capsys.readouterr().out == "Cam/daily/Cam_2026-11-01.mp4\n"


def test_main_lists_every_camera_when_the_config_has_no_ignored_cameras(
	script, tmp_path, monkeypatch, capsys
):
	make_video(tmp_path, "Cam/daily/Cam_2026-11-01.mp4")
	monkeypatch.setattr(script, "VIDEO_ROOT", tmp_path)
	monkeypatch.setattr(script, "load_config", lambda: {})

	assert script.main() == 0
	assert capsys.readouterr().out == "Cam/daily/Cam_2026-11-01.mp4\n"


# An empty list would look like "nothing to send"; a missing folder must be an error instead.
def test_main_exits_with_one_and_prints_nothing_when_the_videos_folder_is_missing(
	script, tmp_path, monkeypatch, capsys
):
	monkeypatch.setattr(script, "VIDEO_ROOT", tmp_path / "missing")
	monkeypatch.setattr(script, "load_config", lambda: {"ignored_cameras": []})

	assert script.main() == 1
	assert capsys.readouterr().out == ""
