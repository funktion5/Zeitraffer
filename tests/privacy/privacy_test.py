import math
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

import src.privacy.anonymize as privacy
from src.privacy.anonymize import (
	BlurSettings,
	Box,
	PrivacyCheckError,
	blur_region,
	parse_blur_settings,
)

BLUR = {
	"strength": 0.25,
	"padding_ratio": 0.25,
	"feather": 0.5,
}

requires_ffmpeg = pytest.mark.skipif(
	shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
	reason="FFmpeg is not installed.",
)

# Stand-in for a real model: behaviour is selected by its first argument.
FAKE_DETECTOR = """
import json
import sys
import time

mode = sys.argv[1]
paths = [line.strip() for line in sys.stdin if line.strip()]

if mode == "fail":
	sys.stderr.write("model file missing")
	sys.exit(3)

if mode == "garbage":
	print("this is not json")
	sys.exit(0)

if mode == "hang" and paths:
	time.sleep(30)

results = {}

for path in paths:
	if mode == "missing" and path.endswith("frame_000002.jpg"):
		continue

	if path.endswith("frame_000001.jpg"):
		box = {"x0": 10, "y0": 10, "x1": 40, "y1": 60, "score": 0.31}

		if mode == "inverted":
			box = {"x0": 40, "y0": 10, "x1": 10, "y1": 60, "score": 0.31}

		results[path] = [box]

	else:
		results[path] = []

print(json.dumps({"detector": "fake-1", "results": results}))
"""


@pytest.fixture
def detector_script(tmp_path: Path) -> Path:
	script = tmp_path / "fake_detector.py"
	script.write_text(FAKE_DETECTOR)

	return script


def detector_command(script: Path, mode: str = "ok") -> list[str]:
	return [sys.executable, str(script), mode]


# Numbered like the video's temporary frames; the fake detector only reads the names.
def make_frames(tmp_path: Path, count: int = 3) -> list[Path]:
	frames = [tmp_path / f"frame_{index:06d}.jpg" for index in range(1, count + 1)]

	for index, frame in enumerate(frames):
		frame.write_bytes(b"jpeg-bytes-" + bytes([index]))

	return frames


# 1080 px high, top third up to y=360: only a box with more than half its height above that goes.
def test_split_top_band_drops_boxes_mostly_in_the_top_part() -> None:
	mount = Box(x0=1545, y0=20, x1=1918, y1=480, score=0.35)
	tall_person = Box(x0=100, y0=200, x1=200, y1=900, score=0.9)
	half = Box(x0=0, y0=260, x1=50, y1=460, score=0.5)

	kept, dropped = privacy.split_top_band([mount, tall_person, half], 1080, 1 / 3)

	assert kept == [tall_person, half]
	assert dropped == [mount]


def test_blur_region_keeps_even_bounds_inside_the_image():
	settings = parse_blur_settings(BLUR)
	region = blur_region(Box(x0=3, y0=5, x1=43, y1=85, score=0.2), 101, 60, settings)

	assert (region.x, region.y) == (0, 0)
	assert region.x + region.w <= 100 and region.y + region.h <= 60
	assert all(value % 2 == 0 for value in (region.x, region.y, region.w, region.h))
	# The 40 px wide box gains at least its 25 % margin on the right.
	assert region.x + region.w >= 53


# With a block from the detector (vehicles, plates) that wins over the strength rule.
def test_pixelate_uses_the_detectors_block_size_when_given():
	settings = parse_blur_settings({**BLUR, "strength": 0.08})
	plain = blur_region(Box(x0=100, y0=100, x1=400, y1=220, score=0.9), 1920, 1080, settings)
	fine = blur_region(
		Box(x0=100, y0=100, x1=400, y1=220, score=0.9, block=4.0), 1920, 1080, settings
	)
	strength_block = max(2, round(min(plain.w, plain.h) * 0.08))

	assert strength_block > 4
	assert privacy._effect_filter(plain, settings).startswith(
		f"scale={math.ceil(plain.w / strength_block)}:{math.ceil(plain.h / strength_block)}:"
	)
	assert privacy._effect_filter(fine, settings).startswith(
		f"scale={math.ceil(fine.w / 4)}:{math.ceil(fine.h / 4)}:"
	)


