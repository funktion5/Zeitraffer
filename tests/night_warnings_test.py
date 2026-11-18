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

		return folder

	def marker(self) -> None:
		(self.root / "state").mkdir(exist_ok=True)
		(self.root / "state" / "run-in-progress").write_text("")


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


def test_main_writes_the_file_also_without_messages(project: Project, monkeypatch) -> None:
	project.run(report=CLEAN_REPORT)
	path = project.root / "state" / "web-jobs" / "warnings.json"
	monkeypatch.setattr(night_warnings, "PROJECT_ROOT", project.root)
	monkeypatch.setattr(night_warnings, "WARNINGS_PATH", path)
	monkeypatch.setattr(
		night_warnings, "load_config", lambda: {"location": {"timezone": "Europe/Berlin"}}
	)

	assert night_warnings.main(now=NOW) == 0

	assert json.loads(path.read_text(encoding="utf-8"))["messages"] == []
