import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT

HELPERS = PROJECT_ROOT / "nas" / "helpers"
SCRIPTS = ["zip_extract.py", "seqzip_extract.py"]


def run_helper(script: str, tmp_path: Path, archive: str | None) -> subprocess.CompletedProcess:
	environment = {
		key: value for key, value in os.environ.items() if key != "TIMELAPSE_NAS_ARCHIVE"
	}
	# The helpers write below the home folder: never the real one.
	environment["HOME"] = str(tmp_path / "home")
	(tmp_path / "home").mkdir(exist_ok=True)

	if archive is not None:
		environment["TIMELAPSE_NAS_ARCHIVE"] = archive

	return subprocess.run(
		[sys.executable, str(HELPERS / script), "missing.zip", "Cam", "2004", "2008"],
		capture_output=True,
		text=True,
		env=environment,
		check=False,
		timeout=60,
	)


# The folder with the zips is a setting, not a path in the code: without it a helper stops with a
# message before it creates or reads anything.
@pytest.mark.parametrize("script", SCRIPTS)
def test_the_helper_needs_the_archive_folder(script, tmp_path):
	result = run_helper(script, tmp_path, archive=None)

	assert result.returncode != 0
	assert "TIMELAPSE_NAS_ARCHIVE" in result.stderr
	assert not (tmp_path / "home" / "nas-cameras").exists()


# The zip is looked up below the folder from the setting.
@pytest.mark.parametrize("script", SCRIPTS)
def test_the_helper_reads_the_zip_from_the_archive_folder(script, tmp_path):
	archive = tmp_path / "archive"
	archive.mkdir()

	result = run_helper(script, tmp_path, archive=str(archive))

	assert result.returncode != 0
	assert str(archive / "missing.zip") in result.stderr
