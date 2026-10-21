from src.flagger.groups import CLASSES, FLOOR, THRESHOLDS, Detection, best_flag


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
	assert FLOOR == 0.30


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
