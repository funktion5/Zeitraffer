import logging
import subprocess
from argparse import Namespace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import src.main as main_module
from src.images import ImageRange


def test_missing_images_diagnostic_empty_camera(monkeypatch, caplog):
    image_range = ImageRange(
        earliest_date=None,
        latest_date=None,
        total_files=0,
        recognized_files=0,
        unrecognized_files=0,
    )

    monkeypatch.setattr(
        main_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(logging.WARNING, logger="timelapse"):
        main_module.log_missing_images_diagnostic("Test-Camera")

    assert "No image files available." in caplog.text

def test_missing_images_diagnostic_unsupported_format(monkeypatch, caplog):
    image_range = ImageRange(
        earliest_date=None,
        latest_date=None,
        total_files=100,
        recognized_files=0,
        unrecognized_files=100,
    )

    monkeypatch.setattr(
        main_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(logging.WARNING, logger="timelapse"):
        main_module.log_missing_images_diagnostic("Test-Camera")

    assert (
        "Image files exist, but their filename format is unsupported."
        in caplog.text
    )
    assert "Unrecognized files: 100" in caplog.text


def test_missing_images_diagnostic_available_range(monkeypatch, caplog):
    image_range = ImageRange(
        earliest_date=date(2023, 2, 12),
        latest_date=date(2025, 10, 9),
        total_files=1000,
        recognized_files=1000,
        unrecognized_files=0,
    )

    monkeypatch.setattr(
        main_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(logging.WARNING, logger="timelapse"):
        main_module.log_missing_images_diagnostic("Test-Camera")

    assert (
        "Available image range: 2023-02-12 - 2025-10-09"
        in caplog.text
    )


def test_missing_images_diagnostic_mixed_formats(monkeypatch, caplog):
    image_range = ImageRange(
        earliest_date=date(2024, 1, 1),
        latest_date=date(2026, 9, 16),
        total_files=1000,
        recognized_files=900,
        unrecognized_files=100,
    )

    monkeypatch.setattr(
        main_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(logging.WARNING, logger="timelapse"):
        main_module.log_missing_images_diagnostic("Test-Camera")

    assert (
        "Available image range: 2024-01-01 - 2026-09-16"
        in caplog.text
    )
    assert (
        "100 files use an unsupported filename format."
        in caplog.text
    )


def test_main_creates_timelapse(monkeypatch):
    target_date = date(2026, 9, 16)

    sunrise = datetime(2026, 9, 16, 7, 0, tzinfo=UTC)
    sunset = datetime(2026, 9, 16, 19, 0, tzinfo=UTC)

    images = [
        Path("image_1.jpg"),
        Path("image_2.jpg"),
    ]

    monkeypatch.setattr(
        main_module,
        "parse_arguments",
        lambda: Namespace(date=target_date),
    )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: {
            "location": {
                "latitude": 52.0,
                "longitude": 9.0,
                "timezone": "Europe/Berlin",
            },
            "daylight_buffer_minutes": 90,
        },
    )

    monkeypatch.setattr(
        main_module,
        "get_cameras",
        lambda: ["Test-Camera"],
    )

    monkeypatch.setattr(
        main_module,
        "get_sun_times",
        lambda **kwargs: (sunrise, sunset),
    )

    monkeypatch.setattr(
        main_module,
        "find_images",
        lambda **kwargs: images,
    )

    create_timelapse_calls = []

    def fake_create_timelapse(camera, target_date, images):
        create_timelapse_calls.append(
            {
                "camera": camera,
                "target_date": target_date,
                "images": images,
            }
        )

        return Path(
            f"videos/{camera}/daily/{target_date.isoformat()}.mp4"
        )

    monkeypatch.setattr(
        main_module,
        "create_timelapse",
        fake_create_timelapse,
    )

    main_module.main()

    assert create_timelapse_calls == [
        {
            "camera": "Test-Camera",
            "target_date": target_date,
            "images": images,
        }
    ]


def test_main_continues_after_camera_video_error(monkeypatch):
    target_date = date(2026, 9, 16)

    sunrise = datetime(
        2026,
        9,
        16,
        7,
        0,
        tzinfo=UTC,
    )
    sunset = datetime(
        2026,
        9,
        16,
        19,
        0,
        tzinfo=UTC,
    )

    images = [Path("image_1.jpg")]

    monkeypatch.setattr(
        main_module,
        "parse_arguments",
        lambda: Namespace(date=target_date),
    )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: {
            "location": {
                "latitude": 52.0,
                "longitude": 9.0,
                "timezone": "Europe/Berlin",
            },
            "daylight_buffer_minutes": 90,
        },
    )

    monkeypatch.setattr(
        main_module,
        "get_cameras",
        lambda: ["Camera-A", "Camera-B"],
    )

    monkeypatch.setattr(
        main_module,
        "get_sun_times",
        lambda **kwargs: (sunrise, sunset),
    )

    monkeypatch.setattr(
        main_module,
        "find_images",
        lambda **kwargs: images,
    )

    processed_cameras = []

    def fake_create_timelapse(camera, target_date, images):
        processed_cameras.append(camera)

        if camera == "Camera-A":
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["ffmpeg"],
            )

        return Path(
            f"videos/{camera}/daily/{target_date.isoformat()}.mp4"
        )

    monkeypatch.setattr(
        main_module,
        "create_timelapse",
        fake_create_timelapse,
    )

    logged_errors = []

    def fake_logger_exception(message):
        logged_errors.append(message)

    monkeypatch.setattr(
        main_module.logger,
        "exception",
        fake_logger_exception,
    )

    main_module.main()

    assert processed_cameras == ["Camera-A", "Camera-B"]

    assert logged_errors == [
        "Failed to process timelapse for camera: Camera-A"
    ]



def test_main_continues_after_image_selection_error(monkeypatch):
    target_date = date(2026, 9, 16)
   

    sunrise = datetime(
        2026,
        9,
        16,
        7,
        0,
        tzinfo=UTC,
    )
    sunset = datetime(
        2026,
        9,
        16,
        19,
        0,
        tzinfo=UTC,
    )

    images = [Path("image_1.jpg")]

    monkeypatch.setattr(
        main_module,
        "parse_arguments",
        lambda: Namespace(date=target_date),
    )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: {
            "location": {
                "latitude": 52.0,
                "longitude": 9.0,
                "timezone": "Europe/Berlin",
            },
            "daylight_buffer_minutes": 90,
        },
    )

    monkeypatch.setattr(
        main_module,
        "get_cameras",
        lambda: ["Camera-A", "Camera-B"],
    )

    monkeypatch.setattr(
        main_module,
        "get_sun_times",
        lambda **kwargs: (sunrise, sunset),
    )

    def fake_find_images(camera, **kwargs):
        if camera == "Camera-A":
            raise OSError("Failed to read camera images")

        return images

    monkeypatch.setattr(
        main_module,
        "find_images",
        fake_find_images,
    )

    processed_cameras = []

    def fake_create_timelapse(camera, target_date, images):
        processed_cameras.append(camera)

        return Path(
            f"videos/{camera}/daily/{target_date.isoformat()}.mp4"
        )

    monkeypatch.setattr(
        main_module,
        "create_timelapse",
        fake_create_timelapse,
    )

    main_module.main()

    assert processed_cameras == ["Camera-B"]


def test_main_logs_and_raises_camera_storage_error(monkeypatch):
    target_date = date(2026, 9, 16)

    monkeypatch.setattr(
        main_module,
        "parse_arguments",
        lambda: Namespace(date=target_date),
    )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: {
            "location": {
                "latitude": 52.0,
                "longitude": 9.0,
                "timezone": "Europe/Berlin",
            },
            "daylight_buffer_minutes": 90,
        },
    )

    def fake_get_cameras():
        raise OSError("Camera storage unavailable")

    monkeypatch.setattr(
        main_module,
        "get_cameras",
        fake_get_cameras,
    )

    logged_errors = []

    def fake_logger_exception(message):
        logged_errors.append(message)

    monkeypatch.setattr(
        main_module.logger,
        "exception",
        fake_logger_exception,
    )

    with pytest.raises(
        OSError,
        match="Camera storage unavailable",
    ):
        main_module.main()

    assert logged_errors == [
        "Failed to access camera storage."
    ]