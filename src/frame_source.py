import os
import shlex
import subprocess
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
	from src.storage_filter import StorageBox

# One ssh listing sends no progress ticks, and the isolated worker running it is killed after
# image_scan_stall_timeout_seconds (60 in config.json) without one. This timeout has to fire first,
# or the worker is reported as stalled and the real error is hidden. A test pins the relation.
NAME_LISTING_TIMEOUT_SECONDS = 45


# Frames of one camera could not be listed or fetched. An OSError, so the jobs treat it as an
# operational failure of that camera, not as a bug.
class FrameFetchError(OSError):
	pass


# Names from the storage box are data from a remote system and end up in local paths and the rsync
# file list. Anything that could leave the cache folder, be read as an option, or fake a second
# `ls -l` line is refused loudly, not cleaned up.
def checked_name(name: str) -> str:
	unsafe = not name or not name.isprintable() or "/" in name or name in (".", "..")

	if unsafe or name.startswith("-"):
		raise FrameFetchError(f"Refusing unsafe name from the storage box: {name!r}")

	return name


# Where camera frames come from. The frame-reading code asks a source for names and paths and
# calls localize() before it reads bytes, so it does not care whether the files are already local
# or have to be fetched first. This module must not import src.images or src.storage_filter at
# module level (circular imports).
class FrameSource(Protocol):
	def list_cameras(self) -> list[str]: ...

	# Iterable, not list: a slow source must be able to hand names over while it is still listing,
	# because the progress ticks that keep a scan alive are driven by the names arriving.
	def list_names(self, camera: str) -> Iterable[str]: ...

	def path_for(self, camera: str, name: str) -> Path: ...

	# Make the files exist locally; raises FrameFetchError if that is not possible.
	def localize(
		self, camera: str, paths: list[Path], progress_callback: Callable[[], None] | None = None
	) -> None: ...

	# Drop fetched copies of one camera.
	def release(self, camera: str) -> None: ...


# Frames in an ordinary folder tree: today's behaviour. Nothing to fetch, nothing to clean up.
@dataclass(frozen=True)
class LocalFrameSource:
	root: Path

	def list_cameras(self) -> list[str]:
		return sorted(
			path.name
			for path in self.root.iterdir()
			if path.is_dir() and not path.name.startswith(".")
		)

	def list_names(self, camera: str) -> Iterator[str]:
		with os.scandir(self.root / camera) as entries:
			for entry in entries:
				yield entry.name

	def path_for(self, camera: str, name: str) -> Path:
		return self.root / camera / name

	def localize(
		self, camera: str, paths: list[Path], progress_callback: Callable[[], None] | None = None
	) -> None:
		pass

	def release(self, camera: str) -> None:
		pass


# Frames on the Storage Box: names are listed over ssh, files are fetched into a cache folder on
# this machine. Listing only here; fetching and cleanup follow in the next tasks.
@dataclass(frozen=True)
class SshFrameSource:
	box: "StorageBox"
	cache_root: Path

	def list_cameras(self) -> list[str]:
		output = self._ls(self.box.base_directory or ".", "camera listing")
		cameras = []

		for line in output.splitlines():
			fields = line.split(maxsplit=8)

			if len(fields) == 9 and fields[0].startswith("d"):
				cameras.append(checked_name(fields[8]))

		return sorted(cameras)

	def list_names(self, camera: str) -> list[str]:
		# Imported here: storage_filter imports src.images, which imports this module.
		from src.storage_filter import parse_ls_output

		checked_name(camera)
		output = self._ls(self.box.camera_directory(camera), f"listing for camera {camera}")

		return [checked_name(name) for name in parse_ls_output(output)]

	def path_for(self, camera: str, name: str) -> Path:
		return self.cache_root / checked_name(camera) / checked_name(name)

	def _ls(self, directory: str, what: str) -> str:
		try:
			result = self.box.run(f"ls -l {shlex.quote(directory)}", NAME_LISTING_TIMEOUT_SECONDS)

		except subprocess.TimeoutExpired as error:
			raise TimeoutError(f"Storage box {what} timed out") from error

		if result.returncode != 0:
			raise FrameFetchError(f"Storage box {what} failed: {result.stderr.strip()}")

		return result.stdout
