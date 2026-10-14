"""Copy one year's interval-window images of a camera from the storage box into ~/nas-cameras.

Read-only on /mnt/cameras: uses the same scan and window as yearly-backfill.py, copies via a
.part file and skips names that already exist locally (NAS pictures win).

Usage: .venv/bin/python3 storagebox_fill.py <camera> <year>
"""

import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path("/home/zruser/timelapse")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.images import CAMERA_ROOT, extract_date, find_interval_images_isolated  # noqa: E402
from src.interval_window import interval_window_from_config, resolve_target_seconds  # noqa: E402

camera, year = sys.argv[1], int(sys.argv[2])
assert str(CAMERA_ROOT) == "/mnt/cameras", f"unexpected source root {CAMERA_ROOT}"
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
