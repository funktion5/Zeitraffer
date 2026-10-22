#!/bin/bash
# Run this on your own computer (macOS, Linux, or Windows inside WSL), never on the host itself.
# Pulls everything a reinstall needs that is not in git into a local backup folder; migrate.sh
# restores it. Needs bash, ssh, rsync and openssl on this computer.
#
# Host, user and backup folder come from backup.env next to this script
# (gitignored — copy backup.env.example). Variables set on the command line win:
#   BACKUP_HOST=192.0.2.10 ./backup.sh     if the hostname doesn't resolve
#   SKIP_VIDEOS=1 ./backup.sh              everything except the videos
#
# The secrets (SSH folder, htpasswd, mount and sudoers files, Apache site) are encrypted with a
# passphrase you enter here. Keep it in a password manager: without it the backup is useless.
set -euo pipefail

# The backup holds an SSH private key and a password hash — keep every file
# this script creates private from the start, not just at the end.
umask 077

# Parsed rather than sourced so the file can't run code, and so a variable
# already set in the environment is not overwritten by it. PI_HOST/PI_USER are
# the names from before the rename and still work.
ENV_FILE="$(cd "$(dirname "$0")" && pwd)/backup.env"
if [[ -f "$ENV_FILE" ]]; then
	while IFS='=' read -r key value || [[ -n "$key" ]]; do
		[[ "$key" =~ ^(BACKUP_HOST|BACKUP_USER|PI_HOST|PI_USER|PROJECT_DIR|DEST|SKIP_VIDEOS)$ ]] \
			|| continue
		[[ -z "${!key:-}" ]] || continue
		value="${value%\"}"
		value="${value#\"}"
		# Expand a leading ~ and $HOME by substitution (not eval), so paths in
		# backup.env stay portable without letting the file run code. PROJECT_DIR is a path on
		# the host, so it is expanded later with the host's home folder.
		if [[ "$key" != PROJECT_DIR ]]; then
			value="${value/#\~/$HOME}"
			value="${value//\$HOME/$HOME}"
		fi
		printf -v "$key" '%s' "$value"
	done <"$ENV_FILE"
fi

BACKUP_HOST="${BACKUP_HOST:-${PI_HOST:-}}"
BACKUP_USER="${BACKUP_USER:-${PI_USER:-}}"
: "${BACKUP_HOST:?not set — copy backup.env.example to backup.env and fill it in}"
: "${BACKUP_USER:?not set — copy backup.env.example to backup.env and fill it in}"
# Outside ~/Documents on purpose: with iCloud "Desktop & Documents" enabled,
# anything there would be uploaded to the cloud.
DEST="${DEST:-$HOME/timelapse-backup}"
SKIP_VIDEOS="${SKIP_VIDEOS:-0}"

# migrate.sh decrypts with the same settings; change both together.
CIPHER=(-aes-256-cbc -pbkdf2 -iter 600000 -md sha256)

TARGET="${BACKUP_USER}@${BACKUP_HOST}"

for tool in ssh scp rsync openssl tar; do
	command -v "$tool" >/dev/null || {
		echo "Missing tool on this computer: $tool" >&2
		exit 1
	}
done

