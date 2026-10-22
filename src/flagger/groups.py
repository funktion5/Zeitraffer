import math
from dataclasses import dataclass

# The flagged COCO classes of the YOLOX model: class id -> (label, group). The model labels a
# bird in flight side-on as an aeroplane first, so bird, airplane and kite form one group. A
# class belongs to exactly one group, so bird is not in "animal".
CLASSES: dict[int, tuple[str, str]] = {
	4: ("airplane", "flying"),
	14: ("bird", "flying"),
	33: ("kite", "flying"),
	15: ("cat", "animal"),
	16: ("dog", "animal"),
	17: ("horse", "animal"),
	18: ("sheep", "animal"),
	19: ("cow", "animal"),
	20: ("elephant", "animal"),
	21: ("bear", "animal"),
	22: ("zebra", "animal"),
	23: ("giraffe", "animal"),
}

THRESHOLDS: dict[str, float] = {
	"animal": 0.30,
	"flying": 0.30,
}

# Weaker hits are never flagged, but count as "something is there" when deciding whether an
# object is stationary: a buoy that only sometimes passes its threshold is still seen weakly in
# most images (SLSV 21.10.2026: "sheep" at 0.33-0.45 in 6 of 72 images, same spot).
PRESENCE_FLOOR: float = 0.10

# Detections below this can play no part at all and are dropped early, in the model output.
FLOOR: float = min(PRESENCE_FLOOR, *THRESHOLDS.values())

# Stationary background (a boat on the shore, a buoy): a hit whose spot holds a box of any
# flagged class (IoU >= STATIONARY_IOU) in at least STATIONARY_SHARE of the day's images, and in
# at least STATIONARY_MIN_IMAGES of them, is never flagged. Any class, because the model calls
# the same boat "airplane" in one image and "kite" in the next (SKM-Mardorf 21.10.2026: a
# catamaran in 69 of 71 images). IoU rather than containment, so a bird flying past in front of
# the boat's large box is not swallowed by it.
STATIONARY_SHARE: float = 0.15
STATIONARY_MIN_IMAGES: int = 3
STATIONARY_IOU: float = 0.3


@dataclass(frozen=True)
class Detection:
	class_id: int
	score: float
	# x1, y1, x2, y2 in full-image pixels.
	box: tuple[float, float, float, float]

	@property
	def label(self) -> str:
		return CLASSES[self.class_id][0]

	@property
	def group(self) -> str:
		return CLASSES[self.class_id][1]


def passes_threshold(detection: Detection) -> bool:
	return detection.class_id in CLASSES and detection.score >= THRESHOLDS[detection.group]


# Return the highest-scoring detection that passes its group threshold, or None.
def best_flag(detections: list[Detection]) -> Detection | None:
	candidates = [detection for detection in detections if passes_threshold(detection)]

	return max(candidates, key=lambda detection: detection.score, default=None)


def iou(first: tuple[float, ...], second: tuple[float, ...]) -> float:
	width = min(first[2], second[2]) - max(first[0], second[0])
	height = min(first[3], second[3]) - max(first[1], second[1])

	if width <= 0 or height <= 0:
		return 0.0

	overlap = width * height
	area_first = (first[2] - first[0]) * (first[3] - first[1])
	area_second = (second[2] - second[0]) * (second[3] - second[1])

	return overlap / (area_first + area_second - overlap)


# One flag per image (or None) for a whole day of one camera, given every image's detections:
# the best hit that is not stationary background.
def pick_flags(per_image: list[list[Detection]]) -> list[Detection | None]:
	needed = max(STATIONARY_MIN_IMAGES, math.ceil(STATIONARY_SHARE * len(per_image)))

	# Every detection counts as presence: detect_image only returns flagged classes from FLOOR,
	# which is PRESENCE_FLOOR.
	def is_stationary(candidate: Detection) -> bool:
		images = sum(
			any(iou(candidate.box, other.box) >= STATIONARY_IOU for other in found)
			for found in per_image
		)
		return images >= needed

	return [
		best_flag([d for d in found if passes_threshold(d) and not is_stationary(d)])
		for found in per_image
	]
