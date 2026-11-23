import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL = ROOT / "install.sh"
HARDENING = ROOT / "config" / "apache-hardening.conf"


# install.sh cannot run here (it needs sudo and apt), so its steps are read as text.
def step_text(name: str) -> str:
	text = INSTALL.read_text()
	match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)

	assert match is not None, f"install.sh has no {name}"

	return match.group(0)


def directives() -> list[str]:
	lines = [line.strip() for line in HARDENING.read_text().splitlines()]

	return [line for line in lines if line and not line.startswith("#")]


# Before login, Apache told everyone its exact version and the operating system.
def test_the_apache_version_is_hidden():
	assert "ServerTokens Prod" in directives()
	assert "ServerSignature Off" in directives()
	# Debian's security.conf sets "ServerTokens OS"; the later file in conf-enabled/ wins.
	assert "zeitraffer-hardening.conf" > "security.conf"
	assert "/etc/apache2/conf-available/zeitraffer-hardening.conf" in step_text(
		"step_web_hardening"
	)


def test_no_other_site_can_show_the_pages_in_a_frame():
	headers = directives()

	assert 'Header always set X-Frame-Options "DENY"' in headers
	assert any(
		line.startswith("Header always set Content-Security-Policy")
		and "frame-ancestors 'none'" in line
		for line in headers
	)


def test_the_browser_gets_the_other_security_headers():
	assert 'Header always set X-Content-Type-Options "nosniff"' in directives()
	assert 'Header always set Referrer-Policy "same-origin"' in directives()


# Debian serves its icon files without the login; no page uses them.
def test_the_debian_icons_are_closed():
	text = HARDENING.read_text()
	block = re.search(r"<Directory /usr/share/apache2/icons>(.*?)</Directory>", text, re.S)

	assert block is not None
	assert "Require all denied" in block.group(1)


# A broken file would keep Apache from starting again, so it is switched off before the reload.
def test_the_file_is_enabled_only_after_a_passing_config_test():
	step = step_text("step_web_hardening")

	assert '"$PROJECT_ROOT/config/apache-hardening.conf"' in step
	assert "sudo a2enmod headers" in step
	assert step.index("sudo apache2ctl configtest") < step.index("sudo systemctl reload apache2")
	assert "sudo a2disconf zeitraffer-hardening" in step


def test_the_step_is_part_of_a_full_run_and_checked():
	text = INSTALL.read_text()
	steps = re.search(r"^ALL_STEPS=\(\n(.*?)^\)", text, re.S | re.M)

	assert steps is not None

	names = steps.group(1).split()

	assert names.index("apache") < names.index("web_hardening") < names.index("verify")

	# Header names are case-insensitive, so verify greps with -i in lower case.
	verify = step_text("step_verify")

	assert "grep -qi '^x-frame-options: DENY'" in verify
	assert "grep -qiE '^server: Apache[[:space:]]*$'" in verify
