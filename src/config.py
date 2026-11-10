import json
from datetime import date
from pathlib import Path

from src.settings import SCOPES, load_valid_settings, merge_settings

# Define the project root and path to the JSON configuration file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
# The values colleagues change on the web UI settings page; optional, see src/settings.py.
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"
# The privacy tab's own file: a save there never touches the general settings, and the reverse.
PRIVACY_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings-privacy.json"


# The file of a settings scope. Read at call time so tests can patch the paths.
def settings_path_for(scope: str) -> Path:
	return {"general": SETTINGS_PATH, "privacy": PRIVACY_SETTINGS_PATH}[scope]


# Loads the application configuration: config.json, with the valid values of settings.json on top.
# A broken config.json still raises (nothing can run without it); a broken settings file does not.
def load_config():
	with CONFIG_PATH.open("r", encoding="utf-8") as file:
		base = json.load(file)

	# Each file only applies the keys of its own scope.
	for scope in SCOPES:
		base = merge_settings(base, load_valid_settings(settings_path_for(scope), scope))

	return base


# Automatic runs scale the daylight buffer with the season; historical runs keep
# the single "daylight_buffer_minutes" value so their filename suffix stays exact.
def automatic_daylight_buffer_for(config: dict, day: date) -> int:
	return config["automatic_daylight_buffer_minutes"][str(day.month)]
