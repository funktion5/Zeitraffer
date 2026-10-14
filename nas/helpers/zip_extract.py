"""Copy the pictures of one 2004-2008 camera zip into ~/nas-cameras/<camera>/.

The old zips in webcam-archive hold year zips (monthly folders) and tars, nested inside one zip.
Read-only over the rclone mount /mnt/nas. Keeps every file whose name src.images.extract_date
recognises (yearly-backfill applies the 12:00 +-90 min window later) within the given years;
unknown names are counted, never guessed. Existing files are kept, so a later tar cannot
overwrite a picture from a year zip. Unreadable inner zips (e.g. webcam1_bsv/2007.zip) are
reported and skipped.

Usage: .venv/bin/python3 zip_extract.py <zip name> <camera> <first year> <last year>
Example: zip_extract.py webcam1_bsv.zip BSV-Steinhude 2004 2008
"""

import collections
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, "/home/zruser/timelapse")

from src.images import extract_date  # noqa: E402

ARCHIVE = Path("/mnt/nas/storagebox-mirror/webcam-bis-2023/Cafe-am-Meer-Promenade/webcam-archive")

zip_name, camera, first_year, last_year = (
	sys.argv[1],
	sys.argv[2],
	int(sys.argv[3]),
	int(sys.argv[4]),
)
target = Path.home() / "nas-cameras" / camera
target.mkdir(parents=True, exist_ok=True)


def store(name: str, read, counts: collections.Counter) -> None:
	base = name.rsplit("/", 1)[-1]
	if base.startswith(".") or not base.lower().endswith(".jpg"):
		counts["other"] += 1
		return
	day = extract_date(base)
	if day is None:
		counts["unknown_format"] += 1
		return
	if not first_year <= day.year <= last_year:
		counts["outside_years"] += 1
		return
	path = target / base
	if path.exists():
		counts["existing"] += 1
		return
	part = path.with_suffix(".part")
	part.write_bytes(read())
	part.rename(path)
	counts["kept"] += 1


with zipfile.ZipFile(ARCHIVE / zip_name) as outer:
	for info in outer.infolist():
		counts = collections.Counter()
		if info.filename.endswith(".zip"):
			try:
				handle = outer.open(info)
				inner = zipfile.ZipFile(handle)
			except zipfile.BadZipFile as exc:
				print(f"{info.filename}: skipped, not readable ({exc})", flush=True)
				continue
			with handle, inner:
				for member in inner.infolist():
					if not member.is_dir():
						store(member.filename, lambda m=member: inner.read(m), counts)
		elif info.filename.endswith(".tar"):
			# Some archived tars are truncated or empty (webcam4_seerosen 20080115, 20080415);
			# keep what was read before the break and report it.
			try:
				with outer.open(info) as handle, tarfile.open(fileobj=handle, mode="r|") as archive:
					for member in archive:
						if member.isfile():
							store(
								member.name, lambda m=member: archive.extractfile(m).read(), counts
							)
			except tarfile.ReadError as exc:
				counts[f"broken_tar ({exc})"] += 1
		else:
			continue
		print(f"{info.filename}: {dict(counts)}", flush=True)
