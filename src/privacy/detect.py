"""Detector for the Zeitraffer privacy step: people and, optionally, licence plate areas.

Run by src/privacy/anonymize.py as a separate process. Every reported box is an area to
pixelate: a whole person, the lower part of a vehicle, where its licence plate usually sits,
and (--plate-search) any plate-like rectangle found anywhere in a vehicle.

Protocol: image paths on stdin, one per line; one JSON object on stdout:
{"detector": "<id>", "results": {"<path>": [{"x0", "y0", "x1", "y1", "score", "label"(, "block")}]}}
An empty request only returns the id. Any unreadable image exits non-zero (fail closed).
Pre/postprocessing follows opencv_zoo models/object_detection_yolox (Apache-2.0).
"""

import argparse
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import cv2
import numpy as np

INPUT_SIZE = 640
STRIDES = (8, 16, 32)
PERSON_CLASS = 0
# COCO: car, motorcycle, bus, truck.
VEHICLE_CLASSES = [2, 3, 5, 7]


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser()
	parser.add_argument("--model", required=True)
	# 1 = whole frame only; 2 = whole frame plus 2x2 overlapping tiles for small people.
	parser.add_argument("--tiles", type=int, choices=(1, 2), default=2)
	parser.add_argument("--threshold", type=float, default=0.25)
	parser.add_argument("--nms", type=float, default=0.45)
	parser.add_argument("--threads", type=int, default=4)
	# 0 = people only; e.g. 0.4 = also the lower 40 % of every vehicle, for its licence plate.
	parser.add_argument("--vehicle-plate-share", type=unit_interval, default=0.0)
	# Vehicles may use a lower cutoff than people: a false vehicle only pixelates some pavement,
	# while a missed one leaves a plate legible. Unset = same as --threshold.
	parser.add_argument("--vehicle-threshold", type=unit_interval, default=None)
	# Also blur plate-like rectangles inside every vehicle: catches plates above the share.
	parser.add_argument("--plate-search", action="store_true")
	# Pixel block size of vehicle and plate areas as a share of the vehicle's width, so a closer
	# (larger) plate gets larger blocks. 0 = the blur step's own strength rule.
	parser.add_argument("--vehicle-block-ratio", type=unit_interval, default=0.0)
	args = parser.parse_args(argv)

	if args.vehicle_threshold is None:
		args.vehicle_threshold = args.threshold

	return args


def unit_interval(value: str) -> float:
	number = float(value)

	if not 0.0 <= number <= 1.0:
		raise argparse.ArgumentTypeError("must be between 0 and 1")

	return number


def detector_id(args: argparse.Namespace) -> str:
	digest = hashlib.sha256(Path(args.model).read_bytes()).hexdigest()[:8]
	name = Path(args.model).stem.replace("object_detection_", "")
	# "-u2": duplicates are merged into their union, also when one lies inside another (see
	# union_of_duplicates); older caches lack it.
	identity = f"{name}-{digest}-ort-t{args.tiles}-c{args.threshold}-u2"

	# A different vehicle setting must not reuse cached results.
	if args.vehicle_plate_share:
		identity += f"-v{args.vehicle_plate_share}"

		if args.vehicle_threshold != args.threshold:
			identity += f"-vc{args.vehicle_threshold}"

		if args.plate_search:
			identity += "-ps"

		if args.vehicle_block_ratio:
			identity += f"-b{args.vehicle_block_ratio}"

	return identity


def make_grid() -> tuple[np.ndarray, np.ndarray]:
	grids = []
	strides = []

	for stride in STRIDES:
		size = INPUT_SIZE // stride
		xv, yv = np.meshgrid(np.arange(size), np.arange(size))
		grid = np.stack((xv, yv), 2).reshape(-1, 2)
		grids.append(grid)
		strides.append(np.full((grid.shape[0], 1), stride))

	return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


class Model:
	def __init__(self, args: argparse.Namespace):
		import onnxruntime as ort

		options = ort.SessionOptions()
		options.intra_op_num_threads = args.threads
		self.session = ort.InferenceSession(args.model, options, providers=["CPUExecutionProvider"])
		self.input_name = self.session.get_inputs()[0].name

	def forward(self, blob: np.ndarray) -> np.ndarray:
		return self.session.run(None, {self.input_name: blob})[0][0]


def letterbox(image: np.ndarray) -> tuple[np.ndarray, float]:
	ratio = min(INPUT_SIZE / image.shape[0], INPUT_SIZE / image.shape[1])
	width = int(image.shape[1] * ratio)
	height = int(image.shape[0] * ratio)
	padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114.0, dtype=np.float32)
	padded[:height, :width] = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
	return padded, ratio


