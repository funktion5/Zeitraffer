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
		"run_isolated_worker",
		lambda **kwargs: image_range,
	)

	with caplog.at_level(
		logging.WARNING,
		logger="timelapse",
	):
		diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert "No recognized image files available." in caplog.text


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
		"run_isolated_worker",
		lambda **kwargs: image_range,
	)

	with caplog.at_level(
		logging.WARNING,
		logger="timelapse",
	):
		diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert "No recognized image files available." in caplog.text

	assert "100 files use an unsupported filename format." in caplog.text


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
		"run_isolated_worker",
		lambda **kwargs: image_range,
	)

	with caplog.at_level(
		logging.WARNING,
		logger="timelapse",
	):
		diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert "Available image range: 2023-02-12 - 2025-10-09" in caplog.text


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
		"run_isolated_worker",
		lambda **kwargs: image_range,
	)

	with caplog.at_level(
		logging.WARNING,
		logger="timelapse",
	):
		diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert "Available image range: 2024-01-01 - 2026-09-16" in caplog.text

	assert "100 files use an unsupported filename format." in caplog.text


# The lookup must run through the shared stall-timeout supervisor.
def test_missing_images_diagnostic_uses_shared_worker_supervisor(
	monkeypatch,
):
	worker_calls = []

	def fake_run_isolated_worker(**kwargs):
		worker_calls.append(kwargs)

		return ImageRange(
			earliest_date=None,
			latest_date=None,
			total_files=0,
			recognized_files=0,
			unrecognized_files=0,
		)

	monkeypatch.setattr(diagnostics_module, "run_isolated_worker", fake_run_isolated_worker)

	diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert worker_calls == [
		{
			"camera": "Test-Camera",
			"target": diagnostics_module.get_image_range,
			"kwargs": {"camera": "Test-Camera"},
			"stall_timeout_seconds": diagnostics_module.IMAGE_RANGE_STALL_TIMEOUT_SECONDS,
			"operation_name": "Image range diagnostic",
		}
	]


def test_missing_images_diagnostic_logs_timeout(
	monkeypatch,
	caplog,
):
	def stalled(**kwargs):
		raise TimeoutError("Image range diagnostic stalled for camera: Test-Camera")

	monkeypatch.setattr(diagnostics_module, "run_isolated_worker", stalled)

	with caplog.at_level(
		logging.WARNING,
		logger="timelapse",
	):
		diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert (
		"Image range diagnostic timed out for Test-Camera after 10 seconds without progress."
		in caplog.text
	)


# A crashed or failing lookup is only logged; the daily job must continue.
def test_missing_images_diagnostic_logs_worker_failure(
	monkeypatch,
	caplog,
):
	def crashed(**kwargs):
		raise RuntimeError("Image range diagnostic worker exited unexpectedly")

	monkeypatch.setattr(diagnostics_module, "run_isolated_worker", crashed)

	with caplog.at_level(
		logging.WARNING,
		logger="timelapse",
	):
		diagnostics_module.log_missing_images_diagnostic("Test-Camera")

	assert "Could not determine available image range for Test-Camera" in caplog.text