def test_label_from_the_detector_is_kept_as_given():
	raw = {"x0": 1, "y0": 1, "x1": 9, "y1": 9, "score": 0.5, "label": "vehicle", "block": 4}

	box = privacy._parse_box(raw, "a.jpg")

	assert (box.label, box.block) == ("vehicle", 4.0)
	assert privacy._parse_box(asdict(box), "a.jpg") == box
	assert privacy._parse_box({**raw, "label": None}, "a.jpg").label is None

	with pytest.raises(PrivacyCheckError, match="'label'"):
		privacy._parse_box({**raw, "label": 3}, "a.jpg")


@pytest.mark.parametrize("block", [0, 0.5, True, "4", float("nan")])
def test_invalid_block_size_from_the_detector_is_refused(block):
	raw = {"x0": 1, "y0": 1, "x1": 9, "y1": 9, "score": 0.5, "block": block}

	with pytest.raises(PrivacyCheckError):
		privacy._parse_box(raw, "a.jpg")


def test_blur_region_core_always_covers_the_detected_box():
	box = Box(x0=200, y0=100, x1=260, y1=260, score=0.4)
	region = blur_region(box, 1920, 1080, parse_blur_settings(BLUR))

	for corner_x, corner_y in [(box.x0, box.y0), (box.x1, box.y1), (box.x0, box.y1)]:
		dx = (corner_x - region.centre_x) / region.half_w
		dy = (corner_y - region.centre_y) / region.half_h
		distance = max(abs(dx), abs(dy))

		assert distance <= region.core + 1e-9


def test_parse_blur_settings_accepts_the_production_defaults():
	assert parse_blur_settings(BLUR) == BlurSettings(
		strength=0.25,
		padding_ratio=0.25,
		feather=0.5,
	)


@pytest.mark.parametrize(
	("change", "message"),
	[
		({"strength": 2}, "strength must be between"),
		({"strength": "strong"}, "strength must be a number"),
		({"padding_ratio": 0.0}, "padding_ratio must be between"),
		({"feather": -0.1}, "feather must be between"),
		({"feather": True}, "feather must be a number"),
	],
)
def test_parse_blur_settings_rejects_invalid_values(change, message):
	with pytest.raises(PrivacyCheckError, match=message):
		parse_blur_settings({**BLUR, **change})


def test_parse_blur_settings_rejects_missing_block():
	with pytest.raises(PrivacyCheckError, match="missing"):
		parse_blur_settings(None)


def make_test_picture(path: Path) -> None:
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-f",
			"lavfi",
			"-i",
			"testsrc=size=320x240",
			"-frames:v",
			"1",
			"-q:v",
			"2",
			str(path),
		],
		check=True,
	)


def mean_difference(first: Path, second: Path, crop: str) -> float:
	output = subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-i",
			str(first),
			"-i",
			str(second),
			"-filter_complex",
			f"[0:v]{crop},format=gray[a];[1:v]{crop},format=gray[b];"
			"[a][b]blend=all_mode=difference,signalstats,"
			"metadata=print:key=lavfi.signalstats.YAVG:file=-",
			"-f",
			"null",
			"-",
		],
		capture_output=True,
		text=True,
		check=True,
	).stdout

	return float(output.strip().splitlines()[-1].split("=")[1])


@requires_ffmpeg
@pytest.mark.parametrize(
	"change",
	[
		{},
		{"feather": 0.0},
		{"feather": 1.0},
	],
)
def test_blur_frame_changes_the_box_but_not_the_rest(tmp_path: Path, change):
	frame = tmp_path / "frame_000001.jpg"
	make_test_picture(frame)
	reference = tmp_path / "reference.jpg"
	shutil.copy2(frame, reference)

	settings = parse_blur_settings({**BLUR, **change})
	privacy.blur_frame(frame, [Box(x0=100, y0=80, x1=160, y1=160, score=0.5)], settings)

	assert privacy._probe_dimensions(frame) == (320, 240)
	# The box centre is fully replaced even when the whole margin fades out.
	assert mean_difference(frame, reference, "crop=40:40:110:100") > 10
	assert mean_difference(frame, reference, "crop=40:40:0:0") < 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_detector_box_with_non_finite_value_is_refused(value):
	from src.privacy.anonymize import _parse_box

	raw = {"x0": 1, "y0": 1, "x1": value, "y1": 9, "score": 0.9}

	with pytest.raises(PrivacyCheckError, match="invalid"):
		_parse_box(raw, "frame.jpg")


# Drop rules: one filter for video mode and the box job.


