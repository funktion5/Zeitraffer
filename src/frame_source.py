import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


# Frames of one camera could not be listed or fetched. An OSError, so the jobs treat it as an
# operational failure of that camera, not as a bug.
class FrameFetchError(OSError):
	pass


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
