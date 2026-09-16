from datetime import date, datetime
from pathlib import Path
from src.images import (
    ImageRange,
    extract_date, 
    extract_time, 
    find_images, 
    find_images_for_date, 
    get_cameras,
    get_image_range,
    )
from src.solar import get_sun_times
from zoneinfo import ZoneInfo

import src.images as images_module

def test_cameras_with_known_dates():
    # Use known dates with existing images to verify that the date-based
    # image search works across different cameras and filename formats.
    cameras = {
        "BSV-Steinhude": date(2025, 10, 9),
        "Nordufer_tele": date(2025, 4, 19),
        "Nordufer_wide": date(2025, 4, 19),
        "Reolink": date(2025, 10, 24),
        "Wunstorf-Marktplatz": date(2024, 10, 30),
    }

    for camera, target_date in cameras.items():
        images = find_images_for_date(camera, target_date)

        # Verify that the search finds at least one image for every
        # camera on its known test date.
        assert len(images) > 0, (
            f"No images found for camera '{camera}' "
            f"on {target_date}."
        )


def test_extract_time_from_camera_filenames():
    # Real filename examples from the different camera systems.
    # Each filename is mapped to the time expected from extract_time().
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

        # Verify that every supported filename format returns
        # the correct hour, minute and second.
        assert result == expected_time, (
            f"Wrong time extracted from '{filename}': "
            f"expected {expected_time}, got {result}"
        )


def test_extract_date_from_camera_filenames():
	# Real filename examples from the different camera systems.
	test_cases = {
		"20260915T145103.jpg": date(2026, 9, 15),
		"scheunenviertel-26-09-15_14-29-56-39.jpg": date(2026, 9, 15),
		"aw10_26-08-27_15-52-07-75.jpg": date(2026, 8, 27),
		"see-26-09-15_14-44-58-48.jpg": date(2026, 9, 15),
		"bsv_steinhude_2510091630.jpg": date(2025, 10, 9),
        "bsv_steinhude_202410020900.jpg": date(2024, 10, 2),
        "bsv_steinhude_202312181415.jpg": date(2023, 12, 18),
		"image_241030_010043.jpg": date(2024, 10, 30),
		"P23091411034310.jpg": date(2023, 9, 14),
		"T23091315270800.jpg": date(2023, 9, 13),
		"Nordufer_tele_20250419T094017.jpg": date(2025, 4, 19),
		"Nordufer_wide_20250419T100009.jpg": date(2025, 4, 19),
		"sam-Reolink_00_20251024145546.jpg": date(2025, 10, 24),
	}

	for filename, expected_date in test_cases.items():
		result = extract_date(filename)

		assert result == expected_date, (
			f"Wrong date extracted from '{filename}': "
			f"expected {expected_date}, got {result}"
		)


def test_extract_date_rejects_invalid_filenames():
	# Filenames without a supported or valid camera date must be rejected.
	invalid_filenames = [
		"random_image.jpg",
		"image_without_date.jpg",
		"20261340T145103.jpg",
		"scheunenviertel-26-99-99_14-29-56-39.jpg",
		"bsv_steinhude_9999991630.jpg",
		"image_999999_010043.jpg",
	]

	for filename in invalid_filenames:
		assert extract_date(filename) is None     

def test_complete_image_selection():
    # Use known camera/date combinations to test the complete selection
    # workflow: find images, extract timestamps and apply the daylight window.
    cameras = {
        "BSV-Steinhude": date(2025, 10, 9),
        "Nordufer_tele": date(2025, 4, 19),
        "Nordufer_wide": date(2025, 4, 19),
        "Reolink": date(2025, 10, 24),
        "Scheunenviertel": date(2026, 9, 14),
        "Wunstorf-Marktplatz": date(2023, 1, 31),
    }

    for camera, target_date in cameras.items():
        # Calculate the daylight window for the selected date.
        sunrise, sunset = get_sun_times(
            target_date=target_date,
            latitude=52.45,
            longitude=9.38,
            timezone="Europe/Berlin",
        )

        # Run the same image-selection logic used by the application.
        images = find_images(
            camera=camera,
            target_date=target_date,
            sunrise=sunrise,
            sunset=sunset,
            daylight_buffer_minutes=90,
        )

        # Verify that at least one image remains after daylight filtering.
        assert len(images) > 0, (
            f"No daylight images found for camera '{camera}' "
            f"on {target_date}."
        )