# On the Windows drives inside WSL (/mnt/c, ...) file permissions are not enforced, so the
# backup would be readable by anything running as this Windows user.
if grep -qi microsoft /proc/version 2>/dev/null && [[ "$DEST" == /mnt/[a-z]/* ]]; then
	echo "WARNING: $DEST is on a Windows drive, where file permissions do not protect the backup." >&2
	echo "         Use a folder in the WSL home instead, e.g. DEST=\$HOME/timelapse-backup." >&2
fi

mkdir -p "$DEST"
chmod 700 "$DEST"

# Asked before connecting, so a typo does not cost a whole login. Read without echo, kept only
# in this process and handed to openssl through a pipe, never as an argument or a file.
while true; do
	read -rsp "Passphrase for the encrypted secrets: " PASSPHRASE
	echo
	read -rsp "Repeat the passphrase: " PASSPHRASE_AGAIN
	echo
	if [[ ${#PASSPHRASE} -lt 12 ]]; then
		echo "Use at least 12 characters." >&2
	elif [[ "$PASSPHRASE" != "$PASSPHRASE_AGAIN" ]]; then
		echo "The two entries differ." >&2
	else
		break
	fi
done
unset PASSPHRASE_AGAIN

# Single-quote a string for the host's POSIX shell.
quote() {
	printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# SSH may ask for a password, so share one connection across every ssh/scp/rsync call below
# and ask once. A short path under /tmp keeps the control socket under macOS's 104-character
# socket limit.
CONTROL_DIR="$(mktemp -d /tmp/timelapse-backup.XXXXXX)"
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=${CONTROL_DIR}/%C" -o ControlPersist=10m)
REMOTE_TAR=""

cleanup() {
	# Never leave the unencrypted secrets on the host, even if a step failed. Only reuse a live
	# shared connection: if the login itself failed, a fresh ssh here would just prompt for the
	# password again during exit.
	if ssh "${SSH_OPTS[@]}" -O check "$TARGET" 2>/dev/null; then
		if [[ -n "$REMOTE_TAR" ]]; then
			ssh "${SSH_OPTS[@]}" "$TARGET" "rm -f $(quote "$REMOTE_TAR")" 2>/dev/null || true
		fi
		ssh "${SSH_OPTS[@]}" -O exit "$TARGET" 2>/dev/null || true
	fi
	rm -rf "$CONTROL_DIR"
}
trap cleanup EXIT

echo "==> Connecting to ${TARGET} (password prompt at most once)"
ssh "${SSH_OPTS[@]}" -fN "$TARGET"

# The home folder is not always /home/<user> (e.g. /usr/home on some web servers).
REMOTE_HOME="$(ssh "${SSH_OPTS[@]}" "$TARGET" 'printf %s "$HOME"')"
PROJECT_DIR="${PROJECT_DIR:-$REMOTE_HOME/timelapse}"
PROJECT_DIR="${PROJECT_DIR/#\~/$REMOTE_HOME}"
PROJECT_DIR="${PROJECT_DIR//\$HOME/$REMOTE_HOME}"
ssh "${SSH_OPTS[@]}" "$TARGET" "test -d $(quote "$PROJECT_DIR")" \
	|| { echo "No project folder at ${PROJECT_DIR} on the host (set PROJECT_DIR)." >&2; exit 1; }

# 1) Secrets. A file the host does not have (no SSHFS mount, no Apache), or cannot read without
#    sudo, is skipped with a warning instead of failing the backup. The temporary archive gets a random name in the
#    user's own home, never a fixed name in a shared /tmp.
REMOTE_TAR="$(ssh "${SSH_OPTS[@]}" "$TARGET" 'mktemp "$HOME/.timelapse-backup.XXXXXX"')"
# shellcheck disable=SC2016 # $f and $@ expand on the host
PACK='umask 077; set --; for f in '"$(quote "$REMOTE_HOME/.ssh")"' /etc/timelapse/mount.env \
	/etc/sudoers.d/timelapse-web /etc/apache2/.htpasswd /etc/apache2/sites-available/zeitraffer.conf; do
	if [ -r "$f" ]; then set -- "$@" "$f"; else echo "  skipped (missing or not readable): $f" >&2; fi
done; tar czf '"$(quote "$REMOTE_TAR")"' "$@" 2>/dev/null'

# Root-owned files need sudo, and sudo needs a terminal for its password prompt, so the check
# and the packing run in one session. A host without sudo (no root) still gets the
# user-level secrets (~/.ssh) backed up.
echo "==> Packing secrets on the host (sudo password prompt)"
ssh "${SSH_OPTS[@]}" -t "$TARGET" "
	if command -v sudo >/dev/null 2>&1 && sudo -v; then
		sudo sh -c $(quote "$PACK") && sudo chown $(quote "$BACKUP_USER") $(quote "$REMOTE_TAR")
	else
		echo '  No sudo on the host: backing up only what this user can read (~/.ssh).' >&2
		sh -c $(quote "$PACK")
	fi"

# Streamed straight into openssl, so the unencrypted archive never lands on this computer.
ssh "${SSH_OPTS[@]}" "$TARGET" "cat $(quote "$REMOTE_TAR")" \
	| openssl enc "${CIPHER[@]}" -salt -pass fd:3 -out "$DEST/pi-backup.tar.gz.enc" \
		3< <(printf '%s' "$PASSPHRASE")
ssh "${SSH_OPTS[@]}" "$TARGET" "rm -f $(quote "$REMOTE_TAR")"
REMOTE_TAR=""
# An unencrypted archive from an older backup in the same folder is no longer needed.
rm -f "$DEST/pi-backup.tar.gz"

# 2) The login user's crontab (no sudo needed, it's the user's own). A host without one is fine.
echo "==> Saving crontab"
ssh "${SSH_OPTS[@]}" "$TARGET" 'crontab -l' >"$DEST/pi-crontab.txt" 2>/dev/null \
	|| { echo "  No crontab for ${BACKUP_USER}." >&2; : >"$DEST/pi-crontab.txt"; }

# 3) config.json is in git, but a local edit on the host would otherwise be lost.
echo "==> Saving config.json"
scp "${SSH_OPTS[@]}" "${TARGET}:${PROJECT_DIR}/config/config.json" "$DEST/config.json"

# 4) Detection models (not in git) and the state folder. The exact model files keep the
#    detector id, so cached blur results stay valid after a restore. The run lock and the
#    "run in progress" marker are left out: restored, the marker would start a run at boot.
for folder in models state; do
	if ssh "${SSH_OPTS[@]}" "$TARGET" "test -d $(quote "$PROJECT_DIR/$folder")"; then
		echo "==> Syncing ${folder}/"
		rsync -a --delete -e "ssh ${SSH_OPTS[*]}" \
			--exclude zeitraffer-run.lock --exclude run-in-progress \
			"${TARGET}:${PROJECT_DIR}/${folder}/" "$DEST/${folder}/"
	else
		echo "  No ${folder}/ on the host, skipped." >&2
	fi
done

# 5) Finished videos. rsync -a keeps the file modes; after copying them back,
#    run "./migrate.sh permissions" so Apache can read them again.
#    No -z: MP4s don't compress, and it only costs the host CPU.
if [[ "$SKIP_VIDEOS" == "1" ]]; then
	echo "==> Skipping videos (SKIP_VIDEOS=1)"
else
	echo "==> Syncing videos"
	rsync -a --progress -e "ssh ${SSH_OPTS[*]}" "${TARGET}:${PROJECT_DIR}/videos/" "$DEST/videos/"
fi

# Proves the passphrase and the archive before anyone relies on them.
echo
echo "Backup landed in: $DEST"
echo "Encrypted secrets contain:"
openssl enc -d "${CIPHER[@]}" -pass fd:3 -in "$DEST/pi-backup.tar.gz.enc" 3< <(printf '%s' "$PASSPHRASE") \
	| tar tzf - | sed 's/^/  - /'
unset PASSPHRASE

cat <<EOF

After a reinstall:
  1. A reinstalled host has new SSH host keys, so clear the old ones here first:
       ssh-keygen -R ${BACKUP_HOST}
  2. Copy the backup and the installer to the host:
       scp "$DEST/pi-backup.tar.gz.enc" "$DEST/pi-crontab.txt" "$DEST/config.json" migrate.sh ${TARGET}:~/
  3. On the host: ./migrate.sh (asks for the passphrase)
  4. Copy models, state and videos back, then fix the permissions on the host:
       rsync -a "$DEST/models/" ${TARGET}:${PROJECT_DIR}/models/
       rsync -a "$DEST/state/" ${TARGET}:${PROJECT_DIR}/state/
       rsync -a --progress "$DEST/videos/" ${TARGET}:${PROJECT_DIR}/videos/
       ./migrate.sh permissions verify
EOF
