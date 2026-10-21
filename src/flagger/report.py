import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.flagger.groups import Detection
from src.logger import logger

HIGHLIGHTS_DIR = "highlights"
MANIFEST_NAME = "manifest.json"
SCHEMA = 1
DAY_FOLDER_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class FlaggedImage:
	path: Path
	detection: Detection
	taken_at: datetime
	# width, height
	image_size: tuple[int, int]


# The web page and its delete wrapper only accept lowercase ".jpg"; originals may end in ".JPG".
def copy_name(path: Path) -> str:
	return path.stem + path.suffix.lower()


def build_manifest(
	camera: str,
	target_date: date,
	created: datetime,
	detector: str,
	checked: int,
	items: list[FlaggedImage],
) -> dict:
	ordered = sorted(items, key=lambda item: item.detection.score, reverse=True)

	return {
		"schema": SCHEMA,
		"camera": camera,
		"date": target_date.isoformat(),
		"created": created.isoformat(),
		"detector": detector,
		"checked": checked,
		"items": [
			{
				"file": copy_name(item.path),
				"taken_at": item.taken_at.isoformat(),
				"group": item.detection.group,
				"label": item.detection.label,
				"score": round(item.detection.score, 4),
				"box": [round(value) for value in item.detection.box],
				"image_size": list(item.image_size),
			}
			for item in ordered
		],
	}


# Build the day's folder next to the old one and swap it in, so the web page never sees a
# half-written report and a failed re-run leaves the previous report in place.
def write_report(
	video_root: Path,
	camera: str,
	target_date: date,
	manifest: dict,
	items: list[FlaggedImage],
) -> Path:
	highlights = video_root / camera / HIGHLIGHTS_DIR
	day = target_date.isoformat()
	target = highlights / day
	# The leading dot keeps the web page from listing work folders.
	building = highlights / f".{day}.tmp"
	previous = highlights / f".{day}.old"

	restore_interrupted_swap(target, previous)

	if building.exists():
		shutil.rmtree(building)

	building.mkdir(parents=True)

	try:
		for item in items:
			shutil.copy2(item.path, building / copy_name(item.path))

		(building / MANIFEST_NAME).write_text(
			json.dumps(manifest, indent="\t", ensure_ascii=False) + "\n",
			encoding="utf-8",
		)

		if target.exists():
			target.rename(previous)

		building.rename(target)

	except BaseException:
		shutil.rmtree(building, ignore_errors=True)
		restore_interrupted_swap(target, previous)
		raise

	shutil.rmtree(previous, ignore_errors=True)

	return target


# A crash between the two renames leaves only the ".old" folder; put it back first.
def restore_interrupted_swap(target: Path, previous: Path) -> None:
	if not previous.exists():
		return

	if target.exists():
		shutil.rmtree(previous)
	else:
		previous.rename(target)


# Remove report folders older than the retention, for every camera. Goes by the date in the
# folder name, never by file times, and only ever touches real directories named YYYY-MM-DD
# directly inside a camera's highlights folder.
def cleanup_old_reports(video_root: Path, today: date, retention_days: int) -> list[Path]:
	cutoff = today - timedelta(days=retention_days)
	removed = []

	for folder in sorted(video_root.glob(f"*/{HIGHLIGHTS_DIR}/*")):
		if not DAY_FOLDER_PATTERN.fullmatch(folder.name):
			continue

		# A symlinked highlights folder could point anywhere; never delete through it.
		if folder.parent.is_symlink() or folder.is_symlink() or not folder.is_dir():
			continue

		try:
			folder_date = date.fromisoformat(folder.name)

		except ValueError:
			continue

		if folder_date >= cutoff:
			continue

		try:
			shutil.rmtree(folder)

		except OSError as error:
			logger.warning(f"Could not remove old highlights {folder}: {error}")
			continue

		logger.debug(f"Removed old highlights: {folder}")
		removed.append(folder)

	return removed
