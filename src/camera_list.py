import json
import os
import sys
import tempfile
from pathlib import Path

from src.config import PROJECT_ROOT, load_config
from src.images import get_cameras
from src.logger import logger

# The web pages read their camera list from here instead of listing the storage themselves: the
# web server user has no ssh key and never talks to the box.
CAMERA_LIST_PATH = PROJECT_ROOT / "state" / "web-jobs" / "cameras.json"


# The page may read at any moment, so the file is replaced in one step: it holds the old list or
# the new one, never half of it, and a failed write leaves the old list and no temporary file.
def write_camera_list(destination: Path, cameras: list[str]) -> None:
	destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)

	descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")

	try:
		with os.fdopen(descriptor, "w", encoding="utf-8") as file:
			json.dump(cameras, file)
			file.write("\n")

		# mkstemp creates the file private; the web server user has to read it.
		os.chmod(temporary, 0o644)
		os.replace(temporary, destination)

	except BaseException:
		Path(temporary).unlink(missing_ok=True)

		raise


# Written by the nightly run, and by hand after a camera is added or removed. A listing that fails
# or comes back empty leaves the old file: the web page must not go blank because of a hiccup.
def main() -> int:
	try:
		available = get_cameras()

	except OSError as error:
		logger.error(f"Camera list not updated: {error}")

		return 1

	ignored = set(load_config().get("ignored_cameras", []))
	cameras = [camera for camera in available if camera not in ignored]

	if not cameras:
		logger.error("Camera list not updated: the listing found no cameras")

		return 1

	write_camera_list(CAMERA_LIST_PATH, cameras)
	logger.info(f"Camera list written: {len(cameras)} cameras")

	return 0


if __name__ == "__main__":
	sys.exit(main())
