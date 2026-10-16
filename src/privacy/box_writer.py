"""The only code allowed to write to the storage box.

Everything else reads the camera images through the read-only mount. This module writes over SSH
with exactly three operations - back up an image, upload a blurred copy under a temporary name,
swap it in - and nothing else: no delete, no general "run a command" function.

Safety rules, in the order they are enforced:
- Cameras must be in the allow-list given at construction (``privacy.blur_cameras`` later).
- Camera and file names must match a strict character set and a known image filename format, so
  every remote command is built from plain tokens and never needs shell quoting.
- Backups are content-addressed (``original/<stem>.<sha16>.jpg``). They are copied to a hidden
  temporary name, verified, and only then renamed with ``mv -n``: a power cut mid-copy leaves at
  most a temporary file that the next round overwrites, never a broken backup under the final
  name, and an existing backup is never overwritten.
- Every write is verified by SHA-256 afterwards; the image is only replaced while the image
  itself and its backup still hash to the recorded original.
- "File missing" is only believed when the box says so explicitly; any other failure stops.
- Proportion: only images whose filename time lies in the last ``max_image_age`` are backed up,
  and at most ``max_backups_per_camera`` per run - independent of whatever scan feeds this.
"""

import hashlib
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import PROJECT_ROOT
from src.images import extract_date, extract_time, image_moment
from src.logger import logger

BACKUP_DIRECTORY_NAME = "original"
DEFAULT_UPLOAD_ROOT = PROJECT_ROOT / "temp"

COMMAND_TIMEOUT_SECONDS = 30
UPLOAD_TIMEOUT_SECONDS = 120
BACKUP_HASH_LENGTH = 16

# Covers every daytime image of the current day. Night images never get here.
DEFAULT_MAX_IMAGE_AGE = timedelta(hours=24)
# Camera clocks drift; anything further ahead than this is an anomaly, not a new image.
DEFAULT_MAX_IMAGE_AHEAD = timedelta(hours=2)
# About twice the busiest camera's full day (SLSV: 144 images).
DEFAULT_MAX_BACKUPS_PER_CAMERA = 300

# ssh and scp report their own (connection) failures with this exit status.
SSH_FAILURE_STATUS = 255

CAMERA_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
IMAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.jpg")
REMOTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")

# Last line of defence: every path of a remote command must look like this.
SAFE_PATH = re.compile(r"/?[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
ALLOWED_REMOTE_COMMANDS = {
	("ls", "-1d"),
	("sha256sum",),
	("mkdir",),
	# Overwrites, so only ever onto our own hidden ".tmp" names (checked in _remote).
	("cp", "-T"),
	# Backup temporary -> final backup name, never over an existing file.
	("mv", "-n", "-T"),
	# Uploaded blurred temporary -> image name: the one deliberate overwrite.
	("mv", "-T"),
}

JPEG_START_MARKER = b"\xff\xd8"
JPEG_END_MARKER = b"\xff\xd9"
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]

Runner = Callable[[list[str], float], subprocess.CompletedProcess]
Clock = Callable[[], datetime]


class BoxWriteRefused(ValueError):
	"""An argument failed validation; nothing was sent to the box."""


class BoxWriteDeferred(BoxWriteRefused):
	"""Refused for now (count limit, timestamp ahead of the clock); a later round may succeed."""


class BoxWriteError(OSError):
	"""The box did not confirm an operation; the image must be left as it is."""


@dataclass(frozen=True)
class Backup:
	camera: str
	name: str
	backup_name: str
	sha256: str


def _run_subprocess(argv: list[str], timeout_seconds: float) -> subprocess.CompletedProcess:
	return subprocess.run(
		argv,
		capture_output=True,
		text=True,
		timeout=timeout_seconds,
		check=False,
	)


def check_camera_name(camera: str) -> None:
	if not CAMERA_NAME.fullmatch(camera):
		raise BoxWriteRefused(f"Unsafe camera name: {camera!r}")

	if camera == BACKUP_DIRECTORY_NAME:
		raise BoxWriteRefused(f"Camera name is reserved: {camera!r}")


# Unknown filename formats are never guessed, and never written to.
def check_image_name(name: str) -> None:
	if not IMAGE_NAME.fullmatch(name):
		raise BoxWriteRefused(f"Unsafe image name: {name!r}")

	if extract_date(name) is None or extract_time(name) is None:
		raise BoxWriteRefused(f"Unknown image filename format: {name!r}")


def _is_safe_path(path: str) -> bool:
	return (
		SAFE_PATH.fullmatch(path) is not None
		and not path.startswith("-")
		and not {".", ".."} & set(path.split("/"))
	)


