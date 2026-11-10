import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL = ROOT / "install.sh"
WEB_SCRIPTS = ROOT / "scripts" / "web"


# install.sh cannot run here (it needs sudo and apt), so its steps are read as text.
def step_text(name: str) -> str:
	text = INSTALL.read_text()
	match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)

	assert match is not None, f"install.sh has no {name}"

	return match.group(0)


def test_the_settings_wrapper_is_installed_root_owned():
	step = step_text("step_web_bridge")

	assert (
		'sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-settings" '
		"/usr/local/sbin/timelapse-web-settings"
	) in step


def test_the_settings_wrapper_has_its_own_sudoers_rule():
	step = step_text("step_web_bridge")

	assert "www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-settings *" in step


# The pages show the saved values, so the web server user has to read the file; it must not be
# closed with the other files in config/ (the upload login among them).
def test_the_web_server_user_can_read_the_settings_file():
	step = step_text("step_permissions")

	assert "! -name settings.json" in step
	assert "chmod o=r config/settings.json" in step


# A wrapper that is installed but not executable in git would fail only on the VPS.
def test_every_installed_wrapper_exists_and_is_executable():
	names = re.findall(r"scripts/web/(timelapse-web-[a-z-]+)\"", step_text("step_web_bridge"))

	assert "timelapse-web-settings" in names

	for name in names:
		path = WEB_SCRIPTS / name

		assert path.is_file(), f"{name} is installed by install.sh but missing"
		assert path.stat().st_mode & 0o111, f"{name} is not executable"
