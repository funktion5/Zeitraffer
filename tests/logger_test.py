import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import src.logger as logger_module


# Run context must identify the process invocation, execution mode, and cameras.
def test_format_run_context_includes_run_details(
	monkeypatch,
):
	monkeypatch.setattr(
		logger_module,
		"RUN_ID",
		"test-run",
	)

	assert (
		logger_module.format_run_context(
			mode="historical",
			cameras=["Scheunenviertel", "SVG"],
		)
		== "run_id=test-run | mode=historical | cameras=Scheunenviertel,SVG"
	)


# Logger setup must install one INFO console handler on a DEBUG application logger.
def test_setup_logger_configures_console_once(
	monkeypatch,
):
	test_logger = logging.getLogger("timelapse")

	monkeypatch.setattr(
		test_logger,
		"handlers",
		[],
	)

	assert logger_module.setup_logger() is test_logger
	assert logger_module.setup_logger() is test_logger
	assert test_logger.level == logging.DEBUG
	assert len(test_logger.handlers) == 1
	assert type(test_logger.handlers[0]) is logging.StreamHandler
	assert test_logger.handlers[0].level == logging.INFO


# Switching jobs must close the previous file and keep DEBUG file logging.
def test_configure_file_logging_switches_and_closes_file_handler(
	tmp_path,
	monkeypatch,
):
	test_logger = logging.Logger("test-file-logging")
	console_handler = logging.StreamHandler()
	test_logger.addHandler(console_handler)

	monkeypatch.setattr(logger_module, "logger", test_logger)
	monkeypatch.setattr(logger_module, "LOG_ROOT", tmp_path / "logs")
	monkeypatch.delenv("TIMELAPSE_DISABLE_FILE_LOGGING", raising=False)
	monkeypatch.setattr(
		logger_module,
		"get_log_path",
		lambda log_type: tmp_path / "logs" / log_type / "test.log",
	)

	logger_module.configure_file_logging("daily")

	daily_handler = next(
		handler for handler in test_logger.handlers if isinstance(handler, logging.FileHandler)
	)

	assert daily_handler.level == logging.DEBUG

	logger_module.configure_file_logging("weekly")

	weekly_handlers = [
		handler for handler in test_logger.handlers if isinstance(handler, logging.FileHandler)
	]

	assert daily_handler.stream is None
	assert len(weekly_handlers) == 1
	assert weekly_handlers[0].baseFilename.endswith("/logs/weekly/test.log")
	assert console_handler in test_logger.handlers

	weekly_handlers[0].close()


# Tests can explicitly disable all production file logging.
def test_configure_file_logging_honors_test_bypass(
	tmp_path,
	monkeypatch,
):
	test_logger = logging.Logger("test-disabled-file-logging")

	monkeypatch.setattr(logger_module, "logger", test_logger)
	monkeypatch.setattr(logger_module, "LOG_ROOT", tmp_path / "logs")
	monkeypatch.setenv("TIMELAPSE_DISABLE_FILE_LOGGING", "1")

	logger_module.configure_file_logging("daily")

	assert test_logger.handlers == []
	assert not (tmp_path / "logs").exists()


# Log files older than the configured retention period must be removed.
def test_cleanup_old_logs_removes_expired_files(
	tmp_path,
	monkeypatch,
):
	log_root = tmp_path / "logs"

	daily_directory = log_root / "daily"

	daily_directory.mkdir(parents=True)

	expired_log = daily_directory / "2026-08-01.log"

	recent_log = daily_directory / "2026-09-10.log"

	expired_log.write_text(
		"old log",
		encoding="utf-8",
	)

	recent_log.write_text(
		"recent log",
		encoding="utf-8",
	)

	class FakeDateTime:
		@classmethod
		def now(
			cls,
			tz=None,
		):
			return datetime(
				2026,
				9,
				18,
				12,
				0,
				tzinfo=ZoneInfo("Europe/Berlin"),
			)

	monkeypatch.setattr(
		logger_module,
		"LOG_ROOT",
		log_root,
	)

	monkeypatch.setattr(
		logger_module,
		"datetime",
		FakeDateTime,
	)

	logger_module.cleanup_old_logs(retention_days=30)

	assert not expired_log.exists()
	assert recent_log.exists()


# Files outside the application log naming scheme must never be deleted.
def test_cleanup_old_logs_ignores_unknown_filenames(
	tmp_path,
	monkeypatch,
):
	log_root = tmp_path / "logs"

	daily_directory = log_root / "daily"

	daily_directory.mkdir(parents=True)

	unknown_log = daily_directory / "important.log"

	unknown_log.write_text(
		"keep this file",
		encoding="utf-8",
	)

	monkeypatch.setattr(
		logger_module,
		"LOG_ROOT",
		log_root,
	)

	logger_module.cleanup_old_logs(retention_days=30)

	assert unknown_log.exists()
