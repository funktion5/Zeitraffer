from dataclasses import dataclass

# The 80 COCO classes of the YOLOX model, index = class id.
COCO_NAMES: tuple[str, ...] = (
	"person",
	"bicycle",
	"car",
	"motorcycle",
	"airplane",
	"bus",
	"train",
	"truck",
	"boat",
	"traffic_light",
	"fire_hydrant",
	"stop_sign",
	"parking_meter",
	"bench",
	"bird",
	"cat",
	"dog",
	"horse",
	"sheep",
	"cow",
	"elephant",
	"bear",
	"zebra",
	"giraffe",
	"backpack",
	"umbrella",
	"handbag",
	"tie",
	"suitcase",
	"frisbee",
	"skis",
	"snowboard",
	"sports_ball",
	"kite",
	"baseball_bat",
	"baseball_glove",
	"skateboard",
	"surfboard",
	"tennis_racket",
	"bottle",
	"wine_glass",
	"cup",
	"fork",
	"knife",
	"spoon",
	"bowl",
	"banana",
	"apple",
	"sandwich",
	"orange",
	"broccoli",
	"carrot",
	"hot_dog",
	"pizza",
	"donut",
	"cake",
	"chair",
	"couch",
	"potted_plant",
	"bed",
	"dining_table",
	"toilet",
	"tv",
	"laptop",
	"mouse",
	"remote",
	"keyboard",
	"cell_phone",
	"microwave",
	"oven",
	"toaster",
	"sink",
	"refrigerator",
	"book",
	"clock",
	"vase",
	"scissors",
	"teddy_bear",
	"hair_drier",
	"toothbrush",
)

# The model labels a bird in flight side-on as an aeroplane first, so bird, airplane and kite
# form one group. A class belongs to exactly one group, so bird is not in "animal".
GROUP_BY_CLASS: dict[int, str] = {
	14: "flying",
	4: "flying",
	33: "flying",
	**{class_id: "animal" for class_id in range(15, 24)},
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
		return COCO_NAMES[self.class_id]

	@property
	def group(self) -> str:
		return GROUP_BY_CLASS[self.class_id]


# Return the highest-scoring detection that passes its group threshold, or None.
def best_flag(detections: list[Detection]) -> Detection | None:
	candidates = [
		detection
		for detection in detections
		if detection.class_id in GROUP_BY_CLASS and detection.score >= THRESHOLDS[detection.group]
	]

	return max(candidates, key=lambda detection: detection.score, default=None)
