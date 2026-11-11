#!/bin/bash
# Fills the test container with FAKE data so every web page has something to show: a camera list,
# small placeholder videos in the folders the pages read, and a preview picture for the blur cameras.
# No real videos, no keys, no Storage Box. Safe to re-run: files that exist are left alone.
# Run it as the run account:  docker compose exec -u zeitraffer web seed-demo-data
set -euo pipefail

PROJECT="$HOME/timelapse"
cd "$PROJECT"

# name:size of the camera's yearly video in MB. The size is only "apparent" (a sparse file), so the
# storage donuts show realistic numbers without using disk space.
CAMERAS=(SLSV:507 Scheunenviertel:481 Uferstrasse:312 Kitestrand:77 Seerosenweg:89 SKM-Mardorf:519)
# The cameras the Verpixelung page offers a preview for (privacy.blur_cameras in config.json).
BLUR_CAMERAS=(SLSV Scheunenviertel)

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

ffmpeg -loglevel error -y -f lavfi -i "testsrc=size=320x180:rate=10" -t 2 -pix_fmt yuv420p "$work/clip.mp4"
ffmpeg -loglevel error -y -f lavfi -i "testsrc=size=640x360" -frames:v 1 -update 1 "$work/picture.jpg"

day() { date -d "-$1 day" +%F; }

put_video() {
	local target="$1" size_mb="${2:-0}"
	[[ -f "$target" ]] && return
	mkdir -p "$(dirname "$target")"
	cp "$work/clip.mp4" "$target"
	if ((size_mb > 0)); then
		truncate -s "${size_mb}M" "$target"
	fi
}

created=0
for entry in "${CAMERAS[@]}"; do
	camera="${entry%%:*}"
	yearly_mb="${entry##*:}"
	base="videos/$camera"

	# The automatic videos of the nightly run: a week of Dailies and one video per longer period.
	for offset in 1 2 3 4 5 6 7; do
		put_video "$base/daily/${camera}_$(day "$offset").mp4"
	done
	put_video "$base/weekly/${camera}_$(day 1).mp4"
	put_video "$base/monthly/${camera}_$(day 1).mp4"
	put_video "$base/yearly/${camera}_$(day 1).mp4" "$yearly_mb"

	# The manual ones (historical runs): a Daily with a daylight buffer, a Monthly with an interval window.
	put_video "$base/manual-runs/daily/${camera}_$(day 3)_60min.mp4"
	put_video "$base/manual-runs/monthly/${camera}_$(day 5)_1200-60min.mp4"
	created=$((created + 1))
done

# The camera list the nightly run writes (python -m src.camera_list); the pages read only this file.
mkdir -p state/web-jobs/previews
printf '[' >state/web-jobs/cameras.json
separator=""
for entry in "${CAMERAS[@]}"; do
	printf '%s"%s"' "$separator" "${entry%%:*}" >>state/web-jobs/cameras.json
	separator=","
done
printf ']\n' >>state/web-jobs/cameras.json

# The Verpixelung page shows the picture the box blur job judged last: a JPEG plus its description.
taken="$(date +%Y-%m-%dT%H:%M:%S%:z)"
for camera in "${BLUR_CAMERAS[@]}"; do
	cp "$work/picture.jpg" "state/web-jobs/previews/$camera.jpg"
	printf '{"image": "demo.jpg", "status": "blurred", "taken": "%s"}\n' "$taken" \
		>"state/web-jobs/previews/$camera.json"
done

# www-data reads the job state through the web pages.
chmod -R o+rX state/web-jobs

echo "Demo data ready: ${created} cameras with videos, camera list, previews for ${BLUR_CAMERAS[*]}."
