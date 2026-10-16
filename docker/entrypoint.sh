#!/bin/bash
# Start of every container run: optionally mount the camera images read-only, then run the given
# command as the unprivileged user "app". See docs/docker.md.
set -euo pipefail

MOUNTPOINT="/mnt/cameras"
SSH_SOURCE="/ssh-ro"
APP_HOME="/home/app"

# The SSH files come in read-only and with host ownership; ssh insists on private, owned files.
if [[ -d "$SSH_SOURCE" ]]; then
	mkdir -p "$APP_HOME/.ssh"
	cp -r "$SSH_SOURCE/." "$APP_HOME/.ssh/"
	chown -R app:app "$APP_HOME/.ssh"
	chmod 700 "$APP_HOME/.ssh"
	find "$APP_HOME/.ssh" -type f -exec chmod 600 {} +
fi

# The live job writes to the storage box. During a trial the Pi stays productive, and two writers
# on the same camera folders would get in each other's way, so it needs an explicit opt-in.
if [[ "$*" == *"src.privacy.blur_box"* && "${ALLOW_BOX_WRITES:-0}" != "1" ]]; then
	echo "ERROR: The live blur job writes to the storage box and is off in this container." >&2
	echo "ERROR: Set ALLOW_BOX_WRITES=1 only once the container replaces the Pi." >&2
	exit 1
fi

# Same options as systemd/cameras-sshfs.service on the Pi: read-only, strict host key check.
if [[ "${MOUNT_CAMERAS:-0}" == "1" ]]; then
	for variable in REMOTE_USER REMOTE_HOST REMOTE_PORT REMOTE_SSH_KEY; do
		if [[ -z "${!variable:-}" ]]; then
			echo "ERROR: $variable is not set (see docker/storage-box.env.example)." >&2
			exit 1
		fi
	done

	sshfs -p "$REMOTE_PORT" \
		-o ro \
		-o IdentityFile="$REMOTE_SSH_KEY" \
		-o UserKnownHostsFile="$APP_HOME/.ssh/known_hosts" \
		-o BatchMode=yes \
		-o StrictHostKeyChecking=yes \
		-o reconnect \
		-o ServerAliveInterval=30 \
		-o ServerAliveCountMax=3 \
		-o allow_other \
		"${REMOTE_USER}@${REMOTE_HOST}:" "$MOUNTPOINT"

	if ! timeout 10 findmnt -rn --mountpoint "$MOUNTPOINT" >/dev/null; then
		echo "ERROR: Camera images could not be mounted at $MOUNTPOINT." >&2
		exit 1
	fi

	echo "INFO: Camera images mounted read-only at $MOUNTPOINT."
fi

# Never run the program as root: drop to "app" with no capabilities left.
exec setpriv --reuid=app --regid=app --init-groups --inh-caps=-all \
	env HOME="$APP_HOME" "$@"
