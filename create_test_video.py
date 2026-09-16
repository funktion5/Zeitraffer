from datetime import date

from src.config import load_config
from src.images import find_images
from src.solar import get_sun_times
from src.video import (
    copy_images_to_temp,
    create_temp_directory,
    create_video,
)


camera = "Scheunenviertel"
target_date = date(2026, 9, 14)

config = load_config()
location = config["location"]
daylight_buffer_minutes = config["daylight_buffer_minutes"]

sunrise, sunset = get_sun_times(
    target_date=target_date,
    latitude=location["latitude"],
    longitude=location["longitude"],
    timezone=location["timezone"],
)

# Find the original camera images within the daylight window.
images = find_images(
    camera=camera,
    target_date=target_date,
    sunrise=sunrise,
    sunset=sunset,
    daylight_buffer_minutes=daylight_buffer_minutes,
)

print(f"Found {len(images)} images.")

if not images:
    raise SystemExit("No images found.")

# Create a clean local working directory.
temp_directory = create_temp_directory(camera, target_date)

# Copy the selected images from SSHFS to local storage.
copied_images = copy_images_to_temp(images, temp_directory)

print(f"Copied {len(copied_images)} images to {temp_directory}.")

# Create the timelapse from the local frames.
video_path = create_video(
    camera=camera,
    target_date=target_date,
    temp_directory=temp_directory,
    
)

print(f"Video created: {video_path}")