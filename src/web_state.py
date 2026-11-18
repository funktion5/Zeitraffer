import json
import os
import tempfile
from pathlib import Path

from src.config import PROJECT_ROOT

# The folder the web pages read their state from (cameras.json lives here too). The web server user
# reads it; only the project user writes it.
WEB_STATE_ROOT = PROJECT_ROOT / "state" / "web-jobs"


# A page may read at any moment, so the file is replaced in one step: it holds the old content or
# the new one, never half of it, and a failed write leaves the old file and no temporary file.
def write_web_json(destination: Path, payload: object) -> None:
	created = not destination.parent.exists()
	destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)

	# The umask cuts mkdir's mode down (cron may run with 077); the web server user has to enter it.
	if created:
		destination.parent.chmod(0o755)

	descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")

	try:
		with os.fdopen(descriptor, "w", encoding="utf-8") as file:
			json.dump(payload, file, ensure_ascii=False)
			file.write("\n")

		# mkstemp creates the file private; the web server user has to read it.
		os.chmod(temporary, 0o644)
		os.replace(temporary, destination)

	except BaseException:
		Path(temporary).unlink(missing_ok=True)

		raise
