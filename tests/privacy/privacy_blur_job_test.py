from functools import partial
from pathlib import Path

import pytest
from privacy_blur_box_test import (
	CAMERA,
	LOCATION,
	NOW,
	OLD_AGE,
	Setup,
	blurred_bytes,
	original_bytes,
	record_in_own_month,
)

import src.privacy.blur_box as blur_box
import src.privacy.blur_job as blur_job
from src.privacy.anonymize import PrivacyCheckError
from src.privacy.box_writer import BoxWriter
from src.storage_filter import acquire_run_lock

# Step 2b of docs/plans/done/2026-11-05-blur-backfill-for-long-videos.md: what a manual Monthly or
# Yearly with --blur-box does between choosing its frames and building the video:
#   blur_job.blur_job_frames(camera, images, config, now=None) -> bool
# True means the video may be built: every frame is confirmed, cut-off ones excepted. When it is
# False the reason is in a log line ending in " - skipping camera: <name>".

PERSON_A = "20260310T120000.jpg"
PERSON_B = "20260311T120000.jpg"
NOBODY = "20260312T120000.jpg"


class FakeFrameSource:
	"""Records what the job would drop from its cache and fetch again."""

	def __init__(self) -> None:
		self.released: list[tuple[str, list[str]]] = []
		self.localized: list[tuple[str, list[str]]] = []
		self.order: list[str] = []

	def release_frames(self, camera: str, names: list[str]) -> None:
		self.released.append((camera, sorted(names)))
		self.order.append("release")

	def localize(self, camera: str, paths: list[Path], progress_callback=None) -> None:
		self.localized.append((camera, sorted(path.name for path in paths)))
		self.order.append("localize")


class JobSetup:
	"""A job's view: its cached copies of the frames, the box behind them, a fake source."""

	def __init__(self, setup: Setup, tmp_path: Path, monkeypatch) -> None:
		self.setup = setup
		self.cache = tmp_path / "job-cache" / CAMERA
		self.cache.mkdir(parents=True)
		self.source = FakeFrameSource()

		monkeypatch.setattr(blur_job, "get_frame_source", lambda: self.source)
		monkeypatch.setattr(blur_job, "get_storage_box", lambda: setup.storage_box)
		monkeypatch.setattr(blur_job, "BLUR_STATE_ROOT", setup.state_root)
		monkeypatch.setattr(blur_box, "BLUR_LOCK_PATH", tmp_path / "blur.lock")
		# The writer talks to the fake box, and its clock stands still.
		monkeypatch.setattr(
			blur_job, "BoxWriter", partial(BoxWriter, runner=setup.box, clock=lambda: NOW)
		)

	# The frame on the box (months old) and the job's own copy of it, from before any blur.
	def frame(self, name: str, cut_off: bool = False) -> Path:
		on_box = self.setup.upload(name, age_seconds=OLD_AGE)
		local = self.cache / name
		local.write_bytes(original_bytes(name))

		if cut_off:
			on_box.write_bytes(b"\xff\xd8half")
			local.write_bytes(b"\xff\xd8half")

		return local

	def run(self, images: list[Path]) -> bool:
		config = {
			"location": LOCATION,
			"privacy": {
				"blur_cameras": [CAMERA],
				"detector_command": self.setup.detector,
				"blur": {"strength": 0.1, "padding_ratio": 0.25, "feather": 0.5},
			},
		}

		return blur_job.blur_job_frames(CAMERA, images, config, NOW)


@pytest.fixture
def job(tmp_path: Path, monkeypatch) -> JobSetup:
	return JobSetup(Setup(tmp_path, monkeypatch), tmp_path, monkeypatch)


