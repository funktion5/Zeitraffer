import cv2
import pytest

from src.config import PROJECT_ROOT
from src.flagger.groups import best_flag
from src.flagger.yolox import OnnxForward, detect_image

MODEL = PROJECT_ROOT / "models" / "object_detection_yolox_2022nov.onnx"
SAMPLE = PROJECT_ROOT / "sandbox" / "flagger-samples" / "strandallee-26-10-20_08-14-58-20.jpg"
BIRD_BOX = (716, 579, 814, 625)

pytestmark = pytest.mark.skipif(
	not (MODEL.is_file() and SAMPLE.is_file()),
	reason="needs the YOLOX model in models/ and the bird sample in sandbox/flagger-samples/",
)


def iou(a, b) -> float:
	width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
	height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
	overlap = width * height
	union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
	return overlap / union


def test_strandallee_bird_is_flagged():
	image = cv2.imread(str(SAMPLE), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)

	best = best_flag(detect_image(image, OnnxForward(MODEL)))

	assert best is not None and best.group == "flying" and best.score >= 0.30
	assert iou(best.box, BIRD_BOX) > 0.5