def test_filter_boxes_drops_known_false_positives_and_the_top_band() -> None:
	sign = Box(x0=706, y0=557, x1=741, y1=640, score=0.9)
	mount = Box(x0=1545, y0=20, x1=1918, y1=480, score=0.35)
	person = Box(x0=739, y0=574, x1=767, y1=644, score=0.9)
	rules = privacy.DropRules(top_share=1 / 3, ignore_boxes={"Cam": [[703, 557, 742, 643]]})

	kept, ignored = privacy.filter_boxes([sign, mount, person], 1080, rules, "Cam")

	assert kept == [person]
	assert ignored == [sign, mount]
	# Known boxes belong to their camera only.
	assert privacy.filter_boxes([sign], 1080, rules, "Other")[0] == [sign]


# A camera's own top share replaces the global one for that camera only, and 0 switches the band off
# there. The frame is 1080 px high; the mount box is mostly (74 %) inside the top third, the low
# box not at all.
def test_filter_boxes_uses_the_cameras_own_top_share() -> None:
	mount = Box(x0=1545, y0=20, x1=1918, y1=480, score=0.35)
	low = Box(x0=100, y0=400, x1=140, y1=500, score=0.9)
	rules = privacy.DropRules(
		top_share=1 / 3,
		top_share_by_camera={"Narrow": 0.1, "Off": 0.0, "Wide": 0.45},
	)

	# No value of its own: the global third decides.
	assert privacy.filter_boxes([mount, low], 1080, rules, "Other") == ([low], [mount])
	# A narrower band keeps the mount (19 % inside), a switched-off band keeps everything.
	assert privacy.filter_boxes([mount, low], 1080, rules, "Narrow") == ([mount, low], [])
	assert privacy.filter_boxes([mount, low], 1080, rules, "Off") == ([mount, low], [])
	# A wider band also takes the low box (86 % inside 0.45 of 1080 = 486 px).
	assert privacy.filter_boxes([mount, low], 1080, rules, "Wide") == ([], [mount, low])


# SLSV: boats on wheeled trailers are found as vehicles, and plate search runs inside them.
def test_filter_boxes_skips_the_camera_s_listed_labels_only() -> None:
	boat = Box(x0=100, y0=600, x1=400, y1=800, score=0.5, label="vehicle")
	stripe = Box(x0=150, y0=700, x1=200, y1=720, score=0.5, label="plate")
	person = Box(x0=500, y0=600, x1=540, y1=700, score=0.9, label="person")
	unlabelled = Box(x0=600, y0=600, x1=640, y1=700, score=0.9)
	rules = privacy.DropRules(skip_labels={"Cam": ["vehicle", "plate"]})

	kept, ignored = privacy.filter_boxes([boat, stripe, person, unlabelled], 1080, rules, "Cam")

	assert kept == [person, unlabelled]
	assert ignored == [boat, stripe]
	assert privacy.filter_boxes([boat], 1080, rules, "Other")[0] == [boat]


# SLSV: boat covers and winches are found as people, mostly with low scores.
def test_filter_boxes_drops_weak_person_boxes_of_that_camera_only() -> None:
	cover = Box(x0=100, y0=600, x1=400, y1=800, score=0.3, label="person")
	person = Box(x0=500, y0=600, x1=540, y1=700, score=0.35, label="person")
	vehicle = Box(x0=600, y0=600, x1=800, y1=700, score=0.2, label="vehicle")
	unlabelled = Box(x0=900, y0=600, x1=940, y1=700, score=0.3)
	rules = privacy.DropRules(min_person_score={"Cam": 0.35})

	kept, ignored = privacy.filter_boxes([cover, person, vehicle, unlabelled], 1080, rules, "Cam")

	assert kept == [person, vehicle, unlabelled]
	assert ignored == [cover]
	assert privacy.filter_boxes([cover], 1080, rules, "Other")[0] == [cover]


def test_parse_drop_rules_accepts_the_production_shape() -> None:
	rules = privacy.parse_drop_rules(
		{
			"ignore_top_share": 0.333,
			"ignore_boxes": {"C": [[1, 2, 3, 4]]},
			"skip_labels": {"D": ["vehicle", "plate"]},
			"min_person_score": {"D": 0.35},
		}
	)

	assert rules == privacy.DropRules(
		top_share=0.333,
		ignore_boxes={"C": [[1, 2, 3, 4]]},
		skip_labels={"D": ["vehicle", "plate"]},
		min_person_score={"D": 0.35},
	)
	assert privacy.parse_drop_rules({}) == privacy.DropRules()


