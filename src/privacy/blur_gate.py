"""The blur gate of an automatic public video (Daily, Monthly, Yearly; the Weekly inherits it).

A video of a blur camera goes public, so it may only contain frames the box blur job has confirmed
(blurred, clean or night). Unconfirmed frames are left out, not blurred here: this module only reads
the blur job's state and never touches the box.
"""

from pathlib import Path

from src.logger import logger
from src.privacy.blur_box import CONFIRMED_STATUSES, DEFAULT_STATE_ROOT, load_processed_for_names

# The box blur job's state; tests point it at a temporary folder.
BLUR_STATE_ROOT = DEFAULT_STATE_ROOT

# At most this many left-out image names go into the log line; the state file has the rest.
LEFT_OUT_NAMES_LOGGED = 10


# Split the images into those the box blur job has confirmed and the rest, in their given order.
# The state is looked up by file name on the page of each frame's own month (and the days after it):
# a Yearly reaches back a year, which the state of the last few days would never show. A name
# without a readable date has no page and counts as unconfirmed.
def split_confirmed_images(
	camera: str,
	images: list[Path],
	timezone: str,
) -> tuple[list[Path], list[Path]]:
	processed = load_processed_for_names(
		BLUR_STATE_ROOT,
		camera,
		[image.name for image in images],
		timezone,
	)
	confirmed = []
	left_out = []

	for image in images:
		entry = processed.get(image.name)

		if entry is not None and entry.get("status") in CONFIRMED_STATUSES:
			confirmed.append(image)
		else:
			left_out.append(image)

	return confirmed, left_out


# The confirmed images of a blur camera; what was left out is named in the log. An empty result is
# the caller's to handle: no confirmed image means no video for that camera.
def apply_blur_gate(
	camera: str,
	images: list[Path],
	timezone: str,
) -> list[Path]:
	confirmed, left_out = split_confirmed_images(camera, images, timezone)

	if left_out:
		names = ", ".join(image.name for image in left_out[:LEFT_OUT_NAMES_LOGGED])
		more = " ..." if len(left_out) > LEFT_OUT_NAMES_LOGGED else ""

		logger.warning(
			f"[{camera}] Blur gate: left out {len(left_out)} of {len(images)} "
			f"unconfirmed images: {names}{more}"
		)

	return confirmed
