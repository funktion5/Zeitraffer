import json
import stat
from pathlib import Path

from src.web_state import WEB_STATE_ROOT, write_web_json


# The web page may read at any moment and runs as another user: whole file, readable, no leftovers.
def test_write_web_json_replaces_the_file_readable_for_the_web(tmp_path: Path) -> None:
	destination = tmp_path / "web-jobs" / "status.json"
	destination.parent.mkdir()
	destination.write_text('{"old": true}\n')

	write_web_json(destination, {"messages": [{"camera": None, "text": "Nichts"}]})

	assert json.loads(destination.read_text(encoding="utf-8")) == {
		"messages": [{"camera": None, "text": "Nichts"}]
	}
	assert stat.S_IMODE(destination.stat().st_mode) == 0o644
	assert [path.name for path in destination.parent.iterdir()] == ["status.json"]


def test_write_web_json_creates_a_folder_the_web_can_enter(tmp_path: Path) -> None:
	destination = tmp_path / "web-jobs" / "status.json"

	write_web_json(destination, [])

	assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o755


def test_the_web_state_root_is_the_folder_the_pages_read() -> None:
	assert WEB_STATE_ROOT.parts[-2:] == ("state", "web-jobs")
