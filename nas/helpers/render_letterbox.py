"""Re-render one yearly backfill video with every frame fitted into 1280x720 (aspect kept).

Mixed-resolution years (Scheunenviertel 2018: 640x480 until April, 1280x720 from August) come
out distorted, because FFmpeg sizes the video after the first frame and stretches the rest.
This reuses yearly-backfill.py's build_year unchanged and only adds a scale+pad filter to the
encode command for this process.

Usage: TIMELAPSE_CAMERA_ROOT=~/nas-cameras .venv/bin/python3 render_letterbox.py <camera> <year>
"""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

# Two levels up from nas/helpers/ is the project root, wherever it is installed.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIT_FILTER = (
	"scale=1280:720:force_original_aspect_ratio=decrease,"
	"pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
)

spec = importlib.util.spec_from_file_location(
	"yearly_backfill", PROJECT_ROOT / "scripts" / "yearly-backfill.py"
)
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

import src.video as video  # noqa: E402  (after the backfill import set cwd and sys.path)

original_run_ffmpeg = video.run_ffmpeg


def run_ffmpeg_fitted(command: list[str]) -> None:
	# Only the frame encode reads an image sequence; leave any other FFmpeg call untouched.
	if "-framerate" in command:
		command = [*command[:-1], "-vf", FIT_FILTER, command[-1]]

	original_run_ffmpeg(command)


video.run_ffmpeg = run_ffmpeg_fitted

camera, year = sys.argv[1], int(sys.argv[2])
config = json.loads((PROJECT_ROOT / "config" / "config.json").read_text())
result = backfill.build_year(camera, date(year, 1, 1), date(year, 12, 31), config, force=True)
print(result)
