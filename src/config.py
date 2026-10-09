import json
from datetime import date
from pathlib import Path

# Define the project root and path to the JSON configuration file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"


# Loads and returns the application configuration from the JSON file.
def load_config():
	with CONFIG_PATH.open("r", encoding="utf-8") as file:
		return json.load(file)


# Automatic runs scale the daylight buffer with the season; historical runs keep
# the single "daylight_buffer_minutes" value so their filename suffix stays exact.
def automatic_daylight_buffer_for(config: dict, day: date) -> int:
	return config["automatic_daylight_buffer_minutes"][str(day.month)]
