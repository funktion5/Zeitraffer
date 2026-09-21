from pathlib import Path

import src.yearly_selection as yearly_selection_module
from src.yearly_selection import (
	select_unique_yearly_images,
	select_yearly_images_isolated,
)


def test_select_unique_yearly_images_selects_closest_images_per_day(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_10-30-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-50-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-55-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-05-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-10-00-00.jpg"
		),
	]

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		lambda image_path, progress_callback=None: image_path.name,
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	assert result == [
		Path(
			"camera_26-09-15_11-50-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-55-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-05-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-10-00-00.jpg"
		),
	]


def test_select_unique_yearly_images_skips_duplicate_and_uses_next_candidate(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_11-45-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-50-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-55-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-05-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-10-00-00.jpg"
		),
	]

	hashes = {
		"camera_26-09-15_12-00-00-00.jpg": "hash-a",
		"camera_26-09-15_11-55-00-00.jpg": "hash-b",
		"camera_26-09-15_12-05-00-00.jpg": "hash-b",
		"camera_26-09-15_11-50-00-00.jpg": "hash-c",
		"camera_26-09-15_12-10-00-00.jpg": "hash-d",
		"camera_26-09-15_11-45-00-00.jpg": "hash-e",
	}

	def fake_get_image_hash(
		image_path,
		progress_callback=None,
	):
		return hashes[
			image_path.name
		]

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		fake_get_image_hash,
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	assert result == [
		Path(
			"camera_26-09-15_11-45-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-50-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-55-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-10-00-00.jpg"
		),
	]


def test_select_unique_yearly_images_returns_fewer_when_not_enough_unique_images(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_11-55-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-05-00-00.jpg"
		),
	]

	hashes = {
		"camera_26-09-15_11-55-00-00.jpg": "same-hash",
		"camera_26-09-15_12-00-00-00.jpg": "same-hash",
		"camera_26-09-15_12-05-00-00.jpg": "other-hash",
	}

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		lambda image_path, progress_callback=None: hashes[
			image_path.name
		],
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	assert result == [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-05-00-00.jpg"
		),
	]


def test_select_unique_yearly_images_keeps_duplicate_tracking_per_day(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-16_12-00-00-00.jpg"
		),
	]

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		lambda image_path, progress_callback=None: "same-hash",
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	# Identical content on different days remains valid.
	assert result == [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-16_12-00-00-00.jpg"
		),
	]


def test_select_unique_yearly_images_returns_days_in_chronological_order(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-17_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-16_12-00-00-00.jpg"
		),
	]

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		lambda image_path, progress_callback=None: image_path.name,
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	assert result == [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-16_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-17_12-00-00-00.jpg"
		),
	]


def test_select_unique_yearly_images_keeps_selected_frames_chronological_within_day(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_12-10-00-00.jpg"
		),
		Path(
			"camera_26-09-15_11-50-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
	]

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		lambda image_path, progress_callback=None: image_path.name,
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	assert result == [
		Path(
			"camera_26-09-15_11-50-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		),
		Path(
			"camera_26-09-15_12-10-00-00.jpg"
		),
	]


def test_select_unique_yearly_images_stops_hashing_after_limit_is_reached(
	monkeypatch,
):
	images = [
		Path(
			f"camera_26-09-15_{hour:02d}-{minute:02d}-00-00.jpg"
		)
		for hour, minute in [
			(
				12,
				0,
			),
			(
				11,
				55,
			),
			(
				12,
				5,
			),
			(
				11,
				50,
			),
			(
				12,
				10,
			),
			(
				11,
				45,
			),
			(
				12,
				15,
			),
		]
	]

	hashed_images = []

	def fake_get_image_hash(
		image_path,
		progress_callback=None,
	):
		hashed_images.append(
			image_path
		)

		return image_path.name

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		fake_get_image_hash,
	)

	result = select_unique_yearly_images(
		images=images,
		images_per_day=5,
	)

	assert len(
		result
	) == 5

	# Once five unique frames exist, farther candidates must not be hashed.
	assert len(
		hashed_images
	) == 5


def test_select_unique_yearly_images_forwards_hash_progress(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		)
	]

	callbacks = []

	def fake_get_image_hash(
		image_path,
		progress_callback=None,
	):
		assert progress_callback is not None

		progress_callback()

		callbacks.append(
			image_path
		)

		return "hash"

	monkeypatch.setattr(
		yearly_selection_module,
		"get_image_hash",
		fake_get_image_hash,
	)

	select_unique_yearly_images(
		images=images,
		progress_callback=lambda: None,
	)

	assert callbacks == [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		)
	]


def test_select_yearly_images_isolated_uses_shared_worker_supervisor(
	monkeypatch,
):
	images = [
		Path(
			"camera_26-09-15_12-00-00-00.jpg"
		)
	]

	worker_calls = []

	def fake_run_isolated_worker(
		**kwargs,
	):
		worker_calls.append(
			kwargs
		)

		return images

	monkeypatch.setattr(
		yearly_selection_module,
		"run_isolated_worker",
		fake_run_isolated_worker,
	)

	result = select_yearly_images_isolated(
		camera="Test-Camera",
		images=images,
		stall_timeout_seconds=10,
		images_per_day=5,
	)

	assert result == images

	assert len(
		worker_calls
	) == 1

	assert worker_calls[0][
		"camera"
	] == "Test-Camera"

	assert worker_calls[0][
		"target"
	] == yearly_selection_module._select_yearly_images_worker

	assert worker_calls[0][
		"args"
	] == (
		images,
		12,
		0,
		5,
	)

	assert worker_calls[0][
		"stall_timeout_seconds"
	] == 10

	assert worker_calls[0][
		"operation_name"
	] == "Yearly image selection"


def test_select_yearly_images_worker_returns_operational_error(
	monkeypatch,
):
	class FakeQueue:
		def __init__(self):
			self.messages = []

		def put(
			self,
			message,
		):
			self.messages.append(
				message
			)

	result_queue = FakeQueue()

	def fake_select_unique_yearly_images(
		**kwargs,
	):
		raise OSError(
			"storage unavailable"
		)

	monkeypatch.setattr(
		yearly_selection_module,
		"select_unique_yearly_images",
		fake_select_unique_yearly_images,
	)

	yearly_selection_module._select_yearly_images_worker(
		images=[],
		target_hour=12,
		target_minute=0,
		images_per_day=5,
		result_queue=result_queue,
	)

	assert result_queue.messages == [
		(
			"error",
			"storage unavailable",
		)
	]