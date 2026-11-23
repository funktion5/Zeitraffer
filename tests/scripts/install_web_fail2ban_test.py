import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL = ROOT / "install.sh"


# install.sh cannot run here (it needs sudo and apt), so its steps are read as text.
def step_text(name: str) -> str:
	text = INSTALL.read_text()
	match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)

	assert match is not None, f"install.sh has no {name}"

	return match.group(0)


def jail_settings() -> dict[str, str]:
	step = step_text("step_web_fail2ban")
	body = re.search(r'cat >"\$jail" <<EOF\n(.*?)^EOF$', step, re.S | re.M)

	assert body is not None

	lines = body.group(1).splitlines()

	assert lines[0] == "[zeitraffer-web]"

	return dict(line.split(" = ", 1) for line in lines[1:])


# Basic Auth alone allows unlimited password guesses. One hour, not a day: the office shares one
# address, so a ban locks out everyone there. Only the web port is blocked, never ssh.
def test_the_jail_blocks_the_web_port_for_an_hour_after_five_failures():
	settings = jail_settings()

	assert settings["enabled"] == "true"
	assert settings["filter"] == "apache-auth"
	assert settings["port"] == "${WEB_PORT}"
	assert settings["banaction"] == "nftables-multiport"
	assert settings["maxretry"] == "5"
	assert settings["findtime"] == "10m"
	assert settings["bantime"] == "1h"


# The journal (Debian's backend for sshd) never sees Apache's failures, and Apache writes them to
# the vhost's log or its main error.log depending on the setup.
def test_the_jail_reads_every_apache_error_log_as_a_file():
	settings = jail_settings()

	assert settings["backend"] == "auto"
	assert settings["logpath"] == "/var/log/apache2/*error.log"


# A broken jail file would keep fail2ban from starting, the ssh jail included.
def test_the_configuration_is_tested_before_the_reload():
	step = step_text("step_web_fail2ban")

	assert step.index("sudo fail2ban-client -t") < step.index("sudo fail2ban-client reload")
	assert "sudo rm -f /etc/fail2ban/jail.d/zeitraffer-web.local" in step


def test_the_step_is_installed_and_checked_in_a_full_run():
	text = INSTALL.read_text()
	steps = re.search(r"^ALL_STEPS=\(\n(.*?)^\)", text, re.S | re.M)

	assert steps is not None

	names = steps.group(1).split()

	# Apache has to exist first: the jail reads its logs.
	assert names.index("web_fail2ban") > names.index("apache")
	assert names.index("web_fail2ban") < names.index("verify")
	assert " fail2ban " in step_text("step_packages")
	assert "sudo fail2ban-client status zeitraffer-web" in step_text("step_verify")
