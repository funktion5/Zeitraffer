import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

import src.config as config_module
from src.config import PROJECT_ROOT
from src.logger import logger
from src.settings import (
	SCOPES,
	base_leaf,
	flatten_leaves,
	get_leaf,
	load_valid_settings,
	merge_settings,
	set_leaf,
	validate_settings,
)

# Private to the account the writer runs as: the web server user never reads it.
SETTINGS_LOG_PATH = PROJECT_ROOT / "logs" / "settings.log"

# Exit codes of "python -m src.settings_save"; the web wrapper hands them on to PHP.
EXIT_SAVED = 0
EXIT_INVALID = 65
EXIT_STALE = 73

# "No value" must stay distinguishable from a value of None or [].
_MISSING = object()


@dataclass(frozen=True)
class SaveResult:
	status: str  # "saved", "invalid" or "stale"
	errors: tuple[str, ...]
	# The settings file's modification time in whole seconds, 0 when there is no file.
	mtime: int


def current_mtime(path: Path) -> int:
	try:
		return int(path.stat().st_mtime)

	except FileNotFoundError:
		return 0


# Lists compare as sets would: the order of ticked cameras carries no meaning.
def _normalize(value: object) -> object:
	return sorted(value) if isinstance(value, list) else value


# Only what differs from config.json is stored. A value set back to the base value disappears from
# the file, so an edit of config.json made later still reaches that key.
def _overrides(base: dict, clean: dict) -> dict:
	overrides: dict = {}

	# The validated submission is walked, not a fixed key list: per-camera keys have no fixed names.
	for key, value in flatten_leaves(clean).items():
		base_value = base_leaf(base, key, _MISSING)

		# An empty list where the base has nothing (a camera without ignore boxes) changes nothing.
		if base_value is _MISSING and value == []:
			continue

		if _normalize(value) != _normalize(base_value):
			set_leaf(overrides, key, _normalize(value))

	return overrides


# The temporary file lives in the settings folder so the rename stays on one filesystem; the web
# server user has to read the result, and mkstemp creates the file private.
def _write_atomically(destination: Path, content: dict) -> None:
	descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")

	try:
		with os.fdopen(descriptor, "w", encoding="utf-8") as file:
			json.dump(content, file, indent=2, sort_keys=True)
			file.write("\n")

		os.chmod(temporary, 0o644)
		os.replace(temporary, destination)

	except BaseException:
		Path(temporary).unlink(missing_ok=True)

		raise


def _effective(base: dict, overrides: dict, key: str) -> object:
	value = get_leaf(overrides, key, _MISSING)

	return value if value is not _MISSING else base_leaf(base, key, _MISSING)


def _render(value: object) -> str:
	return "unset" if value is _MISSING else json.dumps(value)


# One line per save: when, and which keys went from which value to which. No address, no user agent.
# The save is already done at this point, so a log that cannot be written must not fail it.
def _log_changes(log_path: Path, base: dict, before: dict, after: dict, scope: str) -> None:
	changes = []

	for key in sorted(set(flatten_leaves(before)) | set(flatten_leaves(after))):
		old = _effective(base, before, key)
		new = _effective(base, after, key)

		if _normalize(old) != _normalize(new):
			changes.append(f"{key}: {_render(old)} -> {_render(new)}")

	stamp = datetime.now().astimezone().isoformat(timespec="seconds")
	line = f"{stamp} [{scope}] {'; '.join(changes) if changes else 'no changes'}\n"

	try:
		descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)

		with os.fdopen(descriptor, "a", encoding="utf-8") as file:
			file.write(line)

	except OSError as error:
		logger.warning(f"Settings log not written: {error}")


# The values are valid one by one, but some only work together. The flagger raises, for ALL its
# cameras, when one of them is ignored (an ignored camera is not processed), so the combination is
# refused here, judged on what would be in force: config.json with the submission on top. The
# message is plain German and names no key, because the page shows it as a message of its own.
def _cross_field_errors(base: dict, clean: dict, scope: str) -> list[str]:
	if scope != "general":
		return []

	effective = merge_settings(base, clean)
	ignored = set(effective.get("ignored_cameras") or [])
	flagger = effective.get("flagger") or {}
	clashing = [camera for camera in flagger.get("cameras") or [] if camera in ignored]

	if not clashing:
		return []

	return [
		"Unter „Kameras“ abgewählt, unter „Highlights“ aber noch angehakt: "
		f"{', '.join(clashing)}. Bitte auch dort abwählen."
	]


# Saves the complete set of the form's values. Order matters: invalid input is refused before the
# stale check, and nothing is written for either. The submission replaces the whole file, so a
# leaf the form no longer sends loses its override. None for a path means the module constant,
# read at call time so tests can patch it. Two saves in the same second can slip past the stale
# check (the time is whole seconds); with a handful of colleagues that is accepted.
def save_settings(
	submitted: object,
	expected_mtime: int,
	*,
	scope: str = "general",
	config_path: Path | None = None,
	settings_path: Path | None = None,
	log_path: Path | None = None,
) -> SaveResult:
	config_path = config_path if config_path is not None else config_module.CONFIG_PATH
	settings_path = (
		settings_path if settings_path is not None else config_module.settings_path_for(scope)
	)
	log_path = log_path if log_path is not None else SETTINGS_LOG_PATH

	clean, errors = validate_settings(submitted, scope)
	mtime = current_mtime(settings_path)

	with config_path.open("r", encoding="utf-8") as file:
		base = json.load(file)

	errors = [*errors, *_cross_field_errors(base, clean, scope)]

	if errors:
		return SaveResult("invalid", tuple(errors), mtime)

	if expected_mtime != mtime:
		return SaveResult("stale", (), mtime)

	before = load_valid_settings(settings_path, scope)
	after = _overrides(base, clean)

	_write_atomically(settings_path, after)
	_log_changes(log_path, base, before, after, scope)

	return SaveResult("saved", (), current_mtime(settings_path))


# Reads one JSON document from stdin (the complete form values) and answers with one JSON line.
# Unparsable input is treated like any other invalid submission.
def main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int:
	parser = argparse.ArgumentParser(description="Save the values of the web UI settings page.")
	parser.add_argument("--scope", choices=sorted(SCOPES), default="general")
	parser.add_argument("--expected-mtime", type=int, required=True)
	arguments = parser.parse_args(argv)

	text = (stdin if stdin is not None else sys.stdin).read()

	try:
		submitted = json.loads(text)

	# RecursionError: text nested deeper than json can read.
	except (ValueError, RecursionError):
		submitted = None

	result = save_settings(submitted, arguments.expected_mtime, scope=arguments.scope)
	reply = {"status": result.status, "errors": list(result.errors), "mtime": result.mtime}

	print(json.dumps(reply))

	return {"saved": EXIT_SAVED, "invalid": EXIT_INVALID, "stale": EXIT_STALE}[result.status]


if __name__ == "__main__":
	sys.exit(main())
