import ast
import subprocess
import sys
from pathlib import Path

import pytest

import src.images as images_module
import src.storage_box as storage_box_module
from src.config import PROJECT_ROOT
from src.storage_box import STORAGE_BOX_ENV, StorageBox, get_storage_box, parse_ls_output

# The storage box as the rest of the program meets it: its name from the environment, one read-only
# command over ssh, and the parsing of an `ls -l` listing.


# A developer shell may export the setting; these tests must not see it.
@pytest.fixture(autouse=True)
def no_storage_box_environment(monkeypatch):
	monkeypatch.delenv(STORAGE_BOX_ENV, raising=False)


def test_ls_output_keeps_regular_files_with_sizes():
	output = (
		"total 12\n"
		"-rw-r--r-- 1 u1 1108 157852 Aug 17 15:00 cam_250101_120000.jpg\n"
		"-rw-r--r-- 1 u1 1108      0 Aug 17  2024 cam_250101_121500.jpg\n"
		"-rw-r--r-- 1 u1 1108     42 Aug 17 15:00 name with spaces.jpg\n"
		"drwxr-xr-x 2 u1 1108   4096 Aug 17 15:00 archive\n"
		"lrwxrwxrwx 1 u1 1108     10 Aug 17 15:00 link.jpg -> other.jpg\n"
	)

	assert parse_ls_output(output) == {
		"cam_250101_120000.jpg": 157852,
		"cam_250101_121500.jpg": 0,
		"name with spaces.jpg": 42,
	}


def test_storage_box_comes_from_the_environment(monkeypatch):
	monkeypatch.setenv(STORAGE_BOX_ENV, "box")

	assert get_storage_box() == StorageBox("box", "")


def test_storage_box_environment_accepts_a_base_directory(monkeypatch):
	monkeypatch.setenv(STORAGE_BOX_ENV, "box:archive/cams")

	assert get_storage_box() == StorageBox("box", "archive/cams")


def test_storage_box_environment_without_alias_is_an_error(monkeypatch):
	monkeypatch.setenv(STORAGE_BOX_ENV, ":archive")

	with pytest.raises(OSError, match="ssh alias"):
		get_storage_box()


# There is no mount to fall back to: the error names the variable to set.
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_storage_box_setting_is_an_error(monkeypatch, value):
	if value is not None:
		monkeypatch.setenv(STORAGE_BOX_ENV, value)

	with pytest.raises(OSError, match=STORAGE_BOX_ENV):
		get_storage_box()


# The box no longer depends on the camera folder: a mount-like /proc/mounts line is never read.
def test_storage_box_ignores_the_camera_folder(monkeypatch):
	monkeypatch.setattr(images_module, "CAMERA_ROOT", Path("/mnt/cameras"))

	with pytest.raises(OSError, match=STORAGE_BOX_ENV):
		get_storage_box()


def test_commands_run_over_ssh_with_strict_host_checking(monkeypatch):
	calls = []

	def fake_run(command, **kwargs):
		calls.append(command)
		return subprocess.CompletedProcess(command, 0, stdout="")

	monkeypatch.setattr(storage_box_module.subprocess, "run", fake_run)

	StorageBox("user@box", "base/").run("ls -l 'base/Cam'", timeout_seconds=5)

	assert calls[0][0] == "ssh"
	assert calls[0][-2:] == ["user@box", "ls -l 'base/Cam'"]
	assert "StrictHostKeyChecking=yes" in calls[0]
	assert StorageBox("user@box", "base/").camera_directory("Cam") == "base/Cam"


# The module is the bottom of the dependency chain: frame_source, storage_filter and images all need
# it, so it must need none of them.
def test_the_module_imports_nothing_from_this_project():
	tree = ast.parse(Path(storage_box_module.__file__).read_text(encoding="utf-8"))
	imported = []

	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			imported += [alias.name for alias in node.names]
		elif isinstance(node, ast.ImportFrom):
			imported.append(("." * node.level) + (node.module or ""))

	assert not [name for name in imported if name.startswith((".", "src"))], imported


# frame_source used to reach the box through imports inside functions, to get round the cycle
# images -> frame_source -> storage_filter -> images. There is none left.
def test_the_frame_source_has_no_imports_inside_functions():
	tree = ast.parse(Path(PROJECT_ROOT / "src" / "frame_source.py").read_text(encoding="utf-8"))
	inside = [
		(function.name, node.lineno)
		for function in ast.walk(tree)
		if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
		for node in ast.walk(function)
		if isinstance(node, (ast.Import, ast.ImportFrom))
	]

	assert inside == []


# A fresh interpreter: loading the frame source must not pull in the modules that import it.
def test_loading_the_frame_source_does_not_load_images_or_the_storage_filter():
	code = (
		"import sys, src.frame_source; "
		"print(sorted(m for m in ('src.images', 'src.storage_filter') if m in sys.modules))"
	)

	result = subprocess.run(
		[sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
	)

	assert result.stdout.strip() == "[]"
