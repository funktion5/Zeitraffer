import re
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent.parent / "install.sh"


# Cut out of install.sh like the other step tests. The step only prints; it installs nothing.
def cron_lines() -> list[str]:
	text = INSTALL.read_text()
	function = re.search(r"^step_cron_hint\(\) \{\n.*?^\}\n", text, re.S | re.M)

	assert function is not None, "install.sh has no step_cron_hint"

	script = f'set -euo pipefail\nlog() {{ echo "==> $*"; }}\n{function.group(0)}\nstep_cron_hint\n'
	result = subprocess.run(
		["bash", "-c", script],
		env={"PATH": "/usr/bin:/bin", "PROJECT_ROOT": "/srv/timelapse", "BOX_ALIAS": "box"},
		capture_output=True,
		text=True,
		check=True,
	)

	return [line for line in result.stdout.splitlines() if re.match(r"[0-9*]", line)]


# The same lines as docs/verpixelung-box.md, "Aufruf".
def test_the_hint_prints_the_live_blur_round_and_the_watchdog() -> None:
	start = "*/5 * * * * cd /srv/timelapse && export TIMELAPSE_STORAGE_BOX=box && "

	assert cron_lines()[1:] == [
		start + "timeout -k 10 240 .venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras",
		start + "timeout 60 .venv/bin/python3 -m src.privacy.blur_watch",
	]


def test_the_nightly_line_stays_first() -> None:
	assert cron_lines()[0].startswith("0 2 * * * cd /srv/timelapse && ")
