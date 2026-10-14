"""Person detector for the Zeitraffer privacy step.

Run by src/privacy/anonymize.py as a separate process.

Protocol: image paths on stdin, one per line; one JSON object on stdout:
{"detector": "<id>", "results": {"<path>": [{"x0", "y0", "x1", "y1", "score"}]}}
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


def parse_arguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser()
	parser.add_argument("--model", required=True)
	parser.add_argument("--runtime", choices=("ort", "cv2"), default="ort")
	# 1 = whole frame only; 2 = whole frame plus 2x2 overlapping tiles for small people.
	parser.add_argument("--tiles", type=int, choices=(1, 2), default=2)
	parser.add_argument("--threshold", type=float, default=0.25)
	parser.add_argument("--nms", type=float, default=0.45)
	parser.add_argument("--threads", type=int, default=4)
	return parser.parse_args()


def detector_id(args: argparse.Namespace) -> str:
	digest = hashlib.sha256(Path(args.model).read_bytes()).hexdigest()[:8]
	name = Path(args.model).stem.replace("object_detection_", "")
	return f"{name}-{digest}-{args.runtime}-t{args.tiles}-c{args.threshold}"


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
		self.runtime = args.runtime

		if args.runtime == "ort":
			import onnxruntime as ort

			options = ort.SessionOptions()
			options.intra_op_num_threads = args.threads
			self.session = ort.InferenceSession(
				args.model, options, providers=["CPUExecutionProvider"]
			)
			self.input_name = self.session.get_inputs()[0].name

		else:
			cv2.setNumThreads(args.threads)
			self.net = cv2.dnn.readNet(args.model)

	def forward(self, blob: np.ndarray) -> np.ndarray:
		if self.runtime == "ort":
			return self.session.run(None, {self.input_name: blob})[0][0]

		self.net.setInput(blob)
		return self.net.forward()[0]


def letterbox(image: np.ndarray) -> tuple[np.ndarray, float]:
	ratio = min(INPUT_SIZE / image.shape[0], INPUT_SIZE / image.shape[1])
	width = int(image.shape[1] * ratio)
	height = int(image.shape[0] * ratio)
	padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114.0, dtype=np.float32)
	padded[:height, :width] = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
	return padded, ratio


# Detect people in one image region; boxes come back in that region's pixel coordinates.
def detect_region(model, region, grid, strides, threshold) -> list[list[float]]:
	padded, ratio = letterbox(region)
	blob = np.transpose(padded, (2, 0, 1))[np.newaxis]
	dets = model.forward(blob)

	centres = (dets[:, :2] + grid) * strides
	sizes = np.exp(dets[:, 2:4]) * strides
	scores = dets[:, 4] * dets[:, 5 + PERSON_CLASS]
	keep = scores >= threshold

	boxes = []

	for (cx, cy), (w, h), score in zip(centres[keep], sizes[keep], scores[keep], strict=True):
		boxes.append(
			[
				float((cx - w / 2) / ratio),
				float((cy - h / 2) / ratio),
				float((cx + w / 2) / ratio),
				float((cy + h / 2) / ratio),
				float(score),
			]
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
	candidates = []

	for offset_x, offset_y, region in regions(image, args.tiles):
		for x0, y0, x1, y1, score in detect_region(model, region, grid, strides, args.threshold):
			candidates.append([x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y, score])

	if not candidates:
		return []

	xywh = [[c[0], c[1], c[2] - c[0], c[3] - c[1]] for c in candidates]
	keep = cv2.dnn.NMSBoxes(xywh, [c[4] for c in candidates], args.threshold, args.nms)
	height, width = image.shape[:2]

	boxes = []

	for index in np.array(keep).flatten():
		x0, y0, x1, y1, score = candidates[index]
		x0, y0 = max(0.0, x0), max(0.0, y0)
		x1, y1 = min(float(width), x1), min(float(height), y1)

		if x1 > x0 and y1 > y0:
			boxes.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "score": round(score, 4)})

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
		image = cv2.imread(path, cv2.IMREAD_COLOR)

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
