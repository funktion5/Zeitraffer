from pathlib import Path


STATE_ROOT = Path("state")
RUN_MARKER = STATE_ROOT / "run-in-progress"


# Create the persistent marker when an automatic production run starts.
def mark_run_started() -> None:
	STATE_ROOT.mkdir(
		parents=True,
		exist_ok=True,
	)

	RUN_MARKER.touch()


# Remove the marker after the automatic production run finishes successfully.
def mark_run_finished() -> None:
	RUN_MARKER.unlink(
		missing_ok=True,
	)


# Return whether a previous automatic production run was interrupted.
def was_run_interrupted() -> bool:
	return RUN_MARKER.exists()
