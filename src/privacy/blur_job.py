"""The blur step of a manual Monthly or Yearly run with --blur-box.

The job has chosen its frames. Before it builds the video they are blurred on the box, in place
(blur_frames), so this video and every later one that uses the same frames shows them blurred. The
job's own copies were fetched before the blur, so the ones that changed are dropped from its cache
and fetched again. The video is only built when every frame is confirmed; a cut-off JPEG is the
exception, the video step skips it anyway.
"""

from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.images import get_frame_source, image_moment
from src.logger import logger
from src.privacy import blur_box
from src.privacy.anonymize import PrivacyCheckError, parse_blur_settings, parse_drop_rules
from src.privacy.box_writer import DEFAULT_MAX_IMAGE_AGE, BoxWriter
from src.storage_filter import acquire_run_lock, get_storage_box

# The box blur job's state; tests point it at a temporary folder.
BLUR_STATE_ROOT = blur_box.DEFAULT_STATE_ROOT

# On top of the oldest frame's age. The writer's clock keeps running while the job works, so without
# it the oldest frames would be refused an hour into the run.
AGE_MARGIN = timedelta(days=1)


# The line the web UI shows as the reason a camera got no video: it ends in " - skipping camera: ".
def _not_ready(camera: str, reason: str) -> bool:
	logger.warning(f"Blur not finished: {reason} - skipping camera: {camera}")

	return False


# True when the video may be built: every frame is confirmed, cut-off ones excepted.
def blur_job_frames(
	camera: str,
	images: list[Path],
	config: dict,
	now: datetime | None = None,
) -> bool:
	privacy = config.get("privacy") or {}
	detector_command = privacy.get("detector_command")

	if not detector_command:
		raise PrivacyCheckError("privacy.detector_command is not set.")

	settings = parse_blur_settings(privacy.get("blur"))
	rules = parse_drop_rules(privacy)
	timezone = config["location"]["timezone"]
	now = now or datetime.now(ZoneInfo(timezone))
	local_copies = {image.name: image for image in images}
	names = list(local_copies)
	processed = blur_box.load_processed_for_names(BLUR_STATE_ROOT, camera, names, timezone)
	still_open = [
		name
		for name in names
		if processed.get(name, {}).get("status") not in blur_box.CONFIRMED_STATUSES
	]

	logger.info(
		f"[{camera}] Blur: {len(names)} frames, {len(names) - len(still_open)} already confirmed, "
		f"{len(still_open)} to blur"
	)

	if not still_open:
		return True

	with ExitStack() as stack:
		# Another blur round (the nightly catch-up, an earlier job) holds the lock: two writers on
		# the box must never overlap, so this job does not start.
		try:
			stack.enter_context(acquire_run_lock(blur_box.BLUR_LOCK_PATH))

		except RuntimeError:
			return _not_ready(camera, "another blur run holds the lock")

		# The nightly and live rounds only touch images of the last two days. These frames can be
		# months old, so the writer's age limit is sized for the oldest of them and the backup cap
		# for their number. Both stay hard limits; they just fit this job.
		moments = [m for m in (image_moment(name, timezone) for name in still_open) if m]
		max_age = DEFAULT_MAX_IMAGE_AGE

		if moments:
			max_age = max(max_age, now - min(moments) + AGE_MARGIN)

		storage_box = get_storage_box()
		writer = BoxWriter(
			storage_box.remote,
			storage_box.base_directory,
			[camera],
			timezone,
			upload_root=blur_box.WORK_ROOT,
			max_image_age=max_age,
			max_backups_per_camera=len(still_open),
		)
		blur_box.blur_frames(
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
		and not (local_copies[name].exists() and not blur_box.is_complete_jpeg(local_copies[name]))
	]

	if unblurred:
		shown = ", ".join(unblurred[:5])

		return _not_ready(camera, f"{len(unblurred)} of {len(names)} not blurred yet: {shown}")

	return True
