#!/usr/bin/env bash
# Mirror the automatic timelapse videos from the Pi into ./videos for local development.
# Read-only on the Pi. Manual runs and hidden files (e.g. in-progress renders) are skipped.
# Local files that no longer exist on the Pi are deleted, so the folder matches the Pi.
#
# Usage: docker/pull-videos.sh [-n]     (-n = dry run, changes nothing)
set -euo pipefail

ENV_FILE="$(cd "$(dirname "$0")" && pwd)/.env"

# Login (user@address) comes from the environment or the gitignored docker/.env, so no
# address is committed. Read with grep instead of sourcing: .env holds other secrets.
if [[ -z "${PI:-}" && -f "$ENV_FILE" ]]; then
	PI="$(grep -E '^PI=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
fi
if [[ -z "${PI:-}" ]]; then
	echo "PI is not set. Add PI=user@address to docker/.env or run: PI=user@address $0" >&2
	exit 1
fi
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
