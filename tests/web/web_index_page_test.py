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


def test_every_camera_shows_its_size_and_share_of_all_videos(tmp_path):
	out = render(tmp_path, {"A": 300, "B": 100})

	assert "300.0 B" in row_of(out, "A")
	assert "75.0 %" in row_of(out, "A")
	assert "100.0 B" in row_of(out, "B")
	assert "25.0 %" in row_of(out, "B")


def test_the_bar_is_as_wide_as_the_share(tmp_path):
	out = render(tmp_path, {"A": 300, "B": 100})

	assert 'style="width: 75%"' in row_of(out, "A")
	assert 'style="width: 25%"' in row_of(out, "B")


def test_a_camera_without_videos_says_so_and_has_an_empty_bar(tmp_path):
	out = render(tmp_path, {"A": 300, "B": 0})

	assert "keine Videos" in row_of(out, "B")
	assert 'style="width: 0%"' in row_of(out, "B")


def test_no_videos_at_all_does_not_divide_by_zero(tmp_path):
	out = render(tmp_path, {"A": 0})

	assert "keine Videos" in row_of(out, "A")
