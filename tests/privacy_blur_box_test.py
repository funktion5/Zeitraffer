import inspect
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from privacy_fakes import FAKE_DETECTOR, FakeBox, run_in, sha

import src.privacy.blur_box as blur_box
from src.privacy.anonymize import BlurSettings, DropRules, PrivacyCheckError
from src.privacy.blur_box import Daylight
from src.privacy.box_writer import BoxWriter
from src.storage_filter import StorageBox, acquire_run_lock

REMOTE = "user@box.example"
CAMERA = "Test-Camera"
TIMEZONE = "Europe/Berlin"
LOCATION = {"latitude": 52.472, "longitude": 9.333, "timezone": TIMEZONE}
DAYLIGHT = Daylight(LOCATION, 90)
SETTINGS = BlurSettings(0.1, 0.25, 0.5)
NOW = datetime(2026, 6, 15, 14, 0, tzinfo=ZoneInfo(TIMEZONE))

DAY = "20260615T120000.jpg"
DAY_WITH_PERSON = "20260615T130000.jpg"
NIGHT = "20260615T020000.jpg"

# A signpost the detector keeps reporting as a person.
SIGN = [703, 557, 742, 643]
rules_seen: dict[str, object] = {}


def original_bytes(name: str) -> bytes:
	return b"\xff\xd8original-" + name.encode() + b"\xff\xd9"


def blurred_bytes(name: str) -> bytes:
	return b"\xff\xd8blurred" + original_bytes(name)


class Setup:
	"""One local folder serves as the storage box; the job reaches it only over (fake) SSH."""

	def __init__(self, tmp_path: Path, monkeypatch) -> None:
		self.tmp_path = tmp_path
		self.root = tmp_path / "cameras"
		self.camera_dir = self.root / CAMERA
		self.camera_dir.mkdir(parents=True)
		self.state_root = tmp_path / "state"
		self.work_root = tmp_path / "work"
		self.box = FakeBox(self.root, REMOTE)
		self.storage_box = StorageBox(remote=REMOTE, base_directory="")

		monkeypatch.setattr(blur_box, "WORK_ROOT", self.work_root)
		monkeypatch.setenv("FAKE_PEOPLE", DAY_WITH_PERSON)
		monkeypatch.setenv("FAKE_DETECTOR_LOG", str(tmp_path / "detector.log"))

		monkeypatch.setattr(StorageBox, "run", run_in(self.root))

		# Blurring itself is covered by privacy_test; here it only has to change the copy.
		def fake_blur(frame: Path, boxes, settings, size=None) -> None:
			frame.write_bytes(b"\xff\xd8blurred" + frame.read_bytes())

		monkeypatch.setattr(blur_box, "blur_frame", fake_blur)
		# The fake images are no real JPEGs; their size is read before the drop rules apply.
		monkeypatch.setattr(blur_box, "_probe_dimensions", lambda frame: (1920, 1080))

		self.detector_calls: list[int] = []
		self.detector_timeouts: list[float | None] = []
		real_run_detector = blur_box.run_detector

		def counting_run_detector(command, frames, timeout_seconds=None):
			self.detector_calls.append(len(frames))
			self.detector_timeouts.append(timeout_seconds)

			return real_run_detector(command, frames, timeout_seconds)

		monkeypatch.setattr(blur_box, "run_detector", counting_run_detector)

		script = tmp_path / "fake_detector.py"
		script.write_text(FAKE_DETECTOR)
		self.detector = [sys.executable, str(script), "ok"]

	def writer(self, now: datetime = NOW, **limits) -> BoxWriter:
		return BoxWriter(
			REMOTE,
			"",
			[CAMERA],
			TIMEZONE,
			upload_root=self.work_root,
			runner=self.box,
			clock=lambda: now,
			**limits,
		)

	def upload(self, name: str, age_seconds: float = 600, now: datetime = NOW) -> Path:
		image = self.camera_dir / name
		image.write_bytes(original_bytes(name))
		moment = now.timestamp() - age_seconds
		os.utime(image, (moment, moment))

		return image

	def run(self, now: datetime = NOW, writer: BoxWriter | None = None, **options):
		return blur_box.process_box_camera(
			writer or self.writer(now),
			self.storage_box,
			CAMERA,
			self.detector,
			SETTINGS,
			DAYLIGHT,
			self.state_root,
			now,
			**options,
		)

	# The old single file (if any) first, then the monthly files, as load_processed reads them.
	def state_files(self) -> list[Path]:
		legacy = self.state_root / f"{CAMERA}.jsonl"

		return [legacy] * legacy.exists() + sorted((self.state_root / CAMERA).glob("*.jsonl"))

	def states(self) -> dict[str, dict]:
		entries = [
			json.loads(line)
			for path in self.state_files()
			for line in path.read_text().splitlines()
		]

		return {entry["image"]: entry for entry in entries}

	def detected(self) -> list[str]:
		log = self.tmp_path / "detector.log"

		return [Path(line).name for line in log.read_text().splitlines()] if log.exists() else []

	# Uploads (scp with the box as target) and remote cp/mv/mkdir; downloads are reads.
	def writes(self) -> list[str]:
		return [
			argv[-1]
			for argv in self.box.calls
			if (argv[0] == "scp" and argv[-1].startswith(f"{REMOTE}:"))
			or (argv[0] == "ssh" and argv[-1].startswith(("cp ", "mv ", "mkdir ")))
		]

	def downloads(self) -> list[str]:
		return [
			argv[-2].rsplit("/", 1)[-1]
			for argv in self.box.calls
			if argv[0] == "scp" and argv[-2].startswith(f"{REMOTE}:")
		]

	def swaps(self) -> list[str]:
		return [command.split("/")[-1] for command in self.writes() if command.startswith("mv -T ")]

	def leftovers(self) -> list[str]:
		hidden = [path.name for path in self.root.rglob(".*")]
		work = [path.name for path in self.work_root.rglob("*") if path.is_file()]

		return hidden + work


