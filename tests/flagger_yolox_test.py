import math

import numpy as np
import pytest
from flagger_fakes import SequenceForward

from src.flagger.yolox import detect_image, detector_id

FULL_HD = (1080, 1920, 3)


def black(shape=FULL_HD) -> np.ndarray:
	return np.zeros(shape, np.uint8)


def test_whole_frame_box_is_mapped_to_image_pixels():
	found = detect_image(black(), SequenceForward([[(2440, 14, 0.5)]]), tiles=1)

	assert [(d.class_id, d.score) for d in found] == [(14, 0.5)]
	assert found[0].box == pytest.approx((948, 708, 972, 732), abs=0.5)


def test_tile_boxes_are_offset_into_the_full_frame():
	top_left = detect_image(black(), SequenceForward([[], [(2440, 4, 0.8)]]))

	assert top_left[0].box == pytest.approx((568.8, 424.8, 583.2, 439.2), abs=0.5)

	bottom_right = detect_image(black(), SequenceForward([[], [], [], [], [(2440, 4, 0.8)]]))

	assert bottom_right[0].box == pytest.approx((1336.8, 856.8, 1351.2, 871.2), abs=0.5)


def test_whole_frame_and_four_tiles_are_run():
	forward = SequenceForward([])
	detect_image(black(), forward)

	assert forward.count == 5


def test_overlapping_boxes_of_one_class_keep_the_higher_score():
	big = math.log(4)
	forward = SequenceForward([[(2440, 14, 0.5, big), (2441, 14, 0.6, big)]])

	assert [d.score for d in detect_image(black(), forward, tiles=1)] == pytest.approx([0.6])


def test_overlapping_boxes_of_different_classes_are_both_kept():
	forward = SequenceForward([[(2440, 14, 0.5), (2440, 4, 0.8)]])

	found = detect_image(black(), forward, tiles=1)

	assert sorted(d.class_id for d in found) == [4, 14]


def test_classes_outside_the_groups_and_below_the_floor_are_dropped():
	forward = SequenceForward([[(2440, 0, 0.9), (2441, 14, 0.2)]])

	assert detect_image(black(), forward, tiles=1) == []


def test_image_smaller_than_a_tile_does_not_crash():
	assert detect_image(black((10, 10, 3)), SequenceForward([])) == []


def test_one_pixel_image_does_not_crash():
	assert detect_image(black((1, 1, 3)), SequenceForward([])) == []


def test_detector_id_follows_model_bytes_and_tiles(tmp_path):
	first = tmp_path / "a" / "object_detection_yolox_2022nov.onnx"
	second = tmp_path / "b" / "object_detection_yolox_2022nov.onnx"
	first.parent.mkdir()
	second.parent.mkdir()
	first.write_bytes(b"one")
	second.write_bytes(b"two")

	first_id = detector_id(first)

	assert first_id.startswith("yolox_2022nov-")
	assert first_id.endswith("-ort-t2-animal0.3-flying0.3")
	assert first_id != detector_id(second)
	assert "-t1-" in detector_id(first, tiles=1)


def test_boxes_are_clamped_to_the_image():
	# Anchor 0 sits in the top-left corner; a 32 px box there reaches past the edge.
	forward = SequenceForward([[(0, 14, 0.9, math.log(4))]])

	found = detect_image(black(), forward, tiles=1)

	assert found[0].box == pytest.approx((0, 0, 48, 48), abs=0.5)
