#!/bin/bash
# Run this ON THE MAC, not on the Pi. Pulls everything the Pi reinstall needs
# that is not in git into a local backup folder; migrate.sh restores it.
#
#   PI_HOST=192.168.178.41 ./backup-from-mac.sh   if zr-pi.local doesn't resolve
#   SKIP_VIDEOS=1 ./backup-from-mac.sh            config and secrets only
set -euo pipefail

# The backup holds an SSH private key and a password hash — keep every file
# this script creates private from the start, not just at the end.
umask 077

PI_HOST="${PI_HOST:-zr-pi.local}"
PI_USER="${PI_USER:-zruser}"
DEST="${DEST:-/Users/praktikant/Documents/Migration}"
SKIP_VIDEOS="${SKIP_VIDEOS:-0}"

PI="${PI_USER}@${PI_HOST}"
PI_PROJECT="/home/${PI_USER}/timelapse"
REMOTE_TAR="/tmp/pi-backup.tar.gz"
SECRET_FILES="/home/${PI_USER}/.ssh/storagebox_ed25519
/home/${PI_USER}/.ssh/storagebox_ed25519.pub
/home/${PI_USER}/.ssh/known_hosts
/etc/timelapse/mount.env
/etc/sudoers.d/timelapse-web
/etc/apache2/.htpasswd
/etc/apache2/sites-available/zeitraffer.conf"

mkdir -p "$DEST"
chmod 700 "$DEST"

# SSH to the Pi is password-only, so share one connection across every
# ssh/scp/rsync call below and ask for the password once. A short path under
# /tmp keeps the control socket under macOS's 104-character socket limit.
CONTROL_DIR="$(mktemp -d /tmp/pi-backup.XXXXXX)"
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=${CONTROL_DIR}/%C" -o ControlPersist=10m)

cleanup() {
	# Never leave the secrets tar behind on the Pi, even if a step failed.
	# Only reuse a live shared connection: if the login itself failed, a fresh
	# ssh here would just prompt for the password again during exit.
	if ssh "${SSH_OPTS[@]}" -O check "$PI" 2>/dev/null; then
		ssh "${SSH_OPTS[@]}" "$PI" "rm -f ${REMOTE_TAR}" 2>/dev/null || true
		ssh "${SSH_OPTS[@]}" -O exit "$PI" 2>/dev/null || true
	fi
	rm -rf "$CONTROL_DIR"
}
trap cleanup EXIT

echo "==> Connecting to ${PI} (password prompt once)"
ssh "${SSH_OPTS[@]}" -fN "$PI"

# 1) Root-owned secrets. sudo needs a real terminal for its password prompt,
#    and binary data can't travel over one, so the tar is written on the Pi
#    first — with umask 077 it is 600 and only readable by zruser and root.
echo "==> Packing secrets on the Pi (sudo password prompt)"
# shellcheck disable=SC2086 # the file list is meant to word-split
ssh "${SSH_OPTS[@]}" -t "$PI" \
	"sudo sh -c 'umask 077 && rm -f ${REMOTE_TAR} && tar czf ${REMOTE_TAR} $(echo $SECRET_FILES) && chown ${PI_USER}:${PI_USER} ${REMOTE_TAR}'"
scp "${SSH_OPTS[@]}" "${PI}:${REMOTE_TAR}" "$DEST/pi-backup.tar.gz"
ssh "${SSH_OPTS[@]}" "$PI" "rm -f ${REMOTE_TAR}"

# 2) zruser's crontab (no sudo needed, it's the user's own).
echo "==> Saving crontab"
ssh "${SSH_OPTS[@]}" "$PI" 'crontab -l' >"$DEST/pi-crontab.txt"

# 3) config.json is in git, but a local edit on the Pi would otherwise be lost.
echo "==> Saving config.json"
scp "${SSH_OPTS[@]}" "${PI}:${PI_PROJECT}/config/config.json" "$DEST/config.json"

# 4) Finished videos. rsync -a keeps the Pi's file modes; after copying them
#    back, run "./migrate.sh permissions" so Apache can read them again.
#    No -z: MP4s don't compress, and it only costs the Pi CPU.
if [[ "$SKIP_VIDEOS" == "1" ]]; then
	echo "==> Skipping videos (SKIP_VIDEOS=1)"
else
	echo "==> Syncing videos"
	rsync -a --progress -e "ssh ${SSH_OPTS[*]}" "${PI}:${PI_PROJECT}/videos/" "$DEST/videos/"
fi

echo
echo "Backup landed in: $DEST"
tar tzf "$DEST/pi-backup.tar.gz" | sed 's/^/  - /'
cat <<EOF

After the reinstall:
  1. The Pi has new SSH host keys, so clear the old ones on this Mac first:
       ssh-keygen -R ${PI_HOST}
       ssh-keygen -R <the Pi's IP address>
  2. Copy the backup and the installer to the Pi:
       scp "$DEST/pi-backup.tar.gz" "$DEST/pi-crontab.txt" "$DEST/config.json" migrate.sh ${PI}:~/
  3. On the Pi: ./migrate.sh
  4. Copy the videos back, then fix their permissions on the Pi:
       rsync -a --progress "$DEST/videos/" ${PI}:${PI_PROJECT}/videos/
       ./migrate.sh permissions verify
EOF
