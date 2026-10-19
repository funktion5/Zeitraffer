import json
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
	anonymize_frames,
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
import os
import sys
import time

mode = sys.argv[1]
paths = [line.strip() for line in sys.stdin if line.strip()]

log = os.environ.get("FAKE_DETECTOR_LOG")

if log and paths:
	with open(log, "a") as file:
		file.write("\\n".join(paths) + "\\n")

if mode == "fail":
	sys.stderr.write("model file missing")
	sys.exit(3)

if mode == "garbage":
	print("this is not json")
	sys.exit(0)

if mode == "hang" and paths:
	time.sleep(30)

detector = "fake-2" if mode == "swap" and paths else "fake-1"
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

print(json.dumps({"detector": detector, "results": results}))
"""


@pytest.fixture
def detector_script(tmp_path: Path) -> Path:
	script = tmp_path / "fake_detector.py"
	script.write_text(FAKE_DETECTOR)

	return script


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch) -> Path:
	state_root = tmp_path / "state" / "privacy"
	monkeypatch.setattr(privacy, "PRIVACY_STATE_ROOT", state_root)

	return state_root


@pytest.fixture
def blur_calls(monkeypatch) -> list[tuple[str, list[Box]]]:
	calls: list[tuple[str, list[Box]]] = []

	monkeypatch.setattr(
		privacy,
		"blur_frame",
		lambda frame, boxes, settings, size=None: calls.append((frame.name, boxes)),
	)
	# The fake frames are no real images; anonymize_frames reads their size before blurring.
	monkeypatch.setattr(privacy, "_probe_dimensions", lambda frame: (1920, 1080))

	return calls


def detector_command(script: Path, mode: str = "ok") -> list[str]:
	return [sys.executable, str(script), mode]


# Mirror copy_images_to_temp: originals keep their names, copies are numbered frames.
def make_frames(tmp_path: Path, count: int = 3) -> tuple[list[Path], list[Path]]:
	original_dir = tmp_path / "cameras" / "Test-Camera"
	temp_dir = tmp_path / "temp" / "Test-Camera"
	original_dir.mkdir(parents=True)
	temp_dir.mkdir(parents=True)

	originals = []
	frames = []

	for index in range(1, count + 1):
		original = original_dir / f"20260101T12{index:02d}01.jpg"
		original.write_bytes(b"jpeg-bytes-" + bytes([index]))

		frame = temp_dir / f"frame_{index:06d}.jpg"
		shutil.copy2(original, frame)

		originals.append(original)
		frames.append(frame)

	return originals, frames


def read_cache(state_root: Path) -> list[dict]:
	path = state_root / "Test-Camera.jsonl"

	return [json.loads(line) for line in path.read_text().splitlines()]


# 1080 px high, top third up to y=360: only a box with more than half its height above that goes.
def test_split_top_band_drops_boxes_mostly_in_the_top_part() -> None:
	mount = Box(x0=1545, y0=20, x1=1918, y1=480, score=0.35)
	tall_person = Box(x0=100, y0=200, x1=200, y1=900, score=0.9)
	half = Box(x0=0, y0=260, x1=50, y1=460, score=0.5)

	kept, dropped = privacy.split_top_band([mount, tall_person, half], 1080, 1 / 3)

	assert kept == [tall_person, half]
	assert dropped == [mount]


def test_anonymize_skips_a_frame_whose_only_box_is_in_the_top_band(
	tmp_path: Path,
	detector_script: Path,
	isolated_state: Path,
	blur_calls,
	monkeypatch,
):
	originals, frames = make_frames(tmp_path)
	# The fake detector's box spans y 10-60; with a 100 px high frame, 0.4 puts the band at y 40.
	monkeypatch.setattr(privacy, "_probe_dimensions", lambda frame: (100, 100))

	anonymize_frames(
		"Test-Camera",
		originals,
		frames,
		detector_command(detector_script),
		BLUR,
		privacy.DropRules(top_share=0.4),
	)

	assert blur_calls == []
	# Still cached unfiltered: the rule may change without a new detection.
	assert read_cache(isolated_state)[0]["boxes"][0]["y0"] == 10


def test_anonymize_requires_configured_detector(tmp_path: Path):
	originals, frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match="detector_command is not set"):
		anonymize_frames("Test-Camera", originals, frames, None, BLUR)


def test_anonymize_blurs_only_frames_with_detections(
	tmp_path: Path,
	detector_script: Path,
	isolated_state: Path,
	blur_calls,
):
	originals, frames = make_frames(tmp_path)

	anonymize_frames("Test-Camera", originals, frames, detector_command(detector_script), BLUR)

	assert [name for name, _ in blur_calls] == ["frame_000001.jpg"]
	assert blur_calls[0][1] == [Box(x0=10, y0=10, x1=40, y1=60, score=0.31)]

	# The cache is keyed on the original name, not the temporary frame number.
	cache = read_cache(isolated_state)
	assert [entry["image"] for entry in cache] == [original.name for original in originals]
	assert {entry["detector"] for entry in cache} == {"fake-1"}


def test_anonymize_uses_cache_on_rerun(
	tmp_path: Path,
	detector_script: Path,
	monkeypatch,
	blur_calls,
):
	log = tmp_path / "detector.log"
	monkeypatch.setenv("FAKE_DETECTOR_LOG", str(log))
	originals, frames = make_frames(tmp_path)
	command = detector_command(detector_script)

	anonymize_frames("Test-Camera", originals, frames, command, BLUR)
	first_run_requests = log.read_text().splitlines()

	anonymize_frames("Test-Camera", originals, frames, command, BLUR)

	# Only the id probe ran the second time; it sends no paths, so nothing was logged.
	assert log.read_text().splitlines() == first_run_requests
	assert len(first_run_requests) == 3

	# Cached boxes are still blurred, because the copies are fresh every run.
	assert [name for name, _ in blur_calls] == ["frame_000001.jpg", "frame_000001.jpg"]


def test_anonymize_rechecks_changed_files(
	tmp_path: Path,
	detector_script: Path,
	monkeypatch,
	blur_calls,
):
	log = tmp_path / "detector.log"
	monkeypatch.setenv("FAKE_DETECTOR_LOG", str(log))
	originals, frames = make_frames(tmp_path)
	command = detector_command(detector_script)

	anonymize_frames("Test-Camera", originals, frames, command, BLUR)
	log.write_text("")

	frames[1].write_bytes(b"a different and longer picture")

	anonymize_frames("Test-Camera", originals, frames, command, BLUR)

	assert log.read_text().splitlines() == [str(frames[1].resolve())]


def test_anonymize_rechecks_results_from_another_detector(
	tmp_path: Path,
	detector_script: Path,
	isolated_state: Path,
	monkeypatch,
	blur_calls,
):
	log = tmp_path / "detector.log"
	monkeypatch.setenv("FAKE_DETECTOR_LOG", str(log))
	originals, frames = make_frames(tmp_path)

	isolated_state.mkdir(parents=True)
	(isolated_state / "Test-Camera.jsonl").write_text(
		"".join(
			json.dumps(
				{
					"image": original.name,
					"size": frame.stat().st_size,
					"mtime_ns": frame.stat().st_mtime_ns,
					"detector": "old-model-0",
					"boxes": [],
				}
			)
			+ "\n"
			for original, frame in zip(originals, frames, strict=True)
		)
	)

	anonymize_frames("Test-Camera", originals, frames, detector_command(detector_script), BLUR)

	assert len(log.read_text().splitlines()) == 3


@pytest.mark.parametrize(
	("mode", "message"),
	[
		("fail", "exit code 3"),
		("garbage", "not valid JSON"),
		("missing", "no result for frame_000002.jpg"),
		("inverted", "empty or inverted box"),
		("swap", "Detector id changed"),
	],
)
def test_anonymize_fails_closed_on_bad_detector_output(
	tmp_path: Path,
	detector_script: Path,
	isolated_state: Path,
	blur_calls,
	mode: str,
	message: str,
):
	originals, frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match=message):
		anonymize_frames(
			"Test-Camera", originals, frames, detector_command(detector_script, mode), BLUR
		)

	# Nothing is blurred or cached from a batch that was not fully trusted.
	assert blur_calls == []
	assert not (isolated_state / "Test-Camera.jsonl").exists()


def test_anonymize_fails_closed_on_detector_timeout(
	tmp_path: Path,
	detector_script: Path,
	monkeypatch,
	blur_calls,
):
	monkeypatch.setattr(privacy, "DETECTOR_BATCH_TIMEOUT_SECONDS", 1)
	originals, frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match="timed out"):
		anonymize_frames(
			"Test-Camera", originals, frames, detector_command(detector_script, "hang"), BLUR
		)

	assert blur_calls == []


def test_anonymize_fails_closed_when_detector_cannot_start(tmp_path: Path):
	originals, frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match="could not be started"):
		anonymize_frames(
			"Test-Camera", originals, frames, [str(tmp_path / "no-such-detector")], BLUR
		)


def test_anonymize_fails_closed_when_blurring_fails(
	tmp_path: Path,
	detector_script: Path,
	monkeypatch,
):
	def failing_blur(frame, boxes, settings, size=None):
		raise subprocess.CalledProcessError(1, ["ffmpeg"])

	monkeypatch.setattr(privacy, "blur_frame", failing_blur)
	# The fake frames are no real images, and CI has no ffprobe: give them a size.
	monkeypatch.setattr(privacy, "_probe_dimensions", lambda frame: (1920, 1080))
	originals, frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match="Blurring failed for 20260101T120101.jpg"):
		anonymize_frames("Test-Camera", originals, frames, detector_command(detector_script), BLUR)


def test_anonymize_sends_frames_in_batches(
	tmp_path: Path,
	detector_script: Path,
	isolated_state: Path,
	monkeypatch,
	blur_calls,
):
	monkeypatch.setattr(privacy, "DETECTOR_BATCH_SIZE", 2)
	originals, frames = make_frames(tmp_path, count=5)

	anonymize_frames("Test-Camera", originals, frames, detector_command(detector_script), BLUR)

	assert len(read_cache(isolated_state)) == 5


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


def test_label_from_the_detector_is_kept_and_cached_as_given():
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


def test_anonymize_rejects_invalid_blur_settings_before_detecting(
	tmp_path: Path,
	detector_script: Path,
	monkeypatch,
	blur_calls,
):
	log = tmp_path / "detector.log"
	monkeypatch.setenv("FAKE_DETECTOR_LOG", str(log))
	originals, frames = make_frames(tmp_path)

	with pytest.raises(PrivacyCheckError, match="strength"):
		anonymize_frames(
			"Test-Camera",
			originals,
			frames,
			detector_command(detector_script),
			{**BLUR, "strength": 9},
		)

	assert not log.exists()


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


def test_parse_drop_rules_accepts_the_production_shape() -> None:
	rules = privacy.parse_drop_rules(
		{
			"ignore_top_share": 0.333,
			"ignore_boxes": {"C": [[1, 2, 3, 4]]},
			"skip_labels": {"D": ["vehicle", "plate"]},
		}
	)

	assert rules == privacy.DropRules(
		top_share=0.333,
		ignore_boxes={"C": [[1, 2, 3, 4]]},
		skip_labels={"D": ["vehicle", "plate"]},
	)
	assert privacy.parse_drop_rules({}) == privacy.DropRules()


# Each of these would silently drop real people instead of stopping the run.
@pytest.mark.parametrize(
	"privacy_section",
	[
		{"ignore_top_share": 3.33},
		{"ignore_top_share": 0.5},
		{"ignore_top_share": -0.1},
		{"ignore_top_share": True},
		{"ignore_top_share": "0.3"},
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


def test_cache_keeps_only_the_newest_line_per_image(
	tmp_path: Path,
	detector_script: Path,
	isolated_state: Path,
	blur_calls,
):
	originals, frames = make_frames(tmp_path)
	command = detector_command(detector_script)
	anonymize_frames("Test-Camera", originals, frames, command, BLUR)

	# A changed frame is detected again, which appends a second line for it.
	frames[1].write_bytes(b"a different and longer picture")
	anonymize_frames("Test-Camera", originals, frames, command, BLUR)

	cache = read_cache(isolated_state)
	assert [entry["image"] for entry in cache] == [original.name for original in originals]
	assert cache[1]["size"] == len(b"a different and longer picture")
	assert not list(isolated_state.glob(".*.tmp"))


def test_explicit_detector_timeout_wins(tmp_path: Path, detector_script: Path) -> None:
	_, frames = make_frames(tmp_path, count=1)

	with pytest.raises(PrivacyCheckError, match="timed out after 1 s"):
		privacy.run_detector(detector_command(detector_script, "hang"), frames, 1)
