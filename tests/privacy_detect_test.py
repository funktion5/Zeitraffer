import argparse
import math

import numpy as np
import pytest

import src.privacy.detect as detect

GRID, STRIDES = detect.make_grid()
IMAGE = np.zeros((detect.INPUT_SIZE, detect.INPUT_SIZE, 3), dtype=np.uint8)


class FakeModel:
	"""Returns raw YOLOX output with exactly the given boxes; class ids follow COCO."""

	def __init__(self, boxes: list[tuple[int, list[float], float]]):
		self.boxes = boxes

	def forward(self, blob):
		dets = np.zeros((len(GRID), 85), dtype=np.float32)

		for anchor, (class_id, (x0, y0, x1, y1), score) in enumerate(self.boxes):
			stride = STRIDES[anchor][0]
			dets[anchor, 0] = (x0 + x1) / 2 / stride - GRID[anchor][0]
			dets[anchor, 1] = (y0 + y1) / 2 / stride - GRID[anchor][1]
			dets[anchor, 2] = math.log((x1 - x0) / stride)
			dets[anchor, 3] = math.log((y1 - y0) / stride)
			dets[anchor, 4] = 1.0
			dets[anchor, 5 + class_id] = score

		return dets


# Through the real parser, so the tests get exactly the production defaults.
def _args(*options: str, model: str = "model.onnx") -> argparse.Namespace:
	return detect.parse_arguments(["--model", model, "--tiles", "1", *options])


def _detect(boxes, share: float = 0.0) -> list[dict]:
	args = _args("--vehicle-plate-share", str(share))
	return detect.detect_image(FakeModel(boxes), IMAGE, args, GRID, STRIDES)


def _rounded(box: dict) -> tuple:
	return (box["label"], *(round(box[key]) for key in ("x0", "y0", "x1", "y1")))


PERSON = 0
CAR = 2
TRUCK = 7


def test_people_only_by_default() -> None:
	found = _detect([(PERSON, [100, 100, 140, 200], 0.9), (CAR, [300, 300, 500, 400], 0.9)])

	assert [_rounded(box) for box in found] == [("person", 100, 100, 140, 200)]


def test_vehicle_is_reported_as_its_lower_plate_area() -> None:
	found = _detect([(CAR, [300, 300, 500, 400], 0.9)], share=0.4)

	assert [_rounded(box) for box in found] == [("vehicle", 300, 360, 500, 400)]


def test_every_vehicle_class_counts() -> None:
	found = _detect([(TRUCK, [100, 400, 300, 600], 0.8)], share=0.5)

	assert [_rounded(box) for box in found] == [("vehicle", 100, 500, 300, 600)]


# A single merge across labels would drop the person, whose box overlaps the car's by 57 %.
def test_person_in_front_of_a_car_is_never_merged_away() -> None:
	found = _detect(
		[(CAR, [100, 300, 400, 500], 0.95), (PERSON, [150, 250, 350, 500], 0.6)],
		share=0.4,
	)

	assert sorted(_rounded(box) for box in found) == [
		("person", 150, 250, 350, 500),
		("vehicle", 100, 420, 400, 500),
	]


# Real case (Scheunenviertel 2026-08-16): a car across the tile border at x=768 was also found
# as its right half with a higher score, and plain NMS kept only that half.
def test_duplicate_cut_by_a_tile_border_widens_the_kept_box() -> None:
	kept = [768.0, 841.0, 882.0, 928.0, 0.9]
	found = [kept, [673.0, 842.0, 880.0, 932.0, 0.88], [1200.0, 840.0, 1300.0, 930.0, 0.8]]

	assert detect.union_of_duplicates(found, kept, 0.45) == [673.0, 841.0, 882.0, 932.0, 0.9]


def _car_with_plate(plate: bool) -> np.ndarray:
	image = np.full((detect.INPUT_SIZE, detect.INPUT_SIZE, 3), 60, dtype=np.uint8)

	if plate:
		# 80 x 18 px white plate with five dark characters, as at the Scheunenviertel camera.
		image[330:348, 360:440] = 220

		for left in range(366, 430, 13):
			image[333:345, left : left + 6] = 30

	return image


def _detect_plates(image: np.ndarray, plate_search: bool = True) -> list[dict]:
	args = _args("--vehicle-plate-share", "0.4", *(["--plate-search"] if plate_search else []))
	boxes = [(CAR, [300, 300, 500, 400], 0.9)]
	return detect.detect_image(FakeModel(boxes), image, args, GRID, STRIDES)


# The plate sits above the lower 40 % (y 360-400), so only the plate search covers it.
def test_plate_search_adds_the_plate_on_top_of_the_lower_part() -> None:
	found = sorted(_rounded(box) for box in _detect_plates(_car_with_plate(True)))

	assert found == [("plate", 354, 324, 446, 354), ("vehicle", 300, 360, 500, 400)]


