from src.flagger.groups import (
	CLASSES,
	FLOOR,
	PRESENCE_FLOOR,
	THRESHOLDS,
	Detection,
	best_flag,
	iou,
	pick_flags,
)


def test_class_table():
	assert (CLASSES[14], CLASSES[4], CLASSES[33]) == (
		("bird", "flying"),
		("airplane", "flying"),
		("kite", "flying"),
	)
	assert {CLASSES[c][1] for c in range(15, 24)} == {"animal"}
	assert set(CLASSES) == {4, 14, 33, *range(15, 24)}
	# Person is never flagged here.
	assert 0 not in CLASSES


def test_thresholds_and_floor():
	assert THRESHOLDS == {"animal": 0.30, "flying": 0.30}
	assert PRESENCE_FLOOR == 0.10
	assert FLOOR == 0.10


def test_detection_label_and_group():
	detection = Detection(17, 0.4, (0, 0, 1, 1))

	assert (detection.label, detection.group) == ("horse", "animal")


def test_strandallee_bird_is_flagged_as_the_airplane_guess():
	found = [
		Detection(14, 0.497, (716, 579, 814, 626)),
		Detection(4, 0.865, (716, 579, 814, 625)),
	]
	best = best_flag(found)

	assert (best.label, best.group, best.score) == ("airplane", "flying", 0.865)


def test_below_threshold_and_foreign_classes_are_ignored():
	assert best_flag([Detection(16, 0.29, (0, 0, 1, 1)), Detection(0, 0.99, (0, 0, 1, 1))]) is None
	assert best_flag([]) is None


def test_score_exactly_at_the_threshold_is_flagged():
	assert best_flag([Detection(16, 0.30, (0, 0, 1, 1))]).label == "dog"


CATAMARAN = (250, 509, 672, 709)
BUOY = (21, 372, 36, 385)


def day(count: int, *extra: tuple[int, Detection]) -> list[list[Detection]]:
	images = [[] for _ in range(count)]
	for index, detection in extra:
		images[index].append(detection)
	return images


def test_iou():
	assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
	assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == 50 / 150
	assert iou((0, 0, 10, 10), (10, 0, 20, 10)) == 0.0


# SKM-Mardorf 21.10.2026: a catamaran on the shore, "airplane" in nearly every image.
def test_an_object_at_the_same_spot_all_day_is_never_flagged():
	images = [[Detection(4, 0.8, CATAMARAN)] for _ in range(71)]

	assert pick_flags(images) == [None] * 71


# SLSV 21.10.2026: a floating object drifts by a few pixels and is "sheep" only now and then.
def test_a_bobbing_object_seen_mostly_weakly_is_stationary():
	images = []
	for index in range(72):
		shift = index % 8
		box = (1556 + shift, 533, 1584 + shift, 556)
		images.append([Detection(18, 0.4 if index % 12 == 0 else 0.15, box)])

	assert pick_flags(images) == [None] * 72


def test_the_model_calling_the_same_boat_different_things_is_still_stationary():
	images = [[Detection((4, 33, 14)[index % 3], 0.6, CATAMARAN)] for index in range(30)]

	assert pick_flags(images) == [None] * 30


def test_a_real_bird_beside_the_stationary_object_is_kept():
	images = [[Detection(4, 0.8, CATAMARAN)] for _ in range(40)]
	bird = Detection(14, 0.5, (900, 100, 940, 130))
	images[7].append(bird)

	picks = pick_flags(images)

	assert picks[7] == bird
	assert picks.count(None) == 39


# A small bird in front of the boat's big box overlaps it, but the IoU stays small.
def test_a_bird_flying_past_in_front_of_the_boat_is_kept():
	images = [[Detection(4, 0.8, CATAMARAN)] for _ in range(40)]
	bird = Detection(14, 0.45, (400, 550, 440, 580))
	images[3].append(bird)

	assert pick_flags(images)[3] == bird


def test_birds_at_different_spots_are_all_kept():
	images = day(
		30,
		(2, Detection(14, 0.5, (100, 100, 130, 120))),
		(9, Detection(14, 0.5, (600, 300, 630, 320))),
		(20, Detection(4, 0.7, (1200, 50, 1260, 80))),
	)

	assert [index for index, pick in enumerate(pick_flags(images)) if pick] == [2, 9, 20]


# 15 % of 10 images is 2, but it takes at least 3 images at the same spot.
def test_a_short_day_needs_three_images_at_the_same_spot():
	twice = day(10, (1, Detection(14, 0.5, BUOY)), (5, Detection(14, 0.5, BUOY)))
	three_times = day(
		10,
		(1, Detection(14, 0.5, BUOY)),
		(5, Detection(14, 0.5, BUOY)),
		(8, Detection(14, 0.5, BUOY)),
	)

	assert [pick is not None for pick in pick_flags(twice)].count(True) == 2
	assert pick_flags(three_times) == [None] * 10


def test_below_the_share_a_repeated_spot_is_still_flagged():
	# 7 of 72 images is below 15 % (11 images): a bird sitting on a post for a while.
	images = day(72, *[(index, Detection(14, 0.5, BUOY)) for index in range(7)])

	assert [pick is not None for pick in pick_flags(images)].count(True) == 7


def test_weak_hits_alone_are_never_flagged():
	images = day(20, (4, Detection(14, 0.2, (100, 100, 130, 120))))

	assert pick_flags(images) == [None] * 20
