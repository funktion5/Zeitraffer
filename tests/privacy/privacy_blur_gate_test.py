import json
from pathlib import Path

import pytest

import src.privacy.blur_gate as blur_gate
from src.privacy.blur_gate import apply_blur_gate, split_confirmed_images

# The blur gate of a public video built from older frames (Monthly, Yearly): only what the box blur
# job has confirmed goes in. Unlike the Daily's gate it reads the state page of every frame's own
# month, because a Yearly reaches back a year.
#   split_confirmed_images(camera, images, timezone) -> (confirmed, left_out)
#   apply_blur_gate(camera, images, timezone) -> confirmed, with a log line for what was left out

CAMERA = "Blur-Camera"
TIMEZONE = "Europe/Berlin"


@pytest.fixture(autouse=True)
def state_root(monkeypatch, tmp_path) -> Path:
	root = tmp_path / "state"

	monkeypatch.setattr(blur_gate, "BLUR_STATE_ROOT", root)

	return root


# One state file per camera and month, one JSON line per event, like blur_box.record_processed.
def write_state(root: Path, month: str, entries: list[dict], camera: str = CAMERA) -> None:
	path = root / camera / f"{month}.jsonl"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")


def frame(name: str) -> Path:
	return Path("temp") / CAMERA / name


# blurred, clean and night are confirmed; refused, replacing and no entry at all are not. The order
# of the images is kept.
def test_only_confirmed_statuses_pass(state_root):
	names = [f"202603{day:02d}T120000.jpg" for day in range(10, 16)]
	images = [frame(name) for name in names]

	write_state(
		state_root,
		"2026-03",
		[
			{"image": names[0], "status": "blurred"},
			{"image": names[1], "status": "clean"},
			{"image": names[2], "status": "night"},
			{"image": names[3], "status": "refused", "reason": "detector failed"},
			{"image": names[4], "status": "replacing"},
		],
	)

	confirmed, left_out = split_confirmed_images(CAMERA, images, TIMEZONE)

	assert confirmed == images[:3]
	assert left_out == images[3:]


# The last line of an image is the one that counts, like everywhere else in the blur state.
def test_last_state_line_wins(state_root):
	names = ["20260310T120000.jpg", "20260311T120000.jpg"]
	images = [frame(name) for name in names]

	write_state(
		state_root,
		"2026-03",
		[
			{"image": names[0], "status": "refused"},
			{"image": names[0], "status": "blurred"},
			{"image": names[1], "status": "blurred"},
			{"image": names[1], "status": "replacing"},
		],
	)

	confirmed, left_out = split_confirmed_images(CAMERA, images, TIMEZONE)

	assert confirmed == [images[0]]
	assert left_out == [images[1]]


# The state is keyed by file name; the fetched frames live in a folder of their own.
def test_matches_the_file_name_not_the_path(state_root):
	image = Path("somewhere/else/entirely/20260310T120000.jpg")

	write_state(state_root, "2026-03", [{"image": image.name, "status": "clean"}])

	confirmed, left_out = split_confirmed_images(CAMERA, [image], TIMEZONE)

	assert confirmed == [image]
	assert left_out == []


# The reason this module exists: a Yearly's frames sit on many months' pages, far back from today.
def test_reads_the_page_of_every_frames_own_month(state_root):
	names = ["20251111T120000.jpg", "20260310T120000.jpg", "20260905T120000.jpg"]
	images = [frame(name) for name in names]

	for name in names:
		write_state(state_root, f"{name[:4]}-{name[4:6]}", [{"image": name, "status": "blurred"}])

	confirmed, left_out = split_confirmed_images(CAMERA, images, TIMEZONE)

	assert confirmed == images
	assert left_out == []


# The nightly round records an image on the page of its own time, so the last day of a month can
# sit on the next month's page.
def test_a_frame_recorded_on_the_next_months_page_counts(state_root):
	name = "20260131T120000.jpg"

	write_state(state_root, "2026-02", [{"image": name, "status": "blurred"}])

	confirmed, left_out = split_confirmed_images(CAMERA, [frame(name)], TIMEZONE)

	assert confirmed == [frame(name)]
	assert left_out == []


# Nothing is assumed: no state at all, or an empty page, both mean "unconfirmed".
@pytest.mark.parametrize("entries", [None, []])
def test_no_state_means_nothing_is_confirmed(state_root, entries):
	images = [frame("20260310T120000.jpg"), frame("20260311T120000.jpg")]

	if entries is not None:
		write_state(state_root, "2026-03", entries)

	confirmed, left_out = split_confirmed_images(CAMERA, images, TIMEZONE)

	assert confirmed == []
	assert left_out == images


# Another camera's state must not confirm this camera's frames.
def test_another_cameras_state_does_not_count(state_root):
	name = "20260310T120000.jpg"

	write_state(
		state_root,
		"2026-03",
		[{"image": name, "status": "blurred"}],
		camera="Other-Camera",
	)

	confirmed, left_out = split_confirmed_images(CAMERA, [frame(name)], TIMEZONE)

	assert confirmed == []
	assert left_out == [frame(name)]


# A name without a readable date has no state page to look on: fail closed.
def test_a_name_without_a_date_is_left_out(state_root):
	write_state(state_root, "2026-03", [{"image": "a.jpg", "status": "blurred"}])

	confirmed, left_out = split_confirmed_images(CAMERA, [Path("a.jpg")], TIMEZONE)

	assert confirmed == []
	assert left_out == [Path("a.jpg")]


def test_no_images_is_not_an_error():
	assert split_confirmed_images(CAMERA, [], TIMEZONE) == ([], [])


# ---- apply_blur_gate: the same split, plus the log line the jobs share ----


def test_apply_returns_the_confirmed_images_and_names_the_rest(state_root, caplog):
	names = ["20260310T120000.jpg", "20260311T120000.jpg", "20260312T120000.jpg"]
	images = [frame(name) for name in names]

	write_state(state_root, "2026-03", [{"image": names[0], "status": "blurred"}])

	assert apply_blur_gate(CAMERA, images, TIMEZONE) == [images[0]]
	assert f"[{CAMERA}] Blur gate: left out 2 of 3 unconfirmed images" in caplog.text
	assert names[1] in caplog.text
	assert names[2] in caplog.text


# Nothing to report when every image is confirmed.
def test_apply_is_silent_when_everything_is_confirmed(state_root, caplog):
	names = ["20260310T120000.jpg", "20260311T120000.jpg"]
	images = [frame(name) for name in names]

	write_state(state_root, "2026-03", [{"image": name, "status": "blurred"} for name in names])

	assert apply_blur_gate(CAMERA, images, TIMEZONE) == images
	assert "Blur gate" not in caplog.text


# A year of unconfirmed frames must not put 365 names into one log line.
def test_apply_names_at_most_ten_left_out_images(caplog):
	names = [f"202603{day:02d}T120000.jpg" for day in range(1, 21)]
	images = [frame(name) for name in names]

	assert apply_blur_gate(CAMERA, images, TIMEZONE) == []
	assert "left out 20 of 20" in caplog.text
	assert names[9] in caplog.text
	assert names[10] not in caplog.text
	assert "..." in caplog.text
