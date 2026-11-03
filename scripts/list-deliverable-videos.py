"""List the video files that may be copied to the website.

Prints one path per line, relative to the videos folder, ready for rsync:
	.venv/bin/python3 scripts/list-deliverable-videos.py > deliverable.txt
	rsync -a --files-from=deliverable.txt videos/ <target>

Per camera and period only the newest video is listed, chosen by file name like the WordPress
plugin does. Only regular, non-empty, non-hidden .mp4 files directly in
videos/<camera>/{daily,weekly,monthly,yearly}/ count, and never those of a camera in
ignored_cameras. Everything else in videos/ (test renders, highlights, leftovers) stays out.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The src package sits in the project root, not next to this script.
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.logger import logger  # noqa: E402
from src.video import VIDEO_ROOT  # noqa: E402

PERIODS = ("daily", "weekly", "monthly", "yearly")


# A symlink could point out of the videos folder, and the encoder's half-written file is hidden
# until it is renamed. An empty file is a failed render, so the next older video is offered instead.
def newest_valid_video(period_folder: Path) -> Path | None:
	valid = [
		path
		for path in period_folder.glob("*.mp4")
		if not path.name.startswith(".")
		and not path.is_symlink()
		and path.is_file()
		and path.stat().st_size > 0
	]

	return max(valid, key=lambda path: path.name, default=None)


def list_deliverable_videos(videos_root: Path, ignored: set[str]) -> list[str]:
	deliverable = []

	for camera_folder in videos_root.iterdir():
		if camera_folder.name in ignored:
			continue

		if camera_folder.is_symlink() or not camera_folder.is_dir():
			continue

		# Only these four folders are looked at: anything else a camera folder holds is not for the
		# website, whatever its name.
		for period in PERIODS:
			period_folder = camera_folder / period

			if period_folder.is_symlink() or not period_folder.is_dir():
				continue

			newest = newest_valid_video(period_folder)

			if newest is not None:
				deliverable.append(newest.relative_to(videos_root).as_posix())

	return sorted(deliverable)


# Only the paths go to stdout; the logger writes to stderr. A missing folder is an error, because
# an empty list would look like "nothing to send".
def main() -> int:
	videos_root = PROJECT_ROOT / VIDEO_ROOT

	if not videos_root.is_dir():
		logger.error(f"Videos folder not found: {videos_root}")

		return 1

	ignored = set(load_config().get("ignored_cameras", []))

	sys.stdout.write("".join(f"{path}\n" for path in list_deliverable_videos(videos_root, ignored)))

	return 0


if __name__ == "__main__":
	sys.exit(main())
