import json
from pathlib import Path

# Define the project root and path to the JSON configuration file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "cameras.json"


# Loads and returns the application configuration from the JSON file.
def load_config():
	with CONFIG_PATH.open("r", encoding="utf-8") as file:
		return json.load(file)