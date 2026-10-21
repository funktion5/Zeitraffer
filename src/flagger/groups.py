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

# Detections below every group threshold can never be flagged and are dropped early.
FLOOR: float = min(THRESHOLDS.values())


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


# Return the highest-scoring detection that passes its group threshold, or None.
def best_flag(detections: list[Detection]) -> Detection | None:
	candidates = [
		detection
		for detection in detections
		if detection.class_id in CLASSES and detection.score >= THRESHOLDS[detection.group]
	]

	return max(candidates, key=lambda detection: detection.score, default=None)
