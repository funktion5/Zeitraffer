"""Count the pictures of one camera on the NAS tars and the Storage Box, read-only.

Each NAS tar is streamed once through `rclone cat` and only its headers are read (names and
sizes), so nothing is kept in memory or on disk except the lists. The Storage Box is listed with
one `ls -l` over SSH, like the storage filter. Results go to an output folder outside the repo:

	tars.csv    source;tar;images;bytes;error      one line per finished tar (resume marker)
	images.csv  source;tar;name;size               one line per .jpg

`tars` can be stopped and restarted: finished tars are skipped. `report` prints the summary
(per source, per year, missing days, overlaps, name formats) as Markdown.

Usage:
	.venv/bin/python3 nas/helpers/count_images.py tars <out> <source label> <rclone dir> <regex>
	.venv/bin/python3 nas/helpers/count_images.py box <out> <camera>
	.venv/bin/python3 nas/helpers/count_images.py report <out>

Example (Wunstorf-Marktplatz):
	count_images.py tars ~/nas-count/wunstorf archive-2015-2019 \\
		nas:Webcams/storagebox-mirror/webcam-archive-2015-2019 'wunstorf|marktplatz'
"""

import collections
import csv
import re
import subprocess
import sys
import tarfile
from datetime import date, timedelta
from pathlib import Path

# Two levels up from nas/helpers/ is the project root, wherever it is installed.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.images import extract_date  # noqa: E402
from src.storage_filter import get_storage_box, list_camera_files  # noqa: E402

TARS = "tars.csv"
IMAGES = "images.csv"


def done_tars(out: Path) -> set[tuple[str, str]]:
	path = out / TARS
	if not path.exists():
		return set()
	with path.open(newline="") as file:
		return {(row[0], row[1]) for row in csv.reader(file, delimiter=";")}


def count_tars(out: Path, source: str, remote: str, pattern: str) -> None:
	out.mkdir(parents=True, exist_ok=True)
	listing = subprocess.run(
		["rclone", "lsf", "--files-only", remote], capture_output=True, text=True, check=True
	)
	matcher = re.compile(pattern, re.IGNORECASE)
	tars = sorted(n for n in listing.stdout.split() if n.endswith(".tar") and matcher.search(n))
	finished = done_tars(out)
	todo = [name for name in tars if (source, name) not in finished]
	print(f"{len(tars)} tars match, {len(tars) - len(todo)} already done, {len(todo)} to read")

	for number, name in enumerate(todo, 1):
		images = 0
		total = 0
		error = ""
		rows = []
		# Stream mode: the tar is read front to back once, file contents are skipped, not kept.
		process = subprocess.Popen(["rclone", "cat", f"{remote}/{name}"], stdout=subprocess.PIPE)

		try:
			with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
				for member in archive:
					if member.isfile() and member.name.lower().endswith(".jpg"):
						images += 1
						total += member.size
						rows.append((source, name, Path(member.name).name, member.size))

		except (tarfile.TarError, OSError) as failure:
			error = f"{type(failure).__name__}: {failure}"

		finally:
			process.stdout.close()
			process.wait()

		if process.returncode not in (0, None) and not error:
			error = f"rclone exit {process.returncode}"

		with (out / IMAGES).open("a", newline="") as file:
			csv.writer(file, delimiter=";").writerows(rows)

		# Written last: a tar counts as done only once its images are on disk.
		with (out / TARS).open("a", newline="") as file:
			csv.writer(file, delimiter=";").writerow((source, name, images, total, error))

		print(f"[{number}/{len(todo)}] {name}: {images} images, {total / 1e6:.0f} MB {error}")


def count_box(out: Path, camera: str) -> None:
	out.mkdir(parents=True, exist_ok=True)
	files = list_camera_files(get_storage_box(), camera)
	rows = [
		("box", "-", name, size) for name, size in files.items() if name.lower().endswith(".jpg")
	]

	# Replace earlier box rows; the tar rows stay.
	existing = []
	if (out / IMAGES).exists():
		with (out / IMAGES).open(newline="") as file:
			existing = [row for row in csv.reader(file, delimiter=";") if row[0] != "box"]

	with (out / IMAGES).open("w", newline="") as file:
		writer = csv.writer(file, delimiter=";")
		writer.writerows(existing)
		writer.writerows(rows)

	print(f"box {camera}: {number(len(rows))} images, {gigabytes(sum(r[3] for r in rows))} GB")


# German number style, like the earlier count notes: 1.234 images, 4,55 GB.
def number(value: int) -> str:
	return f"{value:,}".replace(",", ".")


def gigabytes(value: int) -> str:
	return f"{value / 1e9:.2f}".replace(".", ",")


def name_shape(name: str) -> str:
	return re.sub(r"\d", "9", name)