@pytest.fixture
def setup(tmp_path: Path, monkeypatch) -> Setup:
	return Setup(tmp_path, monkeypatch)


def test_person_is_blurred_on_the_box_after_verified_backup(setup: Setup) -> None:
	image = setup.upload(DAY_WITH_PERSON)

	summary = setup.run()

	assert summary.blurred == 1
	assert image.read_bytes() == blurred_bytes(DAY_WITH_PERSON)
	state = setup.states()[DAY_WITH_PERSON]
	assert state["status"] == "blurred"
	assert state["blurred_sha256"] == sha(image.read_bytes())
	assert state["boxes"] == [[1, 1, 5, 9, 0.9]]
	backup = setup.camera_dir / "original" / state["backup"]
	assert backup.read_bytes() == original_bytes(DAY_WITH_PERSON)
	assert setup.leftovers() == []


def test_image_without_people_stays_byte_identical(setup: Setup) -> None:
	image = setup.upload(DAY)

	summary = setup.run()

	assert summary.clean == 1
	assert image.read_bytes() == original_bytes(DAY)
	assert setup.states()[DAY]["status"] == "clean"
	# Detect first, back up only with people: nothing at all is written for a clean image.
	assert setup.writes() == []
	assert not (setup.camera_dir / "original").exists()


def test_night_image_is_recorded_without_detection_or_writes(setup: Setup) -> None:
	setup.upload(NIGHT, age_seconds=12 * 3600)

	summary = setup.run()

	assert summary.night == 1
	assert setup.states()[NIGHT]["status"] == "night"
	assert setup.detected() == []
	assert setup.writes() == []


def test_fresh_upload_waits_without_writes(setup: Setup) -> None:
	setup.upload(DAY_WITH_PERSON, age_seconds=1)

	summary = setup.run()

	assert summary.settling == 1
	assert setup.states() == {}
	assert setup.writes() == []


