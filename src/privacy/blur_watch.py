"""Watchdog for the live blur round: report images on the box that stay unchecked too long.

Read-only by design: it lists the box and reads the round's state, nothing else. It takes no lock
and needs no detector, so it keeps reporting while a round is stuck or broken. A stale image is a
warning, not a failure: the exit code is 1 only when the box cannot be asked. See
docs/verpixelung-box.md.

	.venv/bin/python3 -m src.privacy.blur_watch
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import load_config
from src.logger import configure_file_logging, logger
from src.privacy import blur_box
from src.storage.storage_box import StorageBox, get_storage_box
from src.storage.storage_filter import list_images_for_dates
from src.web_state import WEB_STATE_ROOT, write_web_json

STATE_ROOT = blur_box.DEFAULT_STATE_ROOT
# Read by the web UI's banner: the check time shows the watchdog is alive, the counts and the error
# what it found.
STATUS_PATH = WEB_STATE_ROOT / "blur-watch.json"

# The round runs every 5 minutes and checks an image in 5-9 s, so a normal one is done within
# about 6 minutes; 10 leave a margin and still fit the website's 15-minute renewal.
STALE_AFTER_SECONDS = 600
# Keeps one warning line readable after a long outage.
SHOWN_NAMES = 10


# Unchecked images uploaded more than STALE_AFTER_SECONDS ago, over the days the round lists.
def find_stale(storage_box: StorageBox, camera: str, state_root: Path, now: datetime) -> list[str]:
	processed = blur_box.load_processed(state_root, camera, now)
	days = [now.date() - timedelta(days=offset) for offset in range(blur_box.LISTED_DAYS)]
	uploaded = list_images_for_dates(storage_box, camera, days)
	cutoff = now.timestamp() - STALE_AFTER_SECONDS

	return [
		name
		for name, mtime in uploaded.items()
		if mtime <= cutoff
		and processed.get(name, {}).get("status") not in blur_box.CONFIRMED_STATUSES
	]


def write_status(now: datetime, stale_counts: dict[str, int], errors: list[str]) -> None:
	status = {"checked": now.isoformat(), "stale": stale_counts, "error": "; ".join(errors) or None}

	# The banner treats a missing or old file as "watchdog not running", so a failed write is logged
	# and never stops the check itself.
	try:
		write_web_json(STATUS_PATH, status)

	except OSError as error:
		logger.error(f"Could not write the watchdog status for the web UI: {error}")


def main(now: datetime | None = None) -> int:
	configure_file_logging("privacy")

	config = load_config()
	cameras = (config.get("privacy") or {}).get("blur_cameras") or []
	now = now or datetime.now(ZoneInfo(config["location"]["timezone"]))

	try:
		storage_box = get_storage_box()

	except OSError as error:
		logger.error(f"No storage box: {error}")
		write_status(now, {}, [f"No storage box: {error}"])
		return 1

	exit_code = 0
	stale_total = 0
	stale_counts: dict[str, int] = {}
	errors: list[str] = []

	for camera in cameras:
		try:
			stale = find_stale(storage_box, camera, STATE_ROOT, now)

		# TimeoutError is an OSError too.
		except OSError as error:
			logger.error(f"[{camera}] Stale check failed: {error}")
			errors.append(f"[{camera}] {error}")
			exit_code = 1
			continue

		stale_counts[camera] = len(stale)

		if stale:
			stale_total += len(stale)
			hidden = len(stale) - SHOWN_NAMES
			names = ", ".join(stale[:SHOWN_NAMES]) + (f" and {hidden} more" if hidden > 0 else "")
			logger.warning(
				f"[{camera}] {len(stale)} images unblurred for more than "
				f"{STALE_AFTER_SECONDS // 60} minutes: {names}"
			)

	# Written on every run, so a quiet log still shows the watchdog is alive.
	found = f"{stale_total} stale images" if stale_total else "nothing stale"
	logger.info(f"Stale check: {len(cameras)} cameras, {found}")
	write_status(now, stale_counts, errors)

	return exit_code


if __name__ == "__main__":
	sys.exit(main())
