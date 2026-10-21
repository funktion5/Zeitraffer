import fcntl
import json
import logging
from datetime import date

import cv2
import numpy as np
import pytest
from flagger_fakes import SequenceForward

import src.flagger.run as run

CONFIG = {
	"location": {"latitude": 52.45, "longitude": 9.36, "timezone": "Europe/Berlin"},
	"ignored_cameras": ["Ignored"],
	"flagger": {"cameras": ["Cam"], "retention_days": 14},
}


def forbidden(*args, **kwargs):
	raise AssertionError("must not be called")


class FlagAll:
	def __call__(self, blob):
		return SequenceForward([[(2440, 14, 0.9)]])(blob)


@pytest.fixture
def setup(tmp_path, monkeypatch):
	model = tmp_path / "model.onnx"
	model.write_bytes(b"model")
	monkeypatch.setattr(run, "LOCK_PATH", tmp_path / "state" / "run.lock")
	monkeypatch.setattr(run, "VIDEO_ROOT", tmp_path / "videos")
	monkeypatch.setattr(run, "DEFAULT_MODEL", model)
	monkeypatch.setattr(run, "load_config", lambda: json.loads(json.dumps(CONFIG)))
	monkeypatch.setattr(run, "get_cameras", lambda: ["Cam", "Other", "Ignored"])
	monkeypatch.setattr(run, "make_forward", lambda model_path: SequenceForward([]))
	return tmp_path


def record_calls(monkeypatch, name: str, result=0) -> list:
	calls = []

	def fake(*args, **kwargs):
		calls.append((args, kwargs))
		return result

	monkeypatch.setattr(run, name, fake)
	return calls


def test_empty_camera_list_does_not_scan(setup, monkeypatch, caplog):
	monkeypatch.setattr(run, "load_config", lambda: CONFIG | {"flagger": {"cameras": []}})
	monkeypatch.setattr(run, "make_forward", forbidden)
	monkeypatch.setattr(run, "run_cameras", forbidden)
	cleanup = record_calls(monkeypatch, "cleanup_old_reports", [])

	with caplog.at_level(logging.INFO, logger="timelapse"):
		assert run.main([]) == 0

	assert "no cameras configured" in caplog.text
	# Old reports of cameras that were removed from the list still expire.
	assert len(cleanup) == 1


@pytest.mark.parametrize("cameras", [["Nope"], ["Ignored"], ["Cam", "Nope"]])
def test_unknown_or_ignored_camera_stops_before_reading(setup, monkeypatch, cameras):
	monkeypatch.setattr(run, "make_forward", forbidden)
	monkeypatch.setattr(run, "run_cameras", forbidden)

	assert run.main(["--cameras", *cameras]) == 1


def test_configured_ignored_camera_stops_the_run(setup, monkeypatch):
	monkeypatch.setattr(run, "load_config", lambda: CONFIG | {"flagger": {"cameras": ["Ignored"]}})
	monkeypatch.setattr(run, "run_cameras", forbidden)

	assert run.main([]) == 1


def test_held_lock_skips_the_run(setup, monkeypatch, caplog):
	monkeypatch.setattr(run, "run_cameras", forbidden)
	monkeypatch.setattr(run, "cleanup_old_reports", forbidden)
	run.LOCK_PATH.parent.mkdir(parents=True)

	with run.LOCK_PATH.open("a") as held:
		fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)

		with caplog.at_level(logging.INFO, logger="timelapse"):
			assert run.main([]) == 0

	assert "Skipped" in caplog.text


def test_nightly_mode_runs_cameras_then_cleans_up(setup, monkeypatch):
	runs = record_calls(monkeypatch, "run_cameras", 0)
	cleanup = record_calls(monkeypatch, "cleanup_old_reports", [])

	assert run.main(["--target-date", "2026-10-20"]) == 0

	_, kwargs = runs[0]
	assert kwargs["cameras"] == ["Cam"] and kwargs["target_date"] == date(2026, 10, 20)
	assert kwargs["video_root"] == setup / "videos"
	assert kwargs["detector"].startswith("model-")
	assert str(kwargs["now"].tzinfo) == "Europe/Berlin"
	(root, today, retention), _ = cleanup[0]
	assert (root, retention) == (setup / "videos", 14)
	assert today == kwargs["now"].date()


def test_nightly_mode_defaults_to_yesterday(setup, monkeypatch):
	runs = record_calls(monkeypatch, "run_cameras", 0)
	record_calls(monkeypatch, "cleanup_old_reports", [])
	monkeypatch.setattr(run, "get_latest_completed_date", lambda timezone: date(2026, 10, 1))

	run.main([])

	assert runs[0][1]["target_date"] == date(2026, 10, 1)


def test_failed_camera_gives_exit_1_and_cleanup_still_runs(setup, monkeypatch):
	record_calls(monkeypatch, "run_cameras", 1)
	cleanup = record_calls(monkeypatch, "cleanup_old_reports", [])

	assert run.main([]) == 1
	assert len(cleanup) == 1


def test_missing_model_stops_the_run(setup, monkeypatch, tmp_path):
	monkeypatch.setattr(run, "run_cameras", forbidden)

	assert run.main(["--model", str(tmp_path / "missing.onnx")]) == 1


def test_images_mode_writes_a_report_without_config_cameras_or_cleanup(setup, monkeypatch):
	source = setup / "samples"
	source.mkdir()

	for name in ("A_26-10-20_08-14-58-20.jpg", "B_26-10-20_09-14-58-20.JPG"):
		cv2.imwrite(str(source / name), np.zeros((48, 64, 3), np.uint8))

	(source / "notes.txt").write_text("x", encoding="utf-8")
	out = setup / "out"
	monkeypatch.setattr(run, "get_cameras", forbidden)
	monkeypatch.setattr(run, "cleanup_old_reports", forbidden)
	monkeypatch.setattr(run, "make_forward", lambda model_path: FlagAll())

	code = run.main(["--images", str(source), "--out", str(out), "--target-date", "2026-10-20"])

	folder = out / "adhoc" / "highlights" / "2026-10-20"
	manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
	assert code == 0
	assert manifest["checked"] == 2 and manifest["camera"] == "adhoc"
	assert sorted(item["file"] for item in manifest["items"]) == [
		"A_26-10-20_08-14-58-20.jpg",
		"B_26-10-20_09-14-58-20.jpg",
	]
	assert not (setup / "videos").exists()


@pytest.mark.parametrize(
	"argv",
	[
		["--images", "x"],
		["--images", "x", "--out", "y", "--cameras", "A"],
		["--target-date", "20.10.2026"],
	],
)
def test_parse_rejects_bad_combinations(argv):
	with pytest.raises(SystemExit):
		run.parse_arguments(argv)


def test_a_runtime_error_during_the_run_is_not_mistaken_for_a_held_lock(setup, monkeypatch):
	def broken_model(model_path):
		raise RuntimeError("onnxruntime failed to load the model")

	monkeypatch.setattr(run, "make_forward", broken_model)

	with pytest.raises(RuntimeError, match="onnxruntime"):
		run.main([])
