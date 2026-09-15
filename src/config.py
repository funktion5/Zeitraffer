import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "cameras.json"

def load_config():
  with CONFIG_PATH.open("r", encoding="utf-8") as file:
    return json.load(file)