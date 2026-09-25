from argparse import Namespace
from datetime import date
import sys

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
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}

DAILY_FRAMERATE = TEST_CONFIG["timelapse"]["daily_framerate"]
MONTHLY_FRAMERATE = TEST_CONFIG["timelapse"]["monthly_framerate"]
YEARLY_FRAMERATE = TEST_CONFIG["timelapse"]["yearly_framerate"]


def make_arguments(
	date_value: date | None = None,
	cameras: list[str] | None = None,
	jobs: list[str] | None = None,
	target_date: date | None = None,
	daylight_buffer_minutes: int | None = None,
) -> Namespace:
	return Namespace(
		date=date_value,
		cameras=cameras,
		jobs=jobs,
		target_date=target_date,
		daylight_buffer_minutes=daylight_buffer_minutes,
	)


def patch_common_runtime(
	monkeypatch,
	arguments: Namespace,
	config: dict | None = None,
	cameras: list[str] | None = None,
) -> tuple[list[str], list[dict]]:
	if config is None:
		config = TEST_CONFIG

	if cameras is None:
		cameras = [
			"Camera-A",
			"Camera-B",
		]

	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: arguments,
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: config,
	)

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		lambda: cameras,
	)

	configured_log_types: list[str] = []

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: configured_log_types.append(log_type),
	)

	cleanup_calls: list[dict] = []

	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: cleanup_calls.append(kwargs),
	)

	return (
		configured_log_types,
		cleanup_calls,
	)


def patch_automatic_jobs(
	monkeypatch,
) -> list[tuple[str, dict]]:
	job_calls: list[tuple[str, dict]] = []

	def fake_run_daily_job(
		**kwargs,
	):
		job_calls.append(
			(
				"daily",
				kwargs,
			)
		)

	def fake_run_weekly_job(
		**kwargs,
	):
		job_calls.append(
			(
				"weekly",
				kwargs,
			)
		)

	def fake_run_monthly_job(
		**kwargs,
	):
		job_calls.append(
			(
				"monthly",
				kwargs,
			)
		)

	def fake_run_yearly_job(
		**kwargs,
	):
		job_calls.append(
			(
				"yearly",
				kwargs,
			)
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

	return job_calls


# Parse multiple automatic jobs and an explicit target date.
def test_parse_arguments_accepts_jobs_and_target_date(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		[
			"main.py",
			"--jobs",
			"daily",
			"yearly",
			"--target-date",
			"2026-09-15",
		],
	)

	args = main_module.parse_arguments()

	assert args.date is None
	assert args.cameras is None
	assert args.jobs == [
		"daily",
		"yearly",
	]
	assert args.target_date == date(
		2026,
		9,
		15,
	)


# Parse a manual date and optional camera selection.
def test_parse_arguments_accepts_manual_date_and_cameras(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		[
			"main.py",
			"--date",
			"2026-09-15",
			"--cameras",
			"Camera-B",
			"Camera-A",
		],
	)

	args = main_module.parse_arguments()

	assert args.date == date(
		2026,
		9,
		15,
	)
	assert args.cameras == [
		"Camera-B",
		"Camera-A",
	]
	assert args.jobs is None
	assert args.target_date is None


# Parse a historical Weekly target date and its single camera.
def test_parse_arguments_accepts_historical_weekly_camera(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		[
			"main.py",
			"--jobs",
			"weekly",
			"--target-date",
			"2026-09-16",
			"--cameras",
			"Scheunenviertel",
		],
	)

	args = main_module.parse_arguments()

	assert args.jobs == ["weekly"]
	assert args.target_date == date(2026, 9, 16)
	assert args.cameras == ["Scheunenviertel"]


# Argparse must reject unknown automatic job names.
def test_parse_arguments_rejects_unknown_job(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		[
			"main.py",
			"--jobs",
			"invalid-job",
		],
	)

	with pytest.raises(SystemExit):
		main_module.parse_arguments()


# The daylight buffer override must accept exactly the three allowed values.
def test_parse_arguments_accepts_daylight_buffer_minutes(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		[
			"main.py",
			"--daylight-buffer-minutes",
			"60",
		],
	)

	args = main_module.parse_arguments()

	assert args.daylight_buffer_minutes == 60


# Any value outside 30/60/90 must be rejected before jobs ever run.
def test_parse_arguments_rejects_invalid_daylight_buffer_minutes(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		[
			"main.py",
			"--daylight-buffer-minutes",
			"45",
		],
	)

	with pytest.raises(SystemExit):
		main_module.parse_arguments()


# Without the flag, the config's own configured buffer must be left alone.
def test_parse_arguments_defaults_daylight_buffer_minutes_to_none(
	monkeypatch,
):
	monkeypatch.setattr(
		sys,
		"argv",
		["main.py"],
	)

	args = main_module.parse_arguments()

	assert args.daylight_buffer_minutes is None


# Without --jobs, main must preserve the complete automatic workflow.
def test_main_runs_all_automatic_jobs_by_default(
	monkeypatch,
):
	cameras = [
		"Camera-A",
		"Camera-B",
	]

	configured_log_types, cleanup_calls = patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(),
		cameras=cameras,
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert configured_log_types == [
		"daily",
		"weekly",
		"monthly",
		"yearly",
	]

	assert cleanup_calls == [
		{
			"retention_days": 30,
		}
	]

	assert job_calls == [
		(
			"daily",
			{
				"config": TEST_CONFIG,
				"cameras": cameras,
				"framerate": DAILY_FRAMERATE,
				"target_date": None,
				"manual_run": False,
			},
		),
		(
			"weekly",
			{
				"config": TEST_CONFIG,
				"cameras": cameras,
				"target_date": None,
				"manual_run": False,
			},
		),
		(
			"monthly",
			{
				"config": TEST_CONFIG,
				"cameras": cameras,
				"framerate": MONTHLY_FRAMERATE,
				"target_date": None,
				"manual_run": False,
			},
		),
		(
			"yearly",
			{
				"config": TEST_CONFIG,
				"cameras": cameras,
				"framerate": YEARLY_FRAMERATE,
				"target_date": None,
				"manual_run": False,
			},
		),
	]


# Main must run only explicitly selected automatic jobs.
def test_main_runs_only_selected_jobs(
	monkeypatch,
):
	configured_log_types, _ = patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"weekly",
				"yearly",
			],
		),
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert [job for job, _ in job_calls] == [
		"weekly",
		"yearly",
	]

	assert configured_log_types == [
		"weekly",
		"yearly",
	]


