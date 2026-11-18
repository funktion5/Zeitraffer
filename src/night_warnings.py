"""Collect what the night needs Julius for, for the warnings banner of the web UI.

Runs as the last step of the 02:00 cron line, after the videos, the upload and the flagger, and
writes state/web-jobs/warnings.json. Only problems someone has to act on become a message; routine
warnings stay in the logs. The page reads the file and adds its own live checks. See the design
2026-11-18-warning-banner-design.md in docs/plans.

	.venv/bin/python3 -m src.night_warnings
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import PROJECT_ROOT, load_config
from src.logger import logger
from src.web_state import WEB_STATE_ROOT, write_web_json

WARNINGS_PATH = WEB_STATE_ROOT / "warnings.json"

RUN_FOLDER = re.compile(r"\d{8}-\d{6}")
UNREADABLE = re.compile(r"WARNING: (\d+) image names cannot be read")
# The wrapper ends its reasons with "(see <main.out>)", a path the banner does not need.
SEE_SUFFIX = re.compile(r";?\s*\(see [^)]*\)\s*$")

HINT_NOT_STARTED = "Sperre belegt oder Startfehler; Handbuch „Heute Nacht lief nichts“"
HINT_INTERRUPTED = (
	"Lauf von Hand wiederholen; Handbuch „Lauf wurde nach einem Neustart nicht wiederholt“"
)
HINT_RUN_FAILED = "Bericht des Nachtlaufs lesen"
HINT_CAMERA_FAILED = "Ursache im Bericht beheben, Kamera nachholen"
HINT_STORAGE_BOX = "Handbuch „Kamera-Speicher nicht erreichbar“"
HINT_UNREADABLE = "Neue Schreibweise? Handbuch „Unlesbare Dateinamen“"


def message(camera: str | None, text: str, hint: str) -> dict:
	return {"camera": camera, "text": text, "hint": hint}


def reason(text: str) -> str:
	return SEE_SUFFIX.sub("", text).strip().rstrip(";").strip()


# The newest run folder, whatever night it belongs to; None without any.
def newest_run(nightly_root: Path) -> Path | None:
	if not nightly_root.is_dir():
		return None

	runs = sorted(
		folder
		for folder in nightly_root.iterdir()
		if folder.is_dir() and RUN_FOLDER.fullmatch(folder.name)
	)

	return runs[-1] if runs else None


def read_text(path: Path) -> str:
	try:
		return path.read_text(encoding="utf-8", errors="replace")

	except OSError:
		return ""


# The report of this night's run, read by camera block ("== <camera>" starts one).
def report_messages(report: str, interrupted: bool) -> list[dict]:
	messages = []
	camera = None

	for line in report.splitlines():
		stripped = line.strip()

		if line.startswith("== "):
			camera = line[3:].strip()

		elif line.startswith(("FAILED (run): ", "FATAL: ")):
			text = f"Nachtlauf fehlgeschlagen: {reason(line.split(': ', 1)[1])}"
			messages.append(message(None, text, HINT_RUN_FAILED))

		elif line.startswith("STOPPED"):
			interrupted = True

		elif stripped.startswith("FAILED: ") and camera is not None:
			text = f"Fehlgeschlagen: {reason(stripped[8:])}"
			messages.append(message(camera, text, HINT_CAMERA_FAILED))

		elif (match := UNREADABLE.fullmatch(stripped)) and camera is not None:
			messages.append(message(camera, f"{match[1]} Bildnamen nicht lesbar", HINT_UNREADABLE))

	if interrupted:
		# One line for the whole cut-short night; its "FAILED (run)" says the same.
		messages = [m for m in messages if not m["text"].startswith("Nachtlauf fehlgeschlagen")]
		messages.insert(0, message(None, "Nachtlauf unterbrochen", HINT_INTERRUPTED))

	return messages


def collect(now: datetime, project_root: Path) -> dict:
	run = newest_run(project_root / "logs" / "nightly")
	night = {
		"date": now.date().isoformat(),
		"run": None,
		"started": None,
		"finished": now.isoformat(),
	}

	# A folder of an earlier night means the wrapper stopped before making tonight's (run lock held,
	# no camera list): its lines are old and must not come back.
	if run is None or run.name[:8] != now.strftime("%Y%m%d"):
		not_started = message(None, "Nachtlauf nicht gestartet", HINT_NOT_STARTED)

		return {"night": night, "messages": [not_started]}

	started = datetime.strptime(run.name, "%Y%m%d-%H%M%S").replace(tzinfo=now.tzinfo)
	night["run"] = run.name
	night["started"] = started.isoformat()

	# Only the automatic production run sets the marker; still there now, the run never finished.
	interrupted = (project_root / "state" / "run-in-progress").exists()
	messages = report_messages(read_text(run / "report.txt"), interrupted)

	if "Failed to access camera storage" in read_text(run / "main.out"):
		messages.append(message(None, "Storage Box nicht erreichbar", HINT_STORAGE_BOX))

	return {"night": night, "messages": messages}


def main(now: datetime | None = None) -> int:
	config = load_config()
	now = now or datetime.now(ZoneInfo(config["location"]["timezone"]))
	result = collect(now, PROJECT_ROOT)

	try:
		write_web_json(WARNINGS_PATH, result)

	except OSError as error:
		logger.error(f"Could not write the warnings for the web UI: {error}")
		return 1

	logger.info(f"Night warnings: {len(result['messages'])} messages")

	return 0


if __name__ == "__main__":
	sys.exit(main())
