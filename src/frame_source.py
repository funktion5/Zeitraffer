import os
import secrets
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from src.config import PROJECT_ROOT
from src.logger import logger

if TYPE_CHECKING:
	from src.storage_filter import StorageBox

# One ssh listing sends no progress ticks, and the isolated worker running it is killed after
# image_scan_stall_timeout_seconds (60 in config.json) without one. This timeout has to fire first,
# or the worker is reported as stalled and the real error is hidden. A test pins the relation.
NAME_LISTING_TIMEOUT_SECONDS = 45

# The same worker is killed after 60 s without a progress tick, and a running rsync sends none. So
# everything that waits (the rsync itself, the pauses between retries) wakes up every
# HEARTBEAT_SECONDS to tick. rsync's own --timeout then ends a transfer that stopped moving bytes,
# and a worker killed on a stall leaves its rsync running, so the short idle timeout also bounds how
# long such an orphan can keep writing into the cache. The total limit only catches a trickling
# process. All of these are guesses until measured on the real box.
HEARTBEAT_SECONDS = 10
FETCH_RETRY_WAIT_SECONDS = (30, 120)
RSYNC_IDLE_TIMEOUT_SECONDS = 60
RSYNC_TOTAL_TIMEOUT_SECONDS = 60 * 60


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


# Fetched frames are unblurred, so they live in a folder of their own under temp/ that only this
# user can read. The folder is chosen once per run and handed to every worker process through the
# environment: a worker started with "spawn" (macOS) shares no module variables, and a root chosen
# inside a worker would never reach the parent, whose cleanup would then find nothing.
FRAME_CACHE_ENV = "TIMELAPSE_FRAME_CACHE"
FRAME_CACHE_MARKER = ".frame-cache"


# Only names the folder: nothing is created on disk until frames are fetched, so a run that merely
# lists leaves nothing behind.
def frame_cache_root(project_root: Path) -> Path:
	configured = os.environ.get(FRAME_CACHE_ENV)

	if configured:
		return Path(configured)

	root = project_root / "temp" / "frame-cache" / f"{os.getpid()}-{secrets.token_hex(4)}"
	os.environ[FRAME_CACHE_ENV] = str(root)

	return root


# The marker lets the guarded cleanup tell this folder from any other under temp/.
def create_frame_cache(root: Path) -> None:
	root.mkdir(mode=0o700, parents=True, exist_ok=True)
	root.chmod(0o700)
	(root / FRAME_CACHE_MARKER).touch()


# A folder that is already gone is fine (a job that failed before it fetched anything, or a second
# release). Any other failure is raised: frames left behind unnoticed would be unblurred.
def _remove(path: Path) -> None:
	try:
		shutil.rmtree(path)

	except FileNotFoundError:
		pass


