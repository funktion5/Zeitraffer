"""Small YOLOX wrapper for the highlights flagger.

The letterbox, grid, decode and tile layout are copied from src/privacy/detect.py on purpose:
the blur detector stays untouched and the two programs stay independent.
"""

import hashlib
from collections.abc import Callable
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from src.flagger.groups import CLASSES, FLOOR, THRESHOLDS, Detection

INPUT_SIZE = 640
STRIDES = (8, 16, 32)
NMS_IOU = 0.45
TILE_SHARE = 0.6

# Input blob (1, 3, 640, 640) float32 -> raw output (8400, 85).
Forward = Callable[[np.ndarray], np.ndarray]


class OnnxForward:
	def __init__(self, model_path: Path):
		# Imported here so tests and the web side never need onnxruntime to import this module.
		import onnxruntime as ort

		options = ort.SessionOptions()
		options.intra_op_num_threads = 4
		self.session = ort.InferenceSession(
			str(model_path), options, providers=["CPUExecutionProvider"]
		)
		self.input_name = self.session.get_inputs()[0].name

	def __call__(self, blob: np.ndarray) -> np.ndarray:
		return self.session.run(None, {self.input_name: blob})[0][0]


@cache
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


def letterbox(image: np.ndarray) -> tuple[np.ndarray, float]:
	ratio = min(INPUT_SIZE / image.shape[0], INPUT_SIZE / image.shape[1])
	width = max(1, int(image.shape[1] * ratio))
	height = max(1, int(image.shape[0] * ratio))
	padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114.0, dtype=np.float32)
	padded[:height, :width] = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
	return padded, ratio


# Whole frame first, then (with tiles=2) four 60 % tiles: top-left, top-right, bottom-left,
# bottom-right. Small animals far away are only found in the enlarged tiles.
def regions(image: np.ndarray, tiles: int) -> list[tuple[int, int, np.ndarray]]:
	result = [(0, 0, image)]

	if tiles == 2:
		height, width = image.shape[:2]
		tile_w = int(width * TILE_SHARE)
		tile_h = int(height * TILE_SHARE)

		for y in (0, height - tile_h):
			for x in (0, width - tile_w):
				result.append((x, y, image[y : y + tile_h, x : x + tile_w]))

	return result


# Run one region through the model; boxes come back in full-image pixels per class id.
def detect_region(
	region: np.ndarray, offset_x: int, offset_y: int, forward: Forward
) -> dict[int, list[list[float]]]:
	grid, strides = make_grid()
	padded, ratio = letterbox(region)
	blob = np.ascontiguousarray(np.transpose(padded, (2, 0, 1))[np.newaxis])
	dets = forward(blob)

	centres = (dets[:, :2] + grid) * strides
	sizes = np.exp(dets[:, 2:4]) * strides
	found: dict[int, list[list[float]]] = {}

	for class_id in CLASSES:
		scores = dets[:, 4] * dets[:, 5 + class_id]
		keep = scores >= FLOOR

		for (cx, cy), (w, h), score in zip(centres[keep], sizes[keep], scores[keep], strict=True):
			found.setdefault(class_id, []).append(
				[
					float((cx - w / 2) / ratio + offset_x),
					float((cy - h / 2) / ratio + offset_y),
					float((cx + w / 2) / ratio + offset_x),
					float((cy + h / 2) / ratio + offset_y),
					float(score),
				]
			)

	return found


def detect_image(image: np.ndarray, forward: Forward, tiles: int = 2) -> list[Detection]:
	candidates: dict[int, list[list[float]]] = {}

	for offset_x, offset_y, region in regions(image, tiles):
		# A tile of a tiny image can be empty; the whole frame still covers it.
		if region.size == 0:
			continue

		for class_id, boxes in detect_region(region, offset_x, offset_y, forward).items():
			candidates.setdefault(class_id, []).extend(boxes)

	height, width = image.shape[:2]
	detections = []

	# Merged per class: the same bird seen in the whole frame and in a tile counts once.
	for class_id, found in candidates.items():
		xywh = [[c[0], c[1], c[2] - c[0], c[3] - c[1]] for c in found]
		keep = cv2.dnn.NMSBoxes(xywh, [c[4] for c in found], FLOOR, NMS_IOU)

		for index in np.array(keep).flatten():
			x0, y0, x1, y1, score = found[int(index)]
			# Clamped like the blur detector: the page draws the box over the image.
			box = (
				min(max(x0, 0.0), width),
				min(max(y0, 0.0), height),
				min(max(x1, 0.0), width),
				min(max(y1, 0.0), height),
			)
			detections.append(Detection(class_id, score, box))

	return detections


# Identifies model bytes and settings in the manifest, so reports from different setups differ.
def detector_id(model_path: Path, tiles: int = 2) -> str:
	digest = hashlib.sha256()

	with model_path.open("rb") as model_file:
		for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
			digest.update(chunk)

	name = model_path.stem.removeprefix("object_detection_")
	thresholds = "-".join(f"{group}{value:g}" for group, value in sorted(THRESHOLDS.items()))

	return f"{name}-{digest.hexdigest()[:8]}-ort-t{tiles}-{thresholds}"
