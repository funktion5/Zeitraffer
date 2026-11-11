import json
from pathlib import Path

from web_php_test import videos_library


def put(root: Path, relative: str, size: int) -> None:
	path = root / "videos" / relative
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"x" * size)


def test_video_storage_splits_a_camera_into_automatic_manual_highlights_and_other(tmp_path):
	put(tmp_path, "SLSV/daily/a.mp4", 10)
	put(tmp_path, "SLSV/weekly/b.mp4", 20)
	put(tmp_path, "SLSV/monthly/c.mp4", 30)
	put(tmp_path, "SLSV/yearly/d.mp4", 40)
	put(tmp_path, "SLSV/manual-runs/daily/e.mp4", 500)
	put(tmp_path, "SLSV/highlights/2026-11-01/f.jpg", 7)
	put(tmp_path, "SLSV/notes.txt", 3)

	result = videos_library(tmp_path, "echo json_encode(getVideoStorage());")

	assert result["cameras"]["SLSV"] == {
		"automatic": 100,
		"manual": 500,
		"highlights": 7,
		"other": 3,
		"total": 610,
	}
	assert result["automatic"] == 100
	assert result["manual"] == 500
	assert result["highlights"] == 7
	assert result["other"] == 3
	assert result["total"] == 610


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


def test_storage_segments_split_the_disk_into_five_parts(tmp_path):
	result = videos_library(
		tmp_path,
		"echo json_encode(storageSegments(1000.0, 600.0, 100, 50, 20));",
	)

	assert [(part["key"], part["bytes"], part["percent"]) for part in result] == [
		("automatic", 100, 10.0),
		("manual", 50, 5.0),
		("highlights", 20, 2.0),
		("other", 230, 23.0),
		("free", 600, 60.0),
	]


def test_storage_segments_never_go_negative_when_videos_exceed_the_used_space(tmp_path):
	# Sizes of files and of the disk are read at different moments: the rest is clamped to 0.
	result = videos_library(
		tmp_path,
		"echo json_encode(storageSegments(1000.0, 900.0, 80, 50, 10));",
	)

	other = next(part for part in result if part["key"] == "other")

	assert other["bytes"] == 0
	assert sum(part["percent"] for part in result) <= 100.1


def test_storage_usage_reports_level_and_segments(tmp_path):
	put(tmp_path, "A/daily/a.mp4", 10)
	put(tmp_path, "A/manual-runs/daily/b.mp4", 4)
	put(tmp_path, "A/highlights/d/h.jpg", 6)

	result = videos_library(tmp_path, "echo json_encode(getStorageUsage());")

	assert result["level"] in {"ok", "warn", "critical"}
	assert [part["key"] for part in result["segments"]] == [
		"automatic",
		"manual",
		"highlights",
		"other",
		"free",
	]
	assert [part["bytes"] for part in result["segments"][:3]] == [10, 4, 6]
	# "Davon Videos" counts the videos only: highlight pictures have a part of their own.
	assert result["videos"] == "14.0 B"
	assert {"total", "used", "available", "usedPercent"} <= set(result)


# The big donut: a disk of 1000 bytes with 600 free. The segments are what storageSegments() gives:
# the cameras' videos are inside them, so they add up to the whole disk.
def camera_parts(
	tmp_path: Path,
	sizes: dict,
	free: int = 600,
	maximum: int = 6,
	in_segments: int | None = None,
	videos_only: bool = False,
) -> list:
	# in_segments: the video bytes the segments saw, when the folders have grown since.
	videos = sum(sizes.values()) if in_segments is None else in_segments
	segments = [
		{"key": "automatic", "bytes": videos, "percent": 0},
		{"key": "other", "bytes": max(0, 1000 - free - videos), "percent": 0},
		{"key": "free", "bytes": free, "percent": 0},
	]
	cameras = {name: {"total": size} for name, size in sizes.items()}
	segments_php = f"json_decode({json.dumps(json.dumps(segments))}, true)"
	cameras_php = f"json_decode({json.dumps(json.dumps(cameras))}, true)"
	parts_php = (
		f"storageCameraParts({segments_php},"
		f' ["cameras" => {cameras_php}, "total" => {sum(sizes.values())}], {maximum})'
	)
	code = (
		f"echo json_encode({'storageVideoParts(' + parts_php + ')' if videos_only else parts_php});"
	)

	return videos_library(tmp_path, code)


