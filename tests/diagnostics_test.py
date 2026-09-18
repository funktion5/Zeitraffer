import logging
from datetime import date

import src.diagnostics as diagnostics_module
from src.images import ImageRange


def test_missing_images_diagnostic_empty_camera(
    monkeypatch,
    caplog,
):
    image_range = ImageRange(
        earliest_date=None,
        latest_date=None,
        total_files=0,
        recognized_files=0,
        unrecognized_files=0,
    )

    monkeypatch.setattr(
        diagnostics_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="timelapse",
    ):
        diagnostics_module.log_missing_images_diagnostic(
            "Test-Camera"
        )

    assert (
        "No recognized image files available."
        in caplog.text
    )


def test_missing_images_diagnostic_unsupported_format(
    monkeypatch,
    caplog,
):
    image_range = ImageRange(
        earliest_date=None,
        latest_date=None,
        total_files=100,
        recognized_files=0,
        unrecognized_files=100,
    )

    monkeypatch.setattr(
        diagnostics_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="timelapse",
    ):
        diagnostics_module.log_missing_images_diagnostic(
            "Test-Camera"
        )

    assert (
        "No recognized image files available."
        in caplog.text
    )

    assert (
        "100 files use an unsupported filename format."
        in caplog.text
    )


def test_missing_images_diagnostic_available_range(
    monkeypatch,
    caplog,
):
    image_range = ImageRange(
        earliest_date=date(
            2023,
            2,
            12,
        ),
        latest_date=date(
            2025,
            10,
            9,
        ),
        total_files=1000,
        recognized_files=1000,
        unrecognized_files=0,
    )

    monkeypatch.setattr(
        diagnostics_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="timelapse",
    ):
        diagnostics_module.log_missing_images_diagnostic(
            "Test-Camera"
        )

    assert (
        "Available image range: "
        "2023-02-12 - 2025-10-09"
        in caplog.text
    )


def test_missing_images_diagnostic_mixed_formats(
    monkeypatch,
    caplog,
):
    image_range = ImageRange(
        earliest_date=date(
            2024,
            1,
            1,
        ),
        latest_date=date(
            2026,
            9,
            16,
        ),
        total_files=1000,
        recognized_files=900,
        unrecognized_files=100,
    )

    monkeypatch.setattr(
        diagnostics_module,
        "get_image_range",
        lambda camera: image_range,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="timelapse",
    ):
        diagnostics_module.log_missing_images_diagnostic(
            "Test-Camera"
        )

    assert (
        "Available image range: "
        "2024-01-01 - 2026-09-16"
        in caplog.text
    )

    assert (
        "100 files use an unsupported filename format."
        in caplog.text
    )