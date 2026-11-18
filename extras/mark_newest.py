"""Optional extra: mark the newest image of every camera that is not blurred (extras/README.md).

The website's pick-up script publishes only images that carry the checked mark. Blur cameras get it
from the blur round; every other camera is cleared for the website by default, so its newest image
gets the same mark without being looked at. Connected to nothing: it runs only when someone appends
it to the live round's cron line.
"""

import hashlib
import json
import shlex
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import PROJECT_ROOT, load_config
from src.images import date_patterns, get_cameras, image_moment
from src.logger import configure_file_logging, logger
from src.privacy.box_writer import BoxWriter, BoxWriteRefused
from src.privacy.checked_mark import add_mark, has_mark
from src.storage.storage_box import StorageBox, get_storage_box

# The last marked image per camera, so an unchanged camera costs no download.
STATE_FILE = PROJECT_ROOT / "state" / "privacy" / "newest-marked.json"
WORK_ROOT = PROJECT_ROOT / "temp" / "mark-newest"
OUTCOMES = ("marked", "unchanged", "settling", "incomplete", "none", "failed")

LISTING_TIMEOUT_SECONDS = 30
# An upload younger than this may still be in progress; the next run takes it.
SETTLE_SECONDS = 15
JPEG_END_MARKER = b"\xff\xd9"


# The same choice as the pick-up script: the newest by the time in its name, skipping empty files.
# A name without a readable time cannot be placed and is never chosen.
def newest_image(images: dict[str, int], timezone: str) -> str | None:
	candidates: list[tuple[datetime, str]] = []

	for name, size in images.items():
		moment = image_moment(name, timezone)

		if size > 0 and moment is not None:
			candidates.append((moment, name))

	return max(candidates)[1] if candidates else None


# Size and upload time of the images of today and yesterday: the blur round's listing (one ls over
# the date patterns, never the whole folder), plus the size. Kept here so src/ stays unchanged.
def list_images(storage_box: StorageBox, camera: str, now: datetime) -> dict[str, tuple[int, int]]:
	directory = storage_box.camera_directory(camera)
	days = [now.date(), now.date() - timedelta(days=1)]
	patterns = dict.fromkeys(pattern for day in days for pattern in date_patterns(day))
	globs = " ".join(f"{shlex.quote(directory)}/*{pattern}*" for pattern in patterns)
	result = storage_box.run(f"ls -l --time-style=+%s -d {globs}", LISTING_TIMEOUT_SECONDS)

	# A pattern without a match is reported as missing; anything else means an incomplete listing.
	problems = [
		line for line in result.stderr.splitlines() if "No such file or directory" not in line
	]

	if result.returncode not in (0, 2) or problems:
		raise OSError(f"Storage box listing failed for camera {camera}: {result.stderr.strip()}")

	prefix = f"{directory}/"
	images: dict[str, tuple[int, int]] = {}

	for line in result.stdout.splitlines():
		# mode, links, owner, group, size, mtime, path
		fields = line.split(None, 6)

		if len(fields) != 7 or not fields[4].isdigit() or not fields[5].isdigit():
			raise OSError(f"Unreadable storage box listing line for camera {camera}: {line!r}")

		name = fields[6].removeprefix(prefix)

		if (
			fields[0].startswith("-")
			and "/" not in name
			and not name.startswith(".")
			and name.lower().endswith(".jpg")
		):
			images[name] = (int(fields[4]), int(fields[5]))

	return images


# Mark the newest image of one camera, if it is not done yet. Returns "marked", "unchanged" (done or
# already carrying the mark), "settling" (still uploading), "incomplete" (cut off) or "none".
# marked holds the last marked image per camera and is updated here; the caller saves it.
def mark_camera(
	writer: BoxWriter,
	storage_box: StorageBox,
	camera: str,
	marked: dict[str, str],
	now: datetime,
	work_dir: Path,
) -> str:
	images = list_images(storage_box, camera, now)
	name = newest_image({image: size for image, (size, _) in images.items()}, writer.timezone)

	if name is None:
		return "none"

	if marked.get(camera) == name:
		return "unchanged"

	if now.timestamp() - images[name][1] < SETTLE_SECONDS:
		return "settling"

	work_copy = work_dir / name

	try:
		writer.fetch(camera, name, work_copy)
		data = work_copy.read_bytes()

		if not data.endswith(JPEG_END_MARKER):
			return "incomplete"

		if not has_mark(data):
			work_copy.write_bytes(add_mark(data))
			writer.mark_clean(camera, name, hashlib.sha256(data).hexdigest(), work_copy)
			marked[camera] = name

			return "marked"

		marked[camera] = name

		return "unchanged"

	finally:
		work_copy.unlink(missing_ok=True)


# A missing or damaged file only costs one download per camera; it never stops the run.
def load_marked() -> dict[str, str]:
	try:
		data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

	except FileNotFoundError:
		return {}

	except (OSError, json.JSONDecodeError) as error:
		logger.warning(f"Unreadable {STATE_FILE.name}, starting from scratch: {error}")
		return {}

	if not isinstance(data, dict):
		return {}

	return {key: value for key, value in data.items() if isinstance(value, str)}


# Written to a temporary file and swapped in, so a power cut leaves the old file intact.
def save_marked(marked: dict[str, str]) -> None:
	STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
	temporary = STATE_FILE.with_name(f".{STATE_FILE.name}.tmp")
	temporary.write_text(json.dumps(marked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	temporary.replace(STATE_FILE)


def main(now: datetime | None = None) -> int:
	configure_file_logging("privacy")

	config = load_config()
	timezone = config["location"]["timezone"]
	# Blur cameras are marked by the blur round itself; ignored folders are never written.
	skipped = set((config.get("privacy") or {}).get("blur_cameras") or [])
	skipped |= set(config.get("ignored_cameras") or [])
	now = now or datetime.now(ZoneInfo(timezone))

	try:
		storage_box = get_storage_box()
		cameras = [camera for camera in get_cameras() if camera not in skipped]
		# Only these cameras are writable in this run.
		writer = BoxWriter(
			storage_box.remote,
			storage_box.base_directory,
			cameras,
			timezone,
			upload_root=WORK_ROOT,
		)

	except (OSError, BoxWriteRefused, ZoneInfoNotFoundError) as error:
		logger.error(f"No storage box: {error}")
		return 1

	WORK_ROOT.mkdir(parents=True, exist_ok=True)
	marked = load_marked()
	counts: Counter[str] = Counter()

	for camera in cameras:
		try:
			counts[mark_camera(writer, storage_box, camera, marked, now, WORK_ROOT)] += 1

		# One camera's trouble must not stop the others; the next run tries again.
		except (OSError, ValueError, subprocess.SubprocessError) as error:
			logger.error(f"[{camera}] Not marked: {error}")
			counts["failed"] += 1

	save_marked(marked)
	summary = " ".join(f"{outcome}={counts[outcome]}" for outcome in OUTCOMES)
	logger.info(f"Newest marked: {len(cameras)} cameras | {summary}")

	return 1 if counts["failed"] else 0


if __name__ == "__main__":
	sys.exit(main())
