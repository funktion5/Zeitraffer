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


def test_missing_images_diagnostic_timeout_stops_process(
    monkeypatch,
    caplog,
):
    created_processes = []
    created_queues = []

    class FakeQueue:
        def __init__(self):
            self.closed = False

            created_queues.append(
                self
            )

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(
            self,
            target,
            args,
            daemon,
        ):
            self.target = target
            self.args = args
            self.daemon = daemon

            self.started = False
            self.alive = True
            self.terminated = False
            self.killed = False
            self.join_calls = []

            created_processes.append(
                self
            )

        def start(self):
            self.started = True

        def join(
            self,
            timeout,
        ):
            self.join_calls.append(
                timeout
            )

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True
            self.alive = False

    monkeypatch.setattr(
        diagnostics_module,
        "Queue",
        FakeQueue,
    )

    monkeypatch.setattr(
        diagnostics_module,
        "Process",
        FakeProcess,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="timelapse",
    ):
        diagnostics_module.log_missing_images_diagnostic(
            "Test-Camera"
        )

    process = created_processes[0]
    result_queue = created_queues[0]

    assert process.started is True
    assert process.terminated is True
    assert process.killed is True

    assert process.join_calls == [
        diagnostics_module.IMAGE_RANGE_TIMEOUT_SECONDS,
        diagnostics_module.IMAGE_RANGE_PROCESS_STOP_TIMEOUT_SECONDS,
        diagnostics_module.IMAGE_RANGE_PROCESS_STOP_TIMEOUT_SECONDS,
    ]

    assert result_queue.closed is True

    assert (
        "Image range diagnostic timed out for Test-Camera "
        "after 10 seconds."
        in caplog.text
    )