def test_incomplete_upload_waits_even_after_settle_time(setup: Setup) -> None:
	image = setup.upload(DAY_WITH_PERSON)
	image.write_bytes(b"\xff\xd8half")
	os.utime(image, (NOW.timestamp() - 300,) * 2)

	summary = setup.run()

	assert summary.settling == 1
	assert setup.writes() == []


def test_stalled_upload_is_logged_every_round_not_skipped(setup: Setup, caplog) -> None:
	image = setup.upload(DAY_WITH_PERSON)
	image.write_bytes(b"\xff\xd8half")
	os.utime(image, (NOW.timestamp() - 660,) * 2)

	for _ in range(2):
		assert setup.run().failed == 1

	assert caplog.text.count("incomplete for over 10 minutes") == 2
	assert setup.states() == {}
	assert setup.writes() == []


def test_processed_images_are_not_touched_again(setup: Setup) -> None:
	setup.upload(DAY)
	setup.upload(DAY_WITH_PERSON)
	setup.run()
	setup.box.calls.clear()
	detected = setup.detected()

	assert setup.run() == blur_box.BoxRoundSummary()
	assert setup.detected() == detected
	assert setup.writes() == []


def test_power_cut_after_swap_is_recognised_without_reprocessing(setup: Setup) -> None:
	setup.upload(DAY_WITH_PERSON)
	setup.run()

	# Drop the final "blurred" line, as if the Pi died right after the swap.
	path = setup.state_root / CAMERA / "2026-06.jsonl"
	lines = path.read_text().splitlines()
	assert json.loads(lines[-1])["status"] == "blurred"
	path.write_text("\n".join(lines[:-1]) + "\n")
	setup.box.calls.clear()
	detected = setup.detected()

	summary = setup.run()

	assert summary.blurred == 1
	assert setup.states()[DAY_WITH_PERSON]["status"] == "blurred"
	assert setup.detected() == detected
	assert setup.writes() == []


def test_power_cut_before_swap_processes_the_image_again(setup: Setup) -> None:
	image = setup.upload(DAY_WITH_PERSON)
	writer = setup.writer()

	def power_cut(backup, blurred_hash):
		raise OSError("power cut")

	writer.replace = power_cut

	assert setup.run(writer=writer).failed == 1
	assert setup.states()[DAY_WITH_PERSON]["status"] == "replacing"
	assert image.read_bytes() == original_bytes(DAY_WITH_PERSON)

	assert setup.run().blurred == 1
	assert image.read_bytes() == blurred_bytes(DAY_WITH_PERSON)
	assert len(list((setup.camera_dir / "original").glob("*.jpg"))) == 1


def test_two_hour_blackout_backlog_is_done_newest_first_one_at_a_time(
	setup: Setup, monkeypatch
) -> None:
	names = [f"20260615T{hour:02}{minute:02}00.jpg" for hour in (12, 13) for minute in (0, 20, 40)]
	names.append("20260615T115000.jpg")
	monkeypatch.setenv("FAKE_PEOPLE", ",".join(names))

	for name in names:
		setup.upload(name)

	summary = setup.run()

	assert summary.blurred == len(names)
	assert setup.swaps() == sorted(names, reverse=True)
	assert setup.detected() == sorted(names, reverse=True)
	assert setup.detector_calls == [1] * len(names)
	assert setup.leftovers() == []


def test_outage_across_midnight_still_finds_yesterdays_daytime_images(
	setup: Setup, monkeypatch
) -> None:
	shortly_after_midnight = datetime(2026, 6, 16, 0, 30, tzinfo=ZoneInfo(TIMEZONE))
	# 21:00 in June is still inside sunset + 90 min.
	name = "20260615T210000.jpg"
	image = setup.upload(name, now=shortly_after_midnight)
	monkeypatch.setenv("FAKE_PEOPLE", name)

	assert setup.run(now=shortly_after_midnight).blurred == 1
	assert image.read_bytes() == blurred_bytes(name)


