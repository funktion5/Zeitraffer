import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BACKUP = Path(__file__).resolve().parent.parent.parent / "backup.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# Stand in for ssh and rsync, first in PATH. Every call is recorded in $FAKE_LOG. The fake ssh only
# knows `crontab -l`; the fake rsync "pulls" from a folder on this computer that plays the host.
FAKE_SSH = r"""#!/bin/bash
echo "ssh $*" >> "$FAKE_LOG"
if [[ "${@: -1}" == "crontab -l" ]]; then
	if [[ -n "${FAKE_NO_CRONTAB:-}" ]]; then
		echo "no crontab for this user" >&2
		exit 1
	fi
	echo "0 2 * * * example"
	exit 0
fi
exit 99
"""

FAKE_RSYNC = r"""#!/bin/bash
echo "rsync $*" >> "$FAKE_LOG"
source="${@: -2:1}"
destination="${@: -1}"
remote_path="${source#*:}"
if [[ -n "${FAKE_RSYNC_FAIL:-}" && "$remote_path" == *"$FAKE_RSYNC_FAIL"* ]]; then
	echo "rsync error: some files could not be transferred (code 23)" >&2
	exit 23
fi
if [[ ! -d "$FAKE_REMOTE/$remote_path" ]]; then
	echo "rsync: change_dir failed: No such file or directory" >&2
	exit 23
fi
mkdir -p "$destination"
# A catch-all exclude after includes (an rsync filter list) copies only the included files.
includes=()
exclude_all=""
for argument in "$@"; do
	case "$argument" in
		--include=*) includes+=("${argument#--include=}") ;;
		--exclude=\*) exclude_all=1 ;;
	esac
done
if [[ -n "$exclude_all" ]]; then
	for name in "${includes[@]}"; do
		file="$FAKE_REMOTE/$remote_path/$name"
		[[ -f "$file" ]] && cp "$file" "$destination/"
	done
	exit 0
fi
cp -R "$FAKE_REMOTE/$remote_path/." "$destination"
"""

SECRET_NAME = "siteground.env"
STATE_LINE = '{"image": "a.jpg", "status": "blurred"}\n'
SETTINGS_LINE = '{"timelapse": {"crf": 30}}\n'
PRIVACY_LINE = '{"privacy": {"blur_cameras": ["Alpha"]}}\n'


def make_remote(root: Path, settings: bool = True) -> Path:
	remote = root / "remote"
	files = {
		"timelapse/models/model.onnx": "model",
		"timelapse/state/privacy/box/SLSV/2026-11.jsonl": STATE_LINE,
		"timelapse/videos/Camera/daily/Camera_2026-11-08.mp4": "video",
		f"timelapse/config/{SECRET_NAME}": "SITEGROUND_PASS=placeholder\n",
		# Tracked in git, so it must never be saved either.
		"timelapse/config/config.json": "{}\n",
	}

	if settings:
		files["timelapse/config/settings.json"] = SETTINGS_LINE
		files["timelapse/config/settings-privacy.json"] = PRIVACY_LINE

	for name, content in files.items():
		path = remote / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(content)

	return remote


class Run:
	def __init__(self, result, home, log):
		self.result = result
		self.home = home
		self.log = log

	@property
	def destination(self) -> Path:
		return self.home / "timelapse-backup"

	def calls(self, program: str) -> list[str]:
		if not self.log.exists():
			return []

		return [
			line for line in self.log.read_text().splitlines() if line.startswith(f"{program} ")
		]

	# The remote side of every rsync call: <host>:<path>.
	def sources(self) -> list[str]:
		return [
			next(word for word in line.split() if ":" in word and not word.startswith("-"))
			for line in self.calls("rsync")
		]


