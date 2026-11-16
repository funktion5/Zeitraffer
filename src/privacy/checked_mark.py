"""The "checked" mark the website's pick-up job looks for (docs/verpixelung-box.md).

A JPEG comment segment with a fixed text, always directly after the start marker, so the pick-up
job only has to read the first bytes of a file. It changes no pixel: removing it gives back the
exact original bytes, which is how the writer proves a clean image was not altered otherwise.
"""

JPEG_START_MARKER = b"\xff\xd8"
MARK_TEXT = b"blur:checked=true"
# Comment marker, then the segment length (it counts its own two bytes), then the text.
MARK = b"\xff\xfe" + (len(MARK_TEXT) + 2).to_bytes(2, "big") + MARK_TEXT


def has_mark(data: bytes) -> bool:
	return data[:2] == JPEG_START_MARKER and data[2 : 2 + len(MARK)] == MARK


def add_mark(data: bytes) -> bytes:
	if not data.startswith(JPEG_START_MARKER):
		raise ValueError("Only a JPEG can carry the checked mark.")

	if has_mark(data):
		raise ValueError("The image already carries the checked mark.")

	return JPEG_START_MARKER + MARK + data[2:]


def remove_mark(data: bytes) -> bytes:
	if not has_mark(data):
		raise ValueError("The image has no mark to remove.")

	return JPEG_START_MARKER + data[2 + len(MARK) :]
