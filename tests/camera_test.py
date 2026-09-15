from datetime import date

from src.images import extract_time, find_images, find_images_for_date, get_cameras
from src.solar import get_sun_times



def test_cameras_with_known_dates():
    cameras = {
        "BSV-Steinhude": date(2025, 10, 9),
        "Neuer-Winkel-Steinhude": date(2023, 9, 14),
        "Nordufer_tele": date(2025, 4, 19),
        "Nordufer_wide": date(2025, 4, 19),
        "Reolink": date(2025, 10, 24),
        "Wunstorf-Marktplatz": date(2024, 10, 30),
    }

    for camera, target_date in cameras.items():
        images = find_images_for_date(camera, target_date)

        assert len(images) > 0, (
            f"No images found for camera '{camera}' "
            f"on {target_date}."
        )

def test_extract_time_from_camera_filenames():
    test_cases = {
        "20260915T145103.jpg": (14, 51, 3),
        "scheunenviertel-26-09-15_14-29-56-39.jpg": (14, 29, 56),
        "aw10_26-08-27_15-52-07-75.jpg": (15, 52, 7),
        "see-26-09-15_14-44-58-48.jpg": (14, 44, 58),
        "bsv_steinhude_2510091630.jpg": (16, 30, 0),
        "image_241030_010043.jpg": (1, 0, 43),
        "P23091411034310.jpg": (11, 3, 43),
        "T23091315270800.jpg": (15, 27, 8),
        "Nordufer_tele_20250419T094017.jpg": (9, 40, 17),
        "Nordufer_wide_20250419T100009.jpg": (10, 0, 9),
        "sam-Reolink_00_20251024145546.jpg": (14, 55, 46),
    }

    for filename, expected_time in test_cases.items():
        result = extract_time(filename)

        assert result == expected_time, (
            f"Wrong time extracted from '{filename}': "
            f"expected {expected_time}, got {result}"
        )        

def test_complete_image_selection():
    cameras = {
        "BSV-Steinhude": date(2025, 10, 9),
        "Neuer-Winkel-Steinhude": date(2023, 9, 14),
        "Nordufer_tele": date(2025, 4, 19),
        "Nordufer_wide": date(2025, 4, 19),
        "Reolink": date(2025, 10, 24),
        "Scheunenviertel": date(2026, 9, 14),
        "Wunstorf-Marktplatz": date(2023, 1, 31),
    }

    for camera, target_date in cameras.items():
        sunrise, sunset = get_sun_times(
            target_date=target_date,
            latitude=52.45,
            longitude=9.38,
            timezone="Europe/Berlin",
        )

        images = find_images(
            camera=camera,
            target_date=target_date,
            sunrise=sunrise,
            sunset=sunset,
        )

        assert len(images) > 0, (
            f"No daylight images found for camera '{camera}' "
            f"on {target_date}."
        )        

def test_get_cameras():
    cameras = get_cameras()

    assert len(cameras) > 0
    assert cameras == sorted(cameras)
    assert all(not camera.startswith(".") for camera in cameras)