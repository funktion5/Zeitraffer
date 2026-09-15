import re
from datetime import datetime
from pathlib import Path


CAMERA_ROOT = Path("/mnt/cameras")

def get_cameras():
    return sorted(
        path.name
        for path in CAMERA_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def find_images_for_date(camera: str, target_date):
    camera_path = CAMERA_ROOT / camera

    date_patterns = (
        target_date.strftime("%Y%m%d"),
        target_date.strftime("%y%m%d"),
        target_date.strftime("%y-%m-%d"),
    )

    images = set()

    for date_pattern in date_patterns:
        images.update(camera_path.glob(f"*{date_pattern}*.jpg"))

    return sorted(images)

def extract_time(filename: str):
    time_patterns = (
    r"^[A-Za-z]\d{6}(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\d{2}\.jpg$",
    r"_\d{8}(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.jpg$",
    r"_\d{6}(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\d{2}\.jpg$",
    r"_\d{6}(?P<hour>\d{2})(?P<minute>\d{2})\.jpg$",
    r"_(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})-\d{2}\.jpg$",
    r"_\d{6}_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})\.jpg$",
    r"T(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
)

    for pattern in time_patterns:
        match = re.search(pattern, filename)

        if match:
            hour = int(match.group("hour"))
            minute = int(match.group("minute"))
            second = int(match.groupdict().get("second") or 0)

            if hour > 23 or minute > 59 or second > 59:
                continue

            return hour, minute, second

    return None
def find_images(
    camera: str,
    target_date,
    sunrise: datetime,
    sunset: datetime,
):
    daily_images = find_images_for_date(camera, target_date)
    selected_images = []

    for image_path in daily_images:
        image_time = extract_time(image_path.name)

        if image_time is None:
            continue

        hour, minute, second = image_time

        timestamp = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            second,
            tzinfo=sunrise.tzinfo,
        )

        if sunrise <= timestamp <= sunset:
            selected_images.append(image_path)

    return selected_images