def _is_temporary(path: str) -> bool:
	name = path.rsplit("/", 1)[-1]

	return name.startswith(".") and name.endswith(".tmp")


def _check_remote_path(path: str) -> None:
	if not _is_safe_path(path):
		raise BoxWriteRefused(f"Unsafe remote path: {path!r}")


# Content-addressed: the same backup name always stands for the same bytes.
def _backup_name(name: str, sha256: str) -> str:
	return f"{Path(name).stem}.{sha256[:BACKUP_HASH_LENGTH]}.jpg"


class BoxWriter:
	def __init__(
		self,
		remote: str,
		base_directory: str,
		allowed_cameras: Sequence[str],
		timezone: str,
		upload_root: Path = DEFAULT_UPLOAD_ROOT,
		max_image_age: timedelta = DEFAULT_MAX_IMAGE_AGE,
		max_image_ahead: timedelta = DEFAULT_MAX_IMAGE_AHEAD,
		max_backups_per_camera: int = DEFAULT_MAX_BACKUPS_PER_CAMERA,
		runner: Runner = _run_subprocess,
		clock: Clock | None = None,
	) -> None:
		if not REMOTE.fullmatch(remote):
			raise BoxWriteRefused(f"Unsafe storage box remote: {remote!r}")

		# "" is the box user's home; "/" alone would be the box root and is refused.
		if base_directory and not _is_safe_path(base_directory.rstrip("/")):
			raise BoxWriteRefused(f"Unsafe storage box base directory: {base_directory!r}")

		self.remote = remote
		self.base_directory = base_directory.rstrip("/")

		allowed = frozenset(allowed_cameras)

		if not allowed:
			raise BoxWriteRefused("No cameras are allowed for writing")

		for camera in allowed:
			check_camera_name(camera)

		if (
			max_backups_per_camera < 1
			or max_image_age <= timedelta(0)
			or max_image_ahead < timedelta(0)
		):
			raise BoxWriteRefused("Limits must be positive")

		# An unknown zone fails here, at start-up, not on the first image.
		ZoneInfo(timezone)

		self.allowed_cameras = allowed
		self.timezone = timezone
		self.upload_root = upload_root.resolve()
		self.max_image_age = max_image_age
		self.max_image_ahead = max_image_ahead
		self.max_backups_per_camera = max_backups_per_camera
		self._runner = runner
		self._clock = clock or (lambda: datetime.now(ZoneInfo(timezone)))
		self._backups_per_camera: dict[str, int] = {}

	# Remote paths are built here and nowhere else.

	def _camera_directory(self, camera: str) -> str:
		check_camera_name(camera)

		if camera not in self.allowed_cameras:
			raise BoxWriteRefused(f"Camera is not allowed for writing: {camera!r}")

		if not self.base_directory:
			return camera

		return f"{self.base_directory}/{camera}"

	def _image_path(self, camera: str, name: str) -> str:
		check_image_name(name)

		return f"{self._camera_directory(camera)}/{name}"

	def _backup_directory(self, camera: str) -> str:
		return f"{self._camera_directory(camera)}/{BACKUP_DIRECTORY_NAME}"

	def _backup_path(self, backup: Backup) -> str:
		if not SHA256.fullmatch(backup.sha256) or backup.backup_name != _backup_name(
			backup.name, backup.sha256
		):
			raise BoxWriteRefused(f"Backup record does not match its image: {backup!r}")

		return f"{self._backup_directory(backup.camera)}/{backup.backup_name}"

	# Hidden and without .jpg suffix, so neither the timelapse scan nor a "*.jpg" picker
	# sees a half-written file.
	def _temporary_path(self, camera: str, name: str) -> str:
		check_image_name(name)

		return f"{self._camera_directory(camera)}/.{name}.tmp"

	# Remote commands.

	def _run(
		self, argv: list[str], timeout_seconds: float, action: str
	) -> subprocess.CompletedProcess:
		try:
			result = self._runner(argv, timeout_seconds)

		except subprocess.TimeoutExpired as error:
			raise TimeoutError(f"{action} timed out on the storage box") from error

		if result.returncode == SSH_FAILURE_STATUS:
			raise BoxWriteError(f"SSH to the storage box failed: {result.stderr.strip()}")

		return result

	def _remote(self, verb: tuple[str, ...], paths: Sequence[str]) -> subprocess.CompletedProcess:
		if verb not in ALLOWED_REMOTE_COMMANDS:
			raise BoxWriteRefused(f"Remote command is not allowed: {verb!r}")

		if not paths:
			raise BoxWriteRefused(f"Remote command without paths: {verb!r}")

		for path in paths:
			_check_remote_path(path)

		if verb == ("cp", "-T") and not _is_temporary(paths[-1]):
			raise BoxWriteRefused(f"cp may only overwrite a temporary file: {paths[-1]!r}")

		# Every token is from a fixed set or matched SAFE_PATH, so plain spaces are enough;
		# the box's restricted shell has no quoting rules to rely on.
		command = " ".join([*verb, *paths])

		return self._run(
			["ssh", *SSH_OPTIONS, self.remote, command], COMMAND_TIMEOUT_SECONDS, command
		)

	# True only if the box lists the path, False only if it explicitly says it does not exist.
	# A wrong "missing" could otherwise lead to writing over something that is there.
	def _exists(self, path: str) -> bool:
		result = self._remote(("ls", "-1d"), [path])

		if result.returncode == 0 and result.stdout.strip() == path:
			return True

		if result.returncode != 0 and "No such file or directory" in result.stderr:
			return False

		raise BoxWriteError(f"Could not tell whether {path} exists: {result.stderr.strip()}")

	def _hashes(self, paths: Sequence[str]) -> dict[str, str]:
		result = self._remote(("sha256sum",), paths)

		if result.returncode != 0:
			raise BoxWriteError(f"Hashing failed on the storage box: {result.stderr.strip()}")

		hashes: dict[str, str] = {}

		for line in result.stdout.splitlines():
			digest, separator, path = line.partition("  ")

			if separator and SHA256.fullmatch(digest):
				hashes[path] = digest

		if set(hashes) != set(paths):
			raise BoxWriteError(f"Unexpected sha256sum output: {result.stdout.strip()!r}")

		return hashes

	@staticmethod
	def _check_command(result: subprocess.CompletedProcess, action: str) -> None:
		if result.returncode != 0:
			raise BoxWriteError(f"{action} failed on the storage box: {result.stderr.strip()}")

	# Read-only: the image's hash on the box, e.g. to confirm the detector judged these bytes.
	def image_hash(self, camera: str, name: str) -> str:
		image_path = self._image_path(camera, name)

		return self._hashes([image_path])[image_path]

	# Read-only: may this image be written at all (camera, name, time window)? Lets a round refuse
	# an image before spending a detection on it. Contacts nothing.
	def check(self, camera: str, name: str) -> None:
		self._image_path(camera, name)
		moment = image_moment(name, self.timezone)
		now = self._clock()

		if moment is None:
			raise BoxWriteRefused(f"Unknown image filename format: {name!r}")

		if moment < now - self.max_image_age:
			raise BoxWriteRefused(f"{name} is older than {self.max_image_age}; not touching it")

		if moment > now + self.max_image_ahead:
			raise BoxWriteDeferred(f"{name} lies in the future ({moment:%Y-%m-%d %H:%M})")

	# Read-only: does the camera folder exist on the box? A missing folder would otherwise just
	# list as "no images".
	def camera_exists(self, camera: str) -> bool:
		return self._exists(self._camera_directory(camera))

	# Read-only: copy an image from the box into the work folder. The judged bytes come from where
	# they will be written, never from the SSHFS mount, which can hang or serve stale data.
	def fetch(self, camera: str, name: str, local_file: Path) -> None:
		image_path = self._image_path(camera, name)
		_check_remote_path(image_path)
		local = local_file.resolve()

		if not local.is_relative_to(self.upload_root):
			raise BoxWriteRefused(f"Download target is outside {self.upload_root}: {local}")

		argv = ["scp", "-q", *SSH_OPTIONS, f"{self.remote}:{image_path}", str(local)]
		action = f"Download of {name}"
		self._check_command(self._run(argv, UPLOAD_TIMEOUT_SECONDS, action), action)

	# The three write operations.

	def backup(self, camera: str, name: str, expected_sha256: str) -> Backup:
		"""Copy the image to ``original/`` and return the verified backup.

		``expected_sha256`` is the hash of the bytes that were judged; if the image on the box is
		anything else, nothing is written.
		"""
		image_path = self._image_path(camera, name)
		self.check(camera, name)

		if self._backups_per_camera.get(camera, 0) >= self.max_backups_per_camera:
			raise BoxWriteDeferred(
				f"[{camera}] Limit of {self.max_backups_per_camera} backups per run reached"
			)

		original_hash = self._hashes([image_path])[image_path]

		if original_hash != expected_sha256:
			raise BoxWriteError(f"{name} on the box differs from the checked copy; retrying.")

		self._backups_per_camera[camera] = self._backups_per_camera.get(camera, 0) + 1
		backup = Backup(
			camera=camera,
			name=name,
			backup_name=_backup_name(name, original_hash),
			sha256=original_hash,
		)
		backup_directory = self._backup_directory(camera)
		backup_path = self._backup_path(backup)

		if not self._exists(backup_directory):
			self._check_command(self._remote(("mkdir",), [backup_directory]), "mkdir")
			logger.info(f"[{camera}] Created backup directory {backup_directory}")

		if not self._exists(backup_path):
			staging_path = f"{backup_directory}/.{backup.backup_name}.tmp"
			self._check_command(
				self._remote(("cp", "-T"), [image_path, staging_path]),
				f"Backup of {name}",
			)

			if self._hashes([staging_path])[staging_path] != original_hash:
				raise BoxWriteError(f"{name} changed while it was being backed up")

			self._check_command(
				self._remote(("mv", "-n", "-T"), [staging_path, backup_path]),
				f"Finishing backup of {name}",
			)
			logger.info(f"[{camera}] Backed up {name} as {backup.backup_name}")

		hashes = self._hashes([image_path, backup_path])

		if hashes[backup_path] != original_hash:
			raise BoxWriteError(f"Backup of {name} does not match the original")

		if hashes[image_path] != original_hash:
			raise BoxWriteError(f"{name} changed while it was being backed up")

		return backup

	def upload_blurred(self, backup: Backup, local_file: Path) -> str:
		"""Upload the blurred image under its temporary name and return its verified hash."""
		local = local_file.resolve()

		if not local.is_relative_to(self.upload_root):
			raise BoxWriteRefused(f"Upload source is outside {self.upload_root}: {local}")

		# Read once: ~200 KB per image, so checking and hashing the same bytes is cheap.
		data = local.read_bytes() if local.is_file() else b""

		if len(data) < 4 or not (
			data.startswith(JPEG_START_MARKER) and data.endswith(JPEG_END_MARKER)
		):
			raise BoxWriteRefused(f"Upload source is not a complete JPEG: {local}")

		# Validates the backup record before anything leaves the Pi.
		self._backup_path(backup)
		temporary_path = self._temporary_path(backup.camera, backup.name)
		_check_remote_path(temporary_path)
		blurred_hash = hashlib.sha256(data).hexdigest()

		if blurred_hash == backup.sha256:
			raise BoxWriteRefused(f"Blurred copy of {backup.name} is identical to the original")

		# An absolute local path is never mistaken for host:path by scp.
		argv = ["scp", "-q", *SSH_OPTIONS, str(local), f"{self.remote}:{temporary_path}"]
		action = f"Upload of {backup.name}"
		self._check_command(self._run(argv, UPLOAD_TIMEOUT_SECONDS, action), action)

		if self._hashes([temporary_path])[temporary_path] != blurred_hash:
			raise BoxWriteError(f"Uploaded copy of {backup.name} does not match the local file")

		return blurred_hash

	def replace(self, backup: Backup, blurred_hash: str) -> None:
		"""Swap the uploaded blurred copy in, if image and backup are still the original."""
		if not SHA256.fullmatch(blurred_hash):
			raise BoxWriteRefused(f"Invalid blurred hash for {backup.name}")

		if blurred_hash == backup.sha256:
			raise BoxWriteRefused(f"Blurred hash of {backup.name} equals the original")

		image_path = self._image_path(backup.camera, backup.name)
		backup_path = self._backup_path(backup)
		temporary_path = self._temporary_path(backup.camera, backup.name)
		hashes = self._hashes([image_path, backup_path, temporary_path])

		if hashes[backup_path] != backup.sha256:
			raise BoxWriteError(f"Backup of {backup.name} no longer matches; not replacing")

		if hashes[image_path] != backup.sha256:
			raise BoxWriteError(f"{backup.name} changed since its backup; not replacing")

		if hashes[temporary_path] != blurred_hash:
			raise BoxWriteError(f"Uploaded copy of {backup.name} changed; not replacing")

		self._check_command(
			self._remote(("mv", "-T"), [temporary_path, image_path]),
			f"Replacing {backup.name}",
		)

		if self._hashes([image_path])[image_path] != blurred_hash:
			raise BoxWriteError(f"{backup.name} does not hold the blurred copy after replacing")

		logger.info(f"[{backup.camera}] Replaced {backup.name} with its blurred copy")
