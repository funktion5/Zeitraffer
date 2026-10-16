import json
import math
import os
import signal
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.logger import logger

PRIVACY_STATE_ROOT = Path("state") / "privacy"

# Small batches bound the cost of one hung detector call and free its memory regularly.
DETECTOR_BATCH_SIZE = 50
DETECTOR_BATCH_TIMEOUT_SECONDS = 900
BLUR_TIMEOUT_SECONDS = 120

# A detected box is dropped only if it overlaps a known false positive (privacy.ignore_boxes) this
# much (intersection over union). If the camera moves, the overlap falls and the object is blurred
# again: the exception switches itself off rather than moving somewhere else.
MIN_IGNORE_OVERLAP = 0.5
# The top-band rule may never cover half the image or more.
TOP_SHARE_RANGE = (0.0, 0.5)

# Even a tiny box gets a margin, so a slightly short detection never leaves an edge visible.
MIN_BOX_PADDING_PIXELS = 2

BLUR_STRENGTH_RANGE = (0.05, 0.5)
BLUR_PADDING_RANGE = (0.05, 1.0)
BLUR_FEATHER_RANGE = (0.0, 1.0)

DETECTOR_ERROR_LOG_CHARACTERS = 2000


# Any doubt about a frame stops the run; a frame is never used unchecked or unblurred.
class PrivacyCheckError(RuntimeError):
	pass


@dataclass(frozen=True)
class Box:
	x0: float
	y0: float
	x1: float
	y1: float
	score: float
	# Pixel block size set by the detector (vehicles and plates); None = the strength rule.
	block: float | None = None
	# What the detector saw ("person", "vehicle", "plate"); kept in cache and state so a box can
	# be traced afterwards. Never changes how it is blurred.
	label: str | None = None


@dataclass(frozen=True)
class BlurSettings:
	strength: float
	padding_ratio: float
	feather: float


# Boxes to drop before blurring: known false positives per camera and the global top band.
@dataclass(frozen=True)
class DropRules:
	top_share: float = 0.0
	ignore_boxes: dict[str, list[list[int]]] = field(default_factory=dict)


# One blurred area: the even-aligned crop plus the shape whose alpha fades towards its edge.
@dataclass(frozen=True)
class BlurRegion:
	x: int
	y: int
	w: int
	h: int
	centre_x: float
	centre_y: float
	half_w: float
	half_h: float
	# Normalised distance up to which alpha stays 1; it always covers the detected box.
	core: float
	block: float | None = None


def _parse_box(raw: object, image: str) -> Box:
	if not isinstance(raw, dict):
		raise PrivacyCheckError(f"Detector returned a non-object box for {image}.")

	values = {key: _box_number(raw, key, image) for key in ("x0", "y0", "x1", "y1", "score")}

	if values["x1"] <= values["x0"] or values["y1"] <= values["y0"]:
		raise PrivacyCheckError(f"Detector returned an empty or inverted box for {image}.")

	if raw.get("block") is not None:
		values["block"] = _box_number(raw, "block", image)

		if values["block"] < 1:
			raise PrivacyCheckError(f"Detector box for {image} has an invalid 'block'.")

	label = raw.get("label")

	if label is not None and not isinstance(label, str):
		raise PrivacyCheckError(f"Detector box for {image} has an invalid 'label'.")

	return Box(**values, label=label)


def _box_number(raw: dict, key: str, image: str) -> float:
	value = raw.get(key)

	# bool is an int subclass but never a valid number here.
	if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
		raise PrivacyCheckError(f"Detector box for {image} has an invalid '{key}'.")

	return float(value)


