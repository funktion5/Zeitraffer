from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.image_worker import run_isolated_worker
from src.images import (
	extract_date,
	extract_time,
	get_image_hash,
)

# Frames kept per day in a Yearly video.
IMAGES_PER_DAY = 5


# Select up to five unique images per day, closest to the target time.
def select_unique_yearly_images(
	images: list[Path],
	target_seconds_by_date: dict[date, int],
	images_per_day: int = IMAGES_PER_DAY,
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

	for image_path in images:
		image_date = extract_date(image_path.name)

		image_time = extract_time(image_path.name)

		if image_date is None or image_time is None:
			continue

		hour, minute, second = image_time

		capture_seconds = hour * 60 * 60 + minute * 60 + second

		distance_seconds = abs(capture_seconds - target_seconds_by_date[image_date])

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

	for image_date in sorted(images_by_date):
		candidates = sorted(images_by_date[image_date])

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

			if progress_callback is not None:
				progress_callback()

			if image_hash in seen_hashes:
				continue

			seen_hashes.add(image_hash)

			daily_images.append(candidate)

			if len(daily_images) >= images_per_day:
				break

		# Keep selected frames chronological within each day.
		daily_images.sort(
			key=lambda candidate: (
				candidate[1],
				candidate[2],
			)
		)

		selected_images.extend(candidate[2] for candidate in daily_images)

	return selected_images


def select_yearly_images_isolated(
	camera: str,
	images: list[Path],
	stall_timeout_seconds: float,
	target_seconds_by_date: dict[date, int],
) -> list[Path]:
	return run_isolated_worker(
		camera=camera,
		target=select_unique_yearly_images,
		kwargs={
			"images": images,
			"target_seconds_by_date": target_seconds_by_date,
		},
		stall_timeout_seconds=stall_timeout_seconds,
		operation_name="Yearly image selection",
	)
