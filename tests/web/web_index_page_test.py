import json
from pathlib import Path

from web_php_test import render_page

TOKEN = "test-token"


# index.php with the camera list at tmp_path/state/web-jobs/cameras.json and some video bytes per
# camera (a camera mapped to 0 has no folder at all).
def render(tmp_path: Path, sizes: dict[str, int]) -> str:
	list_path = tmp_path / "state" / "web-jobs" / "cameras.json"
	list_path.parent.mkdir(parents=True, exist_ok=True)
	list_path.write_text(json.dumps(list(sizes)))

	for camera, size in sizes.items():
		if size:
			video = tmp_path / "videos" / camera / "daily" / "a.mp4"
			video.parent.mkdir(parents=True, exist_ok=True)
			video.write_bytes(b"x" * size)

	out, _ = render_page(tmp_path, "index.php", {}, {}, None, 0, TOKEN)

	return out


def row_of(out: str, camera: str) -> str:
	start = out.index(f'href="/camera.php?camera={camera}"')

	return out[start : out.index("</a>", start)]


def test_every_camera_shows_its_video_size_in_plain_words(tmp_path):
	out = render(tmp_path, {"A": 300, "B": 100})

	assert "300.0 B Videos" in row_of(out, "A")
	assert "100.0 B Videos" in row_of(out, "B")


# A bar or a percent next to the disk ring reads as "this camera filled X % of the disk".
def test_a_row_shows_no_percent_and_no_bar(tmp_path):
	out = render(tmp_path, {"A": 300, "B": 100})

	assert "%" not in row_of(out, "A")
	assert "camera-share" not in out


def test_a_camera_without_videos_says_so(tmp_path):
	out = render(tmp_path, {"A": 300, "B": 0})

	assert "keine Videos" in row_of(out, "B")
	assert "0.0 B Videos" not in row_of(out, "B")


def test_no_videos_at_all_says_so_for_every_camera(tmp_path):
	out = render(tmp_path, {"A": 0})

	assert "keine Videos" in row_of(out, "A")