# Selected jobs must always execute in the defined workflow order.
def test_main_keeps_defined_job_order(
	monkeypatch,
):
	configured_log_types, _ = patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"yearly",
				"daily",
				"monthly",
			],
		),
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert [job for job, _ in job_calls] == [
		"daily",
		"monthly",
		"yearly",
	]

	assert configured_log_types == [
		"daily",
		"monthly",
		"yearly",
	]


# Duplicate job arguments must not execute a job more than once.
def test_main_deduplicates_selected_jobs(
	monkeypatch,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"daily",
				"daily",
				"yearly",
				"yearly",
			],
		),
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert [job for job, _ in job_calls] == [
		"daily",
		"yearly",
	]


# The buffer override must reach jobs without mutating the caller's config
# dict (load_config's own return value must stay untouched for other callers).
def test_main_applies_daylight_buffer_override_without_mutating_config(
	monkeypatch,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=["daily"],
			daylight_buffer_minutes=60,
		),
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert job_calls[0][1]["config"]["daylight_buffer_minutes"] == 60
	assert TEST_CONFIG["daylight_buffer_minutes"] == 90


# Explicit target dates must reach every selected automatic job.
def test_main_passes_target_date_to_selected_jobs(
	monkeypatch,
):
	target_date = date(
		2026,
		9,
		15,
	)

	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"daily",
				"monthly",
				"yearly",
			],
			target_date=target_date,
		),
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert job_calls == [
		(
			"daily",
			{
				"config": TEST_CONFIG,
				"cameras": [
					"Camera-A",
					"Camera-B",
				],
				"framerate": DAILY_FRAMERATE,
				"target_date": target_date,
				"manual_run": True,
			},
		),
		(
			"monthly",
			{
				"config": TEST_CONFIG,
				"cameras": [
					"Camera-A",
					"Camera-B",
				],
				"framerate": MONTHLY_FRAMERATE,
				"target_date": target_date,
				"manual_run": True,
			},
		),
		(
			"yearly",
			{
				"config": TEST_CONFIG,
				"cameras": [
					"Camera-A",
					"Camera-B",
				],
				"framerate": YEARLY_FRAMERATE,
				"target_date": target_date,
				"manual_run": True,
			},
		),
	]


# --date must run the historical Daily path as a backward-compatible alias.
def test_main_routes_date_alias_to_historical_daily(
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

	configured_log_types, _ = patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			date_value=target_date,
			cameras=requested_cameras,
		),
		cameras=cameras,
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert configured_log_types == [
		"daily",
	]

	assert job_calls == [
		(
			"daily",
			{
				"config": TEST_CONFIG,
				"cameras": requested_cameras,
				"framerate": DAILY_FRAMERATE,
				"target_date": target_date,
				"manual_run": True,
			},
		)
	]


