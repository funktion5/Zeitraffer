#!/usr/bin/env bash
# Mirror the automatic timelapse videos from the Pi into ./videos for local development.
# Read-only on the Pi. Manual runs and hidden files (e.g. in-progress renders) are skipped.
# Local files that no longer exist on the Pi are deleted, so the folder matches the Pi - but only
# after the download finished and a verification pass found nothing left to transfer.
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
EXCLUDES=(--exclude='manual-runs/' --exclude='.*')
RSYNC_OPTS=(-avh "${EXCLUDES[@]}")

if [[ "${1:-}" == "-n" ]]; then
	exec rsync "${RSYNC_OPTS[@]}" --delete --dry-run "$PI:$SRC" "$DEST"
fi

echo "Dry run - what would change:"
rsync "${RSYNC_OPTS[@]}" --delete --dry-run "$PI:$SRC" "$DEST"

read -r -p "Apply these changes (including deletions)? [y/N] " answer
[[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Aborted."; exit 0; }

# 1. Download only. Without --delete nothing local is removed, so an aborted or failed
#    transfer (set -e stops here) leaves the old videos intact. rsync checks each transferred
#    file against a whole-file checksum itself.
rsync "${RSYNC_OPTS[@]}" --progress "$PI:$SRC" "$DEST"

# 2. Verify: a second dry run must list no file to transfer (size and mtime match the Pi).
#    Only file lines are counted; directory timestamp lines are not a sync failure.
pending="$(rsync -rltn --itemize-changes "${EXCLUDES[@]}" "$PI:$SRC" "$DEST" | grep -E '^[<>c]' || true)"
if [[ -n "$pending" ]]; then
	echo "Verification failed - these files are not in sync, old videos were NOT deleted:" >&2
	echo "$pending" >&2
	exit 1
fi
echo "Verified: all videos from the Pi are present locally."

# 3. Only now remove local files that no longer exist on the Pi.
rsync "${RSYNC_OPTS[@]}" --delete "$PI:$SRC" "$DEST"
