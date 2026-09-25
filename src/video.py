import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Literal

import psutil

from src.config import load_config
from src.logger import logger

CONFIG = load_config()

FFMPEG_THREADS = CONFIG["timelapse"]["ffmpeg_threads"]

TEMP_ROOT = Path("temp")
VIDEO_ROOT = Path("videos")
FRAMERATE = 10
FFMPEG_ERROR_LOG_LINES = 40


TimelapseType = Literal["daily", "weekly", "monthly", "yearly"]


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
				ffmpeg_cpu = ffmpeg_process.cpu_percent(
					interval=0.2,
				)

				ffmpeg_memory_mb = ffmpeg_process.memory_info().rss / 1024 / 1024

				system_cpu = psutil.cpu_percent()

				system_memory = psutil.virtual_memory().percent

				peak_cpu = max(
					peak_cpu,
					ffmpeg_cpu,
				)

				peak_memory_mb = max(
					peak_memory_mb,
					ffmpeg_memory_mb,
				)

				peak_system_cpu = max(
					peak_system_cpu,
					system_cpu,
				)

				peak_system_memory = max(
					peak_system_memory,
					system_memory,
				)

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


# Copy selected images locally and rename them as sequential FFmpeg frames.
def copy_images_to_temp(
	images: list[Path],
	temp_directory: Path,
) -> list[Path]:
	logger.info(f"Copying {len(images)} images to temporary directory")

	copied_images = []

	for index, image in enumerate(
		images,
		start=1,
	):
		destination = temp_directory / f"frame_{index:06d}.jpg"

		shutil.copy2(
			image,
			destination,
		)

		copied_images.append(destination)

	logger.debug(f"Copied {len(copied_images)} temporary frames")

	return copied_images


# Return the output path for an image-based timelapse video.
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
) -> Path:
	if daylight_buffer_minutes is not None and timelapse_type in ("monthly", "yearly"):
		raise ValueError(f"{timelapse_type} does not use a daylight buffer.")

	if manual_run:
		output_directory = VIDEO_ROOT / camera / "manual-runs" / timelapse_type
		suffix = f"_{daylight_buffer_minutes}min" if daylight_buffer_minutes is not None else ""

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


# Create a video by concatenating existing compatible video files.
def create_concat_video(
	concat_path: Path,
	output_path: Path,
) -> Path:
	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	# Keep the final video untouched until FFmpeg finishes successfully.
	temporary_output = output_path.parent / f".{output_path.stem}.tmp{output_path.suffix}"

	logger.info(f"Creating concat video: {output_path}")

	command = [
		"ffmpeg",
		"-y",
		"-f",
		"concat",
		"-safe",
		"0",
		"-i",
		str(concat_path),
		"-c",
		"copy",
		str(temporary_output),
	]

	logger.debug(f"FFmpeg command: {' '.join(command)}")

	run_ffmpeg(command)

	temporary_output.replace(output_path)

	logger.info(f"Concat video created successfully: {output_path}")

	return output_path


# Create an MP4 timelapse from the prepared temporary frames.
def create_image_timelapse(
	camera: str,
	target_date: date,
	temp_directory: Path,
	timelapse_type: TimelapseType,
	framerate: int,
	manual_run: bool = False,
	daylight_buffer_minutes: int | None = None,
) -> Path:
	output_path = get_video_path(
		camera=camera,
		target_date=target_date,
		timelapse_type=timelapse_type,
		manual_run=manual_run,
		daylight_buffer_minutes=daylight_buffer_minutes,
	)

	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	# Keep an existing working video untouched until FFmpeg succeeds.
	temporary_output = output_path.parent / f".{output_path.stem}.tmp{output_path.suffix}"

	logger.info(f"Creating video: {output_path}")

	command = [
		"ffmpeg",
		"-y",
		"-framerate",
		str(framerate),
		"-i",
		str(temp_directory / "frame_%06d.jpg"),
		"-c:v",
		"libx264",
		"-threads",
		str(FFMPEG_THREADS),
		"-pix_fmt",
		"yuv420p",
		str(temporary_output),
	]

	logger.debug(f"FFmpeg command: {' '.join(command)}")

	run_ffmpeg(command)

	# Replace the final video only after FFmpeg completed successfully.
	temporary_output.replace(output_path)

	logger.info(f"Video created successfully: {output_path}")

	return output_path


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
	framerate: int = FRAMERATE,
	manual_run: bool = False,
	daylight_buffer_minutes: int | None = None,
) -> Path:
	temp_directory = create_temp_directory(
		camera,
		target_date,
	)

	copy_images_to_temp(
		images,
		temp_directory,
	)

	video_path = create_image_timelapse(
		camera=camera,
		target_date=target_date,
		temp_directory=temp_directory,
		timelapse_type=timelapse_type,
		framerate=framerate,
		manual_run=manual_run,
		daylight_buffer_minutes=daylight_buffer_minutes,
	)

	cleanup_temp_directory(temp_directory)

	return video_path
