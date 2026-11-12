import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Literal

import psutil

from src.config import load_config
from src.images import JPEG_END_MARKER
from src.interval_window import IntervalWindow
from src.logger import logger
from src.privacy.anonymize import anonymize_frames, parse_drop_rules

CONFIG = load_config()

FFMPEG_THREADS = CONFIG["timelapse"]["ffmpeg_threads"]
DETECTOR_COMMAND = CONFIG["privacy"]["detector_command"]
BLUR_SETTINGS = CONFIG["privacy"]["blur"]

TEMP_ROOT = Path("temp")
VIDEO_ROOT = Path("videos")
FFMPEG_ERROR_LOG_LINES = 40

# A host with little memory that kills large encoder processes selects a lighter x264 preset here.
# Unset keeps FFmpeg's own default, so the command is unchanged everywhere else.
X264_PRESET_ENV = "TIMELAPSE_X264_PRESET"
X264_PRESETS = (
	"ultrafast",
	"superfast",
	"veryfast",
	"faster",
	"fast",
	"medium",
	"slow",
	"slower",
	"veryslow",
	"placebo",
)


TimelapseType = Literal["daily", "weekly", "monthly", "yearly"]


# Read at call time, not at import, so isolated workers and tests see the current environment.
def x264_preset_arguments() -> list[str]:
	preset = os.environ.get(X264_PRESET_ENV, "").strip()

	if not preset:
		return []

	if preset not in X264_PRESETS:
		raise ValueError(f"{X264_PRESET_ENV} must be one of {', '.join(X264_PRESETS)}: {preset!r}")

	return ["-preset", preset]


# The x264 quality (CRF): a whole number from 0 to 51; lower is better and larger. config.json
# holds the default, TIMELAPSE_X264_CRF overrides it for one run. Read at call time, like the
# preset.
X264_CRF_ENV = "TIMELAPSE_X264_CRF"
X264_CRF_MAX = 51


def x264_crf_arguments() -> list[str]:
	configured = os.environ.get(X264_CRF_ENV, "").strip()

	if configured:
		# No sign, no decimals, no leading zero: anything else is a typo, not a quality.
		if not re.fullmatch(r"0|[1-9][0-9]?", configured):
			raise ValueError(
				f"{X264_CRF_ENV} must be a whole number from 0 to {X264_CRF_MAX}: {configured!r}"
			)

		crf = int(configured)
		source = X264_CRF_ENV

	else:
		crf = CONFIG["timelapse"]["crf"]
		source = "timelapse.crf"

	# A JSON true is an int in Python and must not pass as 1.
	if not isinstance(crf, int) or isinstance(crf, bool) or not 0 <= crf <= X264_CRF_MAX:
		raise ValueError(f"{source} must be a whole number from 0 to {X264_CRF_MAX}: {crf!r}")

	return ["-crf", str(crf)]


# JPEG start-of-frame markers: the segments that carry the image size (baseline, extended,
# progressive, lossless and the arithmetic-coded variants).
JPEG_FRAME_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


# Width and height from the JPEG header, read segment by segment so an EXIF thumbnail with its own
# size is skipped by its length. None when there is no frame header (not a JPEG, cut off, missing).
def jpeg_size(path: Path) -> tuple[int, int] | None:
	try:
		with path.open("rb") as file:
			if file.read(2) != b"\xff\xd8":
				return None

			while byte := file.read(1):
				if byte != b"\xff":
					continue

				marker = file.read(1)

				while marker == b"\xff":
					marker = file.read(1)

				if not marker:
					return None

				code = marker[0]

				# Markers without a length: padding, TEM, restart markers and the start of image.
				if code == 0x00 or code == 0x01 or 0xD0 <= code <= 0xD8:
					continue

				# The end of the image, or the start of the scan data: no frame header came before.
				if code in (0xD9, 0xDA):
					return None

				length = file.read(2)

				if len(length) < 2:
					return None

				if code in JPEG_FRAME_MARKERS:
					size = file.read(5)

					if len(size) < 5:
						return None

					return int.from_bytes(size[3:5], "big"), int.from_bytes(size[1:3], "big")

				file.seek(int.from_bytes(length, "big") - 2, os.SEEK_CUR)

	except OSError:
		return None

	return None