def test_image_outside_the_window_is_refused_once_and_recorded(setup: Setup, caplog) -> None:
	name = "20260614T120000.jpg"
	image = setup.upload(name, age_seconds=26 * 3600)

	summary = setup.run()

	assert summary.refused == 1
	assert setup.states()[name]["status"] == "refused"
	assert "stays unblurred" in caplog.text
	assert image.read_bytes() == original_bytes(name)
	assert setup.writes() == []
	# Refused before any detection is spent on it.
	assert setup.detected() == []

	assert setup.run() == blur_box.BoxRoundSummary()


def test_count_limit_defers_the_rest_to_the_next_round(setup: Setup, monkeypatch) -> None:
	names = ["20260615T120000.jpg", "20260615T121000.jpg", "20260615T122000.jpg"]
	monkeypatch.setenv("FAKE_PEOPLE", ",".join(names))

	for name in names:
		setup.upload(name)

	summary = setup.run(writer=setup.writer(max_backups_per_camera=2))

	assert (summary.blurred, summary.failed) == (2, 1)
	assert names[0] not in setup.states()

	assert setup.run().blurred == 1


def test_broken_detector_writes_nothing_and_logs_every_image(setup: Setup, caplog) -> None:
	images = [setup.upload(DAY), setup.upload(DAY_WITH_PERSON)]
	setup.detector[-1] = "fail"

	summary = setup.run()

	assert summary.failed == 2
	assert all(image.read_bytes() == original_bytes(image.name) for image in images)
	assert setup.states() == {}
	assert setup.swaps() == []
	assert caplog.text.count("retrying next round") == 2
	assert [path for path in setup.work_root.rglob("*") if path.is_file()] == []


# Newest first: the bad image must not keep the older ones from being done, round after round.
def test_image_the_detector_cannot_handle_blocks_only_itself(setup: Setup, monkeypatch) -> None:
	names = ["20260615T110000.jpg", "20260615T120000.jpg", "20260615T130000.jpg"]
	bad = names[-1]
	monkeypatch.setenv("FAKE_PEOPLE", ",".join(names))
	monkeypatch.setenv("FAKE_CRASH_ON", bad)

	for name in names:
		setup.upload(name)

	for _ in range(2):
		summary = setup.run()

		assert summary.failed == 1
		assert (setup.camera_dir / bad).read_bytes() == original_bytes(bad)

	assert summary.blurred == 0
	assert setup.swaps() == names[1::-1]


def test_image_rewritten_during_detection_is_not_marked_clean(setup: Setup, monkeypatch) -> None:
	image = setup.upload(DAY)
	monkeypatch.setenv("FAKE_REWRITE", str(image))

	assert setup.run().failed == 1
	assert DAY not in setup.states()


def test_blur_that_changes_nothing_is_retried_not_fatal(setup: Setup, monkeypatch) -> None:
	image = setup.upload(DAY_WITH_PERSON)
	monkeypatch.setattr(blur_box, "blur_frame", lambda frame, boxes, settings, size=None: None)

	assert setup.run().failed == 1
	assert image.read_bytes() == original_bytes(DAY_WITH_PERSON)
	assert DAY_WITH_PERSON not in setup.states()


# A dated name without a readable time must not pass as a night image.
def test_image_without_readable_time_is_refused_not_taken_for_night(setup: Setup) -> None:
	name = "cam_260615_x.jpg"
	setup.upload(name)

	summary = setup.run()

	assert (summary.night, summary.refused) == (0, 1)
	assert setup.states()[name]["status"] == "refused"


# main(): which cameras may be written at all.

BLUR = {"strength": 0.1, "padding_ratio": 0.25}


