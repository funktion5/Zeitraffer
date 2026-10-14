import json
import shutil
import subprocess
import sys
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
	"style": "blur",
	"strength": 0.25,
	"padding_ratio": 0.25,
	"shape": "ellipse",
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
		lambda frame, boxes, settings: calls.append((frame.name, boxes)),
	)

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

	summary = anonymize_frames(
		"Test-Camera", originals, frames, detector_command(detector_script), BLUR
	)

	assert [name for name, _ in blur_calls] == ["frame_000001.jpg"]
	assert blur_calls[0][1] == [Box(x0=10, y0=10, x1=40, y1=60, score=0.31)]

	assert summary.frames_total == 3
	assert summary.frames_with_people == 1
	assert summary.frames_without_people == 2
	assert summary.detections_total == 1
	assert summary.detector == "fake-1"

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

	summary = anonymize_frames("Test-Camera", originals, frames, command, BLUR)

	# Only the id probe ran the second time; it sends no paths, so nothing was logged.
	assert log.read_text().splitlines() == first_run_requests
	assert len(first_run_requests) == 3

	# Cached boxes are still blurred, because the copies are fresh every run.
	assert [name for name, _ in blur_calls] == ["frame_000001.jpg", "frame_000001.jpg"]
	assert summary.frames_with_people == 1


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

	summary = anonymize_frames(
		"Test-Camera", originals, frames, detector_command(detector_script), BLUR
	)

	assert len(log.read_text().splitlines()) == 3
	assert summary.frames_with_people == 1


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
	def failing_blur(frame, boxes, settings):
		raise subprocess.CalledProcessError(1, ["ffmpeg"])

	monkeypatch.setattr(privacy, "blur_frame", failing_blur)
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

	summary = anonymize_frames(
		"Test-Camera", originals, frames, detector_command(detector_script), BLUR
	)

	assert summary.frames_total == 5
	assert len(read_cache(isolated_state)) == 5


def test_blur_region_keeps_even_bounds_inside_the_image():
	settings = parse_blur_settings({**BLUR, "shape": "rectangle"})
	region = blur_region(Box(x0=3, y0=5, x1=43, y1=85, score=0.2), 101, 60, settings)

	assert (region.x, region.y) == (0, 0)
	assert region.x + region.w <= 100 and region.y + region.h <= 60
	assert all(value % 2 == 0 for value in (region.x, region.y, region.w, region.h))
	# The 40 px wide box gains at least its 25 % margin on the right.
	assert region.x + region.w >= 53


@pytest.mark.parametrize("shape", ["rectangle", "ellipse"])
def test_blur_region_core_always_covers_the_detected_box(shape):
	box = Box(x0=200, y0=100, x1=260, y1=260, score=0.4)
	region = blur_region(box, 1920, 1080, parse_blur_settings({**BLUR, "shape": shape}))

	for corner_x, corner_y in [(box.x0, box.y0), (box.x1, box.y1), (box.x0, box.y1)]:
		dx = (corner_x - region.centre_x) / region.half_w
		dy = (corner_y - region.centre_y) / region.half_h
		distance = (dx * dx + dy * dy) ** 0.5 if shape == "ellipse" else max(abs(dx), abs(dy))

		assert distance <= region.core + 1e-9


def test_parse_blur_settings_accepts_the_production_defaults():
	assert parse_blur_settings(BLUR) == BlurSettings(
		style="blur",
		strength=0.25,
		padding_ratio=0.25,
		shape="ellipse",
		feather=0.5,
	)


@pytest.mark.parametrize(
	("change", "message"),
	[
		({"style": "smudge"}, "style must be one of"),
		({"shape": "circle"}, "shape must be one of"),
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

	with pytest.raises(PrivacyCheckError, match="style"):
		anonymize_frames(
			"Test-Camera",
			originals,
			frames,
			detector_command(detector_script),
			{**BLUR, "style": "none"},
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
		{"shape": "rectangle", "feather": 0.0},
		{"style": "pixelate"},
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
