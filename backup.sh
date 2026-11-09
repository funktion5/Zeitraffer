#!/bin/bash
# Saves what a new host needs and the Git repository does not hold, so install.sh can restore it.
# Runs on any computer with ssh and rsync (the Mac, usually) and only READS from the host: rsync
# pulls and `crontab -l`. Nothing is written on the host.
#
# Usage:
#   BACKUP_HOST=<ssh alias> ./backup.sh              models/, state/ and the crontab (reference)
#   BACKUP_HOST=<ssh alias> VIDEOS=1 ./backup.sh     plus videos/ (several GB; the nightly run
#                                                    builds new ones, so they are optional)
#
# Settings: environment variables, or one NAME=value per line in backup.env next to this script
# (or in the file named by BACKUP_CONFIG). The environment wins. See backup.env.example.
#   BACKUP_HOST   ssh alias of the host in ~/.ssh/config (required)
#   PROJECT_DIR   project folder on the host, relative to its home (default: timelapse)
#   DEST          where the backup goes (default: ~/timelapse-backup, made private: mode 700)
#   VIDEOS        1 also saves videos/ (default: 0)
#
# Deliberately NOT saved: every secret. The web login is created by install.sh (step web_login),
# the upload password is typed into config/siteground.env by hand (template:
# config/siteground.env.example), and the Storage Box ssh key is a new one on every host.
#
# Restoring: copy the backup folder to ~/timelapse-backup on the new host; ./install.sh restores it
# (step restore). Details: docs/vps.md.

set -euo pipefail


# ============================================================
# FUNCTIONS
# ============================================================

error_exit() {
    echo "[ERROR] $1" >&2
    exit "${2:-1}"
}

info() {
    echo "$1"
}


# ============================================================
# SETTINGS
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${BACKUP_CONFIG:-$SCRIPT_DIR/backup.env}"

BACKUP_HOST="${BACKUP_HOST:-}"
PROJECT_DIR="${PROJECT_DIR:-}"
DEST="${DEST:-}"
VIDEOS="${VIDEOS:-}"

# The file only fills what the environment leaves empty. It is read as text, never executed, and
# only these four names count.
if [[ -r "$CONFIG_FILE" ]]; then
    while IFS='=' read -r KEY VALUE || [[ -n "$KEY" ]]; do
        case "$KEY" in
            BACKUP_HOST|PROJECT_DIR|DEST|VIDEOS)
                [[ -n "${!KEY}" ]] || printf -v "$KEY" '%s' "$VALUE"
                ;;
        esac
    done < "$CONFIG_FILE"
fi

PROJECT_DIR="${PROJECT_DIR:-timelapse}"
DEST="${DEST:-$HOME/timelapse-backup}"
VIDEOS="${VIDEOS:-0}"

# The values end up in ssh and rsync arguments: anything that could be read as an option or as a
# second command is refused before the first call.
[[ -n "$BACKUP_HOST" ]] \
    || error_exit "BACKUP_HOST is not set: the ssh alias of the host (see backup.env.example)." 2

[[ "$BACKUP_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9._@-]*$ ]] \
    || error_exit "Invalid BACKUP_HOST: $BACKUP_HOST" 2

[[ "$PROJECT_DIR" =~ ^[A-Za-z0-9._/-]+$ && "$PROJECT_DIR" != /* && "$PROJECT_DIR" != *..* ]] \
    || error_exit "Invalid PROJECT_DIR (relative to the host's home, no '..'): $PROJECT_DIR" 2

[[ "$VIDEOS" == "0" || "$VIDEOS" == "1" ]] \
    || error_exit "VIDEOS must be 0 or 1." 2

for TOOL in ssh rsync; do
    command -v "$TOOL" >/dev/null 2>&1 \
        || error_exit "$TOOL was not found on this computer." 2
done


# ============================================================
# BACKUP
# ============================================================

mkdir -p "$DEST"
chmod 700 "$DEST"

FAILED=()

# Pulls <name>/ of the project into the backup folder. A failure is remembered, not fatal: the
# other items are still saved, and the run ends with an error.
pull() {
    local name="$1"
    shift

    mkdir -p "$DEST/$name"
    info "==> $name/"

    if rsync -a "$@" -e ssh "$BACKUP_HOST:$PROJECT_DIR/$name/" "$DEST/$name/"; then
        return 0
    fi

    echo "[WARN] $name/ could not be saved." >&2
    FAILED+=("$name")
}

pull models

# Locks and the run marker would block the new host; web-jobs/ is only transient job status.
pull state --exclude='*.lock' --exclude='run-in-progress' --exclude='web-jobs/'

if [[ "$VIDEOS" == "1" ]]; then
    # Hidden files are half-written renders and macOS leftovers.
    pull videos --progress --exclude='.*'
else
    info "==> videos/ skipped (VIDEOS=1 saves them)"
fi

# For reference only: the cron lines of one host must never be pasted onto another.
info "==> crontab (for reference)"

if ! ssh -- "$BACKUP_HOST" 'crontab -l' > "$DEST/crontab.txt" 2>/dev/null; then
    : > "$DEST/crontab.txt"
    info "  No crontab on $BACKUP_HOST (or it is not readable)."
fi


# ============================================================
# DONE
# ============================================================

echo "----------------------------------------"
info "Backup folder: $DEST"
du -sh "$DEST"/* 2>/dev/null || true
info "Not saved on purpose: the web login (install.sh creates it), the upload password (typed into"
info "config/siteground.env by hand) and the ssh key (a new one per host)."

if [[ ${#FAILED[@]} -gt 0 ]]; then
    error_exit "Not saved: ${FAILED[*]}" 1
fi

info "Done."
