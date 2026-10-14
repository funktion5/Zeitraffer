from pathlib import Path

import src.run_state as run_state


# Starting an automatic run must create the persistent interruption marker.
def test_mark_run_started_creates_marker(
	tmp_path: Path,
	monkeypatch,
):
	marker = tmp_path / "state" / "run-in-progress"

	monkeypatch.setattr(
		run_state,
		"STATE_ROOT",
		tmp_path / "state",
	)

	monkeypatch.setattr(
		run_state,
		"RUN_MARKER",
		marker,
	)

	run_state.mark_run_started()

	assert marker.exists()
	assert marker.is_file()


# Finishing an automatic run must remove the interruption marker.
def test_mark_run_finished_removes_marker(
	tmp_path: Path,
	monkeypatch,
):
	marker = tmp_path / "state" / "run-in-progress"

	marker.parent.mkdir(
		parents=True,
	)

	marker.touch()

	monkeypatch.setattr(
		run_state,
		"RUN_MARKER",
		marker,
	)

	run_state.mark_run_finished()

	assert not marker.exists()


# Finishing must stay safe when no interruption marker exists.
def test_mark_run_finished_is_safe_without_marker(
	tmp_path: Path,
	monkeypatch,
):
	marker = tmp_path / "state" / "run-in-progress"

	monkeypatch.setattr(
		run_state,
		"RUN_MARKER",
		marker,
	)

	run_state.mark_run_finished()

	assert not marker.exists()