# Run the detector in its own process group so a timeout also kills anything it spawned.
def _call_detector(
	command: list[str],
	frames: list[Path],
	timeout_seconds: float | None = None,
) -> dict:
	timeout_seconds = timeout_seconds or DETECTOR_BATCH_TIMEOUT_SECONDS
	request = "".join(f"{frame.resolve()}\n" for frame in frames)

	try:
		process = subprocess.Popen(
			command,
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			start_new_session=True,
		)

	except OSError as error:
		raise PrivacyCheckError(f"Detector could not be started: {error}") from error

	try:
		stdout, stderr = process.communicate(request, timeout=timeout_seconds)

	except subprocess.TimeoutExpired as error:
		os.killpg(process.pid, signal.SIGKILL)
		process.communicate()

		raise PrivacyCheckError(
			f"Detector timed out after {timeout_seconds:g} s on a batch of {len(frames)} frames."
		) from error

	if process.returncode != 0:
		raise PrivacyCheckError(
			f"Detector failed with exit code {process.returncode}: "
			f"{stderr[-DETECTOR_ERROR_LOG_CHARACTERS:].strip()}"
		)

	try:
		payload = json.loads(stdout)

	except json.JSONDecodeError as error:
		raise PrivacyCheckError("Detector output is not valid JSON.") from error

	if not isinstance(payload, dict):
		raise PrivacyCheckError("Detector output is not a JSON object.")

	detector = payload.get("detector")

	if not isinstance(detector, str) or not detector:
		raise PrivacyCheckError("Detector output has no detector id.")

	if not isinstance(payload.get("results"), dict):
		raise PrivacyCheckError("Detector output has no results object.")

	return payload


# Detect people in one batch; every requested frame must come back, even with no boxes.
def run_detector(
	command: list[str],
	frames: list[Path],
	timeout_seconds: float | None = None,
) -> tuple[str, dict[Path, list[Box]]]:
	payload = _call_detector(command, frames, timeout_seconds)
	results = payload["results"]

	boxes_by_frame: dict[Path, list[Box]] = {}

	for frame in frames:
		raw_boxes = results.get(str(frame.resolve()))

		if raw_boxes is None:
			raise PrivacyCheckError(f"Detector returned no result for {frame.name}.")

		if not isinstance(raw_boxes, list):
			raise PrivacyCheckError(f"Detector result for {frame.name} is not a list.")

		boxes_by_frame[frame] = [_parse_box(raw, frame.name) for raw in raw_boxes]

	return payload["detector"], boxes_by_frame


# The top of a camera image shows sky, roofs or the camera's own mount, never a person close
# enough to matter: a box mostly up there is a false positive (Scheunenviertel 2026-08-16: the
# mount's hook, twice). Applied when blurring, so cached detections stay valid.
# privacy.ignore_top_share sets the part (1/3 decided with Julius 2026-10-16); 0 switches it off.
def split_top_band(boxes: list[Box], height: int, share: float) -> tuple[list[Box], list[Box]]:
	limit = height * share
	kept: list[Box] = []
	dropped: list[Box] = []

	for box in boxes:
		inside = max(0.0, min(box.y1, limit) - box.y0) / (box.y1 - box.y0)
		(dropped if inside > 0.5 else kept).append(box)

	return kept, dropped


def box_overlap(box: Box, reference: list[int]) -> float:
	x0, y0, x1, y1 = reference
	width = min(box.x1, x1) - max(box.x0, x0)
	height = min(box.y1, y1) - max(box.y0, y0)

	if width <= 0 or height <= 0:
		return 0.0

	intersection = width * height
	union = (box.x1 - box.x0) * (box.y1 - box.y0) + (x1 - x0) * (y1 - y0) - intersection

	return intersection / union


# The one place boxes are dropped, for video mode and the box job alike.
def filter_boxes(
	boxes: list[Box], height: int, rules: DropRules, camera: str
) -> tuple[list[Box], list[Box]]:
	references = rules.ignore_boxes.get(camera, [])
	known = [
		box for box in boxes if any(box_overlap(box, r) >= MIN_IGNORE_OVERLAP for r in references)
	]
	kept, top = split_top_band([box for box in boxes if box not in known], height, rules.top_share)

	return kept, known + top


# Checked when a run starts: a typo here would silently drop real people, so it stops the run.
def parse_drop_rules(privacy: dict) -> DropRules:
	top_share = privacy.get("ignore_top_share", 0.0)

	if (
		isinstance(top_share, bool)
		or not isinstance(top_share, (int, float))
		or not TOP_SHARE_RANGE[0] <= top_share < TOP_SHARE_RANGE[1]
	):
		raise PrivacyCheckError("privacy.ignore_top_share must be a number from 0 to below 0.5.")

	ignore_boxes = privacy.get("ignore_boxes") or {}

	if not isinstance(ignore_boxes, dict):
		raise PrivacyCheckError("privacy.ignore_boxes must map cameras to box lists.")

	for camera, references in ignore_boxes.items():
		for box in references if isinstance(references, list) else [None]:
			if not (
				isinstance(box, list)
				and len(box) == 4
				and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in box)
				and box[2] > box[0]
				and box[3] > box[1]
			):
				raise PrivacyCheckError(f"privacy.ignore_boxes for {camera} has an invalid box.")

	return DropRules(top_share=float(top_share), ignore_boxes=ignore_boxes)