def test_camera_parts_list_the_cameras_biggest_first_then_the_rest_of_the_disk(tmp_path):
	result = camera_parts(tmp_path, {"A": 50, "B": 80, "C": 20})

	assert [(part["label"], part["bytes"], part["percent"]) for part in result] == [
		("B", 80, 8.0),
		("A", 50, 5.0),
		("C", 20, 2.0),
		("Sonstiges (System, Modelle, Logs)", 250, 25.0),
		("Frei", 600, 60.0),
	]


def test_camera_parts_lump_the_smallest_cameras_together(tmp_path):
	result = camera_parts(tmp_path, {"A": 50, "B": 30, "C": 20, "D": 10}, maximum=2)

	assert [(part["label"], part["bytes"]) for part in result[:3]] == [
		("A", 50),
		("B", 30),
		("Weitere Kameras (2)", 30),
	]


def test_camera_parts_leave_out_cameras_and_parts_without_bytes(tmp_path):
	result = camera_parts(tmp_path, {"A": 100, "B": 0}, free=900)

	assert [part["label"] for part in result] == ["A", "Frei"]


# The folders are measured a moment after the disk: they can be bigger than the segments say.
def test_camera_parts_always_add_up_to_the_whole_disk(tmp_path):
	result = camera_parts(tmp_path, {"A": 600, "B": 300}, free=200, in_segments=700)

	assert sum(part["bytes"] for part in result) == 1000
	assert "Sonstiges (System, Modelle, Logs)" not in [part["label"] for part in result]


def test_camera_parts_give_every_part_its_own_colour(tmp_path):
	result = camera_parts(tmp_path, {"A": 50, "B": 80, "C": 20, "D": 10, "E": 5, "F": 4, "G": 3})

	colours = [part["color"] for part in result]

	assert len(set(colours)) == len(colours)


def test_camera_parts_say_what_kind_of_part_each_one_is(tmp_path):
	result = camera_parts(tmp_path, {"A": 50, "B": 30, "C": 20, "D": 10}, maximum=2)

	assert [part["kind"] for part in result] == ["camera", "camera", "more", "other", "free"]


# The donut of the videos only: just the cameras, each as a share of all videos.
def test_video_parts_are_only_the_cameras_as_a_share_of_the_videos(tmp_path):
	result = camera_parts(tmp_path, {"A": 300, "B": 100}, videos_only=True)

	assert [(part["label"], part["bytes"], part["videoPercent"]) for part in result] == [
		("A", 300, 75.0),
		("B", 100, 25.0),
	]


def test_video_parts_include_the_lumped_cameras_but_not_the_disk_parts(tmp_path):
	result = camera_parts(tmp_path, {"A": 50, "B": 30, "C": 20}, maximum=1, videos_only=True)

	assert [part["label"] for part in result] == ["A", "Weitere Kameras (2)"]


def test_video_parts_without_any_videos_are_empty(tmp_path):
	assert camera_parts(tmp_path, {}, videos_only=True) == []


# "Weitere Kameras (1)" would hide a camera's name for nothing: one left over is shown as itself.
def test_a_single_camera_over_the_limit_is_shown_by_name(tmp_path):
	result = camera_parts(tmp_path, {"A": 50, "B": 30, "C": 20}, maximum=2)

	assert [part["label"] for part in result[:3]] == ["A", "B", "C"]
	assert "more" not in [part["kind"] for part in result]