@pytest.fixture
def rounds(tmp_path: Path, monkeypatch) -> list[tuple[str, list[str]]]:
	calls: list[tuple[str, list[str]]] = []
	(tmp_path / "cameras" / CAMERA).mkdir(parents=True)
	(tmp_path / "cameras" / "Other").mkdir()
	config = {
		"location": LOCATION,
		"daylight_buffer_minutes": 90,
		"privacy": {
			"blur_cameras": [CAMERA, "Other"],
			"ignore_boxes": {CAMERA: [SIGN]},
			"ignore_top_share": 0.333,
			"detector_command": ["detector"],
			"blur": {**BLUR, "feather": 0.5},
		},
	}

	def record_round(writer, storage_box, camera, *args, rules=None):
		calls.append((camera, sorted(writer.allowed_cameras)))
		rules_seen[camera] = rules

		return blur_box.BoxRoundSummary()

	# The folder check goes to the box over SSH; here the local folders stand in for it.
	monkeypatch.setattr(
		BoxWriter, "camera_exists", lambda self, camera: (tmp_path / "cameras" / camera).is_dir()
	)
	monkeypatch.setattr(blur_box, "BLUR_LOCK_PATH", tmp_path / "blur.lock")
	monkeypatch.setattr(blur_box, "load_config", lambda: config)
	monkeypatch.setattr(blur_box, "get_storage_box", lambda: StorageBox(REMOTE, ""))
	monkeypatch.setattr(blur_box, "process_box_camera", record_round)

	return calls


def test_manual_run_can_only_write_the_named_camera(rounds) -> None:
	assert blur_box.main(["--cameras", CAMERA]) == 0
	assert rounds == [(CAMERA, [CAMERA])]


def test_cron_run_covers_every_blur_camera(rounds) -> None:
	assert blur_box.main(["--all-blur-cameras"]) == 0
	assert [camera for camera, _ in rounds] == [CAMERA, "Other"]


def test_camera_outside_the_blur_list_is_refused_before_any_contact(rounds, monkeypatch) -> None:
	monkeypatch.setattr(blur_box, "get_storage_box", lambda: pytest.fail("box contacted"))

	assert blur_box.main(["--cameras", CAMERA, "Scheunenviertel"]) == 1
	assert rounds == []


def test_camera_selection_is_required(rounds) -> None:
	with pytest.raises(SystemExit):
		blur_box.main([])


def test_missing_camera_folder_is_an_error(rounds, tmp_path: Path) -> None:
	(tmp_path / "cameras" / "Other").rmdir()

	assert blur_box.main(["--all-blur-cameras"]) == 1
	assert [camera for camera, _ in rounds] == [CAMERA]


def test_round_is_skipped_while_another_blur_round_runs(rounds, tmp_path: Path) -> None:
	with acquire_run_lock(tmp_path / "blur.lock"):
		assert blur_box.main(["--all-blur-cameras"]) == 0

	assert rounds == []


def test_night_name_uploaded_in_daylight_is_checked_not_skipped(setup: Setup, monkeypatch) -> None:
	# The filename clock says 02:00, the upload happened at 13:50: trust neither alone.
	setup.upload(NIGHT)
	monkeypatch.setenv("FAKE_PEOPLE", NIGHT)

	summary = setup.run()

	assert (summary.night, summary.blurred) == (0, 1)


# Matches the day's listing pattern, but no known format reads its date: refuse and log it.
def test_unreadable_name_is_refused_and_logged_not_dropped(setup: Setup, caplog) -> None:
	name = "IMG20260615-120000.jpg"
	setup.upload(name)

	assert setup.run().refused == 1
	assert setup.states()[name]["status"] == "refused"
	assert "stays unblurred" in caplog.text


def test_image_two_days_back_is_refused_and_logged(setup: Setup, caplog) -> None:
	name = "20260613T120000.jpg"
	setup.upload(name, age_seconds=50 * 3600)

	assert setup.run().refused == 1
	assert setup.states()[name]["status"] == "refused"
	assert "stays unblurred" in caplog.text