# Ticks while waiting: a retry wait longer than the stall timeout would otherwise get the worker
# killed as "stalled" before the retry happens.
def _sleep_with_progress(seconds: float, progress_callback: Callable[[], None] | None) -> None:
	remaining = seconds

	while remaining > 0:
		step = min(remaining, HEARTBEAT_SECONDS)
		time.sleep(step)
		remaining -= step

		if progress_callback is not None:
			progress_callback()


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
# this machine and removed again by release().
@dataclass(frozen=True)
class SshFrameSource:
	box: "StorageBox"
	cache_root: Path
	# release() only ever deletes strictly inside this folder, see _guarded_root.
	temp_root: Path = PROJECT_ROOT / "temp"

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

	# Fetch what is not in the cache yet. A call never removes a file it did not fetch (manual
	# Weekly localizes once per day); only a camera that fails for good loses its whole folder,
	# because a half-fetched camera must never be handed on.
	def localize(
		self, camera: str, paths: list[Path], progress_callback: Callable[[], None] | None = None
	) -> None:
		camera_directory = self.cache_root / checked_name(camera)
		names = sorted({checked_name(path.name) for path in paths})

		if not self._missing(camera_directory, names):
			return

		create_frame_cache(self.cache_root)
		camera_directory.mkdir(exist_ok=True)

		for wait_seconds in (*FETCH_RETRY_WAIT_SECONDS, None):
			try:
				self._fetch(camera, camera_directory, names, progress_callback)
				return

			except OSError as error:
				if wait_seconds is None:
					shutil.rmtree(camera_directory, ignore_errors=True)
					raise FrameFetchError(f"Could not fetch {camera}: {error}") from error

				logger.warning(
					f"Fetching camera {camera} failed, retrying in {wait_seconds} s: {error}"
				)
				_sleep_with_progress(wait_seconds, progress_callback)

	def _missing(self, camera_directory: Path, names: list[str]) -> list[str]:
		return [name for name in names if not (camera_directory / name).exists()]

	def _fetch(
		self,
		camera: str,
		camera_directory: Path,
		names: list[str],
		progress_callback: Callable[[], None] | None,
	) -> None:
		# Recomputed on every attempt: a retry only fetches what the failed one did not deliver.
		missing = self._missing(camera_directory, names)

		# Pulls from the box into the cache, never the other way round (tested, and enforced by the
		# structural guard in tests/privacy_box_writer_test.py).
		command = [
			"rsync",
			"-t",
			"--from0",
			"--files-from=-",
			f"--timeout={RSYNC_IDLE_TIMEOUT_SECONDS}",
			"-e",
			"ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
			f"{self.box.remote}:{self.box.camera_directory(camera)}/",
			f"{camera_directory}/",
		]
		started = time.monotonic()

		try:
			process = subprocess.Popen(
				command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
			)

		except OSError as error:
			raise FrameFetchError(f"rsync could not start for camera {camera}: {error}") from error

		# One rsync for everything the job needs. The names go in with the first call; a call that
		# times out loses nothing, the next one carries on.
		pending_input = "\0".join(missing).encode() + b"\0"

		while True:
			try:
				_, stderr = process.communicate(pending_input, timeout=HEARTBEAT_SECONDS)
				break

			except subprocess.TimeoutExpired:
				pending_input = None

				if time.monotonic() - started > RSYNC_TOTAL_TIMEOUT_SECONDS:
					process.kill()
					process.communicate()
					raise FrameFetchError(f"rsync did not finish for camera {camera}") from None

				if progress_callback is not None:
					progress_callback()

		if process.returncode != 0:
			raise FrameFetchError(
				f"rsync failed for camera {camera} (exit {process.returncode}): "
				f"{stderr.decode(errors='replace').strip()}"
			)

		elapsed = time.monotonic() - started
		logger.info(f"Camera {camera}: fetched {len(missing)} frames in {elapsed:.1f} s")

	# Drops this run's fetched copies of one camera. The caller does it when the camera's job is
	# done, also after a failure: the frames are unblurred.
	def release(self, camera: str) -> None:
		try:
			checked_name(camera)

		except FrameFetchError as error:
			raise ValueError(f"Unsafe camera name: {camera!r}") from error

		root = self._guarded_root()

		if root is not None:
			_remove(root / camera)

	def release_all(self) -> None:
		root = self._guarded_root()

		if root is not None:
			_remove(root)

	# Deleting is only ever allowed strictly inside temp/, after resolving symlinks and "..", and
	# only in a folder that carries the marker, so a wrong cache_root can never wipe anything else.
	# None means there is nothing to release.
	def _guarded_root(self) -> Path | None:
		if not self.cache_root.exists():
			return None

		root = self.cache_root.resolve()

		if self.temp_root.resolve() not in root.parents:
			raise ValueError(f"Frame cache must be inside {self.temp_root}: {root}")

		if not (root / FRAME_CACHE_MARKER).is_file():
			raise ValueError(f"Not a frame cache folder (marker missing): {root}")

		return root

	def _ls(self, directory: str, what: str) -> str:
		try:
			result = self.box.run(f"ls -l {shlex.quote(directory)}", NAME_LISTING_TIMEOUT_SECONDS)

		except subprocess.TimeoutExpired as error:
			raise TimeoutError(f"Storage box {what} timed out") from error

		if result.returncode != 0:
			raise FrameFetchError(f"Storage box {what} failed: {result.stderr.strip()}")

		return result.stdout


FRAME_SOURCE_ENV = "TIMELAPSE_FRAME_SOURCE"


# "ssh" is a switch of its own, not implied by TIMELAPSE_STORAGE_BOX: that one is already set on
# hosts for the blur jobs and must not change where the frames come from. Decided here, not in
# src/images.py, because the structural test in tests/privacy_box_writer_test.py lists every module
# that mentions ssh, and the big images module should not be one of them.
def build_frame_source(camera_root: Path, project_root: Path) -> FrameSource:
	kind = os.environ.get(FRAME_SOURCE_ENV) or "local"

	if kind == "local":
		return LocalFrameSource(camera_root)

	if kind == "ssh":
		# Imported here: storage_filter imports src.images, which imports this module.
		from src.storage_filter import get_storage_box

		return SshFrameSource(
			get_storage_box(), frame_cache_root(project_root), project_root / "temp"
		)

	raise ValueError(f"{FRAME_SOURCE_ENV} must be 'local' or 'ssh', not {kind!r}")
