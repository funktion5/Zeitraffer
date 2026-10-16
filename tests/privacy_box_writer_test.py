import ast
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from privacy_fakes import FakeBox
from privacy_fakes import sha as _sha
from src.config import PROJECT_ROOT
from src.privacy.box_writer import (
	ALLOWED_REMOTE_COMMANDS,
	Backup,
	BoxWriteError,
	BoxWriter,
	BoxWriteRefused,
)

REMOTE = "user@box.example"
CAMERA = "TestCam"
OTHER_CAMERA = "OtherCam"
NAME = "20261015T120000.jpg"
TIMEZONE = "Europe/Berlin"
NOW = datetime(2026, 10, 15, 13, 0, tzinfo=ZoneInfo(TIMEZONE))
ORIGINAL = b"\xff\xd8original-bytes\xff\xd9"
BLURRED = b"\xff\xd8blurred-bytes\xff\xd9"
WRITE_VERBS = {"cp", "mv", "mkdir", "rm", "unlink", "rmdir", "dd", "touch", "chmod"}


@pytest.fixture
def box(tmp_path: Path) -> FakeBox:
	root = tmp_path / "box"
	(root / CAMERA).mkdir(parents=True)
	(root / OTHER_CAMERA).mkdir()
	(root / CAMERA / NAME).write_bytes(ORIGINAL)
	(root / OTHER_CAMERA / NAME).write_bytes(ORIGINAL)

	return FakeBox(root, REMOTE)


@pytest.fixture
def upload_root(tmp_path: Path) -> Path:
	root = tmp_path / "temp"
	root.mkdir()

	return root


@pytest.fixture
def writer(box: FakeBox, upload_root: Path) -> BoxWriter:
	return _writer(box, upload_root)


def _writer(box, upload_root: Path, cameras=(CAMERA,), base="", now=NOW, **limits) -> BoxWriter:
	return BoxWriter(
		REMOTE,
		base,
		list(cameras),
		TIMEZONE,
		upload_root=upload_root,
		runner=box,
		clock=lambda: now,
		**limits,
	)


@pytest.fixture
def blurred_file(upload_root: Path) -> Path:
	path = upload_root / NAME
	path.write_bytes(BLURRED)

	return path


# The hash a caller judged: the image's current bytes (any value if the name is never reached).
def _current_hash(box: FakeBox, camera: str, name: str) -> str:
	path = box.path(f"{camera}/{name}")

	return _sha(path.read_bytes()) if "/" not in name and path.is_file() else "0" * 64


def _backup_path(box: FakeBox, backup: Backup) -> Path:
	return box.path(f"{CAMERA}/original/{backup.backup_name}")


