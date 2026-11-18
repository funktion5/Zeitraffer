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
HINT_FLAGGER = "Handbuch „Flagger startet nicht oder überspringt“"
HINT_BLUR_GATE = "Läuft die Verpixelung? Handbuch „Verpixelung“"
HINT_MODEL = "Handbuch „Modelldatei fehlt“"
HINT_UPLOAD_FAILED = "Upload-Protokoll prüfen; die nächste Nacht lädt erneut hoch"
HINT_UPLOAD_NOT_RUN = "Cron-Zeile prüfen"

LOG_LINE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} \| (\w+) \| (.*)")
CAMERA_PREFIX = re.compile(r"\[([^\]]+)\] (.*)")
BLUR_GATE = re.compile(r"\[([^\]]+)\] Blur gate: no confirmed image - skipping camera\.")
UPLOAD_FAILED_COUNT = re.compile(r"fehlgeschlagen=([1-9]\d*)")
UPLOAD_FAILURE_LINES = (
	"Mindestens eine Kamera ist fehlgeschlagen.",
	"SITEGROUND_HOST, SITEGROUND_USER und SITEGROUND_PASS müssen ausgefüllt sein.",
)
UPLOAD_LOG = Path("logs") / "siteground-delivery.log"
# Without a run folder the night still began with the 02:00 cron line.
NIGHT_START_HOUR = 2


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


# The messages of this night's log of one job: lines from `since` up to `now` only, because a web
# job later the same day writes into the same file.
def log_lines(path: Path, since: datetime, now: datetime) -> list[tuple[str, str]]:
	lines = []

	for line in read_text(path).splitlines():
		match = LOG_LINE.fullmatch(line)

		if match is None:
			continue

		moment = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)

		if since <= moment <= now:
			lines.append((match[2], match[3]))

	return lines


def flagger_messages(path: Path, since: datetime, now: datetime) -> list[dict]:
	messages = []

	# The flagger logs ERROR only for real failures: not started, a camera failed, nothing readable.
	for level, text in log_lines(path, since, now):
		if level != "ERROR":
			continue

		camera_line = CAMERA_PREFIX.fullmatch(text)
		camera, detail = camera_line.groups() if camera_line else (None, text)
		detail = detail.removeprefix("Flagger ")
		messages.append(message(camera, f"Flagger: {detail}", HINT_FLAGGER))

	return messages


# The Daily skips a camera without images before its blur gate, so there this line always means
# images, none of them confirmed. The Monthly/Yearly gate also fires on an empty window.
def blur_gate_messages(path: Path, since: datetime, now: datetime) -> list[dict]:
	return [
		message(match[1], "Kein bestätigtes Bild, Tagesvideo ausgelassen", HINT_BLUR_GATE)
		for _, text in log_lines(path, since, now)
		if (match := BLUR_GATE.fullmatch(text))
	]


def model_messages(model_paths: list[Path], project_root: Path) -> list[dict]:
	messages = []

	for path in dict.fromkeys(model_paths):
		if not path.is_file():
			shown = path.relative_to(project_root) if path.is_relative_to(project_root) else path
			messages.append(message(None, f"Erkennungsmodell fehlt: {shown}", HINT_MODEL))

	return messages


# The upload log has no times, and the web UI's upload writes into it too, so the 02:00 cron line
# writes a marker before the night's upload; this night's block is what follows its last marker.
def upload_messages(path: Path, now: datetime) -> list[dict]:
	lines = read_text(path).splitlines()
	marker = f"=== Nachtlauf {now.date().isoformat()} ==="
	starts = [index for index, line in enumerate(lines) if line.strip() == marker]

	if not starts:
		return [message(None, "Upload auf die Website lief nicht", HINT_UPLOAD_NOT_RUN)]

	block = lines[starts[-1] + 1 :]
	failed_cameras = sum(
		1 for line in block if "Ergebnis:" in line and UPLOAD_FAILED_COUNT.search(line)
	)

	if failed_cameras:
		text = f"Upload auf die Website fehlgeschlagen ({failed_cameras} Kameras)"

	elif any(failure in line for line in block for failure in UPLOAD_FAILURE_LINES):
		text = "Upload auf die Website fehlgeschlagen"

	else:
		return []

	return [message(None, text, HINT_UPLOAD_FAILED)]


# The model files the blur detector and the flagger load, as configured.
def configured_model_paths(config: dict, project_root: Path) -> list[Path]:
	from src.flagger.run import DEFAULT_MODEL

	command = (config.get("privacy") or {}).get("detector_command") or []
	paths = [DEFAULT_MODEL]

	if "--model" in command[:-1]:
		paths.insert(0, project_root / command[command.index("--model") + 1])

	return paths


def collect(now: datetime, project_root: Path, model_paths: list[Path] | None = None) -> dict:
	run = newest_run(project_root / "logs" / "nightly")
	night = {
		"date": now.date().isoformat(),
		"run": None,
		"started": None,
		"finished": now.isoformat(),
	}
	messages = []

	# A folder of an earlier night means the wrapper stopped before making tonight's (run lock held,
	# no camera list): its report lines are old and must not come back.
	if run is None or run.name[:8] != now.strftime("%Y%m%d"):
		messages.append(message(None, "Nachtlauf nicht gestartet", HINT_NOT_STARTED))
		since = now.replace(hour=NIGHT_START_HOUR, minute=0, second=0, microsecond=0)

	else:
		since = datetime.strptime(run.name, "%Y%m%d-%H%M%S").replace(tzinfo=now.tzinfo)
		night["run"] = run.name
		night["started"] = since.isoformat()

		# Only the automatic production run sets the marker; still there now, it never finished.
		interrupted = (project_root / "state" / "run-in-progress").exists()
		messages += report_messages(read_text(run / "report.txt"), interrupted)

		if "Failed to access camera storage" in read_text(run / "main.out"):
			messages.append(message(None, "Storage Box nicht erreichbar", HINT_STORAGE_BOX))

	date = now.date().isoformat()
	messages += flagger_messages(project_root / "logs" / "flagger" / f"{date}.log", since, now)
	messages += blur_gate_messages(project_root / "logs" / "daily" / f"{date}.log", since, now)
	messages += model_messages(model_paths or [], project_root)
	messages += upload_messages(project_root / UPLOAD_LOG, now)

	return {"night": night, "messages": messages}


def main(now: datetime | None = None) -> int:
	config = load_config()
	now = now or datetime.now(ZoneInfo(config["location"]["timezone"]))
	result = collect(now, PROJECT_ROOT, configured_model_paths(config, PROJECT_ROOT))

	try:
		write_web_json(WARNINGS_PATH, result)

	except OSError as error:
		logger.error(f"Could not write the warnings for the web UI: {error}")
		return 1

	logger.info(f"Night warnings: {len(result['messages'])} messages")

	return 0


if __name__ == "__main__":
	sys.exit(main())
