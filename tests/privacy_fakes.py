"""Shared fakes for the privacy tests: a storage box shell and a detector. Not collected."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest


# Runs a storage box command with real bash in a local folder: globs, ls and sha256sum
# behave as on the box. Patched in for StorageBox.run.
def run_in(folder: Path):
	def run(storage_box, command: str, timeout_seconds: float) -> subprocess.CompletedProcess:
		return subprocess.run(
			["bash", "-c", command],
			cwd=folder,
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			check=False,
		)

	return run


def sha(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


class FakeBox:
	"""Emulates the storage box's restricted shell (GNU coreutils output) over a local folder.

	Anything outside the commands BoxWriter is meant to use fails the test.
	"""

	def __init__(self, root: Path, remote: str) -> None:
		self.root = root
		self.remote = remote
		self.calls: list[list[str]] = []
		self.after_command = None
		self.fail_next: dict[str, subprocess.CompletedProcess] = {}
		self.corrupt_upload = False
		# Power cut on the Pi mid-copy: the box keeps half a file and SSH reports a lost link.
		self.cut_copy = False

	def path(self, remote_path: str) -> Path:
		return self.root / remote_path

	def __call__(self, argv: list[str], timeout_seconds: float) -> subprocess.CompletedProcess:
		self.calls.append(argv)

		if argv[0] == "scp":
			result = self._scp(argv)
		elif argv[0] == "ssh":
			assert argv[-2] == self.remote
			result = self._ssh(argv[-1])
		else:
			pytest.fail(f"Unexpected program: {argv}")

		if self.after_command is not None:
			self.after_command(argv)

		return result

	@staticmethod
	def result(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
		return subprocess.CompletedProcess([], code, stdout, stderr)

	def _ssh(self, command: str) -> subprocess.CompletedProcess:
		tokens = command.split(" ")
		verb = tokens[0]

		if verb in self.fail_next:
			return self.fail_next.pop(verb)

		if tokens[:2] == ["ls", "-1d"]:
			path = tokens[2]

			if self.path(path).exists():
				return self.result(0, f"{path}\n")

			return self.result(
				2, stderr=f"/usr/bin/ls: cannot access '{path}': No such file or directory\n"
			)

		if verb == "sha256sum":
			lines, errors = [], []

			for path in tokens[1:]:
				if self.path(path).is_file():
					lines.append(f"{sha(self.path(path).read_bytes())}  {path}")
				else:
					errors.append(f"/usr/bin/sha256sum: {path}: No such file or directory")

			return self.result(1 if errors else 0, "\n".join(lines) + "\n", "\n".join(errors))

		if verb == "mkdir":
			self.path(tokens[1]).mkdir()
			return self.result(0)

		if tokens[:2] == ["cp", "-T"]:
			if self.cut_copy:
				self.cut_copy = False
				self.path(tokens[3]).write_bytes(self.path(tokens[2]).read_bytes()[:5])
				return self.result(255, stderr="Connection to box closed")

			shutil.copyfile(self.path(tokens[2]), self.path(tokens[3]))
			return self.result(0)

		if tokens[:3] == ["mv", "-n", "-T"]:
			if not self.path(tokens[4]).exists():
				self.path(tokens[3]).replace(self.path(tokens[4]))

			return self.result(0)

		if tokens[:2] == ["mv", "-T"]:
			self.path(tokens[2]).replace(self.path(tokens[3]))
			return self.result(0)

		pytest.fail(f"Command not allowed on the fake box: {command}")

	def _scp(self, argv: list[str]) -> subprocess.CompletedProcess:
		source, target = argv[-2], argv[-1]

		# Download: box -> Pi.
		if ":" in source:
			remote, _, remote_path = source.partition(":")
			assert remote == self.remote

			if not self.path(remote_path).is_file():
				return self.result(1, stderr=f"scp: {remote_path}: No such file or directory")

			shutil.copyfile(self.path(remote_path), target)
			return self.result(0)

		local = source
		remote, _, remote_path = target.partition(":")
		assert remote == self.remote
		data = Path(local).read_bytes()

		if self.corrupt_upload:
			data = data[:-3] + b"\xff\xd9"

		self.path(remote_path).write_bytes(data)

		return self.result(0)

	def remote_commands(self) -> list[str]:
		return [argv[-1] for argv in self.calls if argv[0] == "ssh"]


# Stand-in for the real model: a box for every path whose name is listed in FAKE_PEOPLE.
FAKE_DETECTOR = """
import json
import os
import sys

paths = [line.strip() for line in sys.stdin if line.strip()]
log = os.environ.get("FAKE_DETECTOR_LOG")

if log and paths:
	with open(log, "a") as file:
		file.write("\\n".join(paths) + "\\n")

if sys.argv[1] == "fail" and paths:
	sys.exit(3)

# Simulates one image the detector cannot handle.
crash_on = os.environ.get("FAKE_CRASH_ON")

if crash_on and any(os.path.basename(path) == crash_on for path in paths):
	sys.exit(3)

# Simulates the camera rewriting the image while detection runs.
rewrite = os.environ.get("FAKE_REWRITE")

if rewrite and paths:
	with open(rewrite, "ab") as file:
		file.write(b"late-bytes\\xff\\xd9")

people = os.environ.get("FAKE_PEOPLE", "").split(",")
# Optional: the boxes reported for every listed image, as JSON [[x0, y0, x1, y1(, label)], ...].
boxes = json.loads(os.environ.get("FAKE_BOXES") or "[[1, 1, 5, 9]]")
results = {
	path: [
		{
			"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3], "score": 0.9,
			**({"label": b[4]} if len(b) > 4 else {}),
		}
		for b in boxes
	]
	if os.path.basename(path) in people else []
	for path in paths
}
print(json.dumps({"detector": "fake-1", "results": results}))
"""
