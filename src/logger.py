import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

LOG_ROOT = Path("logs")
LOG_TIMEZONE = ZoneInfo("Europe/Berlin")

LogType = Literal[
	"daily",
	"manual",
	"weekly",
	"monthly",
	"yearly",
]


def get_log_path(log_type: LogType) -> Path:
	"""Return the log file path for the current job and day."""
	current_date = datetime.now(
		tz=LOG_TIMEZONE,
	).date()

	return LOG_ROOT / log_type / f"{current_date.isoformat()}.log"


# Remove log files whose log date is older than the configured retention period.
def cleanup_old_logs(
	retention_days: int,
) -> None:
	if not LOG_ROOT.exists():
		return

	cutoff_date = datetime.now(tz=LOG_TIMEZONE).date() - timedelta(days=retention_days)

	for log_path in LOG_ROOT.rglob("*.log"):
		try:
			log_date = date.fromisoformat(log_path.stem)

		except ValueError:
			# Ignore files that do not follow the application log naming scheme.
			continue

		if log_date >= cutoff_date:
			continue

		logger.debug(f"Removing expired log file: {log_path}")

		log_path.unlink()


def setup_logger() -> logging.Logger:
	"""Configure the shared application logger."""
	logger = logging.getLogger("timelapse")
	logger.setLevel(logging.DEBUG)

	if logger.handlers:
		return logger

	formatter = logging.Formatter(
		"%(asctime)s | %(levelname)s | %(message)s",
	)

	console_handler = logging.StreamHandler()
	console_handler.setLevel(logging.INFO)
	console_handler.setFormatter(formatter)

	logger.addHandler(console_handler)

	return logger


def configure_file_logging(
	log_type: LogType,
) -> None:
	"""Write future log messages to the selected job log file."""

	# Tests must never write production log files.
	if os.getenv("TIMELAPSE_DISABLE_FILE_LOGGING") == "1":
		return

	# Remove an existing file handler before switching job type.
	for handler in logger.handlers[:]:
		if isinstance(handler, logging.FileHandler):
			logger.removeHandler(handler)
			handler.close()

	log_path = get_log_path(log_type)

	log_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	formatter = logging.Formatter(
		"%(asctime)s | %(levelname)s | %(message)s",
	)

	file_handler = logging.FileHandler(
		log_path,
		encoding="utf-8",
	)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)

	logger.addHandler(file_handler)


logger = setup_logger()
