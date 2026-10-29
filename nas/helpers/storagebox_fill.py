"""Copy one year's interval-window images of a camera from the storage box into ~/nas-cameras.

Read-only on the camera storage: reads through the frame source (the storage box over ssh, or a
local folder), uses the same scan and window as yearly-backfill.py, copies via a .part file and
skips names that already exist locally (NAS pictures win).

Usage: .venv/bin/python3 storagebox_fill.py <camera> <year>
"""

import atexit
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

# Two levels up from nas/helpers/ is the project root, wherever it is installed.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.image_worker import exit_on_sigterm  # noqa: E402
from src.images import (  # noqa: E402
	extract_date,
	find_interval_images_isolated,
	release_camera_frames,
)
from src.interval_window import interval_window_from_config, resolve_target_seconds  # noqa: E402


# In a function behind the guard: the scan starts worker processes, and where they are started by
# importing this file again (macOS, and Linux from Python 3.14) it must not run the copy twice.
def main() -> int:
	camera, year = sys.argv[1], int(sys.argv[2])

	# The fetched frames are unblurred and only needed for the copy below: they go on every exit, a
	# failure included, and a stop signal becomes a normal exit that runs this too.
	atexit.register(release_camera_frames, camera)
	exit_on_sigterm()

	target = Path.home() / "nas-cameras" / camera
	target.mkdir(parents=True, exist_ok=True)

	config = json.loads((PROJECT_ROOT / "config" / "config.json").read_text())
	window = interval_window_from_config(config)
	start, end = date(year, 1, 1), date(year, 12, 31)
	images = find_interval_images_isolated(
		camera=camera,
		start_date=start,
		end_date=end,
		stall_timeout_seconds=config["image_scan_stall_timeout_seconds"],
		target_seconds_by_date=resolve_target_seconds(window, start, end, config["location"]),
		tolerance_minutes=window.tolerance_minutes,
	)

	local_days = {extract_date(p.name) for p in target.iterdir()} - {None}
	copied = skipped = 0
	new_days = set()

	for source in images:
		destination = target / source.name

		if destination.exists():
			skipped += 1
			continue

		partial = target / f".{source.name}.part"
		shutil.copy2(source, partial)
		partial.replace(destination)
		copied += 1
		new_days.add(extract_date(source.name))

	print(
		f"{camera} {year}: storage-box window images={len(images)} copied={copied} "
		f"already-local={skipped} | new days={len(new_days - local_days)}"
	)

	return 0


if __name__ == "__main__":
	sys.exit(main())