def test_full_cycle_replaces_image_and_keeps_verified_original(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	blurred_hash = writer.upload_blurred(backup, blurred_file)
	writer.replace(backup, blurred_hash)

	assert backup.backup_name == f"20261015T120000.{_sha(ORIGINAL)[:16]}.jpg"
	assert _backup_path(box, backup).read_bytes() == ORIGINAL
	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == BLURRED
	assert not box.path(f"{CAMERA}/.{NAME}.tmp").exists()
	assert sorted(p.name for p in box.path(f"{CAMERA}/original").iterdir()) == [backup.backup_name]
	assert box.path(f"{OTHER_CAMERA}/{NAME}").read_bytes() == ORIGINAL

	for command in box.remote_commands():
		verb = tuple(token for token in command.split(" ") if "/" not in token)
		assert verb in ALLOWED_REMOTE_COMMANDS, command


def test_backup_is_idempotent_and_copies_once(writer: BoxWriter, box: FakeBox) -> None:
	first = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	second = writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	assert first == second
	assert sum(command.startswith("cp ") for command in box.remote_commands()) == 1
	assert sum(command.startswith("mkdir ") for command in box.remote_commands()) == 1


def test_existing_backup_is_never_overwritten(writer: BoxWriter, box: FakeBox) -> None:
	backup_name = f"20261015T120000.{_sha(ORIGINAL)[:16]}.jpg"
	existing = box.path(f"{CAMERA}/original/{backup_name}")
	existing.parent.mkdir()
	existing.write_bytes(b"something else")

	with pytest.raises(BoxWriteError, match="does not match"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	assert existing.read_bytes() == b"something else"
	assert not any(command.startswith("cp ") for command in box.remote_commands())


def test_image_changing_during_backup_is_reported(writer: BoxWriter, box: FakeBox) -> None:
	def rewrite(argv: list[str]) -> None:
		if argv[-1].startswith("cp "):
			box.path(f"{CAMERA}/{NAME}").write_bytes(b"\xff\xd8newer\xff\xd9")

	box.after_command = rewrite

	with pytest.raises(BoxWriteError, match="changed while"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))


# The camera rewrites the image between hashing and copying: the copy holds the new bytes, which
# must never land under the name of the old hash, or that name would be stuck forever.
def test_rewrite_before_copy_never_reaches_the_final_backup_name(
	writer: BoxWriter, box: FakeBox
) -> None:
	newer = b"\xff\xd8newer\xff\xd9"

	def rewrite(argv: list[str]) -> None:
		if argv[-1].startswith("ls -1d ") and argv[-1].endswith(".jpg"):
			box.path(f"{CAMERA}/{NAME}").write_bytes(newer)
			box.after_command = None

	box.after_command = rewrite

	with pytest.raises(BoxWriteError, match="changed while"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	assert not box.path(f"{CAMERA}/original/20261015T120000.{_sha(ORIGINAL)[:16]}.jpg").exists()

	backup = writer.backup(CAMERA, NAME, _sha(newer))

	assert _backup_path(box, backup).read_bytes() == newer


@pytest.mark.parametrize(
	"stderr",
	[
		"/usr/bin/ls: cannot access 'x': Permission denied",
		"",
		"Connection reset",
	],
)
def test_unclear_existence_stops_before_writing(
	writer: BoxWriter, box: FakeBox, stderr: str
) -> None:
	box.fail_next["ls"] = FakeBox.result(2, stderr=stderr)

	with pytest.raises(BoxWriteError, match="Could not tell"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	assert not any(command.split(" ")[0] in WRITE_VERBS for command in box.remote_commands())


def test_ssh_failure_is_an_error(writer: BoxWriter, box: FakeBox) -> None:
	box.fail_next["sha256sum"] = FakeBox.result(255, stderr="Connection refused")

	with pytest.raises(BoxWriteError, match="SSH"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))


def test_timeout_is_a_timeout_error(box: FakeBox, upload_root: Path) -> None:
	def slow(argv: list[str], timeout_seconds: float) -> subprocess.CompletedProcess:
		raise subprocess.TimeoutExpired(argv, timeout_seconds)

	writer = _writer(slow, upload_root)

	with pytest.raises(TimeoutError):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))


def test_garbled_hash_output_is_an_error(writer: BoxWriter, box: FakeBox) -> None:
	box.fail_next["sha256sum"] = FakeBox.result(0, f"abc  {CAMERA}/{NAME}\n")

	with pytest.raises(BoxWriteError, match="Unexpected sha256sum"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))


def test_camera_outside_allow_list_is_refused_without_contact(
	writer: BoxWriter, box: FakeBox
) -> None:
	with pytest.raises(BoxWriteRefused, match="not allowed"):
		writer.backup(OTHER_CAMERA, NAME, _current_hash(box, OTHER_CAMERA, NAME))

	assert box.calls == []


@pytest.mark.parametrize(
	"name",
	[
		"../20261015T120000.jpg",
		"sub/20261015T120000.jpg",
		".20261015T120000.jpg",
		"-20261015T120000.jpg",
		"20261015T120000.jpg;rm",
		"20261015T120000.jpg x",
		"20261015T 120000.jpg",
		"20261015T120000.jpg\n",
		"20261015T120000.JPG",
		"20261015T120000.png",
		"20261015T120000",
		"no-date-here.jpg",
		"$(id).jpg",
		"",
	],
)
def test_unsafe_or_unknown_image_names_are_refused_without_contact(
	writer: BoxWriter, box: FakeBox, name: str
) -> None:
	with pytest.raises(BoxWriteRefused):
		writer.backup(CAMERA, name, _current_hash(box, CAMERA, name))

	assert box.calls == []


def test_real_camera_name_formats_are_accepted(box: FakeBox, upload_root: Path) -> None:
	writer = _writer(box, upload_root, cameras=["Scheunenviertel"])

	assert writer._image_path("Scheunenviertel", "scheunenviertel-26-10-13_00-14-56-20.jpg")
	assert writer._image_path("Scheunenviertel", "20261015T080102.jpg")


