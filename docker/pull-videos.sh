#!/usr/bin/env bash
# Mirror the automatic timelapse videos from the Pi into ./videos for local development.
# Read-only on the Pi. Manual runs and hidden files (e.g. in-progress renders) are skipped.
# Local files that no longer exist on the Pi are deleted, so the folder matches the Pi.
#
# Usage: docker/pull-videos.sh [-n]     (-n = dry run, changes nothing)
set -euo pipefail

PI="${PI:-zruser@192.168.178.41}"
SRC="/home/zruser/timelapse/videos/"
DEST="$(cd "$(dirname "$0")/.." && pwd)/videos/"

# Excluded paths are also protected from --delete (no --delete-excluded), so a local
# manual-runs/ folder or hidden files survive the mirror.
RSYNC_OPTS=(-avh --delete --exclude='manual-runs/' --exclude='.*')

if [[ "${1:-}" == "-n" ]]; then
	exec rsync "${RSYNC_OPTS[@]}" --dry-run "$PI:$SRC" "$DEST"
fi

echo "Dry run - what would change:"
rsync "${RSYNC_OPTS[@]}" --dry-run "$PI:$SRC" "$DEST"

read -r -p "Apply these changes (including deletions)? [y/N] " answer
[[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Aborted."; exit 0; }

rsync "${RSYNC_OPTS[@]}" --progress "$PI:$SRC" "$DEST"