def test_time_budget_postpones_the_rest_newest_first(setup: Setup, monkeypatch) -> None:
	names = ["20260615T110000.jpg", "20260615T120000.jpg", "20260615T130000.jpg"]
	monkeypatch.setenv("FAKE_PEOPLE", ",".join(names))

	for name in names:
		setup.upload(name)

	def run_with_no_budget():
		return blur_box.process_box_camera(
			setup.writer(),
			setup.storage_box,
			CAMERA,
			setup.detector,
			SETTINGS,
			DAYLIGHT,
			setup.state_root,
			NOW,
			time_budget_seconds=0,
		)

	summary = run_with_no_budget()

	# At least one image per round, the newest; the rest waits for the next round.
	assert (summary.blurred, summary.postponed) == (1, 2)
	assert setup.swaps() == [names[2]]

	run_with_no_budget()

	assert setup.swaps() == [names[2], names[1]]


def test_failed_check_of_an_interrupted_swap_is_retried(setup: Setup, caplog) -> None:
	setup.upload(DAY_WITH_PERSON)
	path = setup.state_root / f"{CAMERA}.jsonl"
	path.parent.mkdir(parents=True)
	path.write_text(
		json.dumps({"image": DAY_WITH_PERSON, "status": "replacing", "blurred_sha256": "0" * 64})
		+ "\n"
	)
	setup.box.fail_next["sha256sum"] = FakeBox.result(255, stderr="Connection closed")

	assert setup.run().failed == 1
	assert "retrying next round" in caplog.text
	assert setup.states()[DAY_WITH_PERSON]["status"] == "replacing"

	assert setup.run().blurred == 1


@pytest.mark.parametrize("field", ["failed", "refused"])
def test_exit_code_reports_failed_or_refused_images(rounds, monkeypatch, field) -> None:
	monkeypatch.setattr(
		blur_box,
		"process_box_camera",
		lambda *args, **kwargs: blur_box.BoxRoundSummary(**{field: 1}),
	)

	assert blur_box.main(["--cameras", CAMERA]) == 1


def test_aborted_camera_does_not_stop_the_next_one(rounds, monkeypatch) -> None:
	def round_with_trouble(writer, storage_box, camera, *args, **kwargs):
		rounds.append((camera, []))

		if camera == CAMERA:
			raise OSError("listing failed")

		return blur_box.BoxRoundSummary()

	monkeypatch.setattr(blur_box, "process_box_camera", round_with_trouble)

	assert blur_box.main(["--all-blur-cameras"]) == 1
	assert [camera for camera, _ in rounds] == [CAMERA, "Other"]


def test_unusable_timezone_is_logged_not_a_traceback(rounds, monkeypatch, caplog) -> None:
	config = blur_box.load_config()
	config["location"] = {**LOCATION, "timezone": "Europe/Mars"}
	monkeypatch.setattr(blur_box, "load_config", lambda: config)

	assert blur_box.main(["--all-blur-cameras"]) == 1
	assert "Cannot write to the storage box" in caplog.text
	assert rounds == []


def test_person_image_rewritten_during_detection_is_not_blurred_yet(
	setup: Setup, monkeypatch
) -> None:
	image = setup.upload(DAY_WITH_PERSON)
	monkeypatch.setenv("FAKE_REWRITE", str(image))

	assert setup.run().failed == 1
	assert setup.swaps() == []
	assert image.read_bytes().endswith(b"late-bytes\xff\xd9")

	# Next round judges the new bytes and blurs them.
	monkeypatch.delenv("FAKE_REWRITE")
	os.utime(image, (NOW.timestamp() - 600,) * 2)

	assert setup.run().blurred == 1
	assert image.read_bytes().startswith(b"\xff\xd8blurred")


def test_only_images_with_people_are_backed_up(setup: Setup) -> None:
	setup.upload(DAY)
	setup.upload(DAY_WITH_PERSON)

	setup.run()

	backups = [path.name for path in (setup.camera_dir / "original").iterdir()]
	assert len(backups) == 1
	assert backups[0].startswith(DAY_WITH_PERSON.removesuffix(".jpg") + ".")


