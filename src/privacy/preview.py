"""The preview picture of the web UI's Verpixelung page: one frame of a blur camera.

The page lets colleagues draw ignore boxes on a real picture of the camera. The picture is never a
raw frame the blur job has not seen: only a frame the box blur job has judged (blurred or clean) is
a candidate. A night frame is recorded without running the detector, so it is never shown. A frame
is shown only if the bytes on the box are the ones the job recorded.

The frame is fetched with the frame source (this module starts no ssh itself), checked, and cached
under state/web-jobs/previews/ with a short description, where the web server user can read it. The
web server reads the picture's size from the picture itself. It cannot reach the Storage Box, so the
root-owned wrapper timelapse-web-preview runs this as the run user.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import src.frame_source as frame_source
from src.config import PROJECT_ROOT, load_config
from src.frame_source import FrameFetchError
from src.images import get_frame_source, image_moment
from src.logger import logger
from src.privacy import blur_box

# The box blur job's state; tests point it at a temporary folder.
BLUR_STATE_ROOT = blur_box.DEFAULT_STATE_ROOT
PREVIEW_ROOT = PROJECT_ROOT / "state" / "web-jobs" / "previews"

# Best first. Both kinds went through the detector; a night frame did not, so it is left out.
KINDS = ("blurred", "clean")

# The bytes the blur job judged, by kind: the blurred copy it wrote, or the untouched original it
# found clean.
JUDGED_HASH_FIELD = {"blurred": "blurred_sha256", "clean": "original_sha256"}

# A box that answers slowly must not be asked about the whole backlog.
MAX_CANDIDATES = 3

# Exit codes of "python -m src.privacy.preview"; the web wrapper hands them on to PHP.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNKNOWN_CAMERA = 66
EXIT_NO_FRAME = 67


@dataclass(frozen=True)
class Candidate:
	name: str
	kind: str
	moment: datetime
	entry: dict


def _preference(candidate: Candidate) -> tuple[int, int, float, str]:
	midday = candidate.moment.replace(hour=12, minute=0, second=0, microsecond=0)

	return (
		KINDS.index(candidate.kind),
		# Newest day first.
		-candidate.moment.toordinal(),
		abs((candidate.moment - midday).total_seconds()),
		candidate.name,
	)


# Judged frames, best first. Unfinished and night frames may show a person, so they are no
# candidates; nor is a name without a readable time.
def rank_candidates(processed: dict[str, dict], timezone: str) -> list[Candidate]:
	candidates = []

	for name, entry in processed.items():
		kind = entry.get("status")
		moment = image_moment(name, timezone)

		if kind in KINDS and moment is not None:
			candidates.append(Candidate(name, kind, moment, entry))

	return sorted(candidates, key=_preference)


# Must be a complete JPEG with the bytes the job judged. A frame without a recorded hash (an old
# state line) is accepted.
def _is_judged_frame(path: Path, candidate: Candidate) -> bool:
	if not blur_box.is_complete_jpeg(path):
		return False

	expected = candidate.entry.get(JUDGED_HASH_FIELD.get(candidate.kind, ""))

	return not expected or blur_box.sha256_file(path) == expected


# The temporary file lives next to its destination so the rename stays on one filesystem. mkstemp
# makes it private; the web server user has to read the result.
def _write_json_atomically(destination: Path, content: dict) -> None:
	descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")
	staged = Path(temporary)

	try:
		with os.fdopen(descriptor, "w", encoding="utf-8") as file:
			json.dump(content, file)

		staged.chmod(0o644)
		os.replace(staged, destination)

	finally:
		staged.unlink(missing_ok=True)


# Copies the frame first and checks the COPY, so what is checked is what is published. None when
# the frame is not fit to show; the caller then tries the next one.
def _publish(
	source_path: Path, candidate: Candidate, camera: str, preview_root: Path
) -> dict | None:
	if not source_path.is_file():
		return None

	preview_root.mkdir(parents=True, exist_ok=True)
	preview_root.chmod(0o755)
	descriptor, temporary = tempfile.mkstemp(dir=preview_root, prefix=f".{camera}.", suffix=".jpg")
	staged = Path(temporary)

	try:
		with os.fdopen(descriptor, "wb") as target, source_path.open("rb") as source:
			shutil.copyfileobj(source, target)

		if not _is_judged_frame(staged, candidate):
			return None

		staged.chmod(0o644)
		os.replace(staged, preview_root / f"{camera}.jpg")

	finally:
		staged.unlink(missing_ok=True)

	info = {
		"image": candidate.name,
		"status": candidate.kind,
		"taken": candidate.moment.isoformat(),
	}
	_write_json_atomically(preview_root / f"{camera}.json", info)

	return info


# The preview of one camera: the best frame the job has judged that can still be shown. None when
# there is none; an older preview then stays as it is. The fetched copy is dropped in every case:
# a frame source may hold a cache of fetched frames.
def build_preview(
	camera: str,
	config: dict,
	state_root: Path,
	preview_root: Path,
	now: datetime,
) -> dict | None:
	timezone = config["location"]["timezone"]
	processed = blur_box.load_processed(state_root, camera, now)
	candidates = rank_candidates(processed, timezone)[:MAX_CANDIDATES]

	if not candidates:
		return None

	source = get_frame_source()

	try:
		for candidate in candidates:
			path = source.path_for(camera, candidate.name)

			try:
				source.localize(camera, [path])

			except FrameFetchError as error:
				logger.warning(f"[{camera}] Preview frame {candidate.name} not fetched: {error}")

				continue

			info = _publish(path, candidate, camera, preview_root)

			if info is not None:
				return info

			logger.warning(f"[{camera}] Preview frame {candidate.name} is not fit to show, skipped")

	finally:
		source.release(camera)

	return None


# A function of its own so a test can fix the time: the state is read by month.
def current_time(timezone: str) -> datetime:
	return datetime.now(ZoneInfo(timezone))


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Cache a preview picture of one blur camera.")
	parser.add_argument("camera")
	arguments = parser.parse_args(argv)

	config = load_config()
	blur_cameras = (config.get("privacy") or {}).get("blur_cameras") or []

	# The name comes from a web request: only a camera of the blur list has a preview.
	if arguments.camera not in blur_cameras:
		print(json.dumps({"status": "unknown_camera"}))

		return EXIT_UNKNOWN_CAMERA

	# A click must answer in seconds: one attempt at the fetch, not the waits of a night job.
	frame_source.FETCH_RETRY_WAIT_SECONDS = ()

	try:
		info = build_preview(
			arguments.camera,
			config,
			BLUR_STATE_ROOT,
			PREVIEW_ROOT,
			current_time(config["location"]["timezone"]),
		)

	# The reason goes to the log, never to the browser. A ValueError is a setup error, such as no
	# frame source configured.
	except (OSError, ValueError) as error:
		logger.error(f"[{arguments.camera}] Preview failed: {error}")
		print(json.dumps({"status": "failed"}))

		return EXIT_FAILED

	if info is None:
		print(json.dumps({"status": "none"}))

		return EXIT_NO_FRAME

	# "status" last: the cache description uses the same key for the kind of frame, and the
	# reply's "ok" is what the web side checks.
	print(json.dumps({**info, "status": "ok"}))

	return EXIT_OK


if __name__ == "__main__":
	sys.exit(main())
