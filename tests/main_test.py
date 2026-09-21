from argparse import Namespace
from datetime import date

import pytest

import src.main as main_module

TEST_CONFIG = {
	"location": {
		"latitude": 52.0,
		"longitude": 9.0,
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"image_scan_stall_timeout_seconds": 10,
	"log_retention_days": 30,
	"ignored_cameras": [],
	"timelapse": {
		"daily_framerate": 10,
		"manual_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}

DAILY_FRAMERATE = TEST_CONFIG[
	"timelapse"
][
	"daily_framerate"
]

MANUAL_FRAMERATE = TEST_CONFIG[
	"timelapse"
][
	"manual_framerate"
]

MONTHLY_FRAMERATE = TEST_CONFIG[
	"timelapse"
][
	"monthly_framerate"
]

YEARLY_FRAMERATE = TEST_CONFIG[
	"timelapse"
][
	"yearly_framerate"
]


# Without a date, main must coordinate all automatic jobs.
def test_main_runs_automatic_job(
	monkeypatch,
):
	cameras = [
		"Camera-A",
		"Camera-B",
	]

	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=None,
			cameras=None,
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: TEST_CONFIG,
	)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		lambda: cameras,
	)

	configured_log_types = []

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: configured_log_types.append(
			log_type
		),
	)

	# Main tests must not remove real application log files.
	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: None,
	)

	daily_calls = []

	def fake_run_daily_job(
		config,
		cameras,
		framerate,
	):
		daily_calls.append(
			{
				"config": config,
				"cameras": cameras,
				"framerate": framerate,
			}
		)

	monkeypatch.setattr(
		main_module,
		"run_daily_job",
		fake_run_daily_job,
	)

	weekly_calls = []

	def fake_run_weekly_job(
		config,
		cameras,
	):
		weekly_calls.append(
			{
				"config": config,
				"cameras": cameras,
			}
		)

	monkeypatch.setattr(
		main_module,
		"run_weekly_job",
		fake_run_weekly_job,
	)

	monthly_calls = []

	def fake_run_monthly_job(
		config,
		cameras,
		framerate,
	):
		monthly_calls.append(
			{
				"config": config,
				"cameras": cameras,
				"framerate": framerate,
			}
		)

	monkeypatch.setattr(
		main_module,
		"run_monthly_job",
		fake_run_monthly_job,
	)

	yearly_calls = []

	def fake_run_yearly_job(
		config,
		cameras,
		framerate,
	):
		yearly_calls.append(
			{
				"config": config,
				"cameras": cameras,
				"framerate": framerate,
			}
		)

	monkeypatch.setattr(
		main_module,
		"run_yearly_job",
		fake_run_yearly_job,
	)

	manual_called = False

	def fake_run_manual_job(
		**kwargs,
	):
		nonlocal manual_called
		manual_called = True

	monkeypatch.setattr(
		main_module,
		"run_manual_job",
		fake_run_manual_job,
	)

	main_module.main()

	assert configured_log_types == [
		"daily",
		"weekly",
		"monthly",
		"yearly",
	]

	assert daily_calls == [
		{
			"config": TEST_CONFIG,
			"cameras": cameras,
			"framerate": DAILY_FRAMERATE,
		}
	]

	assert weekly_calls == [
		{
			"config": TEST_CONFIG,
			"cameras": cameras,
		}
	]

	assert monthly_calls == [
		{
			"config": TEST_CONFIG,
			"cameras": cameras,
			"framerate": MONTHLY_FRAMERATE,
		}
	]

	assert yearly_calls == [
		{
			"config": TEST_CONFIG,
			"cameras": cameras,
			"framerate": YEARLY_FRAMERATE,
		}
	]

	assert manual_called is False


# A supplied date must coordinate a manual job.
def test_main_runs_manual_job(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		16,
	)

	cameras = [
		"Camera-A",
		"Camera-B",
	]

	requested_cameras = [
		"Camera-B",
	]

	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=target_date,
			cameras=requested_cameras,
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: TEST_CONFIG,
	)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		lambda: cameras,
	)

	configured_log_types = []

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: configured_log_types.append(
			log_type
		),
	)

	# Main tests must not remove real application log files.
	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: None,
	)

	manual_calls = []

	def fake_run_manual_job(
		config,
		available_cameras,
		target_date,
		requested_cameras,
		framerate,
	):
		manual_calls.append(
			{
				"config": config,
				"available_cameras": available_cameras,
				"target_date": target_date,
				"requested_cameras": requested_cameras,
				"framerate": framerate,
			}
		)

	monkeypatch.setattr(
		main_module,
		"run_manual_job",
		fake_run_manual_job,
	)

	automatic_jobs_called = []

	def fake_run_daily_job(
		**kwargs,
	):
		automatic_jobs_called.append(
			"daily"
		)

	def fake_run_weekly_job(
		**kwargs,
	):
		automatic_jobs_called.append(
			"weekly"
		)

	def fake_run_monthly_job(
		**kwargs,
	):
		automatic_jobs_called.append(
			"monthly"
		)

	def fake_run_yearly_job(
		**kwargs,
	):
		automatic_jobs_called.append(
			"yearly"
		)

	monkeypatch.setattr(
		main_module,
		"run_daily_job",
		fake_run_daily_job,
	)

	monkeypatch.setattr(
		main_module,
		"run_weekly_job",
		fake_run_weekly_job,
	)

	monkeypatch.setattr(
		main_module,
		"run_monthly_job",
		fake_run_monthly_job,
	)

	monkeypatch.setattr(
		main_module,
		"run_yearly_job",
		fake_run_yearly_job,
	)

	main_module.main()

	assert configured_log_types == [
		"manual"
	]

	assert manual_calls == [
		{
			"config": TEST_CONFIG,
			"available_cameras": cameras,
			"target_date": target_date,
			"requested_cameras": requested_cameras,
			"framerate": MANUAL_FRAMERATE,
		}
	]

	# Manual runs must stay independent from all automatic jobs.
	assert automatic_jobs_called == []