def test_job_frames_are_blurred_and_only_those_copies_are_fetched_again(job, monkeypatch) -> None:
	monkeypatch.setenv("FAKE_PEOPLE", f"{PERSON_A},{PERSON_B}")
	images = [job.frame(name) for name in (PERSON_A, PERSON_B, NOBODY)]

	assert job.run(images) is True

	states = job.setup.states()
	assert [states[name]["status"] for name in (PERSON_A, PERSON_B, NOBODY)] == [
		"blurred",
		"blurred",
		"clean",
	]
	assert (job.setup.camera_dir / PERSON_A).read_bytes() == blurred_bytes(PERSON_A)
	assert (job.setup.camera_dir / NOBODY).read_bytes() == original_bytes(NOBODY)
	# The job's copies are from before the blur: only the blurred ones are dropped, then fetched
	# again, in that order.
	assert job.source.released == [(CAMERA, [PERSON_A, PERSON_B])]
	assert job.source.localized == [(CAMERA, [PERSON_A, PERSON_B])]
	assert job.source.order == ["release", "localize"]


def test_confirmed_frames_cause_no_work_and_no_refetch(job) -> None:
	images = [job.frame(name) for name in (PERSON_A, NOBODY)]

	for name in (PERSON_A, NOBODY):
		record_in_own_month(job.setup, name, "blurred")

	assert job.run(images) is True

	assert job.setup.detected() == []
	assert job.setup.writes() == []
	assert (job.source.released, job.source.localized) == ([], [])


def test_the_log_names_the_numbers_before_anything_is_blurred(job, monkeypatch, caplog) -> None:
	caplog.set_level("INFO")
	monkeypatch.setenv("FAKE_PEOPLE", f"{PERSON_A},{PERSON_B}")
	images = [job.frame(name) for name in (PERSON_A, PERSON_B, NOBODY)]
	record_in_own_month(job.setup, NOBODY, "clean")

	job.run(images)

	assert f"[{CAMERA}] Blur: 3 frames, 1 already confirmed, 2 to blur" in caplog.text


# No video from an incomplete blur. The warning ends in " - skipping camera: <name>", which is the
# wording the web UI shows as the reason.
def test_a_frame_that_stays_unblurred_makes_the_job_not_ready(job, monkeypatch, caplog) -> None:
	monkeypatch.setenv("FAKE_PEOPLE", f"{PERSON_A},{PERSON_B}")
	images = [job.frame(name) for name in (PERSON_A, PERSON_B, NOBODY)]

	def probe(frame: Path):
		if frame.name == PERSON_B:
			raise PrivacyCheckError(f"Cannot read the size of {frame.name}: ''")

		return (1920, 1080)

	monkeypatch.setattr(blur_box, "_probe_dimensions", probe)

	assert job.run(images) is False

	assert f"1 of 3 not blurred yet: {PERSON_B} - skipping camera: {CAMERA}" in caplog.text
	# What was blurred is still dropped from the cache, so nothing stale is left behind.
	assert job.source.released == [(CAMERA, [PERSON_A])]


# The video step skips a cut-off JPEG anyway, so such a frame is no reason to hold the video back.
def test_a_cut_off_frame_does_not_stop_the_job(job, monkeypatch) -> None:
	monkeypatch.setenv("FAKE_PEOPLE", PERSON_A)
	images = [job.frame(PERSON_A), job.frame(PERSON_B, cut_off=True)]

	assert job.run(images) is True

	assert PERSON_B not in job.setup.states()
	assert job.source.released == [(CAMERA, [PERSON_A])]


def test_a_busy_blur_lock_stops_the_job_before_anything_is_written(
	job, monkeypatch, tmp_path, caplog
) -> None:
	monkeypatch.setenv("FAKE_PEOPLE", PERSON_A)
	images = [job.frame(PERSON_A)]

	with acquire_run_lock(tmp_path / "blur.lock"):
		assert job.run(images) is False

	assert f"another blur run holds the lock - skipping camera: {CAMERA}" in caplog.text
	assert job.setup.detected() == []
	assert job.setup.writes() == []
	assert job.source.released == []


# The video is built after the blur step and must not wait on, or hold, the blur lock.
def test_the_blur_lock_is_free_again_after_the_blur_step(job, monkeypatch, tmp_path) -> None:
	monkeypatch.setenv("FAKE_PEOPLE", PERSON_A)

	job.run([job.frame(PERSON_A)])

	with acquire_run_lock(tmp_path / "blur.lock"):
		pass