def test_get_cameras():
    # Read the available cameras dynamically from the mounted camera storage.
    cameras = get_cameras()

    # Verify that camera discovery returns at least one directory.
    assert len(cameras) > 0

    # Verify that camera names are returned in a predictable sorted order.
    assert cameras == sorted(cameras)

    # Verify that hidden system directories such as .ssh are ignored.
    assert all(not camera.startswith(".") for camera in cameras)
    

def test_get_image_range(tmp_path, monkeypatch):
	camera_root = tmp_path / "cameras"
	camera_directory = camera_root / "Test-Camera"
	camera_directory.mkdir(parents=True)

	# Create supported filenames across different dates.
	(camera_directory / "20260915T145103.jpg").touch()
	(camera_directory / "20260910T120000.jpg").touch()
	(camera_directory / "20260920T180000.jpg").touch()

	# Simulate a new or unsupported camera filename format.
	(camera_directory / "unknown-camera-format.jpg").touch()

	monkeypatch.setattr("src.images.CAMERA_ROOT", camera_root)

	result = get_image_range("Test-Camera")

	assert result.earliest_date == date(2026, 9, 10)
	assert result.latest_date == date(2026, 9, 20)

	assert result.total_files == 4
	assert result.recognized_files == 3
	assert result.unrecognized_files == 1    


def test_get_image_range_with_unknown_format(tmp_path, monkeypatch):
	# Simulate a new camera whose filename format is completely unknown.
	camera_root = tmp_path / "cameras"
	camera_directory = camera_root / "New-Camera"
	camera_directory.mkdir(parents=True)

	(camera_directory / "capture-alpha.jpg").touch()
	(camera_directory / "photo-something.jpg").touch()
	(camera_directory / "new-system-file.jpg").touch()

	monkeypatch.setattr("src.images.CAMERA_ROOT", camera_root)

	result = get_image_range("New-Camera")

	# Files exist, but none of their dates can be safely determined.
	assert result.total_files == 3
	assert result.recognized_files == 0
	assert result.unrecognized_files == 3

	# Never guess a date when the filename format is unsupported.
	assert result.earliest_date is None
	assert result.latest_date is None

def test_find_images_uses_daylight_buffer(monkeypatch):
    
	target_date = date(2026, 9, 16)
	timezone = ZoneInfo("Europe/Berlin")

	sunrise = datetime(2026, 9, 16, 7, 0, tzinfo=timezone)
	sunset = datetime(2026, 9, 16, 19, 0, tzinfo=timezone)
    

	test_images = [
		Path("camera_26-09-16_06-29-00-00.jpg"),
		Path("camera_26-09-16_06-31-00-00.jpg"),
		Path("camera_26-09-16_19-29-00-00.jpg"),
		Path("camera_26-09-16_19-31-00-00.jpg"),
	]

	def fake_find_images_for_date(camera, target_date):
		return test_images

	monkeypatch.setattr(
		images_module,
		"find_images_for_date",
		fake_find_images_for_date,
	)

	result = images_module.find_images(
		camera="Test-Camera",
		target_date=target_date,
		sunrise=sunrise,
		sunset=sunset,
        daylight_buffer_minutes=30
	)

	assert result == [
		Path("camera_26-09-16_06-31-00-00.jpg"),
		Path("camera_26-09-16_19-29-00-00.jpg"),
	]