def test_failed_hash_check_of_a_clean_image_is_retried(setup: Setup) -> None:
	setup.upload(DAY)
	setup.box.fail_next["sha256sum"] = FakeBox.result(255, stderr="Connection closed")

	assert setup.run().failed == 1
	assert DAY not in setup.states()

	assert setup.run().clean == 1


def test_image_leaving_the_window_during_detection_is_refused_after_it(
	setup: Setup, monkeypatch
) -> None:
	# The clock passes 24 h between the pre-check and the backup.
	setup.upload(DAY_WITH_PERSON)
	times = iter([NOW, NOW + timedelta(hours=24)])
	writer = BoxWriter(
		REMOTE,
		"",
		[CAMERA],
		TIMEZONE,
		upload_root=setup.work_root,
		runner=setup.box,
		clock=lambda: next(times),
	)

	summary = setup.run(writer=writer)

	assert summary.refused == 1
	assert setup.states()[DAY_WITH_PERSON]["status"] == "refused"
	assert setup.writes() == []


# Known false positives (privacy.ignore_boxes).


def _run_with_sign(setup: Setup, monkeypatch, boxes: list[list[int]]):
	monkeypatch.setenv("FAKE_BOXES", json.dumps(boxes))

	return setup.run(rules=DropRules(ignore_boxes={CAMERA: [SIGN]}))


def test_box_on_the_known_sign_is_ignored_and_recorded(setup: Setup, monkeypatch) -> None:
	image = setup.upload(DAY_WITH_PERSON)

	summary = _run_with_sign(setup, monkeypatch, [[706, 557, 741, 640]])

	assert summary.clean == 1
	assert image.read_bytes() == original_bytes(DAY_WITH_PERSON)
	assert setup.writes() == []
	assert setup.states()[DAY_WITH_PERSON]["ignored_boxes"] == [[706, 557, 741, 640, 0.9]]


# A moved camera: the sign no longer matches, so it is blurred again instead of skipped.
def test_box_shifted_away_from_the_sign_is_blurred(setup: Setup, monkeypatch) -> None:
	setup.upload(DAY_WITH_PERSON)

	summary = _run_with_sign(setup, monkeypatch, [[723, 557, 762, 643]])

	assert summary.blurred == 1
	assert "ignored_boxes" not in setup.states()[DAY_WITH_PERSON]


# The detector's label goes into the state, so a blurred box can be traced afterwards.
def test_blurred_box_keeps_its_label_in_the_state(setup: Setup, monkeypatch) -> None:
	setup.upload(DAY_WITH_PERSON)

	summary = _run_with_sign(setup, monkeypatch, [[100, 500, 400, 600, "vehicle"]])

	assert summary.blurred == 1
	assert setup.states()[DAY_WITH_PERSON]["boxes"] == [[100, 500, 400, 600, 0.9, "vehicle"]]


def test_person_next_to_the_sign_is_still_blurred(setup: Setup, monkeypatch) -> None:
	setup.upload(DAY_WITH_PERSON)

	summary = _run_with_sign(setup, monkeypatch, [[703, 557, 742, 643], [739, 574, 767, 644]])

	assert summary.blurred == 1
	state = setup.states()[DAY_WITH_PERSON]
	assert state["boxes"] == [[739, 574, 767, 644, 0.9]]
	assert state["ignored_boxes"] == [[703, 557, 742, 643, 0.9]]


# One validated rule set for every camera; filter_boxes picks each camera's known boxes.
def test_every_camera_gets_the_validated_drop_rules(rounds) -> None:
	rules_seen.clear()

	assert blur_box.main(["--all-blur-cameras"]) == 0
	expected = DropRules(top_share=0.333, ignore_boxes={CAMERA: [SIGN]})
	assert rules_seen == {CAMERA: expected, "Other": expected}