# An empty request returns the detector id, so cached results can be validated without a run.
def probe_detector_id(command: list[str]) -> str:
	return _call_detector(command, [])["detector"]


def _cache_path(camera: str) -> Path:
	return PRIVACY_STATE_ROOT / f"{camera}.jsonl"


def _file_identity(frame: Path) -> tuple[int, int]:
	# copy2 keeps size and mtime, so the local copy identifies the original without an SSHFS stat.
	stat = frame.stat()

	return stat.st_size, stat.st_mtime_ns


# Read cached results; a later line for the same image replaces an earlier one.
def load_cache(camera: str) -> dict[str, dict]:
	path = _cache_path(camera)

	if not path.exists():
		return {}

	entries: dict[str, dict] = {}

	with path.open(encoding="utf-8") as file:
		for line in file:
			line = line.strip()

			if not line:
				continue

			try:
				entry = json.loads(line)

			except json.JSONDecodeError:
				# A damaged line is only a cache miss; the frame is simply checked again.
				logger.warning(f"Ignoring unreadable privacy cache line for camera: {camera}")
				continue

			if isinstance(entry, dict) and isinstance(entry.get("image"), str):
				entries[entry["image"]] = entry

	return entries


def _cached_boxes(
	entry: dict | None,
	frame: Path,
	detector: str,
) -> list[Box] | None:
	if entry is None or entry.get("detector") != detector:
		return None

	size, mtime_ns = _file_identity(frame)

	if entry.get("size") != size or entry.get("mtime_ns") != mtime_ns:
		return None

	boxes = entry.get("boxes")

	if not isinstance(boxes, list):
		return None

	try:
		return [_parse_box(raw, frame.name) for raw in boxes]

	except PrivacyCheckError:
		return None


# Every re-detection appends a line, so the file only grows; keep the newest line per image.
# Written to a temporary file and swapped in, so a power cut leaves the old cache intact.
def _compact_cache(camera: str) -> None:
	path = _cache_path(camera)

	if not path.exists():
		return

	lines = path.read_text(encoding="utf-8").splitlines()
	entries = load_cache(camera)

	if len(lines) == len(entries):
		return

	temporary = path.with_name(f".{path.name}.tmp")
	temporary.write_text("".join(json.dumps(entry) + "\n" for entry in entries.values()))
	temporary.replace(path)


def _append_cache(
	camera: str,
	entries: list[dict],
) -> None:
	path = _cache_path(camera)
	path.parent.mkdir(parents=True, exist_ok=True)

	with path.open("a", encoding="utf-8") as file:
		for entry in entries:
			file.write(json.dumps(entry) + "\n")


def _probe_dimensions(frame: Path) -> tuple[int, int]:
	output = subprocess.run(
		[
			"ffprobe",
			"-v",
			"error",
			"-select_streams",
			"v:0",
			"-show_entries",
			"stream=width,height",
			"-of",
			"csv=p=0",
			str(frame),
		],
		capture_output=True,
		text=True,
		check=True,
		timeout=BLUR_TIMEOUT_SECONDS,
	).stdout.strip()

	try:
		width, height = (int(value) for value in output.split(","))

	except ValueError as error:
		raise PrivacyCheckError(f"Cannot read the size of {frame.name}: {output!r}") from error

	return width, height


def _number_in_range(raw: dict, key: str, bounds: tuple[float, float]) -> float:
	value = raw.get(key)

	if isinstance(value, bool) or not isinstance(value, (int, float)):
		raise PrivacyCheckError(f"privacy.blur.{key} must be a number.")

	if not bounds[0] <= value <= bounds[1]:
		raise PrivacyCheckError(f"privacy.blur.{key} must be between {bounds[0]} and {bounds[1]}.")

	return float(value)