# Camera filters without a manual or historical date must be rejected.
def test_main_rejects_camera_filter_without_date(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			cameras=[
				"Camera-A",
			],
		),
	)

	with pytest.raises(
		ValueError,
		match="--cameras can only be used with --date or --target-date.",
	):
		main_module.main()


# Manual mode and automatic job selection must not be mixed.
def test_main_rejects_manual_date_with_jobs(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			date_value=date(
				2026,
				9,
				15,
			),
			jobs=[
				"daily",
			],
		),
	)

	with pytest.raises(
		ValueError,
		match="--date cannot be used together with --jobs.",
	):
		main_module.main()


# Manual mode and an automatic target date must not be mixed.
def test_main_rejects_manual_date_with_target_date(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			date_value=date(
				2026,
				9,
				15,
			),
			target_date=date(
				2026,
				9,
				14,
			),
		),
	)

	with pytest.raises(
		ValueError,
		match="--date cannot be used together with --target-date.",
	):
		main_module.main()


# An automatic target date has no meaning without selected jobs.
def test_main_rejects_target_date_without_jobs(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			target_date=date(
				2026,
				9,
				15,
			),
		),
	)

	with pytest.raises(
		ValueError,
		match="--target-date can only be used together with --jobs.",
	):
		main_module.main()


# Camera filters must not apply to current automatic selected jobs.
def test_main_rejects_camera_filter_for_automatic_jobs(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			cameras=[
				"Camera-A",
			],
			jobs=[
				"daily",
			],
		),
	)

	with pytest.raises(
		ValueError,
		match="--cameras can only be used with --date or --target-date.",
	):
		main_module.main()


# A historical Weekly must identify exactly one camera.
@pytest.mark.parametrize(
	"requested_cameras",
	[
		None,
		[],
		["Camera-A", "Camera-B"],
	],
)
def test_main_requires_one_camera_for_historical_weekly(
	monkeypatch,
	requested_cameras,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			cameras=requested_cameras,
			jobs=["weekly"],
			target_date=date(2026, 9, 16),
		),
	)

	with pytest.raises(
		ValueError,
		match="Historical Weekly requires exactly one camera with --cameras.",
	):
		main_module.main()


# A historical Weekly cannot be combined with another selected job.
def test_main_requires_historical_weekly_to_be_selected_alone(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			cameras=["Camera-A"],
			jobs=["daily", "weekly"],
			target_date=date(2026, 9, 16),
		),
	)

	with pytest.raises(
		ValueError,
		match="Historical Weekly must be selected as the only job.",
	):
		main_module.main()


# Historical jobs must process only their requested cameras.
def test_main_filters_historical_jobs_to_requested_cameras(
	monkeypatch,
):
	target_date = date(2026, 9, 16)

	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			cameras=["Camera-C", "Camera-A"],
			jobs=["daily", "monthly", "yearly"],
			target_date=target_date,
		),
		cameras=["Camera-A", "Camera-B", "Camera-C"],
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert [kwargs["cameras"] for _, kwargs in job_calls] == [
		["Camera-C", "Camera-A"],
		["Camera-C", "Camera-A"],
		["Camera-C", "Camera-A"],
	]


# A historical Weekly must process only its requested camera.
def test_main_filters_historical_weekly_to_requested_camera(
	monkeypatch,
):
	target_date = date(2026, 9, 16)

	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			cameras=["Camera-B"],
			jobs=["weekly"],
			target_date=target_date,
		),
		cameras=["Camera-A", "Camera-B", "Camera-C"],
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert job_calls == [
		(
			"weekly",
			{
				"config": TEST_CONFIG,
				"cameras": ["Camera-B"],
				"target_date": target_date,
				"manual_run": True,
			},
		),
	]


# An unavailable historical Weekly camera must fail without running another camera.
def test_main_rejects_unknown_historical_weekly_camera(
	monkeypatch,
	caplog,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			cameras=["Unknown-Camera"],
			jobs=["weekly"],
			target_date=date(2026, 9, 16),
		),
		cameras=["Camera-A", "Camera-B"],
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	with pytest.raises(
		ValueError,
		match="Requested cameras not found: Unknown-Camera",
	):
		main_module.main()

	assert job_calls == []
	assert "Requested cameras not found: Unknown-Camera" in caplog.text


# Any unavailable historical camera must reject the complete request.
def test_main_rejects_unknown_camera_for_historical_jobs(
	monkeypatch,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			cameras=["Camera-A", "Unknown-Camera"],
			jobs=["monthly", "yearly"],
			target_date=date(2026, 9, 16),
		),
		cameras=["Camera-A", "Camera-B"],
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	with pytest.raises(
		ValueError,
		match="Requested cameras not found: Unknown-Camera",
	):
		main_module.main()

	assert job_calls == []


