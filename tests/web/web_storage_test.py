import json
from pathlib import Path

from web_php_test import videos_library


def put(root: Path, relative: str, size: int) -> None:
	path = root / "videos" / relative
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"x" * size)


def test_video_storage_splits_a_camera_into_automatic_manual_and_other(tmp_path):
	put(tmp_path, "SLSV/daily/a.mp4", 10)
	put(tmp_path, "SLSV/weekly/b.mp4", 20)
	put(tmp_path, "SLSV/monthly/c.mp4", 30)
	put(tmp_path, "SLSV/yearly/d.mp4", 40)
	put(tmp_path, "SLSV/manual-runs/daily/e.mp4", 500)
	put(tmp_path, "SLSV/highlights/2026-11-01/f.jpg", 7)

	result = videos_library(tmp_path, "echo json_encode(getVideoStorage());")

	assert result["cameras"]["SLSV"] == {"automatic": 100, "manual": 500, "other": 7, "total": 607}
	assert result["automatic"] == 100
	assert result["manual"] == 500
	assert result["other"] == 7
	assert result["total"] == 607


def test_video_storage_adds_up_all_cameras(tmp_path):
	put(tmp_path, "A/daily/a.mp4", 10)
	put(tmp_path, "B/daily/b.mp4", 5)
	put(tmp_path, "B/manual-runs/yearly/c.mp4", 3)

	result = videos_library(tmp_path, "echo json_encode(getVideoStorage());")

	assert sorted(result["cameras"]) == ["A", "B"]
	assert (result["automatic"], result["manual"], result["total"]) == (15, 3, 18)


# The disk is counted as it is: an ignored camera's videos still fill it.
def test_video_storage_counts_cameras_that_are_ignored(tmp_path):
	(tmp_path / "config").mkdir()
	(tmp_path / "config" / "config.json").write_text(json.dumps({"ignored_cameras": ["A"]}))
	put(tmp_path, "A/daily/a.mp4", 10)

	result = videos_library(tmp_path, "echo json_encode(getVideoStorage());")

	assert result["total"] == 10


def test_video_storage_skips_loose_files_symlinks_and_odd_names(tmp_path):
	put(tmp_path, "A/daily/a.mp4", 10)
	put(tmp_path, "loose.txt", 99)
	put(tmp_path, ".hidden/daily/x.mp4", 99)
	outside = tmp_path / "outside.bin"
	outside.write_bytes(b"x" * 1000)
	(tmp_path / "videos" / "A" / "daily" / "link.mp4").symlink_to(outside)

	result = videos_library(tmp_path, "echo json_encode(getVideoStorage());")

	assert list(result["cameras"]) == ["A"]
	assert result["total"] == 10


def test_video_storage_without_a_videos_folder_is_empty(tmp_path):
	result = videos_library(tmp_path, "echo json_encode(getVideoStorage());")

	assert result["cameras"] == []
	assert result["total"] == 0


def test_storage_level_switches_at_80_and_90_percent(tmp_path):
	result = videos_library(
		tmp_path,
		'echo json_encode(array_map("storageLevel", [0, 79.9, 80, 89.9, 90, 100]));',
	)

	assert result == ["ok", "ok", "warn", "warn", "critical", "critical"]


def test_storage_segments_split_the_disk_into_four_parts(tmp_path):
	result = videos_library(
		tmp_path,
		"echo json_encode(storageSegments(1000.0, 600.0, 100, 50));",
	)

	assert [(part["key"], part["bytes"], part["percent"]) for part in result] == [
		("automatic", 100, 10.0),
		("manual", 50, 5.0),
		("other", 250, 25.0),
		("free", 600, 60.0),
	]


def test_storage_segments_never_go_negative_when_videos_exceed_the_used_space(tmp_path):
	# Sizes of files and of the disk are read at different moments: the rest is clamped to 0.
	result = videos_library(
		tmp_path,
		"echo json_encode(storageSegments(1000.0, 900.0, 80, 50));",
	)

	other = next(part for part in result if part["key"] == "other")

	assert other["bytes"] == 0
	assert sum(part["percent"] for part in result) <= 100.1


def test_storage_usage_reports_level_and_segments(tmp_path):
	put(tmp_path, "A/daily/a.mp4", 10)
	put(tmp_path, "A/manual-runs/daily/b.mp4", 4)

	result = videos_library(tmp_path, "echo json_encode(getStorageUsage());")

	assert result["level"] in {"ok", "warn", "critical"}
	assert [part["key"] for part in result["segments"]] == ["automatic", "manual", "other", "free"]
	assert result["segments"][0]["bytes"] == 10
	assert result["segments"][1]["bytes"] == 4
	assert {"total", "used", "available", "usedPercent"} <= set(result)