# Camera filters without a manual date must be rejected.
def test_main_rejects_camera_filter_without_date(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=None,
			cameras=[
				"Camera-A"
			],
		),
	)

	with pytest.raises(
		ValueError,
		match=(
			"--cameras can only be used "
			"together with --date."
		),
	):
		main_module.main()


# Failure to access the complete camera storage must stop the job.
def test_main_logs_and_raises_camera_storage_error(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		16,
	)

	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=target_date,
			cameras=None,
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: TEST_CONFIG,
	)

	# Main tests must not remove real application log files.
	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: None,
	)

	def fake_get_cameras():
		raise OSError(
			"Camera storage unavailable"
		)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		fake_get_cameras,
	)

	logged_errors = []

	def fake_logger_exception(
		message,
	):
		logged_errors.append(
			message
		)

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


# Globally ignored cameras must not be passed to Daily jobs.
def test_main_filters_ignored_cameras_for_daily(
	monkeypatch,
):
	config = {
		**TEST_CONFIG,
		"ignored_cameras": [
			"Camera-B",
		],
	}

	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=None,
			cameras=None,
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: config,
	)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		lambda: [
			"Camera-A",
			"Camera-B",
			"Camera-C",
		],
	)

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: None,
	)

	# Main tests must not remove real application log files.
	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: None,
	)

	received_cameras = []

	def fake_run_daily_job(
		config,
		cameras,
		framerate,
	):
		received_cameras.extend(
			cameras
		)

	monkeypatch.setattr(
		main_module,
		"run_daily_job",
		fake_run_daily_job,
	)

	monkeypatch.setattr(
		main_module,
		"run_weekly_job",
		lambda **kwargs: None,
	)

	monkeypatch.setattr(
		main_module,
		"run_monthly_job",
		lambda **kwargs: None,
	)

	monkeypatch.setattr(
		main_module,
		"run_yearly_job",
		lambda **kwargs: None,
	)

	main_module.main()

	assert received_cameras == [
		"Camera-A",
		"Camera-C",
	]


# Globally ignored cameras must stay ignored even when requested manually.
def test_main_filters_ignored_cameras_for_manual(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		16,
	)

	config = {
		**TEST_CONFIG,
		"ignored_cameras": [
			"Camera-B",
		],
	}

	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=target_date,
			cameras=[
				"Camera-B",
				"Camera-C",
			],
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: config,
	)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		lambda: [
			"Camera-A",
			"Camera-B",
			"Camera-C",
		],
	)

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: None,
	)

	# Main tests must not remove real application log files.
	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: None,
	)

	manual_calls = []

	def fake_run_manual_job(
		config,
		available_cameras,
		target_date,
		requested_cameras,
		framerate,
	):
		manual_calls.append(
			{
				"available_cameras": available_cameras,
				"requested_cameras": requested_cameras,
				"framerate": framerate,
			}
		)

	monkeypatch.setattr(
		main_module,
		"run_manual_job",
		fake_run_manual_job,
	)

	main_module.main()

	assert manual_calls == [
		{
			"available_cameras": [
				"Camera-A",
				"Camera-C",
			],
			"requested_cameras": [
				"Camera-B",
				"Camera-C",
			],
			"framerate": MANUAL_FRAMERATE,
		}
	]


# Main must pass the configured retention period to log cleanup.
def test_main_passes_log_retention_to_cleanup(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: Namespace(
			date=None,
			cameras=None,
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: TEST_CONFIG,
	)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		list,
	)

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: None,
	)

	cleanup_calls = []

	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: cleanup_calls.append(
			kwargs
		),
	)

	monkeypatch.setattr(
		main_module,
		"run_daily_job",
		lambda **kwargs: None,
	)

	monkeypatch.setattr(
		main_module,
		"run_weekly_job",
		lambda **kwargs: None,
	)

	monkeypatch.setattr(
		main_module,
		"run_monthly_job",
		lambda **kwargs: None,
	)

	monkeypatch.setattr(
		main_module,
		"run_yearly_job",
		lambda **kwargs: None,
	)

	main_module.main()

	assert cleanup_calls == [
		{
			"retention_days": 30
		}
	]