def day_ranges(days: list[date]) -> list[str]:
	ranges = []
	for day in sorted(days):
		if ranges and ranges[-1][1] + timedelta(days=1) == day:
			ranges[-1][1] = day
		else:
			ranges.append([day, day])
	return [f"{a:%d.%m.}" if a == b else f"{a:%d.%m.}-{b:%d.%m.}" for a, b in ranges]


def report(out: Path) -> None:
	sources: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
	tar_stats: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
	per_year: dict[tuple[int, str], list[int]] = collections.defaultdict(lambda: [0, 0])
	days: dict[int, set[date]] = collections.defaultdict(set)
	first_last: dict[str, list[date]] = {}
	seen: dict[str, set[str]] = collections.defaultdict(set)
	# Tars overlap in time, so the same picture can sit in several tars of one source.
	counted: set[str] = set()
	repeats: collections.Counter = collections.Counter()
	shapes: collections.Counter = collections.Counter()
	undated: collections.Counter = collections.Counter()

	with (out / TARS).open(newline="") as file:
		for source, _tar, images, _bytes, error in csv.reader(file, delimiter=";"):
			stats = tar_stats[source]
			stats[0] += 1
			stats[1] += int(images) == 0
			stats[2] += bool(error)

	with (out / IMAGES).open(newline="") as file:
		for source, _tar, name, size in csv.reader(file, delimiter=";"):
			size = int(size)
			seen[name].add(source)

			if name in counted:
				repeats[source] += 1
				continue

			counted.add(name)
			sources[source][0] += 1
			sources[source][1] += size
			shapes[(source, name_shape(name))] += 1
			day = extract_date(name)

			if day is None:
				undated[source] += 1
				continue

			per_year[(day.year, source)][0] += 1
			per_year[(day.year, source)][1] += size
			days[day.year].add(day)
			span = first_last.setdefault(source, [day, day])
			span[0] = min(span[0], day)
			span[1] = max(span[1], day)

	print("## Alle Bilder\n")
	print('Jeder Dateiname zählt einmal; Mehrfachkopien in weiteren Tars stehen unter „doppelt".\n')
	print("| Quelle | Bilder | GB | Tars (leer, Fehler) | Zeitraum | ohne Datum | doppelt |")
	print("|---|---:|---:|---|---|---:|---:|")
	for source, (count, size) in sorted(sources.items()):
		tars = tar_stats.get(source)
		tar_text = f"{tars[0]} (leer {tars[1]}, Fehler {tars[2]})" if tars else "-"
		span = first_last.get(source)
		span_text = f"{span[0]:%d.%m.%Y} - {span[1]:%d.%m.%Y}" if span else "-"
		print(
			f"| {source} | {number(count)} | {gigabytes(size)} | {tar_text} | {span_text} "
			f"| {number(undated[source])} | {number(repeats[source])} |"
		)
	total = sum(c for c, _ in sources.values())
	total_size = sum(s for _, s in sources.values())
	print(
		f"| **Summe** | **{number(total)}** | **{gigabytes(total_size)}** | | | | "
		f"{number(sum(repeats.values()))} |"
	)

	print("\n## Pro Jahr\n")
	source_names = sorted(sources)
	print("| Jahr | " + " | ".join(source_names) + " | Tage mit Bildern | fehlende Tage |")
	print("|---" * (len(source_names) + 3) + "|")
	for year in sorted(days):
		cells = []
		for source in source_names:
			count, size = per_year.get((year, source), (0, 0))
			cells.append(f"{number(count)} · {gigabytes(size)} GB" if count else "-")
		start, end = date(year, 1, 1), date(year, 12, 31)
		first = min(days[year])
		last = max(days[year])
		all_days = [start + timedelta(n) for n in range((end - start).days + 1)]
		missing = [d for d in all_days if first <= d <= last and d not in days[year]]
		missing_text = ", ".join(day_ranges(missing)) if missing else "keine"
		edge = f" (Daten {first:%d.%m.}-{last:%d.%m.})" if (first, last) != (start, end) else ""
		print(f"| {year} | " + " | ".join(cells) + f" | {len(days[year])}{edge} | {missing_text} |")

	print("\n## Überschneidungen\n")
	overlap = collections.Counter(tuple(sorted(s)) for s in seen.values() if len(s) > 1)
	if overlap:
		for combo, count in overlap.most_common():
			print(f"- {' + '.join(combo)}: {number(count)} gleiche Dateinamen")
	else:
		print("- keine gleichen Dateinamen in zwei Quellen")

	print("\n## Namensformate (Ziffern als 9)\n")
	for (source, shape), count in sorted(shapes.items(), key=lambda item: -item[1])[:15]:
		print(f"- {source}: `{shape}` ({number(count)})")


def main() -> None:
	command, out = sys.argv[1], Path(sys.argv[2]).expanduser()

	if command == "tars":
		count_tars(out, sys.argv[3], sys.argv[4], sys.argv[5])
	elif command == "box":
		count_box(out, sys.argv[3])
	elif command == "report":
		report(out)
	else:
		sys.exit(__doc__)


if __name__ == "__main__":
	main()
