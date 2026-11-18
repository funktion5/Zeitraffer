import os
import subprocess
from dataclasses import dataclass

# The Storage Box: its name from the environment, one read-only command over ssh, and the parsing of
# an `ls -l` listing. It imports nothing from this project, so frame_source, storage_filter and
# images can all use it without a cycle.

# The storage box is named here as "<ssh alias>[:<base directory>]".
# The alias carries user, port and key via ~/.ssh/config, so none of them is in the repository.
STORAGE_BOX_ENV = "TIMELAPSE_STORAGE_BOX"


@dataclass(frozen=True)
class StorageBox:
	remote: str
	base_directory: str

	def camera_directory(self, camera: str) -> str:
		if not self.base_directory:
			return camera

		return f"{self.base_directory.rstrip('/')}/{camera}"

	# Run one read-only command on the storage box's own shell. User, host, port and key come from
	# the alias in the user's ~/.ssh/config, so none of them is in the repository.
	def run(self, command: str, timeout_seconds: float) -> subprocess.CompletedProcess:
		return subprocess.run(
			[
				"ssh",
				"-o",
				"BatchMode=yes",
				"-o",
				"StrictHostKeyChecking=yes",
				self.remote,
				command,
			],
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			check=False,
		)


# Return the storage box named by the environment. There is no mount to read it from any more.
def get_storage_box() -> StorageBox:
	configured = os.environ.get(STORAGE_BOX_ENV, "").strip()

	if not configured:
		raise OSError(f"{STORAGE_BOX_ENV} is not set")

	remote, _, base_directory = configured.partition(":")

	if not remote:
		raise OSError(f"{STORAGE_BOX_ENV} must start with an ssh alias or user@host")

	return StorageBox(remote=remote, base_directory=base_directory)


# Map regular file names to their size from `ls -l` output.
def parse_ls_output(output: str) -> dict[str, int]:
	file_sizes: dict[str, int] = {}

	for line in output.splitlines():
		fields = line.split(maxsplit=8)

		# The "total" line, directories and symlinks are skipped.
		if len(fields) < 9 or not fields[0].startswith("-"):
			continue

		file_sizes[fields[8]] = int(fields[4])

	return file_sizes