# A camera's own top share: a map of camera to number, with the same limits as the global one.
def test_parse_drop_rules_reads_the_per_camera_top_share() -> None:
	rules = privacy.parse_drop_rules(
		{"ignore_top_share": 0.333, "ignore_top_share_per_camera": {"A": 0.1, "B": 0, "C": 0.49}}
	)

	assert rules.top_share == 0.333
	assert rules.top_share_by_camera == {"A": 0.1, "B": 0.0, "C": 0.49}
	assert all(isinstance(share, float) for share in rules.top_share_by_camera.values())
	# Without the key every camera follows the global value.
	assert privacy.parse_drop_rules({"ignore_top_share": 0.2}).top_share_by_camera == {}


# Each of these would silently drop real people instead of stopping the run.
@pytest.mark.parametrize(
	"privacy_section",
	[
		{"ignore_top_share": 3.33},
		{"ignore_top_share": 0.5},
		{"ignore_top_share": -0.1},
		{"ignore_top_share": True},
		{"ignore_top_share": "0.3"},
		{"ignore_top_share_per_camera": 0.3},
		{"ignore_top_share_per_camera": [0.1]},
		{"ignore_top_share_per_camera": {"C": 0.5}},
		{"ignore_top_share_per_camera": {"C": 3.33}},
		{"ignore_top_share_per_camera": {"C": -0.1}},
		{"ignore_top_share_per_camera": {"C": True}},
		{"ignore_top_share_per_camera": {"C": "0.3"}},
		{"ignore_top_share_per_camera": {"C": None}},
		{"ignore_boxes": [[1, 2, 3, 4]]},
		{"ignore_boxes": {"C": [[1, 2, 3]]}},
		{"ignore_boxes": {"C": [[3, 2, 1, 4]]}},
		{"ignore_boxes": {"C": [[1.5, 2, 3, 4]]}},
		{"ignore_boxes": {"C": "703, 557, 742, 643"}},
		{"skip_labels": ["vehicle"]},
		{"skip_labels": {"C": "vehicle"}},
		{"skip_labels": {"C": []}},
		{"skip_labels": {"C": ["person"]}},
		{"skip_labels": {"C": ["vehicle", "Plate"]}},
		{"min_person_score": 0.35},
		{"min_person_score": {"C": 3.5}},
		{"min_person_score": {"C": 0.51}},
		{"min_person_score": {"C": -0.1}},
		{"min_person_score": {"C": "0.35"}},
		{"min_person_score": {"C": True}},
	],
)
def test_parse_drop_rules_refuses_values_that_would_drop_too_much(privacy_section) -> None:
	with pytest.raises(PrivacyCheckError):
		privacy.parse_drop_rules(privacy_section)


@pytest.mark.parametrize("output", ["", "1920", "1920,abc", "1920,1080,3"])
def test_unreadable_image_size_is_a_privacy_error(monkeypatch, tmp_path: Path, output) -> None:
	monkeypatch.setattr(
		privacy.subprocess,
		"run",
		lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
	)

	with pytest.raises(PrivacyCheckError, match="Cannot read the size"):
		privacy._probe_dimensions(tmp_path / "frame.jpg")


def test_explicit_detector_timeout_wins(tmp_path: Path, detector_script: Path) -> None:
	frames = make_frames(tmp_path, count=1)

	with pytest.raises(PrivacyCheckError, match="timed out after 1 s"):
		privacy.run_detector(detector_command(detector_script, "hang"), frames, 1)


def test_run_detector_returns_the_boxes_of_every_frame(
	tmp_path: Path, detector_script: Path
) -> None:
	frames = make_frames(tmp_path)

	detector, boxes = privacy.run_detector(detector_command(detector_script), frames, 10)

	assert detector == "fake-1"
	assert boxes == {
		frames[0]: [Box(x0=10, y0=10, x1=40, y1=60, score=0.31)],
		frames[1]: [],
		frames[2]: [],
	}


# The box blur relies on these: a frame is never treated as clean on doubtful detector output.
@pytest.mark.parametrize(
	("mode", "message"),
	[
		("fail", "exit code 3"),
		("garbage", "not valid JSON"),
		("missing", "no result for frame_000002.jpg"),
		("inverted", "empty or inverted box"),
	],
)
def test_run_detector_fails_closed_on_bad_output(
	tmp_path: Path, detector_script: Path, mode: str, message: str
) -> None:
	frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match=message):
		privacy.run_detector(detector_command(detector_script, mode), frames, 10)


def test_run_detector_fails_closed_when_the_detector_cannot_start(tmp_path: Path) -> None:
	frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match="could not be started"):
		privacy.run_detector([str(tmp_path / "no-such-detector")], frames, 10)
