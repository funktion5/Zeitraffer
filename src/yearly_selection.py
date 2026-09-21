from collections.abc import Callable
from datetime import date
from multiprocessing import Queue
from pathlib import Path

from src.image_worker import run_isolated_worker
from src.images import (
	extract_date,
	extract_time,
	get_image_hash,
)


# Select up to five unique images per day, closest to the target time.
def select_unique_yearly_images(
	images: list[Path],
	target_hour: int = 12,
	target_minute: int = 0,
	images_per_day: int = 5,
	progress_callback: Callable[[], None] | None = None,
) -> list[Path]:
	images_by_date: dict[
		date,
		list[
			tuple[
				int,
				int,
				Path,
			]
		],
	] = {}

	target_seconds = (
		target_hour * 60 * 60
		+ target_minute * 60
	)

	for image_path in images:
		image_date = extract_date(
			image_path.name
		)

		image_time = extract_time(
			image_path.name
		)

		if (
			image_date is None
			or image_time is None
		):
			continue

		hour, minute, second = image_time

		capture_seconds = (
			hour * 60 * 60
			+ minute * 60
			+ second
		)

		distance_seconds = abs(
			capture_seconds
			- target_seconds
		)

		images_by_date.setdefault(
			image_date,
			[],
		).append(
			(
				distance_seconds,
				capture_seconds,
				image_path,
			)
		)

	selected_images: list[Path] = []

	for image_date in sorted(
		images_by_date
	):
		candidates = sorted(
			images_by_date[
				image_date
			]
		)

		daily_images: list[
			tuple[
				int,
				int,
				Path,
			]
		] = []

		seen_hashes: set[str] = set()

		for candidate in candidates:
			image_path = candidate[2]

			image_hash = get_image_hash(
				image_path=image_path,
				progress_callback=progress_callback,
			)

			if image_hash in seen_hashes:
				continue

			seen_hashes.add(
				image_hash
			)

			daily_images.append(
				candidate
			)

			if (
				len(daily_images)
				>= images_per_day
			):
				break

		# Keep selected frames chronological within each day.
		daily_images.sort(
			key=lambda candidate: (
				candidate[1],
				candidate[2],
			)
		)

		selected_images.extend(
			candidate[2]
			for candidate in daily_images
		)

	return selected_images


def _select_yearly_images_worker(
	images: list[Path],
	target_hour: int,
	target_minute: int,
	images_per_day: int,
	result_queue: Queue,
) -> None:
	def report_progress():
		result_queue.put(
			(
				"progress",
				None,
			)
		)

	try:
		selected_images = select_unique_yearly_images(
			images=images,
			target_hour=target_hour,
			target_minute=target_minute,
			images_per_day=images_per_day,
			progress_callback=report_progress,
		)

		result_queue.put(
			(
				"success",
				selected_images,
			)
		)

	except OSError as error:
		result_queue.put(
			(
				"error",
				str(error),
			)
		)


def select_yearly_images_isolated(
	camera: str,
	images: list[Path],
	stall_timeout_seconds: float,
	target_hour: int = 12,
	target_minute: int = 0,
	images_per_day: int = 5,
) -> list[Path]:
	return run_isolated_worker(
		camera=camera,
		target=_select_yearly_images_worker,
		args=(
			images,
			target_hour,
			target_minute,
			images_per_day,
		),
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Yearly image selection",
	)