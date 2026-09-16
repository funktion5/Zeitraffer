from datetime import date
from pathlib import Path
import shutil
import subprocess


TEMP_ROOT = Path("temp")
VIDEO_ROOT = Path("videos")
VIDEO_FRAMERATE = 10


# Creates a clean temporary working directory for a camera and date.
def create_temp_directory(camera: str, target_date: date) -> Path:
    temp_directory = TEMP_ROOT / camera / target_date.isoformat()

    if temp_directory.exists():
        shutil.rmtree(temp_directory)

    temp_directory.mkdir(parents=True)

    return temp_directory


# Copies selected images locally and renames them as sequential FFmpeg frames.
def copy_images_to_temp(images: list[Path], temp_directory: Path) -> list[Path]:
    copied_images = []

    for index, image in enumerate(images, start=1):
        destination = temp_directory / f"frame_{index:06d}.jpg"

        shutil.copy2(image, destination)
        copied_images.append(destination)

    return copied_images    


# Creates a daily MP4 timelapse from the prepared temporary frames.
def create_video(
    camera: str,
    target_date: date,
    temp_directory: Path,
    
) -> Path:

    output_directory = VIDEO_ROOT / camera / "daily"
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / f"{target_date.isoformat()}.mp4"

    command = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(VIDEO_FRAMERATE),
        "-i",
        str(temp_directory / "frame_%06d.jpg"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    subprocess.run(command, check=True)

    return output_path


# Removes the temporary working directory after successful processing.
def cleanup_temp_directory(temp_directory: Path) -> None:
    if temp_directory.exists():
        shutil.rmtree(temp_directory)


# Creates a complete timelapse from selected images and cleans up temporary files.
def create_timelapse(
	camera: str,
	target_date: date,
	images: list[Path],
) -> Path:
	temp_directory = create_temp_directory(camera, target_date)

	copy_images_to_temp(images, temp_directory)

	video_path = create_video(
		camera=camera,
		target_date=target_date,
		temp_directory=temp_directory,
	)

	cleanup_temp_directory(temp_directory)

	return video_path