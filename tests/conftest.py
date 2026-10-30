import os
from pathlib import Path

import pytest

os.environ["TIMELAPSE_DISABLE_FILE_LOGGING"] = "1"
# A preset set on the machine running the tests (the web server) must not change expected commands.
os.environ.pop("TIMELAPSE_X264_PRESET", None)
os.environ.pop("TIMELAPSE_X264_CRF", None)
# Without TIMELAPSE_CAMERA_ROOT the box variable now selects the ssh source, so a box exported in
# the shell must never turn a test that forgot to patch the source into a run against the real box.
os.environ.pop("TIMELAPSE_STORAGE_BOX", None)
os.environ.pop("TIMELAPSE_FRAME_SOURCE", None)


# Job tests stub the image finders but still build a frame source for their cleanup. The old
# /mnt/cameras default gave them an empty local source; with no default folder each test gets the
# same harmless, nonexistent one. Tests of the unset case set CAMERA_ROOT to None themselves.
@pytest.fixture(autouse=True)
def nonexistent_camera_root(monkeypatch):
	import src.images as images_module

	monkeypatch.setattr(images_module, "CAMERA_ROOT", Path("/nonexistent-camera-root"))