def run_backup(
	tmp_path, env=None, config_text=None, no_crontab=False, fail=None, settings=True
) -> Run:
	tmp_path.mkdir(parents=True, exist_ok=True)
	bin_dir = tmp_path / "bin"
	bin_dir.mkdir(exist_ok=True)

	for name, script in (("ssh", FAKE_SSH), ("rsync", FAKE_RSYNC)):
		path = bin_dir / name
		path.write_text(script)
		path.chmod(0o755)

	home = tmp_path / "home"
	home.mkdir(exist_ok=True)
	log = tmp_path / "calls.log"
	config = tmp_path / "backup.env"

	if config_text is not None:
		config.write_text(config_text)

	# HOME and BACKUP_CONFIG are always redirected: the real home folder and a real backup.env in
	# the project must never be read or written by a test.
	environment = {
		"PATH": f"{bin_dir}:/usr/bin:/bin",
		"HOME": str(home),
		"FAKE_LOG": str(log),
		"FAKE_REMOTE": str(make_remote(tmp_path, settings)),
		"BACKUP_CONFIG": str(config),
		"BACKUP_HOST": "alias",
	}

	if no_crontab:
		environment["FAKE_NO_CRONTAB"] = "1"

	if fail:
		environment["FAKE_RSYNC_FAIL"] = fail

	environment.update(env or {})

	# An empty value removes a variable, so a test can leave BACKUP_HOST unset.
	environment = {key: value for key, value in environment.items() if value != ""}

	result = subprocess.run(
		["bash", str(BACKUP)],
		env=environment,
		capture_output=True,
		text=True,
		check=False,
	)

	return Run(result, home, log)


def names_below(folder: Path) -> list[str]:
	return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())


# The default backup: what a new host needs and Git does not hold (the web UI settings included).
# Videos are left out.
def test_models_state_settings_and_crontab_are_saved(tmp_path):
	run = run_backup(tmp_path)

	assert run.result.returncode == 0
	assert names_below(run.destination) == [
		"config/settings-privacy.json",
		"config/settings.json",
		"crontab.txt",
		"models/model.onnx",
		"state/privacy/box/SLSV/2026-11.jsonl",
	]
	assert (run.destination / "config/settings.json").read_text() == SETTINGS_LINE
	assert (run.destination / "config/settings-privacy.json").read_text() == PRIVACY_LINE
	assert (run.destination / "crontab.txt").read_text() == "0 2 * * * example\n"
	assert run.sources() == [
		"alias:timelapse/models/",
		"alias:timelapse/state/",
		"alias:timelapse/config/",
	]


# Locks and the run marker would block the new host, and the web job folder is transient.
def test_state_is_saved_without_locks_and_transient_files(tmp_path):
	run = run_backup(tmp_path)

	state_call = next(line for line in run.calls("rsync") if "alias:timelapse/state/" in line)

	assert "--exclude=*.lock" in state_call
	assert "--exclude=run-in-progress" in state_call
	assert "--exclude=web-jobs/" in state_call


def test_videos_are_saved_only_with_the_switch(tmp_path):
	plain = run_backup(tmp_path / "plain")

	assert not (plain.destination / "videos").exists()
	assert "alias:timelapse/videos/" not in plain.sources()

	with_videos = run_backup(tmp_path / "with", env={"VIDEOS": "1"})

	assert with_videos.result.returncode == 0
	assert (with_videos.destination / "videos/Camera/daily/Camera_2026-11-08.mp4").exists()

	videos_call = next(line for line in with_videos.calls("rsync") if "/videos/" in line)

	# Half-written renders are hidden files.
	assert "--exclude=.*" in videos_call


# Nothing secret is ever saved: the upload password lives in config/ on the host, next to the
# settings file, so the config pull is limited to that one file.
def test_no_secret_is_requested_or_saved(tmp_path):
	run = run_backup(tmp_path, env={"VIDEOS": "1"})

	config_calls = [line for line in run.calls("rsync") if "alias:timelapse/config/" in line]

	assert len(config_calls) == 1
	assert "--include=settings.json" in config_calls[0]
	assert "--include=settings-privacy.json" in config_calls[0]
	assert "--exclude=*" in config_calls[0]
	assert config_calls[0].index("--include=settings.json") < config_calls[0].index("--exclude=*")
	assert config_calls[0].index("--include=settings-privacy.json") < config_calls[0].index(
		"--exclude=*"
	)
	assert SECRET_NAME not in " ".join(names_below(run.destination))
	assert "config/config.json" not in names_below(run.destination)


