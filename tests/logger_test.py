from datetime import datetime
from zoneinfo import ZoneInfo

import src.logger as logger_module


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