# Failure to access complete camera storage must stop the run.
def test_main_logs_and_raises_camera_storage_error(
	monkeypatch,
):
	monkeypatch.setattr(
		main_module,
		"parse_arguments",
		lambda: make_arguments(
			jobs=[
				"yearly",
			],
		),
	)

	monkeypatch.setattr(
		main_module,
		"load_config",
		lambda: TEST_CONFIG,
	)

	configured_log_types = []

	monkeypatch.setattr(
		main_module,
		"configure_file_logging",
		lambda log_type: configured_log_types.append(log_type),
	)

	monkeypatch.setattr(
		main_module,
		"cleanup_old_logs",
		lambda **kwargs: None,
	)

	def fake_get_cameras():
		raise OSError("Camera storage unavailable")

	monkeypatch.setattr(
		main_module,
		"get_cameras",
		fake_get_cameras,
	)

	logged_errors = []

	monkeypatch.setattr(
		main_module.logger,
		"exception",
		lambda message: logged_errors.append(message),
	)

	with pytest.raises(
		OSError,
		match="Camera storage unavailable",
	):
		main_module.main()

	assert configured_log_types == [
		"yearly",
	]

	assert logged_errors == [
		"Failed to access camera storage.",
	]


# Globally ignored cameras must be filtered before automatic jobs start.
def test_main_filters_ignored_cameras_for_automatic_jobs(
	monkeypatch,
):
	config = {
		**TEST_CONFIG,
		"ignored_cameras": [
			"Camera-B",
		],
	}

	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"daily",
				"yearly",
			],
		),
		config=config,
		cameras=[
			"Camera-A",
			"Camera-B",
			"Camera-C",
		],
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	main_module.main()

	for _, kwargs in job_calls:
		assert kwargs["cameras"] == [
			"Camera-A",
			"Camera-C",
		]


# A globally ignored camera requested through --date must abort before Daily starts.
def test_main_rejects_ignored_camera_for_date_alias(
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

	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			date_value=target_date,
			cameras=[
				"Camera-B",
				"Camera-C",
			],
		),
		config=config,
		cameras=[
			"Camera-A",
			"Camera-B",
			"Camera-C",
		],
	)

	job_calls = patch_automatic_jobs(monkeypatch)

	with pytest.raises(
		ValueError,
		match="Requested cameras not found: Camera-B",
	):
		main_module.main()

	assert job_calls == []


# Main must pass the configured retention period to log cleanup once.
def test_main_passes_log_retention_to_cleanup(
	monkeypatch,
):
	_, cleanup_calls = patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"monthly",
				"yearly",
			],
		),
		cameras=[],
	)

	patch_automatic_jobs(monkeypatch)

	main_module.main()

	assert cleanup_calls == [
		{
			"retention_days": 30,
		}
	]


def test_main_marks_automatic_production_run_started_and_finished(
	monkeypatch,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(),
	)

	patch_automatic_jobs(monkeypatch)

	state_calls = []

	monkeypatch.setattr(
		main_module,
		"mark_run_started",
		lambda: state_calls.append("started"),
	)

	monkeypatch.setattr(
		main_module,
		"mark_run_finished",
		lambda: state_calls.append("finished"),
	)

	main_module.main()

	assert state_calls == [
		"started",
		"finished",
	]


def test_main_keeps_run_marker_when_automatic_production_run_fails(
	monkeypatch,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(),
	)

	state_calls = []

	monkeypatch.setattr(
		main_module,
		"mark_run_started",
		lambda: state_calls.append("started"),
	)

	monkeypatch.setattr(
		main_module,
		"mark_run_finished",
		lambda: state_calls.append("finished"),
	)

	def fake_run_daily_job(
		**kwargs,
	):
		raise RuntimeError("Daily failed")

	monkeypatch.setattr(
		main_module,
		"run_daily_job",
		fake_run_daily_job,
	)

	with pytest.raises(
		RuntimeError,
		match="Daily failed",
	):
		main_module.main()

	assert state_calls == [
		"started",
	]


def test_main_does_not_mark_selected_job_run(
	monkeypatch,
):
	patch_common_runtime(
		monkeypatch=monkeypatch,
		arguments=make_arguments(
			jobs=[
				"daily",
			],
		),
	)

	patch_automatic_jobs(monkeypatch)

	state_calls = []

	monkeypatch.setattr(
		main_module,
		"mark_run_started",
		lambda: state_calls.append("started"),
	)

	monkeypatch.setattr(
		main_module,
		"mark_run_finished",
		lambda: state_calls.append("finished"),
	)

	main_module.main()

	assert state_calls == []
