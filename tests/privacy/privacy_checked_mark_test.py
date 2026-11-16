import shutil
import subprocess
from pathlib import Path

import pytest

from src.privacy.checked_mark import add_mark, has_mark, remove_mark

# A minimal stand-in: start marker, some bytes, end marker.
IMAGE = b"\xff\xd8\xff\xe0 jfif and image data \xff\xd9"

# The contract with the website's pick-up job: these exact bytes, right after FF D8.
MARK_BYTES = b"\xff\xfe\x00\x13blur:checked=true"

requires_ffmpeg = pytest.mark.skipif(
	shutil.which("ffmpeg") is None, reason="FFmpeg is not installed."
)


def test_the_mark_sits_right_after_the_start_marker() -> None:
	marked = add_mark(IMAGE)

	assert marked[:2] == b"\xff\xd8"
	assert marked[2:23] == MARK_BYTES
	assert marked[23:] == IMAGE[2:]
	# The pick-up job reads no more than this.
	assert b"blur:checked=true" in marked[:32]


def test_removing_the_mark_gives_the_original_bytes_back() -> None:
	assert remove_mark(add_mark(IMAGE)) == IMAGE


def test_has_mark_only_trusts_the_fixed_position() -> None:
	assert has_mark(add_mark(IMAGE))
	assert not has_mark(IMAGE)
	# The same text anywhere else (camera comment, image data) is not our mark.
	assert not has_mark(IMAGE[:-2] + MARK_BYTES + b"\xff\xd9")


def test_an_image_is_never_marked_twice() -> None:
	with pytest.raises(ValueError, match="already"):
		add_mark(add_mark(IMAGE))


@pytest.mark.parametrize("data", [b"", b"\xff", b"GIF89a...", b"\x00\x00\xff\xd8"])
def test_only_a_jpeg_can_be_marked(data: bytes) -> None:
	with pytest.raises(ValueError, match="JPEG"):
		add_mark(data)


def test_an_unmarked_image_cannot_be_unmarked() -> None:
	with pytest.raises(ValueError, match="no mark"):
		remove_mark(IMAGE)


def _pixels_md5(path: Path) -> str:
	result = subprocess.run(
		["ffmpeg", "-v", "error", "-i", str(path), "-f", "md5", "-"],
		capture_output=True,
		text=True,
		check=True,
	)

	return result.stdout.strip()


# A real JPEG: the mark must not change a single decoded pixel.
@requires_ffmpeg
def test_a_marked_jpeg_decodes_to_the_same_pixels(tmp_path: Path) -> None:
	original = tmp_path / "original.jpg"
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-f",
			"lavfi",
			"-i",
			"testsrc=size=160x120",
			"-frames:v",
			"1",
			str(original),
		],
		check=True,
	)
	marked = tmp_path / "marked.jpg"
	marked.write_bytes(add_mark(original.read_bytes()))

	assert _pixels_md5(marked) == _pixels_md5(original)
