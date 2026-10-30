import numpy as np

ANCHORS = 8400
OUTPUTS = 85


# Fake model forward: one list of (anchor, class_id, score[, size_log]) per call, in call order
# (whole frame first, then the tiles top-left, top-right, bottom-left, bottom-right).
class SequenceForward:
	def __init__(self, calls: list[list[tuple]]):
		self.calls = list(calls)
		self.count = 0

	def __call__(self, blob: np.ndarray) -> np.ndarray:
		assert blob.shape == (1, 3, 640, 640)
		dets = np.zeros((ANCHORS, OUTPUTS), dtype=np.float32)
		entries = self.calls[self.count] if self.count < len(self.calls) else []
		self.count += 1

		for entry in entries:
			anchor, class_id, score = entry[:3]
			size_log = entry[3] if len(entry) > 3 else 0.0
			dets[anchor, 2:4] = size_log
			dets[anchor, 4] = 1.0
			dets[anchor, 5 + class_id] = score

		return dets
