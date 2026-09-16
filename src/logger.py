import logging

from pathlib import Path


LOG_ROOT = Path("logs")
LOG_PATH = LOG_ROOT / "timelapse.log"


def setup_logger() -> logging.Logger:
	"""Configure and return the application logger."""
	LOG_ROOT.mkdir(parents=True, exist_ok=True)

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

	file_handler = logging.FileHandler(
		LOG_PATH,
		encoding="utf-8",
	)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)

	logger.addHandler(console_handler)
	logger.addHandler(file_handler)

	return logger


logger = setup_logger()