# Frames of two sizes in one video (an exchanged camera: Uferstrasse 640x480, then 1920x1080):
# ffmpeg would stretch every frame to the first one's size, so the 16:9 footage came out narrow.
# With mixed sizes every frame is fitted into the largest size, aspect ratio kept, black bars
# where it does not fill. One size adds nothing, so those commands are unchanged.
def frame_fit_arguments(temp_directory: Path) -> list[str]:
	frame_sizes = (jpeg_size(frame) for frame in temp_directory.glob("frame_*.jpg"))
	sizes = {size for size in frame_sizes if size is not None}

	if len(sizes) < 2:
		return []

	width, height = max(sizes, key=lambda size: (size[0] * size[1], size[0]))

	# yuv420p needs even sizes.
	width += width % 2
	height += height % 2

	found = ", ".join(f"{w}x{h}" for w, h in sorted(sizes))

	logger.info(
		f"Frames of {len(sizes)} different sizes ({found}): "
		f"fitting every frame into {width}x{height}"
	)

	return [
		"-vf",
		f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
		f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1",
	]


# Run FFmpeg, record peak resource use, and retain failure diagnostics.
def run_ffmpeg(command: list[str]) -> None:
	with tempfile.TemporaryFile() as error_output:
		process = subprocess.Popen(
			command,
			stderr=error_output,
		)

		ffmpeg_process = psutil.Process(process.pid)

		peak_cpu = 0.0
		peak_memory_mb = 0.0
		peak_system_cpu = 0.0
		peak_system_memory = 0.0

		while process.poll() is None:
			try:
				peak_cpu = max(peak_cpu, ffmpeg_process.cpu_percent(interval=0.2))
				peak_memory_mb = max(peak_memory_mb, ffmpeg_process.memory_info().rss / 1024 / 1024)
				peak_system_cpu = max(peak_system_cpu, psutil.cpu_percent())
				peak_system_memory = max(peak_system_memory, psutil.virtual_memory().percent)

			except psutil.NoSuchProcess:
				break

			time.sleep(0.1)

		return_code = process.wait()

		logger.info(
			"Peak hardware usage | "
			f"FFmpeg CPU: {peak_cpu:.1f}% | "
			f"FFmpeg RAM: {peak_memory_mb:.1f} MB | "
			f"System CPU: {peak_system_cpu:.1f}% | "
			f"System RAM: {peak_system_memory:.1f}%"
		)

		if return_code == 0:
			return

		error_output.seek(0)

		stderr_lines = (
			error_output.read()
			.decode(
				"utf-8",
				errors="replace",
			)
			.splitlines()
		)

		stderr_tail = "\n".join(stderr_lines[-FFMPEG_ERROR_LOG_LINES:])

		if not stderr_tail:
			stderr_tail = "No FFmpeg error output was captured."

		logger.error(f"FFmpeg failed with exit code {return_code}:\n{stderr_tail}")

		raise subprocess.CalledProcessError(
			return_code,
			command,
			stderr=stderr_tail,
		)


# Create a clean temporary working directory for a camera and date.
def create_temp_directory(
	camera: str,
	target_date: date,
) -> Path:
	temp_directory = TEMP_ROOT / camera / target_date.isoformat()

	if temp_directory.exists():
		logger.debug(f"Removing existing temporary directory: {temp_directory}")

		shutil.rmtree(temp_directory)

	temp_directory.mkdir(parents=True)

	logger.debug(f"Created temporary directory: {temp_directory}")

	return temp_directory


# A camera upload cut off part-way still has a size, so the 0-byte filter misses it. FFmpeg would
# fill its missing lower part with the previous frame. Every camera ends its JPEGs with this marker.
def is_complete_jpeg(path: Path) -> bool:
	with path.open("rb") as file:
		try:
			file.seek(-len(JPEG_END_MARKER), os.SEEK_END)
		except OSError:
			return False

		return file.read() == JPEG_END_MARKER