@pytest.mark.parametrize(
	"change",
	[
		{"ignore_top_share": 3.33},
		{"ignore_top_share": "a third"},
		{"ignore_boxes": {CAMERA: [[1, 2]]}},
	],
)
def test_invalid_drop_rule_stops_before_any_contact(rounds, monkeypatch, caplog, change) -> None:
	config = blur_box.load_config()
	config["privacy"] = {**config["privacy"], **change}
	monkeypatch.setattr(blur_box, "load_config", lambda: config)
	monkeypatch.setattr(blur_box, "get_storage_box", lambda: pytest.fail("box contacted"))

	assert blur_box.main(["--all-blur-cameras"]) == 1
	assert "Invalid privacy settings" in caplog.text
	assert rounds == []


# The camera mount at the top right, reported as a person at dusk (Scheunenviertel 2026-08-16).
def test_box_mostly_in_the_top_band_is_ignored_and_recorded(setup: Setup, monkeypatch) -> None:
	image = setup.upload(DAY_WITH_PERSON)
	monkeypatch.setenv("FAKE_BOXES", json.dumps([[1545, 20, 1918, 480]]))

	summary = setup.run(rules=DropRules(top_share=1 / 3))

	assert summary.clean == 1
	assert image.read_bytes() == original_bytes(DAY_WITH_PERSON)
	assert setup.writes() == []
	assert setup.states()[DAY_WITH_PERSON]["ignored_boxes"] == [[1545, 20, 1918, 480, 0.9]]


# The judged bytes come over SSH from the box; the SSHFS mount is never read, so it cannot hang
# the round or serve stale data.
def test_image_is_downloaded_from_the_box_never_read_from_the_mount(setup: Setup) -> None:
	setup.upload(DAY_WITH_PERSON)

	assert setup.run().blurred == 1
	assert setup.downloads() == [DAY_WITH_PERSON]
	assert "CAMERA_ROOT" not in inspect.getsource(blur_box)
	assert "/mnt" not in inspect.getsource(blur_box)


def test_image_gone_between_listing_and_download_is_retried(setup: Setup, monkeypatch) -> None:
	setup.upload(DAY)
	monkeypatch.setattr(
		blur_box,
		"list_images_for_dates",
		lambda box, camera, days: {DAY: int(NOW.timestamp()) - 600, DAY_WITH_PERSON: 0},
	)

	summary = setup.run()

	assert (summary.clean, summary.failed) == (1, 1)
	assert DAY_WITH_PERSON not in setup.states()
	assert setup.writes() == []


# An image whose size cannot be read fails alone; it used to stop the whole round, every minute.
def test_unreadable_image_size_fails_only_that_image(setup: Setup, monkeypatch) -> None:
	names = ["20260615T120000.jpg", "20260615T130000.jpg"]
	monkeypatch.setenv("FAKE_PEOPLE", ",".join(names))

	for name in names:
		setup.upload(name)

	def probe(frame: Path):
		if frame.name == names[1]:
			raise PrivacyCheckError(f"Cannot read the size of {frame.name}: ''")

		return (1920, 1080)

	monkeypatch.setattr(blur_box, "_probe_dimensions", probe)

	summary = setup.run()

	assert (summary.blurred, summary.failed) == (1, 1)
	assert setup.swaps() == [names[0]]


def test_live_detection_uses_the_short_timeout(setup: Setup) -> None:
	setup.upload(DAY)

	setup.run()

	assert setup.detector_timeouts == [blur_box.DETECTOR_TIMEOUT_SECONDS]
	assert blur_box.DETECTOR_TIMEOUT_SECONDS <= 180


# State files from before the monthly split are still read, so nothing is processed twice.
def test_state_from_the_old_single_file_is_honoured(setup: Setup) -> None:
	setup.upload(DAY_WITH_PERSON)
	legacy = setup.state_root / f"{CAMERA}.jsonl"
	legacy.parent.mkdir(parents=True)
	legacy.write_text(json.dumps({"image": DAY_WITH_PERSON, "status": "blurred"}) + "\n")

	assert setup.run() == blur_box.BoxRoundSummary()
	assert setup.detected() == []