# Validate before any frame is touched, so a typo stops the run instead of weakening the blur.
def parse_blur_settings(raw: object) -> BlurSettings:
	if not isinstance(raw, dict):
		raise PrivacyCheckError("privacy.blur is missing or not an object.")

	return BlurSettings(
		strength=_number_in_range(raw, "strength", BLUR_STRENGTH_RANGE),
		padding_ratio=_number_in_range(raw, "padding_ratio", BLUR_PADDING_RANGE),
		feather=_number_in_range(raw, "feather", BLUR_FEATHER_RANGE),
	)


# Size the blurred shape around a box: the inner shape encloses the box, the margin is added
# outside it. Only the margin may fade, so the detected box itself is always fully blurred.
def blur_region(
	box: Box,
	width: int,
	height: int,
	settings: BlurSettings,
) -> BlurRegion:
	box_w = box.x1 - box.x0
	box_h = box.y1 - box.y0
	padding_x = max(MIN_BOX_PADDING_PIXELS, box_w * settings.padding_ratio)
	padding_y = max(MIN_BOX_PADDING_PIXELS, box_h * settings.padding_ratio)

	inner_half_w = box_w / 2
	inner_half_h = box_h / 2
	half_w = inner_half_w + padding_x
	half_h = inner_half_h + padding_y

	centre_x = (box.x0 + box.x1) / 2
	centre_y = (box.y0 + box.y1) / 2

	# Even bounds keep the crop aligned with the 4:2:0 chroma planes.
	x0 = max(0, math.floor((centre_x - half_w) / 2) * 2)
	y0 = max(0, math.floor((centre_y - half_h) / 2) * 2)
	x1 = min(width // 2 * 2, math.ceil((centre_x + half_w) / 2) * 2)
	y1 = min(height // 2 * 2, math.ceil((centre_y + half_h) / 2) * 2)

	return BlurRegion(
		x=x0,
		y=y0,
		w=x1 - x0,
		h=y1 - y0,
		centre_x=centre_x,
		centre_y=centre_y,
		half_w=half_w,
		half_h=half_h,
		core=max(inner_half_w / half_w, inner_half_h / half_h),
		block=box.block,
	)


# Pixelate: shrink to one pixel per block, then enlarge without smoothing.
def _effect_filter(region: BlurRegion, settings: BlurSettings) -> str:
	short_side = min(region.w, region.h)
	block = round(region.block) if region.block else max(2, round(short_side * settings.strength))
	columns = max(1, math.ceil(region.w / block))
	rows = max(1, math.ceil(region.h / block))

	return f"scale={columns}:{rows}:flags=area,scale={region.w}:{region.h}:flags=neighbor,setsar=1"


def _alpha_expression(region: BlurRegion, settings: BlurSettings) -> str:
	dx = f"(X+{region.x}-{region.centre_x:.2f})/{region.half_w:.2f}"
	dy = f"(Y+{region.y}-{region.centre_y:.2f})/{region.half_h:.2f}"

	distance = f"max(abs({dx}),abs({dy}))"

	# Fully opaque up to fade_start, then linear to zero at the outer edge of the margin.
	fade_start = region.core + (1 - region.core) * (1 - settings.feather)

	if fade_start >= 1:
		return f"255*lte({distance},1)"

	return f"255*clip((1-{distance})/{1 - fade_start:.4f},0,1)"


# Build one filter graph that blurs every region of a frame in a single FFmpeg call.
def build_blur_filter(regions: list[BlurRegion], settings: BlurSettings) -> tuple[str, str]:
	crops = "".join(f"[c{index}]" for index in range(len(regions)))
	parts = [f"[0:v]split={len(regions) + 1}[base]{crops}"]
	current = "base"

	for index, region in enumerate(regions):
		parts.append(
			f"[c{index}]crop={region.w}:{region.h}:{region.x}:{region.y},"
			f"{_effect_filter(region, settings)},format=yuva420p,"
			f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{_alpha_expression(region, settings)}'"
			f"[b{index}]"
		)
		parts.append(f"[{current}][b{index}]overlay={region.x}:{region.y}[o{index}]")
		current = f"o{index}"

	return ";".join(parts), f"[{current}]"


# Blur all regions of one frame and replace the copy only after FFmpeg succeeded.
def blur_frame(
	frame: Path,
	boxes: list[Box],
	settings: BlurSettings,
	size: tuple[int, int] | None = None,
) -> None:
	width, height = size or _probe_dimensions(frame)
	regions = [blur_region(box, width, height, settings) for box in boxes]
	regions = [region for region in regions if region.w >= 2 and region.h >= 2]

	# Boxes entirely outside the image leave nothing to blur, which means the detector is wrong.
	if not regions:
		raise PrivacyCheckError(f"No blurrable region left for {frame.name}.")

	filter_graph, output_label = build_blur_filter(regions, settings)
	temporary = frame.with_name(f".{frame.stem}.blur{frame.suffix}")

	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-i",
			str(frame),
			"-filter_complex",
			filter_graph,
			"-map",
			output_label,
			"-frames:v",
			"1",
			"-q:v",
			"2",
			str(temporary),
		],
		capture_output=True,
		check=True,
		timeout=BLUR_TIMEOUT_SECONDS,
	)

	temporary.replace(frame)