@pytest.mark.parametrize("camera", ["", "..", ".", "a/b", "-rf", "original", "a b", "x;y"])
def test_unsafe_camera_names_are_refused(camera: str, box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused):
		BoxWriter(REMOTE, "", [camera], TIMEZONE, runner=box)


def test_empty_allow_list_is_refused(box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused, match="No cameras"):
		BoxWriter(REMOTE, "", [], TIMEZONE, runner=box)


@pytest.mark.parametrize(
	"remote", ["-oProxyCommand=x", "box.example", "user@", "user@host;id", "user@host x"]
)
def test_unsafe_remote_is_refused(remote: str, box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused, match="remote"):
		BoxWriter(remote, "", [CAMERA], TIMEZONE, runner=box)


@pytest.mark.parametrize("base", ["..", "a/../b", "a b", "-x", "a;b", "./a"])
def test_unsafe_base_directory_is_refused(base: str, box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused, match="base directory"):
		BoxWriter(REMOTE, base, [CAMERA], TIMEZONE, runner=box)


def test_base_directory_prefixes_every_path(box: FakeBox, upload_root: Path) -> None:
	(box.root / "cams").mkdir()
	shutil.move(box.root / CAMERA, box.root / "cams" / CAMERA)
	writer = _writer(box, upload_root, base="cams/")

	writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	assert all(
		path.startswith("cams/")
		for command in box.remote_commands()
		for path in command.split(" ")
		if "/" in path
	)


def test_disallowed_remote_command_is_refused(writer: BoxWriter, box: FakeBox) -> None:
	for verb in [("rm",), ("rm", "-rf"), ("cp",), ("cp", "-n", "-T"), ("mv",), ("chmod",)]:
		with pytest.raises(BoxWriteRefused, match="not allowed"):
			writer._remote(verb, [f"{CAMERA}/{NAME}"])

	assert box.calls == []


@pytest.mark.parametrize("path", ["../x", "a/../b", "-rf", "a b", "a;b", "a/./b", "a\nb", ""])
def test_unsafe_remote_paths_are_refused(writer: BoxWriter, box: FakeBox, path: str) -> None:
	with pytest.raises(BoxWriteRefused, match="Unsafe remote path"):
		writer._remote(("sha256sum",), [path])

	assert box.calls == []


