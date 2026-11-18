import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import src.night_warnings as night_warnings
from src.night_warnings import collect

TIMEZONE = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 18, 3, 15, tzinfo=TIMEZONE)
RUN = "20261118-020005"


class Project:
	"""A project folder with what a night leaves behind."""

	def __init__(self, root: Path) -> None:
		self.root = root

	def run(self, name: str = RUN, report: str = "", main_out: str = "") -> Path:
		folder = self.root / "logs" / "nightly" / name
		folder.mkdir(parents=True)
		(folder / "report.txt").write_text(report, encoding="utf-8")
		(folder / "main.out").write_text(main_out, encoding="utf-8")

		# A fine upload of tonight unless a test sets its own, so only the tested rule speaks.
		if not (self.root / "logs" / "siteground-delivery.log").exists():
			self.upload_log(CLEAN_UPLOAD)

		return folder

	def marker(self) -> None:
		(self.root / "state").mkdir(exist_ok=True)
		(self.root / "state" / "run-in-progress").write_text("")

	def log(self, job: str, text: str, date: str = "2026-11-18") -> None:
		folder = self.root / "logs" / job
		folder.mkdir(parents=True, exist_ok=True)
		(folder / f"{date}.log").write_text(text, encoding="utf-8")

	def upload_log(self, text: str) -> None:
		(self.root / "logs").mkdir(exist_ok=True)
		(self.root / "logs" / "siteground-delivery.log").write_text(text, encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Project:
	return Project(tmp_path)


def messages(project: Project) -> list[dict]:
	return collect(NOW, project.root)["messages"]


def texts(project: Project) -> list[tuple]:
	return [(message["camera"], message["text"]) for message in messages(project)]


CLEAN_REPORT = (
	f"Nightly run {RUN} | preset=medium | box=storagebox\n"
	"== Alpha\n   ok: 4 videos verified\n"
	"== Bravo Cam\n   ok: 3 videos verified\n"
	"Cameras: 2, failed: 0\n"
)


def test_a_clean_night_has_no_messages(project: Project) -> None:
	project.run(report=CLEAN_REPORT)

	result = collect(NOW, project.root)

	assert result["messages"] == []
	assert result["night"] == {
		"date": "2026-11-18",
		"run": RUN,
		"started": "2026-11-18T02:00:05+01:00",
		"finished": NOW.isoformat(),
	}


# The wrapper stopped before making a folder (e.g. the run lock was held): the night before must not
# come back with its own lines.
def test_a_missing_run_folder_gives_night_not_started(project: Project) -> None:
	project.run(name="20261117-020001", report="== Alpha\n   FAILED: old problem (see x)\n")

	result = collect(NOW, project.root)

	assert [(m["camera"], m["text"]) for m in result["messages"]] == [
		(None, "Nachtlauf nicht gestartet")
	]
	assert result["night"]["run"] is None
	assert result["night"]["started"] is None


def test_no_nightly_folder_at_all_gives_night_not_started(project: Project) -> None:
	project.upload_log(CLEAN_UPLOAD)

	assert texts(project) == [(None, "Nachtlauf nicht gestartet")]


def test_failed_camera_lines_are_reported(project: Project) -> None:
	project.run(
		report=(
			"== Alpha\n   ok: 4 videos verified\n"
			"== Bravo Cam\n   FAILED: the log names it as failed; (see /x/main.out)\n"
		)
	)

	assert texts(project) == [("Bravo Cam", "Fehlgeschlagen: the log names it as failed")]
	assert messages(project)[0]["hint"] == "Ursache im Bericht beheben, Kamera nachholen"


def test_run_marker_and_failed_run_give_one_interrupted_message(project: Project) -> None:
	project.run(report="FAILED (run): src.main exited with 137; (see /x/main.out)\n")
	project.marker()

	assert texts(project) == [(None, "Nachtlauf unterbrochen")]


def test_failed_run_alone(project: Project) -> None:
	project.run(report="FAILED (run): expected 4 job summary lines, found 3; (see /x/main.out)\n")

	assert texts(project) == [
		(None, "Nachtlauf fehlgeschlagen: expected 4 job summary lines, found 3")
	]


def test_fatal_and_stopped_lines_count_as_a_failed_or_interrupted_night(project: Project) -> None:
	project.run(report="FATAL: the storage box lists no cameras\n")

	assert texts(project) == [(None, "Nachtlauf fehlgeschlagen: the storage box lists no cameras")]


def test_a_stopped_run_is_interrupted(project: Project) -> None:
	project.run(report="STOPPED by signal (exit 143): the run was cut short\n")

	assert texts(project) == [(None, "Nachtlauf unterbrochen")]


def test_storage_box_unreachable_from_main_out(project: Project) -> None:
	project.run(
		report=CLEAN_REPORT,
		main_out="2026-11-18 02:00:07,000 | ERROR | Failed to access camera storage.\n",
	)

	assert texts(project) == [(None, "Storage Box nicht erreichbar")]


def test_unreadable_names_from_the_report(project: Project) -> None:
	project.run(
		report=(
			"== Strandterrassen\n   ok: 2 videos verified\n"
			"   WARNING: 856 image names cannot be read\n"
			"== Alpha\n   ok: 4 videos verified\n"
		)
	)

	assert texts(project) == [("Strandterrassen", "856 Bildnamen nicht lesbar")]
	assert messages(project)[0]["hint"] == "Neue Schreibweise? Handbuch „Unlesbare Dateinamen“"


NIGHT_MARKER = "=== Nachtlauf 2026-11-18 ===\n"
CLEAN_UPLOAD = (
	NIGHT_MARKER + "[INFO]   Kamera:          Alpha\n"
	"[INFO] Ergebnis: hochgeladen=4 übersprungen=0 fehlgeschlagen=0 gelöscht=4\n"
	"[INFO] Alle Kameras erfolgreich abgeschlossen.\n"
)


# A night whose run and upload went fine; each test below breaks one thing.
def fine_night(project: Project) -> None:
	project.run(report=CLEAN_REPORT)
	project.upload_log(CLEAN_UPLOAD)


def test_flagger_errors_are_reported(project: Project) -> None:
	fine_night(project)
	project.log(
		"flagger",
		"2026-11-18 03:13:05,085 | ERROR | [Strandterrassen] none of 38 images could be read"
		" - nothing written\n"
		"2026-11-18 03:14:00,000 | ERROR | Flagger not started: model file missing: /m.onnx\n"
		"2026-11-18 03:14:01,000 | WARNING | Camera SKM-Mardorf: excluded 3 empty image files\n",
	)

	assert texts(project) == [
		("Strandterrassen", "Flagger: none of 38 images could be read - nothing written"),
		(None, "Flagger: not started: model file missing: /m.onnx"),
	]


# Lines of an earlier run on the same day (a manual flagger run at 01:00) are not this night's.
def test_flagger_lines_before_the_run_are_ignored(project: Project) -> None:
	fine_night(project)
	project.log("flagger", "2026-11-18 01:00:00,000 | ERROR | [Alpha] failed: old\n")

	assert texts(project) == []


def test_blur_gate_from_the_daily_log_only(project: Project) -> None:
	fine_night(project)
	gate = (
		"2026-11-18 02:05:00,000 | WARNING | [SLSV] Blur gate: no confirmed image"
		" - skipping camera.\n"
	)
	project.log("monthly", gate)

	assert texts(project) == []

	project.log("daily", gate)

	assert texts(project) == [("SLSV", "Kein bestätigtes Bild, Tagesvideo ausgelassen")]


def test_missing_model_is_reported_once_per_path(project: Project) -> None:
	fine_night(project)
	present = project.root / "models" / "present.onnx"
	present.parent.mkdir()
	present.write_bytes(b"x")
	missing = project.root / "models" / "missing.onnx"

	result = collect(NOW, project.root, model_paths=[present, missing, missing])

	assert [(m["camera"], m["text"]) for m in result["messages"]] == [
		(None, "Erkennungsmodell fehlt: models/missing.onnx")
	]


def test_upload_failure_counts_cameras(project: Project) -> None:
	project.run(report=CLEAN_REPORT)
	project.upload_log(
		NIGHT_MARKER + "[INFO] Ergebnis: hochgeladen=1 übersprungen=0 fehlgeschlagen=2 gelöscht=0\n"
		"[INFO] Ergebnis: hochgeladen=3 übersprungen=0 fehlgeschlagen=0 gelöscht=0\n"
		"[INFO] Ergebnis: hochgeladen=0 übersprungen=0 fehlgeschlagen=1 gelöscht=0\n"
		"[WARN] Mindestens eine Kamera ist fehlgeschlagen.\n"
	)

	assert texts(project) == [(None, "Upload auf die Website fehlgeschlagen (2 Kameras)")]


def test_upload_missing_login_is_a_failure(project: Project) -> None:
	project.run(report=CLEAN_REPORT)
	project.upload_log(
		NIGHT_MARKER + "[WARN] SITEGROUND_HOST, SITEGROUND_USER und SITEGROUND_PASS müssen"
		" ausgefüllt sein.\n"
	)

	assert texts(project) == [(None, "Upload auf die Website fehlgeschlagen")]


def test_upload_without_marker_did_not_run(project: Project) -> None:
	project.run(report=CLEAN_REPORT)
	project.upload_log(
		"[INFO] Ergebnis: hochgeladen=4 übersprungen=0 fehlgeschlagen=0 gelöscht=4\n"
	)

	assert texts(project) == [(None, "Upload auf die Website lief nicht")]


def test_upload_all_skipped_is_not_a_failure(project: Project) -> None:
	project.run(report=CLEAN_REPORT)
	project.upload_log(
		NIGHT_MARKER + "[INFO] Ergebnis: hochgeladen=0 übersprungen=4 fehlgeschlagen=0 gelöscht=0\n"
	)

	assert texts(project) == []


# Yesterday's failed upload stays yesterday's: only the block after tonight's marker counts.
def test_only_this_nights_upload_block_counts(project: Project) -> None:
	project.run(report=CLEAN_REPORT)
	project.upload_log(
		"=== Nachtlauf 2026-11-17 ===\n"
		"[INFO] Ergebnis: hochgeladen=0 übersprungen=0 fehlgeschlagen=3 gelöscht=0\n" + CLEAN_UPLOAD
	)

	assert texts(project) == []


# Without a run folder the other checks still run, counted from 02:00 of this night.
def test_a_night_that_did_not_start_still_reports_the_upload(project: Project) -> None:
	project.upload_log("")

	assert texts(project) == [
		(None, "Nachtlauf nicht gestartet"),
		(None, "Upload auf die Website lief nicht"),
	]


def test_main_writes_the_file_also_without_messages(project: Project, monkeypatch) -> None:
	fine_night(project)
	path = project.root / "state" / "web-jobs" / "warnings.json"
	monkeypatch.setattr(night_warnings, "PROJECT_ROOT", project.root)
	monkeypatch.setattr(night_warnings, "WARNINGS_PATH", path)
	monkeypatch.setattr(
		night_warnings, "load_config", lambda: {"location": {"timezone": "Europe/Berlin"}}
	)
	# The real model paths depend on the host (Docker has no models/); that rule has its own test.
	monkeypatch.setattr(night_warnings, "configured_model_paths", lambda config, root: [])

	assert night_warnings.main(now=NOW) == 0

	assert json.loads(path.read_text(encoding="utf-8"))["messages"] == []