def test_plate_search_finds_nothing_on_a_car_without_plate() -> None:
	found = [_rounded(box) for box in _detect_plates(_car_with_plate(False))]

	assert found == [("vehicle", 300, 360, 500, 400)]


def test_plate_search_is_off_unless_asked() -> None:
	found = [_rounded(box) for box in _detect_plates(_car_with_plate(True), plate_search=False)]

	assert found == [("vehicle", 300, 360, 500, 400)]


# 4 px for a 300 px wide car; plates inherit their car's block, people keep the blur rule.
def test_vehicle_block_scales_with_the_vehicle_width() -> None:
	args = _args(
		"--vehicle-plate-share", "0.4", "--plate-search", "--vehicle-block-ratio", "0.0133"
	)
	boxes = [(CAR, [300, 300, 500, 400], 0.9), (PERSON, [100, 100, 140, 200], 0.9)]

	found = detect.detect_image(FakeModel(boxes), _car_with_plate(True), args, GRID, STRIDES)

	assert {box["label"]: box.get("block") for box in found} == {
		"plate": 4,
		"vehicle": 4,
		"person": None,
	}
	assert detect.vehicle_block(300, 0.0133) == 4
	assert detect.vehicle_block(600, 0.0133) == 8
	assert detect.vehicle_block(80, 0.0133) == detect.MIN_VEHICLE_BLOCK


def test_weak_vehicle_detection_is_ignored() -> None:
	assert _detect([(CAR, [300, 300, 500, 400], 0.1)], share=0.4) == []


def test_vehicle_threshold_lowers_the_cutoff_for_vehicles_only() -> None:
	args = _args("--vehicle-plate-share", "0.4", "--vehicle-threshold", "0.15")
	boxes = [(CAR, [300, 300, 500, 400], 0.2), (PERSON, [100, 100, 140, 200], 0.2)]

	found = detect.detect_image(FakeModel(boxes), IMAGE, args, GRID, STRIDES)

	assert [_rounded(box) for box in found] == [("vehicle", 300, 360, 500, 400)]


def test_detector_id_changes_only_with_the_vehicle_setting(tmp_path) -> None:
	model = tmp_path / "object_detection_yolox_test.onnx"
	model.write_bytes(b"model")

	def identity(*options: str) -> str:
		return detect.detector_id(_args(*options, model=str(model)))

	people_only = identity()
	with_plates = identity("--vehicle-plate-share", "0.4")

	assert people_only.endswith("-ort-t1-c0.25-u2")
	assert with_plates == people_only + "-v0.4"
	assert identity("--vehicle-plate-share", "0.4", "--vehicle-threshold", "0.25") == with_plates
	assert (
		identity("--vehicle-plate-share", "0.4", "--vehicle-threshold", "0.15")
		== with_plates + "-vc0.15"
	)
	assert identity("--vehicle-plate-share", "0.4", "--plate-search") == with_plates + "-ps"
	assert (
		identity("--vehicle-plate-share", "0.4", "--vehicle-block-ratio", "0.0133")
		== with_plates + "-b0.0133"
	)


@pytest.mark.parametrize("value", ["-0.1", "1.5", "abc"])
def test_value_outside_zero_to_one_is_rejected(value: str) -> None:
	with pytest.raises((argparse.ArgumentTypeError, ValueError)):
		detect.unit_interval(value)


# A quarter cut at a tile corner overlaps the whole too little for IoU (0.25 here).
def test_person_lying_inside_another_box_is_widened_to_it() -> None:
	whole = [100.0, 100.0, 300.0, 500.0, 0.6]
	quarter = [200.0, 300.0, 300.0, 500.0, 0.9]

	assert detect.union_of_duplicates([quarter, whole], quarter, 0.45, contained=True) == [
		100.0,
		100.0,
		300.0,
		500.0,
		0.9,
	]
	# Vehicles keep their own box, so a car's plate band stays on the car.
	assert detect.union_of_duplicates([quarter, whole], quarter, 0.45) == quarter


def test_only_people_are_widened_by_containment_in_detect_image() -> None:
	boxes = [
		(PERSON, [100, 100, 300, 500], 0.6),
		(PERSON, [200, 300, 300, 500], 0.9),
		(CAR, [350, 100, 600, 400], 0.6),
		(CAR, [480, 250, 600, 400], 0.9),
	]

	found = sorted(_rounded(box) for box in _detect(boxes, share=1.0))

	assert ("person", 100, 100, 300, 500) in found
	assert ("person", 200, 300, 300, 500) not in found
	assert ("vehicle", 480, 250, 600, 400) in found
