"""Delete dark (night) pictures of a camera inside given date ranges from ~/nas-cameras.

For cameras whose clock was wrong for a while, the 12:00 window picks night pictures. This
measures each picture's mean brightness (FFmpeg scale to 1x1 grey, 0..255) and deletes those
below the threshold, then reports how many bright pictures each day keeps.

Usage: .venv/bin/python3 delete_dark.py <camera> <from YYYY-MM-DD> <to YYYY-MM-DD> [...more ranges]
Example (Uferstrasse, 2026-10-05 findings):
	delete_dark.py Uferstrasse 2016-11-01 2017-02-28 2018-04-01 2018-07-31
"""

import collections
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/home/zruser/timelapse")

from src.images import extract_date  # noqa: E402

THRESHOLD = 40

camera = sys.argv[1]
bounds = [date.fromisoformat(value) for value in sys.argv[2:]]
periods = list(zip(bounds[::2], bounds[1::2]))
folder = Path.home() / "nas-cameras" / camera


def brightness(path: Path) -> int:
	result = subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-i",
			str(path),
			"-vf",
			"scale=1:1,format=gray",
			"-f",
			"rawvideo",
			"-",
		],
		capture_output=True,
	)
	# Unreadable pictures count as bright so they are never deleted by mistake.
	return result.stdout[0] if result.stdout else 255


removed = collections.Counter()
kept = collections.Counter()

for picture in sorted(folder.iterdir()):
	day = extract_date(picture.name)

	if day is None or not any(start <= day <= end for start, end in periods):
		continue

	if brightness(picture) < THRESHOLD:
		picture.unlink()
		removed[day] += 1
	else:
		kept[day] += 1

days = set(removed) | set(kept)
print(f"removed {sum(removed.values())} dark pictures on {len(removed)} days")

for start, end in periods:
	in_period = [day for day in days if start <= day <= end]
	few = [day for day in in_period if 0 < kept[day] < 5]
	none = [day for day in in_period if kept[day] == 0]
	print(
		f"{start}..{end}: {len(in_period)} days | <5 bright left: {len(few)} | "
		f"none left: {len(none)}"
	)
