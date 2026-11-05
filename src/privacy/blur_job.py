"""The blur step of a manual Monthly or Yearly run with --blur-box.

The job has chosen its frames. Before it builds the video they are blurred on the box, in place
(blur_frames), so this video and every later one that uses the same frames shows them blurred. The
job's own copies were fetched before the blur, so the ones that changed are dropped from its cache
and fetched again. The video is only built when every frame is confirmed; a cut-off JPEG is the
exception, the video step skips it anyway.
"""

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.images import get_frame_source, image_moment
from src.logger import logger
from src.privacy import blur_box
from src.privacy.anonymize import PrivacyCheckError, parse_blur_settings, parse_drop_rules
from src.privacy.box_writer import DEFAULT_MAX_IMAGE_AGE, BoxWriter
from src.storage_filter import StorageBox, acquire_run_lock, get_storage_box

# The box blur job's state; tests point it at a temporary folder.
BLUR_STATE_ROOT = blur_box.DEFAULT_STATE_ROOT

# On top of the oldest frame's age, so the writer's limit never sits exactly on a frame.
AGE_MARGIN = timedelta(days=1)

# At most this many names of unblurred frames go into the reason; the state files have the rest.
NAMES_IN_REASON = 5


@dataclass(frozen=True)
class BlurJobResult:
	# True when the video may be built: every frame is confirmed, cut-off ones excepted.
	ready: bool
	# Empty when ready; otherwise a sentence for the log.
	reason: str
	summary: blur_box.BoxRoundSummary


# The nightly and live rounds only touch images of the last two days. A job's frames can be months
# old, so the writer's age limit is sized for the oldest of them and the backup cap for their
# number. Both stay hard limits; they just fit this job.
def _writer_for_frames(
	storage_box: StorageBox,
	camera: str,
	names: list[str],
	timezone: str,
	now: datetime,
	writer_options: dict | None,
) -> BoxWriter:
	moments = [m for m in (image_moment(name, timezone) for name in names) if m is not None]
	max_age = DEFAULT_MAX_IMAGE_AGE

	if moments:
		max_age = max(max_age, now - min(moments) + AGE_MARGIN)

	options = {"upload_root": blur_box.WORK_ROOT, **(writer_options or {})}

	return BoxWriter(
		storage_box.remote,
		storage_box.base_directory,
		[camera],
		timezone,
		max_image_age=max_age,
		max_backups_per_camera=len(names),
		**options,
	)


def _is_cut_off(path: Path) -> bool:
	return path.exists() and not blur_box.is_complete_jpeg(path)


def blur_job_frames(
	camera: str,
	images: list[Path],
	config: dict,
	now: datetime,
	writer_options: dict | None = None,
) -> BlurJobResult:
	privacy = config.get("privacy") or {}

	if camera not in (privacy.get("blur_cameras") or []):
		raise ValueError(f"{camera} is not in privacy.blur_cameras, nothing is written.")

	detector_command = privacy.get("detector_command")

	if not detector_command:
		raise PrivacyCheckError("privacy.detector_command is not set.")

	settings = parse_blur_settings(privacy.get("blur"))
	rules = parse_drop_rules(privacy)
	timezone = config["location"]["timezone"]
	local_copies = {image.name: image for image in images}
	names = list(local_copies)
	confirmed, still_open = blur_box.split_confirmed_names(BLUR_STATE_ROOT, camera, names, timezone)

	logger.info(
		f"[{camera}] Blur: {len(names)} frames, {len(confirmed)} already confirmed, "
		f"{len(still_open)} to blur"
	)

	if not still_open:
		return BlurJobResult(True, "", blur_box.BoxRoundSummary())

	with ExitStack() as stack:
		# Another blur round (the nightly catch-up, an earlier job) holds the lock: two writers on
		# the box must never overlap, so this job does not start.
		try:
			stack.enter_context(acquire_run_lock(blur_box.BLUR_LOCK_PATH))

		except RuntimeError:
			return BlurJobResult(
				False, "another blur run holds the lock", blur_box.BoxRoundSummary()
			)

		writer = _writer_for_frames(
			get_storage_box(), camera, still_open, timezone, now, writer_options
		)
		summary = blur_box.blur_frames(
			writer, camera, still_open, detector_command, settings, BLUR_STATE_ROOT, now, rules
		)

	# The job's copies of the frames that changed on the box are from before the blur: drop just
	# those and fetch them again, so the video shows the blurred ones.
	processed = blur_box.load_processed_for_names(BLUR_STATE_ROOT, camera, still_open, timezone)
	blurred = [name for name in still_open if processed.get(name, {}).get("status") == "blurred"]

	if blurred:
		source = get_frame_source()
		source.release_frames(camera, blurred)
		source.localize(camera, [local_copies[name] for name in blurred])

	# A frame that is not confirmed holds the video back, unless it is cut off: the video step
	# skips such a frame anyway, so it needs no blur.
	unblurred = [
		name
		for name in still_open
		if processed.get(name, {}).get("status") not in blur_box.CONFIRMED_STATUSES
		and not _is_cut_off(local_copies[name])
	]

	if not unblurred:
		return BlurJobResult(True, "", summary)

	shown = ", ".join(unblurred[:NAMES_IN_REASON])
	more = " ..." if len(unblurred) > NAMES_IN_REASON else ""

	return BlurJobResult(
		False,
		f"{len(unblurred)} of {len(names)} frames are not blurred yet: {shown}{more}",
		summary,
	)