def test_forged_backup_record_is_refused(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	real = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	box.calls.clear()

	forged = [
		Backup(CAMERA, NAME, "../../elsewhere.jpg", real.sha256),
		Backup(CAMERA, NAME, f"other.{real.sha256[:16]}.jpg", real.sha256),
		Backup(CAMERA, NAME, real.backup_name, "0" * 64),
		Backup(OTHER_CAMERA, NAME, real.backup_name, real.sha256),
		Backup(CAMERA, "../x.jpg", real.backup_name, real.sha256),
	]

	for backup in forged:
		with pytest.raises(BoxWriteRefused):
			writer.upload_blurred(backup, blurred_file)

		with pytest.raises(BoxWriteRefused):
			writer.replace(backup, _sha(BLURRED))

	assert box.calls == []


def test_upload_source_outside_upload_root_is_refused(
	writer: BoxWriter, box: FakeBox, tmp_path: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	box.calls.clear()
	outside = tmp_path / "outside.jpg"
	outside.write_bytes(BLURRED)

	with pytest.raises(BoxWriteRefused, match="outside"):
		writer.upload_blurred(backup, outside)

	assert box.calls == []


def test_upload_symlink_escaping_upload_root_is_refused(
	writer: BoxWriter, tmp_path: Path, upload_root: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	outside = tmp_path / "outside.jpg"
	outside.write_bytes(BLURRED)
	link = upload_root / "link.jpg"
	link.symlink_to(outside)

	with pytest.raises(BoxWriteRefused, match="outside"):
		writer.upload_blurred(backup, link)


@pytest.mark.parametrize("data", [b"", b"\xff", b"\xff\xd8truncated", b"not a jpeg\xff\xd9"])
def test_incomplete_upload_source_is_refused(
	writer: BoxWriter, box: FakeBox, upload_root: Path, data: bytes
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	box.calls.clear()
	source = upload_root / "broken.jpg"
	source.write_bytes(data)

	with pytest.raises(BoxWriteRefused, match="complete JPEG"):
		writer.upload_blurred(backup, source)

	assert box.calls == []


def test_unchanged_blur_result_is_refused(writer: BoxWriter, upload_root: Path) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	source = upload_root / "same.jpg"
	source.write_bytes(ORIGINAL)

	with pytest.raises(BoxWriteRefused, match="identical"):
		writer.upload_blurred(backup, source)


def test_corrupted_upload_is_detected(writer: BoxWriter, box: FakeBox, blurred_file: Path) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	box.corrupt_upload = True

	with pytest.raises(BoxWriteError, match="does not match the local"):
		writer.upload_blurred(backup, blurred_file)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == ORIGINAL


def test_upload_never_touches_the_image_name(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	writer.upload_blurred(backup, blurred_file)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == ORIGINAL
	assert box.path(f"{CAMERA}/.{NAME}.tmp").read_bytes() == BLURRED

	scp = [argv for argv in box.calls if argv[0] == "scp"]
	assert len(scp) == 1
	assert scp[0][-1] == f"{REMOTE}:{CAMERA}/.{NAME}.tmp"
	assert Path(scp[0][-2]).is_absolute()


def test_replace_refuses_when_image_changed_after_backup(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	blurred_hash = writer.upload_blurred(backup, blurred_file)
	box.path(f"{CAMERA}/{NAME}").write_bytes(b"\xff\xd8re-uploaded\xff\xd9")

	with pytest.raises(BoxWriteError, match="changed since its backup"):
		writer.replace(backup, blurred_hash)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == b"\xff\xd8re-uploaded\xff\xd9"
	assert not any(command.startswith("mv -T ") for command in box.remote_commands())


def test_replace_refuses_when_backup_is_damaged(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	blurred_hash = writer.upload_blurred(backup, blurred_file)
	_backup_path(box, backup).write_bytes(b"damaged")

	with pytest.raises(BoxWriteError, match="Backup .* no longer matches"):
		writer.replace(backup, blurred_hash)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == ORIGINAL


def test_replace_refuses_when_backup_is_missing(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	blurred_hash = writer.upload_blurred(backup, blurred_file)
	_backup_path(box, backup).unlink()

	with pytest.raises(BoxWriteError, match="Hashing failed"):
		writer.replace(backup, blurred_hash)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == ORIGINAL


def test_replace_refuses_when_upload_changed(
	writer: BoxWriter, box: FakeBox, blurred_file: Path
) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	blurred_hash = writer.upload_blurred(backup, blurred_file)
	box.path(f"{CAMERA}/.{NAME}.tmp").write_bytes(b"\xff\xd8other\xff\xd9")

	with pytest.raises(BoxWriteError, match="Uploaded copy .* changed"):
		writer.replace(backup, blurred_hash)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == ORIGINAL


@pytest.mark.parametrize("blurred_hash", ["", "abc", "Z" * 64, "../" * 21 + "a"])
def test_replace_refuses_invalid_hash(writer: BoxWriter, box: FakeBox, blurred_hash: str) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	box.calls.clear()

	with pytest.raises(BoxWriteRefused):
		writer.replace(backup, blurred_hash)

	with pytest.raises(BoxWriteRefused):
		writer.replace(backup, backup.sha256)

	assert box.calls == []


def test_failed_move_is_an_error(writer: BoxWriter, box: FakeBox, blurred_file: Path) -> None:
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))
	blurred_hash = writer.upload_blurred(backup, blurred_file)
	box.fail_next["mv"] = FakeBox.result(1, stderr="mv: Permission denied")

	with pytest.raises(BoxWriteError, match="Replacing"):
		writer.replace(backup, blurred_hash)

	assert box.path(f"{CAMERA}/{NAME}").read_bytes() == ORIGINAL


def test_power_cut_mid_copy_leaves_no_broken_backup(writer: BoxWriter, box: FakeBox) -> None:
	box.cut_copy = True

	with pytest.raises(BoxWriteError, match="SSH"):
		writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	backups = list(box.path(f"{CAMERA}/original").iterdir())
	assert all(path.name.startswith(".") and path.name.endswith(".tmp") for path in backups)

	# Next round after the restart: the half copy is overwritten and the backup completes.
	backup = writer.backup(CAMERA, NAME, _sha(ORIGINAL))

	assert _backup_path(box, backup).read_bytes() == ORIGINAL
	assert [p.name for p in box.path(f"{CAMERA}/original").iterdir()] == [backup.backup_name]


def test_cp_may_only_overwrite_temporary_files(writer: BoxWriter, box: FakeBox) -> None:
	for target in [f"{CAMERA}/original/x.jpg", f"{CAMERA}/{NAME}", f"{CAMERA}/x.tmp"]:
		with pytest.raises(BoxWriteRefused, match="temporary"):
			writer._remote(("cp", "-T"), [f"{CAMERA}/{NAME}", target])

	assert box.calls == []


def _add_image(box: FakeBox, name: str) -> None:
	box.path(f"{CAMERA}/{name}").write_bytes(b"\xff\xd8" + name.encode() + b"\xff\xd9")


def test_every_image_of_the_day_is_inside_the_window(box: FakeBox, upload_root: Path) -> None:
	late_evening = datetime(2026, 10, 15, 23, 59, tzinfo=ZoneInfo(TIMEZONE))
	writer = _writer(box, upload_root, now=late_evening)

	for minute in range(0, 24 * 60, 10):
		writer.check(CAMERA, f"20261015T{minute // 60:02}{minute % 60:02}00.jpg")


def test_two_hour_blackout_is_caught_up(box: FakeBox, upload_root: Path) -> None:
	names = [
		f"20261015T{hour:02}{minute:02}00.jpg" for hour in (11, 12) for minute in range(0, 60, 10)
	]

	for name in names:
		_add_image(box, name)

	after_restart = datetime(2026, 10, 15, 13, 5, tzinfo=ZoneInfo(TIMEZONE))
	writer = _writer(box, upload_root, now=after_restart)

	for name in names:
		writer.backup(CAMERA, name, _current_hash(box, CAMERA, name))

	assert len(list(box.path(f"{CAMERA}/original").iterdir())) == len(names)


def test_old_image_is_refused_without_contact(writer: BoxWriter, box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused, match="older than"):
		writer.backup(CAMERA, "20261014T125900.jpg", "0" * 64)

	assert box.calls == []


def test_image_just_inside_the_age_limit_is_accepted(writer: BoxWriter, box: FakeBox) -> None:
	_add_image(box, "20261014T130100.jpg")

	writer.backup(CAMERA, "20261014T130100.jpg", _current_hash(box, CAMERA, "20261014T130100.jpg"))


def test_image_far_in_the_future_is_refused(writer: BoxWriter, box: FakeBox) -> None:
	with pytest.raises(BoxWriteRefused, match="future"):
		writer.backup(CAMERA, "20261015T153000.jpg", "0" * 64)

	assert box.calls == []


def test_small_clock_drift_ahead_is_accepted(writer: BoxWriter, box: FakeBox) -> None:
	_add_image(box, "20261015T140000.jpg")

	writer.backup(CAMERA, "20261015T140000.jpg", _current_hash(box, CAMERA, "20261015T140000.jpg"))


def test_backup_count_per_camera_is_capped(box: FakeBox, upload_root: Path) -> None:
	box.path(f"{OTHER_CAMERA}/20261015T110000.jpg").write_bytes(ORIGINAL)
	writer = _writer(box, upload_root, cameras=[CAMERA, OTHER_CAMERA], max_backups_per_camera=3)
	names = [f"20261015T1{minute}0000.jpg" for minute in range(4)]

	for name in names[:3]:
		_add_image(box, name)
		writer.backup(CAMERA, name, _current_hash(box, CAMERA, name))

	box.calls.clear()

	with pytest.raises(BoxWriteRefused, match="Limit of 3"):
		writer.backup(CAMERA, names[3], _current_hash(box, CAMERA, names[3]))

	assert box.calls == []

	# The cap is per camera: another camera still gets its own budget.
	writer.backup(OTHER_CAMERA, "20261015T110000.jpg", _sha(ORIGINAL))


@pytest.mark.parametrize(
	"limits",
	[
		{"max_backups_per_camera": 0},
		{"max_image_age": timedelta(0)},
		{"max_image_ahead": timedelta(hours=-1)},
	],
)
def test_invalid_limits_are_refused(box: FakeBox, upload_root: Path, limits: dict) -> None:
	with pytest.raises(BoxWriteRefused, match="Limits"):
		_writer(box, upload_root, **limits)


def test_unknown_timezone_fails_at_start(box: FakeBox) -> None:
	with pytest.raises(ZoneInfoNotFoundError, match="Mars"):
		BoxWriter(REMOTE, "", [CAMERA], "Europe/Mars", runner=box)


def test_default_clock_is_timezone_aware(box: FakeBox) -> None:
	writer = BoxWriter(REMOTE, "", [CAMERA], TIMEZONE, runner=box)

	assert writer._clock().tzinfo is not None


# Structural guard: a write to the storage box can only come from box_writer.py. Any other
# Python file that starts ssh/scp/sftp/rsync must be listed here as read-only and is checked
# for write commands.
WRITER_MODULE = "src/privacy/box_writer.py"
READ_ONLY_SSH_MODULES = {"src/storage_filter.py"}
REMOTE_PROGRAMS = {"ssh", "scp", "sftp", "rsync", "sshfs"}


def _python_files() -> list[Path]:
	return sorted(
		path
		for folder in ("src", "scripts", "nas")
		for path in (PROJECT_ROOT / folder).rglob("*.py")
		if "__pycache__" not in path.parts
	)


def _string_constants(path: Path) -> list[str]:
	tree = ast.parse(path.read_text(encoding="utf-8"))

	return [
		node.value
		for node in ast.walk(tree)
		if isinstance(node, ast.Constant) and isinstance(node.value, str)
	]


def test_only_known_modules_start_remote_programs() -> None:
	users = {
		path.relative_to(PROJECT_ROOT).as_posix()
		for path in _python_files()
		if REMOTE_PROGRAMS & {string.split(" ")[0] for string in _string_constants(path)}
	}

	assert users <= READ_ONLY_SSH_MODULES | {WRITER_MODULE}


def test_read_only_ssh_modules_send_no_write_commands() -> None:
	verbs = "|".join(sorted(WRITE_VERBS | {"scp", "sftp", "rsync"}))

	for module in READ_ONLY_SSH_MODULES:
		for string in _string_constants(PROJECT_ROOT / module):
			# Also a bare verb as its own argument-list element, e.g. ["rm", path].
			assert not re.search(rf"(^|\s)({verbs})(\s|$)", string), f"{module}: {string!r}"


def test_camera_mount_stays_read_only() -> None:
	unit = (PROJECT_ROOT / "systemd" / "cameras-sshfs.service").read_text(encoding="utf-8")
	exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
	options = re.findall(r"-o (\S+)", exec_start)

	assert "ro" in options
	assert "rw" not in options


def test_backup_writes_nothing_when_the_image_is_not_the_judged_one(
	writer: BoxWriter, box: FakeBox
) -> None:
	with pytest.raises(BoxWriteError, match="differs from the checked copy"):
		writer.backup(CAMERA, NAME, _sha(b"bytes the detector saw"))

	assert not box.path(f"{CAMERA}/original").exists()
	assert not any(command.split(" ")[0] in WRITE_VERBS for command in box.remote_commands())


# Read-only helpers of the box job: download and folder check.


def test_fetch_downloads_the_box_bytes_into_the_work_folder(writer, box, upload_root) -> None:
	target = upload_root / NAME

	writer.fetch(CAMERA, NAME, target)

	assert target.read_bytes() == ORIGINAL
	assert box.calls[-1][-2] == f"{REMOTE}:{CAMERA}/{NAME}"
	# Nothing on the box changed.
	assert (box.root / CAMERA / NAME).read_bytes() == ORIGINAL


def test_fetch_refuses_a_target_outside_the_work_folder(writer, box, tmp_path) -> None:
	with pytest.raises(BoxWriteRefused, match="outside"):
		writer.fetch(CAMERA, NAME, tmp_path / NAME)

	assert box.calls == []


def test_fetch_refuses_a_camera_that_is_not_selected(writer, box, upload_root) -> None:
	with pytest.raises(BoxWriteRefused):
		writer.fetch(OTHER_CAMERA, NAME, upload_root / NAME)

	assert box.calls == []


def test_fetch_of_a_missing_image_is_an_error(writer, upload_root) -> None:
	with pytest.raises(OSError, match="Download"):
		writer.fetch(CAMERA, "20261015T120500.jpg", upload_root / "x.jpg")


def test_camera_exists_asks_the_box(writer, box) -> None:
	assert writer.camera_exists(CAMERA) is True

	shutil.rmtree(box.root / CAMERA)

	assert writer.camera_exists(CAMERA) is False