# Copy selected images locally and rename them as sequential FFmpeg frames. The check runs on the
# local copy, so it costs no extra read of the camera storage. Returns (original, frame) pairs.
def copy_images_to_temp(
	images: list[Path],
	temp_directory: Path,
) -> list[tuple[Path, Path]]:
	logger.info(f"Copying {len(images)} images to temporary directory")

	copied_images = []

	for image in images:
		destination = temp_directory / f"frame_{len(copied_images) + 1:06d}.jpg"

		shutil.copy2(
			image,
			destination,
		)

		if not is_complete_jpeg(destination):
			logger.warning(f"Skipping truncated image (no JPEG end marker): {image}")

			destination.unlink()

			continue

		copied_images.append((image, destination))

	skipped = len(images) - len(copied_images)

	if skipped:
		logger.warning(f"Skipped {skipped} of {len(images)} truncated images")

	if images and not copied_images:
		raise OSError(f"No complete images left to encode in {temp_directory}")

	logger.debug(f"Copied {len(copied_images)} temporary frames")

	return copied_images


# Return the output path for automatic or explicit-date timelapses.
# The daylight buffer is only ever embedded in manual/historical filenames,
# since it can vary per request there; automatic runs always use the single
# configured buffer, so their filenames stay exactly as before.
def get_video_path(
	camera: str,
	target_date: date,
	timelapse_type: TimelapseType,
	manual_run: bool = False,
	daylight_buffer_minutes: int | None = None,
	interval_window: IntervalWindow | None = None,
	blur_people: bool = False,
) -> Path:
	# Blurring exists for manual Dailies and the calendar-year Yearly backfill
	# (scripts/yearly-backfill.py); the suffix keeps them apart from unblurred videos.
	if blur_people and not (manual_run and timelapse_type in ("daily", "yearly")):
		raise ValueError("Blurred videos are only allowed for manual daily and yearly runs.")

	if daylight_buffer_minutes is not None and timelapse_type in ("monthly", "yearly"):
		raise ValueError(f"{timelapse_type} does not use a daylight buffer.")

	if interval_window is not None and timelapse_type not in ("monthly", "yearly"):
		raise ValueError(f"{timelapse_type} does not use an interval window.")

	# Automatic videos keep one name per type; a custom window only exists for manual runs.
	if interval_window is not None and not manual_run:
		raise ValueError("An interval window suffix is only allowed for manual runs.")

	if manual_run:
		output_directory = VIDEO_ROOT / camera / "manual-runs" / timelapse_type

		if daylight_buffer_minutes is not None:
			suffix = f"_{daylight_buffer_minutes}min"

		elif interval_window is not None:
			suffix = f"_{interval_window.label()}"

		else:
			suffix = ""

		if blur_people:
			suffix += "_blur"

		return output_directory / f"{camera}_{target_date.isoformat()}{suffix}.mp4"

	output_directory = VIDEO_ROOT / camera / timelapse_type

	return output_directory / f"{camera}_{target_date.isoformat()}.mp4"


# Keep only the newest automatic video for the selected timelapse type.
def cleanup_automatic_video_retention(
	camera: str,
	timelapse_type: Literal["weekly", "monthly", "yearly"],
	current_video: Path,
) -> None:
	video_directory = VIDEO_ROOT / camera / timelapse_type

	if not video_directory.exists():
		return

	for existing_video in video_directory.glob(f"{camera}_*.mp4"):
		if existing_video == current_video:
			continue

		logger.debug(f"Removing outdated {timelapse_type} video: {existing_video}")

		existing_video.unlink()


# Create an FFmpeg concat file from existing video files.
def create_concat_file(
	videos: list[Path],
	temp_directory: Path,
) -> Path:
	temp_directory.mkdir(
		parents=True,
		exist_ok=True,
	)

	concat_path = temp_directory / "concat.txt"

	lines = [f"file '{video.resolve()}'" for video in videos]

	concat_path.write_text(
		"\n".join(lines) + "\n",
		encoding="utf-8",
	)

	logger.debug(f"Created concat file: {concat_path}")

	return concat_path