# The model knows no licence plates, so inside a vehicle we look for one by its shape: a bright
# rectangle, about 3-6 times as wide as tall, with several dark characters in a row. Only ever
# blurred in addition to the vehicle's lower part: a miss here must not leave a plate legible.
def find_plate(crop: np.ndarray) -> tuple[int, int, int, int] | None:
	if crop.size == 0:
		return None

	gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
	width = gray.shape[1]

	# Bright relative to the surroundings, so sun and shade both work.
	bright = cv2.adaptiveThreshold(
		gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, -15
	)
	# Closes the gaps the characters cut into the plate; a larger kernel merges it with chrome.
	bright = cv2.morphologyEx(
		bright, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
	)
	contours, _ = cv2.findContours(bright, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
	best = None

	for contour in contours:
		x, y, w, h = cv2.boundingRect(contour)

		if not (2.8 <= w / h <= 6.5 and h >= 6 and 25 <= w <= width * 0.6):
			continue

		inner = gray[y : y + h, x : x + w]
		dark = inner < inner.mean() - 25

		if not 0.08 <= float(dark.mean()) <= 0.5:
			continue

		# Several separate dark blobs across the middle rows: characters, not an edge or stripe.
		columns = dark[h // 4 : h - h // 4].any(axis=0).astype(np.int8)
		blobs = int((np.diff(columns) == 1).sum())

		if blobs >= 3 and (best is None or blobs > best[0]):
			best = (blobs, (x, y, w, h))

	return best[1] if best else None


# A car or person on a tile border is also found cut in half in that tile, sometimes with a
# higher score than the whole one. Plain NMS would then keep only the half; widening the kept
# box over every duplicate it replaced always blurs the whole object. A quarter cut at a tile
# corner overlaps the whole too little for IoU, so for people a kept box lying mostly inside
# another one is widened as well (only ever blurs more). Not for vehicles: there it could move a
# car's plate band onto the larger vehicle behind it, and a cut car's whole box is kept anyway.
def union_of_duplicates(
	found: list[list[float]], kept: list[float], nms: float, contained: bool = False
) -> list[float]:
	x0, y0, x1, y1, score = kept

	for other in found:
		if iou(kept, other) > nms or (contained and inside_share(kept, other) >= MIN_INSIDE_SHARE):
			x0, y0 = min(x0, other[0]), min(y0, other[1])
			x1, y1 = max(x1, other[2]), max(y1, other[3])

	return [x0, y0, x1, y1, score]


MIN_INSIDE_SHARE = 0.8


# How much of box a lies inside box b.
def inside_share(a: list[float], b: list[float]) -> float:
	width = min(a[2], b[2]) - max(a[0], b[0])
	height = min(a[3], b[3]) - max(a[1], b[1])

	if width <= 0 or height <= 0:
		return 0.0

	return width * height / ((a[2] - a[0]) * (a[3] - a[1]))


def iou(a: list[float], b: list[float]) -> float:
	width = min(a[2], b[2]) - max(a[0], b[0])
	height = min(a[3], b[3]) - max(a[1], b[1])

	if width <= 0 or height <= 0:
		return 0.0

	overlap = width * height
	area_a = (a[2] - a[0]) * (a[3] - a[1])
	area_b = (b[2] - b[0]) * (b[3] - b[1])
	return overlap / (area_a + area_b - overlap)


# 4 px at the Scheunenviertel camera (cars ~300 px wide) leaves no character legible
# (decided with Julius 2026-10-16); far-away cars never go below that.
MIN_VEHICLE_BLOCK = 4


def vehicle_block(vehicle_width: float, ratio: float) -> int:
	return max(MIN_VEHICLE_BLOCK, round(vehicle_width * ratio))


def plate_box(image: np.ndarray, vehicle: tuple, score: float) -> dict | None:
	height, width = image.shape[:2]
	x0, y0 = max(0, int(vehicle[0])), max(0, int(vehicle[1]))
	x1, y1 = min(width, int(vehicle[2])), min(height, int(vehicle[3]))
	plate = find_plate(image[y0:y1, x0:x1])

	if plate is None:
		return None

	x, y, w, h = plate
	# The found rectangle can sit just inside the plate's border; a margin covers the rest.
	pad = max(2, h // 3)
	return {
		"x0": float(max(0, x0 + x - pad)),
		"y0": float(max(0, y0 + y - pad)),
		"x1": float(min(width, x0 + x + w + pad)),
		"y1": float(min(height, y0 + y + h + pad)),
		"score": round(score, 4),
		"label": "plate",
	}


# Detect people (and vehicles) in one image region; boxes come back in that region's pixel
# coordinates as (label, [x0, y0, x1, y1, score]).
def detect_region(model, region, grid, strides, thresholds) -> list[tuple[str, list]]:
	padded, ratio = letterbox(region)
	blob = np.transpose(padded, (2, 0, 1))[np.newaxis]
	dets = model.forward(blob)

	centres = (dets[:, :2] + grid) * strides
	sizes = np.exp(dets[:, 2:4]) * strides
	scores_by_label = {"person": dets[:, 4] * dets[:, 5 + PERSON_CLASS]}

	if "vehicle" in thresholds:
		scores_by_label["vehicle"] = dets[:, 4] * dets[:, 5 + np.array(VEHICLE_CLASSES)].max(axis=1)

	boxes = []

	for label, scores in scores_by_label.items():
		keep = scores >= thresholds[label]

		for (cx, cy), (w, h), score in zip(centres[keep], sizes[keep], scores[keep], strict=True):
			boxes.append(
				(
					label,
					[
						float((cx - w / 2) / ratio),
						float((cy - h / 2) / ratio),
						float((cx + w / 2) / ratio),
						float((cy + h / 2) / ratio),
						float(score),
					],
				)
			)

	return boxes


def regions(image: np.ndarray, tiles: int) -> list[tuple[int, int, np.ndarray]]:
	result = [(0, 0, image)]

	if tiles == 2:
		height, width = image.shape[:2]
		# 20 % overlap so a person on a tile border is whole in at least one tile.
		tile_w = int(width * 0.6)
		tile_h = int(height * 0.6)

		for y in (0, height - tile_h):
			for x in (0, width - tile_w):
				result.append((x, y, image[y : y + tile_h, x : x + tile_w]))

	return result


def detect_image(model, image, args, grid, strides) -> list[dict]:
	candidates: dict[str, list] = {}
	thresholds = {"person": args.threshold}

	if args.vehicle_plate_share > 0:
		thresholds["vehicle"] = args.vehicle_threshold

	for offset_x, offset_y, region in regions(image, args.tiles):
		for label, (x0, y0, x1, y1, score) in detect_region(
			model, region, grid, strides, thresholds
		):
			candidates.setdefault(label, []).append(
				[x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y, score]
			)

	height, width = image.shape[:2]
	boxes = []

	# Merged per label: a person in front of a car must never be merged away into the car.
	for label, found in candidates.items():
		xywh = [[c[0], c[1], c[2] - c[0], c[3] - c[1]] for c in found]
		keep = cv2.dnn.NMSBoxes(xywh, [c[4] for c in found], thresholds[label], args.nms)

		for index in np.array(keep).flatten():
			x0, y0, x1, y1, score = union_of_duplicates(
				found, found[index], args.nms, contained=label == "person"
			)

			extra = {}

			if label == "vehicle":
				if args.vehicle_block_ratio:
					extra["block"] = vehicle_block(x1 - x0, args.vehicle_block_ratio)

				plate = plate_box(image, (x0, y0, x1, y1), score) if args.plate_search else None

				if plate:
					boxes.append({**plate, **extra})

				# Only the plate area of a vehicle is reported: its lower part.
				y0 = y1 - (y1 - y0) * args.vehicle_plate_share

			x0, y0 = max(0.0, x0), max(0.0, y0)
			x1, y1 = min(float(width), x1), min(float(height), y1)

			if x1 > x0 and y1 > y0:
				box = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "score": round(score, 4)}
				boxes.append({**box, "label": label, **extra})

	return boxes


def main() -> int:
	args = parse_arguments()
	paths = [line.strip() for line in sys.stdin if line.strip()]
	identity = detector_id(args)

	if not paths:
		print(json.dumps({"detector": identity, "results": {}}))
		return 0

	started = time.monotonic()
	model = Model(args)
	grid, strides = make_grid()
	load_seconds = time.monotonic() - started

	results = {}

	for path in paths:
		# FFmpeg blurs the stored pixels; boxes must be found on exactly those, not on an
		# EXIF-rotated view.
		image = cv2.imread(path, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)

		if image is None:
			sys.stderr.write(f"cannot read image: {path}\n")
			return 2

		image_started = time.monotonic()
		results[path] = detect_image(model, image, args, grid, strides)
		sys.stderr.write(
			f"timing {Path(path).name} {time.monotonic() - image_started:.3f}s "
			f"boxes={len(results[path])}\n"
		)

	peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
	sys.stderr.write(
		f"summary images={len(paths)} load={load_seconds:.2f}s "
		f"total={time.monotonic() - started:.1f}s peak_rss={peak_mb:.0f}MB\n"
	)

	print(json.dumps({"detector": identity, "results": results}))
	return 0


if __name__ == "__main__":
	sys.exit(main())
