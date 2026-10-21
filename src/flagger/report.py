import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.flagger.groups import Detection
from src.logger import logger

HIGHLIGHTS_DIR = "highlights"
MANIFEST_NAME = "manifest.json"
SCHEMA = 1


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
		"created": created.isoformat(timespec="seconds"),
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


# Build the day's folder under a work name, then swap it in: the web page never sees a
# half-written report, and a failure while copying leaves the previous report in place.
def write_report(
	video_root: Path,
	camera: str,
	target_date: date,
	manifest: dict,
	items: list[FlaggedImage],
) -> Path:
	highlights = video_root / camera / HIGHLIGHTS_DIR
	target = highlights / target_date.isoformat()
	# The leading dot keeps the web page from listing work folders.
	building = highlights / f".{target_date.isoformat()}.tmp"

	if building.exists():
		shutil.rmtree(building)

	building.mkdir(parents=True)

	try:
		for item in items:
			# copyfile, not copy2: the copy gets normal umask permissions so the web server can
			# read it, whatever mode the original on the camera mount has.
			shutil.copyfile(item.path, building / copy_name(item.path))

		(building / MANIFEST_NAME).write_text(
			json.dumps(manifest, indent="\t", ensure_ascii=False) + "\n",
			encoding="utf-8",
		)

	except BaseException:
		shutil.rmtree(building, ignore_errors=True)
		raise

	if target.exists():
		shutil.rmtree(target)

	building.rename(target)

	return target


# Remove report folders older than the retention, for every camera, plus work folders a hard
# crash left behind. Goes by the date in the folder name, never by file times, and only ever
# touches real directories named YYYY-MM-DD or .YYYY-MM-DD.tmp inside a highlights folder.
def cleanup_old_reports(video_root: Path, today: date, retention_days: int) -> list[Path]:
	cutoff = today - timedelta(days=retention_days)
	removed = []

	for folder in sorted(video_root.glob(f"*/{HIGHLIGHTS_DIR}/*")):
		name = folder.name
		day = name[1:-4] if name.startswith(".") and name.endswith(".tmp") else name

		# A symlinked highlights folder could point anywhere; never delete through it.
		if folder.parent.is_symlink() or folder.is_symlink() or not folder.is_dir():
			continue

		try:
			folder_date = date.fromisoformat(day)

		except ValueError:
			continue

		# fromisoformat also accepts "20260901" and week dates; only plain YYYY-MM-DD counts.
		if folder_date.isoformat() != day or folder_date >= cutoff:
			continue

		try:
			shutil.rmtree(folder)

		except OSError as error:
			logger.warning(f"Could not remove old highlights {folder}: {error}")
			continue

		logger.debug(f"Removed old highlights: {folder}")
		removed.append(folder)

	return removed