# Run FFmpeg into a hidden temporary file and atomically replace the final
# video only after it succeeded, so a failed rebuild leaves the old one intact.
def encode_video(
	ffmpeg_arguments: list[str],
	output_path: Path,
	description: str,
) -> Path:
	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	temporary_output = output_path.parent / f".{output_path.stem}.tmp{output_path.suffix}"

	logger.info(f"Creating {description}: {output_path}")

	command = ["ffmpeg", "-y", *ffmpeg_arguments, str(temporary_output)]

	logger.debug(f"FFmpeg command: {' '.join(command)}")

	run_ffmpeg(command)

	temporary_output.replace(output_path)

	logger.info(f"{description.capitalize()} created successfully: {output_path}")

	return output_path


# Create a video by concatenating existing compatible video files.
def create_concat_video(
	concat_path: Path,
	output_path: Path,
) -> Path:
	return encode_video(
		["-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy"],
		output_path=output_path,
		description="concat video",
	)


# Create an MP4 timelapse from the prepared temporary frames.
def create_image_timelapse(
	camera: str,
	target_date: date,
	temp_directory: Path,
	timelapse_type: TimelapseType,
	framerate: int,
	manual_run: bool = False,
	daylight_buffer_minutes: int | None = None,
	interval_window: IntervalWindow | None = None,
	blur_people: bool = False,
) -> Path:
	output_path = get_video_path(
		camera=camera,
		target_date=target_date,
		timelapse_type=timelapse_type,
		manual_run=manual_run,
		daylight_buffer_minutes=daylight_buffer_minutes,
		interval_window=interval_window,
		blur_people=blur_people,
	)

	return encode_video(
		[
			"-framerate",
			str(framerate),
			"-i",
			str(temp_directory / "frame_%06d.jpg"),
			"-c:v",
			"libx264",
			*x264_preset_arguments(),
			*x264_crf_arguments(),
			"-threads",
			str(FFMPEG_THREADS),
			*frame_fit_arguments(temp_directory),
			"-pix_fmt",
			"yuv420p",
		],
		output_path=output_path,
		description="video",
	)


# Remove the temporary working directory after successful processing.
def cleanup_temp_directory(
	temp_directory: Path,
) -> None:
	if temp_directory.exists():
		shutil.rmtree(temp_directory)

		logger.debug(f"Removed temporary directory: {temp_directory}")


# Create a complete image-based timelapse and clean up temporary files.
def create_timelapse(
	camera: str,
	target_date: date,
	images: list[Path],
	timelapse_type: TimelapseType,
	framerate: int,
	manual_run: bool = False,
	daylight_buffer_minutes: int | None = None,
	interval_window: IntervalWindow | None = None,
	blur_people: bool = False,
) -> Path:
	temp_directory = create_temp_directory(
		camera,
		target_date,
	)

	copied_images = copy_images_to_temp(
		images,
		temp_directory,
	)

	# Only the temporary copies are blurred; a failure raises before anything is encoded.
	if blur_people:
		anonymize_frames(
			camera=camera,
			originals=[original for original, _ in copied_images],
			frames=[frame for _, frame in copied_images],
			detector_command=DETECTOR_COMMAND,
			blur_settings=BLUR_SETTINGS,
			# Checked only when blurring is asked for: a bad value must not stop normal videos.
			drop_rules=parse_drop_rules(CONFIG["privacy"]),
		)

	video_path = create_image_timelapse(
		camera=camera,
		target_date=target_date,
		temp_directory=temp_directory,
		timelapse_type=timelapse_type,
		framerate=framerate,
		manual_run=manual_run,
		daylight_buffer_minutes=daylight_buffer_minutes,
		interval_window=interval_window,
		blur_people=blur_people,
	)

	cleanup_temp_directory(temp_directory)

	return video_path