# Check every copied frame for people and blur them in place, failing closed on any doubt.
def anonymize_frames(
	camera: str,
	originals: list[Path],
	frames: list[Path],
	detector_command: list[str] | None,
	blur_settings: object,
	drop_rules: DropRules | None = None,
) -> None:
	if not detector_command:
		raise PrivacyCheckError("Blurring was requested but privacy.detector_command is not set.")

	settings = parse_blur_settings(blur_settings)
	rules = drop_rules or DropRules()

	if len(originals) != len(frames):
		raise PrivacyCheckError("Original and copied frame lists differ in length.")

	detector = probe_detector_id(detector_command)
	cache = load_cache(camera)

	boxes_by_frame: dict[Path, list[Box]] = {}
	unchecked: list[tuple[Path, Path]] = []

	for original, frame in zip(originals, frames, strict=True):
		cached = _cached_boxes(cache.get(original.name), frame, detector)

		if cached is None:
			unchecked.append((original, frame))

		else:
			boxes_by_frame[frame] = cached

	logger.info(
		f"Privacy check with {detector}: {len(frames) - len(unchecked)} cached, "
		f"{len(unchecked)} to detect"
	)

	for start in range(0, len(unchecked), DETECTOR_BATCH_SIZE):
		batch = unchecked[start : start + DETECTOR_BATCH_SIZE]
		batch_detector, results = run_detector(detector_command, [frame for _, frame in batch])

		# A model swap between calls would mix results the cache cannot tell apart.
		if batch_detector != detector:
			raise PrivacyCheckError(
				f"Detector id changed during the run ({detector} -> {batch_detector})."
			)

		entries = []

		for original, frame in batch:
			boxes_by_frame[frame] = results[frame]
			size, mtime_ns = _file_identity(frame)

			entries.append(
				{
					"image": original.name,
					"size": size,
					"mtime_ns": mtime_ns,
					"detector": detector,
					"boxes": [asdict(box) for box in results[frame]],
				}
			)

		_append_cache(camera, entries)

	if unchecked:
		_compact_cache(camera)

	# Every detector call has returned (and its process exited) before the first FFmpeg blur.
	frames_blurred = 0
	detections_total = 0
	ignored_total = 0

	for original, frame in zip(originals, frames, strict=True):
		boxes = boxes_by_frame.get(frame)

		if boxes is None:
			raise PrivacyCheckError(f"Frame was never checked: {original.name}")

		if not boxes:
			continue

		try:
			size = _probe_dimensions(frame)

		except (OSError, subprocess.SubprocessError) as error:
			raise PrivacyCheckError(f"Cannot read the size of {original.name}: {error}") from error

		boxes, ignored = filter_boxes(boxes, size[1], rules, camera)
		ignored_total += len(ignored)

		for box in ignored:
			logger.info(f"Ignored box in {original.name}: {asdict(box)}")

		if not boxes:
			continue

		try:
			blur_frame(frame, boxes, settings, size)

		except (OSError, ValueError, subprocess.SubprocessError) as error:
			raise PrivacyCheckError(f"Blurring failed for {original.name}: {error}") from error

		frames_blurred += 1
		detections_total += len(boxes)

	logger.info(
		f"Privacy summary for {camera}: frames={len(frames)} | blurred={frames_blurred} | "
		f"detections={detections_total} | ignored={ignored_total} | detector={detector}"
	)