# A host that never saved settings has no file: that is not a failure.
def test_the_settings_file_is_optional(tmp_path):
	run = run_backup(tmp_path, settings=False)

	assert run.result.returncode == 0
	assert "config/settings.json" not in names_below(run.destination)
	assert "config/settings-privacy.json" not in names_below(run.destination)
	assert SECRET_NAME not in " ".join(names_below(run.destination))


def test_the_backup_folder_is_private(tmp_path):
	run = run_backup(tmp_path)

	assert stat.S_IMODE(run.destination.stat().st_mode) == 0o700


# The host is only read: one `crontab -l` over ssh, and rsync pulls into the backup folder. No
# --delete, so an older backup is never emptied by a smaller new one.
def test_the_host_is_only_read(tmp_path):
	run = run_backup(tmp_path, env={"VIDEOS": "1"})

	assert run.calls("ssh") == ["ssh -- alias crontab -l"]

	for line in run.calls("rsync"):
		assert "--delete" not in line
		assert line.split()[-1].startswith(str(run.destination))


def test_the_host_is_required(tmp_path):
	run = run_backup(tmp_path, env={"BACKUP_HOST": ""})

	assert run.result.returncode == 2
	assert "BACKUP_HOST" in run.result.stderr
	assert run.calls("rsync") == []
	assert run.calls("ssh") == []


# The values end up in ssh and rsync arguments, so anything that could be read as an option or a
# second command is refused before a single call is made.
@pytest.mark.parametrize(
	"env",
	[
		{"BACKUP_HOST": "-oProxyCommand=x"},
		{"BACKUP_HOST": "a b"},
		{"BACKUP_HOST": "host;ls"},
		{"PROJECT_DIR": "../elsewhere"},
		{"PROJECT_DIR": "/absolute"},
		{"PROJECT_DIR": "a b"},
		{"VIDEOS": "2"},
	],
)
def test_unsafe_settings_are_refused(tmp_path, env):
	run = run_backup(tmp_path, env=env)

	assert run.result.returncode == 2
	assert "[ERROR]" in run.result.stderr
	assert run.calls("rsync") == []
	assert run.calls("ssh") == []


# backup.env supplies what the environment leaves empty; comment lines and other names are ignored.
def test_settings_come_from_the_config_file_and_the_environment_wins(tmp_path):
	config = "# the host\nBACKUP_HOST=fromfile\nOTHER=ignored\nPROJECT_DIR=timelapse\n"

	from_file = run_backup(tmp_path / "file", env={"BACKUP_HOST": ""}, config_text=config)

	assert from_file.result.returncode == 0
	assert from_file.sources()[0] == "fromfile:timelapse/models/"

	from_env = run_backup(tmp_path / "env", env={"BACKUP_HOST": "fromenv"}, config_text=config)

	assert from_env.sources()[0] == "fromenv:timelapse/models/"


# One item that cannot be pulled is reported and fails the run, but the others are still saved.
def test_a_failed_item_does_not_stop_the_others(tmp_path):
	run = run_backup(tmp_path, fail="models")

	assert run.result.returncode == 1
	assert "Not saved: models" in run.result.stderr
	assert (run.destination / "state/privacy/box/SLSV/2026-11.jsonl").exists()


def test_a_host_without_a_crontab_is_fine(tmp_path):
	run = run_backup(tmp_path, no_crontab=True)

	assert run.result.returncode == 0
	assert (run.destination / "crontab.txt").read_text() == ""
	assert "No crontab" in run.result.stdout


def test_running_it_twice_works(tmp_path):
	first = run_backup(tmp_path)
	second = run_backup(tmp_path)

	assert first.result.returncode == 0
	assert second.result.returncode == 0


# The summary says what is not in the backup, so nobody expects a secret to be there.
def test_the_summary_names_what_is_not_saved(tmp_path):
	run = run_backup(tmp_path)

	assert "web login" in run.result.stdout
	assert "upload password" in run.result.stdout
	assert "ssh key" in run.result.stdout
