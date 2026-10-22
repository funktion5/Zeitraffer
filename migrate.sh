#!/bin/bash
# One-shot reinstall migration. Copy this file anywhere on the new Pi and run
# it as the login user (not root) after copying the Mac backup
# (pi-backup.tar.gz, pi-crontab.txt, config.json) into $HOME — it clones the
# repo itself. Users and paths are taken from the running session, so nothing
# about a particular Pi is written into this file.
#
# Usage:
#   ./migrate.sh                  run every step in order
#   ./migrate.sh permissions      run only the named step(s), e.g. after the
#   ./migrate.sh permissions verify   videos have been copied over by hand
#
# Videos are not part of this script; they are copied manually. Re-run the
# permissions step afterwards so Apache can read them.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/funktion5/Zeitraffer.git}"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
PROJECT_ROOT="${PROJECT_ROOT:-$HOME/timelapse}"
# backup.sh writes the encrypted .enc; an unencrypted archive from before still works.
if [[ -z "${BACKUP_TAR:-}" ]]; then
	BACKUP_TAR="$HOME/pi-backup.tar.gz.enc"
	[[ -f "$BACKUP_TAR" ]] || BACKUP_TAR="$HOME/pi-backup.tar.gz"
fi
# Must match backup.sh; change both together.
CIPHER=(-aes-256-cbc -pbkdf2 -iter 600000 -md sha256)
BACKUP_CRONTAB="${BACKUP_CRONTAB:-$HOME/pi-crontab.txt}"
BACKUP_CONFIG="${BACKUP_CONFIG:-$HOME/config.json}"

# This Pi is wired via Ethernet, so WiFi is disabled outright rather than
# restored — nothing depends on it and one less radio to worry about.
DISABLE_WIFI="${DISABLE_WIFI:-1}"

ALL_STEPS=(
	preflight
	packages
	clone
	venv
	restore_backup
	known_hosts
	sshfs_mount
	apache
	web_bridge
	permissions
	disable_wifi
	verify
)

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
fail() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

require_file() {
	[[ -f "$1" ]] || fail "Missing expected file: $1"
}

step_preflight() {
	log "Preflight checks"
	[[ "$(id -u)" != "0" ]] || fail "Run this as the Pi's login user, not root."
	require_file "$BACKUP_TAR"
	require_file "$BACKUP_CRONTAB"
	# config.json is committed to git and was clean at last check, so it's
	# optional here — git clone alone reproduces it. Warn, don't block.
	[[ -f "$BACKUP_CONFIG" ]] || warn "$BACKUP_CONFIG not found — using the version from git clone instead."
	sudo -v || fail "sudo access is required."
}

step_packages() {
	log "Installing packages"
	sudo apt-get update
	sudo apt-get install -y \
		git python3 python3-venv python3-pip \
		ffmpeg sshfs openssl \
		apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache

	if ! grep -qx "user_allow_other" /etc/fuse.conf 2>/dev/null; then
		echo "user_allow_other" | sudo tee -a /etc/fuse.conf >/dev/null
	fi
}

step_clone() {
	if [[ -d "$PROJECT_ROOT/.git" ]]; then
		local existing_url
		existing_url="$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || true)"
		[[ "$existing_url" == "$REPO_URL" ]] \
			|| fail "$PROJECT_ROOT is already a git repo, but its origin ($existing_url) doesn't match $REPO_URL."
		log "$PROJECT_ROOT already cloned from the right repo — leaving it as-is"
		return
	fi
	if [[ -d "$PROJECT_ROOT" ]]; then
		[[ -z "$(ls -A "$PROJECT_ROOT" 2>/dev/null)" ]] \
			|| fail "$PROJECT_ROOT already exists and is not empty — remove or move it first, then re-run."
		rmdir "$PROJECT_ROOT"
	fi
	log "Cloning the repo to $PROJECT_ROOT"
	git clone "$REPO_URL" "$PROJECT_ROOT"
}

step_venv() {
	log "Setting up Python virtualenv"
	cd "$PROJECT_ROOT"
	python3 -m venv .venv
	"$PROJECT_ROOT/.venv/bin/pip" install -r requirements.txt
}

step_restore_backup() {
	log "Restoring backup (SSHFS key, mount.env, sudoers, htpasswd, vhost)"
	# Extract to a staging dir instead of straight onto /, so a broken sudoers
	# file is caught by visudo before it can lock sudo out for the rest of the run.
	local staging
	staging="$(mktemp -d)"
	# EXIT, not RETURN: fail() exits from inside this function, and a RETURN
	# trap would not fire then — leaving the extracted secrets in /tmp.
	# shellcheck disable=SC2064
	trap "sudo rm -rf '$staging'" EXIT
	if [[ "$BACKUP_TAR" == *.enc ]]; then
		local passphrase
		read -rsp "Passphrase of the backup: " passphrase
		echo
		# Through a pipe, never as an argument or a file; the plain archive is never written.
		openssl enc -d "${CIPHER[@]}" -pass fd:3 -in "$BACKUP_TAR" 3< <(printf '%s' "$passphrase") \
			| sudo tar xzf - -C "$staging" \
			|| fail "Could not decrypt $BACKUP_TAR (wrong passphrase?)."
		unset passphrase
	else
		sudo tar xzf "$BACKUP_TAR" -C "$staging"
	fi

	local sudoers="$staging/etc/sudoers.d/timelapse-web"
	sudo test -f "$sudoers" || fail "Backup has no etc/sudoers.d/timelapse-web."
	sudo visudo -cf "$sudoers" >/dev/null || fail "Backed-up sudoers file does not parse — not installing it."
	sudo grep -q "/usr/local/sbin/timelapse-web-trigger" "$sudoers" \
		|| fail "Backed-up sudoers file lacks the timelapse-web-trigger rule."
	# Exact names: "timelapse-web-delete" alone would also match "timelapse-web-delete-highlight".
	sudo grep -Eq "/usr/local/sbin/timelapse-web-delete([[:space:],]|$)" "$sudoers" \
		|| fail "Backed-up sudoers file lacks the timelapse-web-delete rule."
	# Backups from before the highlights page lack this rule; restore them anyway.
	sudo grep -Eq "/usr/local/sbin/timelapse-web-delete-highlight([[:space:],]|$)" "$sudoers" \
		|| warn "Backed-up sudoers file lacks the timelapse-web-delete-highlight rule. Add it afterwards with sudo visudo -f /etc/sudoers.d/timelapse-web: www-data ALL=($RUN_USER) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight"
	sudo install -o root -g root -m 440 "$sudoers" /etc/sudoers.d/timelapse-web

	sudo install -D -o root -g root -m 600 "$staging/etc/timelapse/mount.env" /etc/timelapse/mount.env
	# Only Apache needs to read the password hashes, not every local user.
	sudo install -o root -g www-data -m 640 "$staging/etc/apache2/.htpasswd" /etc/apache2/.htpasswd
	sudo install -o root -g root -m 644 \
		"$staging/etc/apache2/sites-available/zeitraffer.conf" \
		/etc/apache2/sites-available/zeitraffer.conf

	# tar strips the leading slash, so the backup stores $HOME as home/<user>.
	# That only matches if the backup was taken for the same user.
	local staged_ssh="$staging/${HOME#/}/.ssh"
	sudo test -d "$staged_ssh" \
		|| fail "Backup has no ${HOME#/}/.ssh — was it made for another PI_USER?"

	# Restore every file of the backed-up ~/.ssh, so no key file name is hardcoded here.
	# known_hosts is merged below; authorized_keys is left out so a restore never adds logins.
	install -d -m 700 "$HOME/.ssh"
	local staged_file name mode
	while IFS= read -r staged_file; do
		name="$(basename "$staged_file")"
		[[ "$name" == "known_hosts" || "$name" == "authorized_keys" ]] && continue
		mode=600
		[[ "$name" == *.pub ]] && mode=644
		sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m "$mode" "$staged_file" "$HOME/.ssh/$name"
	done < <(sudo find "$staged_ssh" -maxdepth 1 -type f)

	# mount.env names the key the SSHFS mount uses; it must have come back with ~/.ssh.
	local key_path
	key_path="$(sudo bash -c 'source "$1" && printf "%s" "$REMOTE_SSH_KEY"' _ /etc/timelapse/mount.env)"
	key_path="${key_path/#\~/$HOME}"
	[[ -n "$key_path" ]] || fail "REMOTE_SSH_KEY is empty in /etc/timelapse/mount.env."
	[[ -f "$key_path" ]] || fail "The key from mount.env ($key_path) is not in the backup."
	[[ -f "$HOME/.ssh/config" ]] \
		|| log "No ~/.ssh/config in the backup — the storage filter needs a Host entry (see README)."

	# The Storage Box's host key survives a Pi reinstall, so restoring it keeps
	# the trust that was established originally instead of re-scanning. Older
	# backups lack this file; step_known_hosts then falls back to a confirmed scan.
	local backup_known_hosts="$staged_ssh/known_hosts"
	if sudo test -f "$backup_known_hosts"; then
		touch "$HOME/.ssh/known_hosts"
		chmod 644 "$HOME/.ssh/known_hosts"
		local line
		while IFS= read -r line; do
			[[ -n "$line" ]] || continue
			grep -qxF -- "$line" "$HOME/.ssh/known_hosts" || printf '%s\n' "$line" >>"$HOME/.ssh/known_hosts"
		done < <(sudo cat "$backup_known_hosts")
	fi

	sudo rm -rf "$staging"
	trap - EXIT

	if [[ -f "$BACKUP_CONFIG" ]]; then
		cp "$BACKUP_CONFIG" "$PROJECT_ROOT/config/config.json"
	fi
	crontab "$BACKUP_CRONTAB"
}

step_known_hosts() {
	log "Accepting the Storage Box host key"
	local host port lookup scanned
	# mount.env is root:600 — read it as root rather than relaxing its mode.
	# A non-space delimiter keeps an empty REMOTE_HOST from shifting the port
	# into the host field.
	IFS='|' read -r host port < <(
		sudo bash -c 'source /etc/timelapse/mount.env && printf "%s|%s\n" "$REMOTE_HOST" "${REMOTE_PORT:-22}"'
	)
	[[ -n "$host" ]] || fail "REMOTE_HOST is empty in /etc/timelapse/mount.env."
	if [[ "$port" == "22" ]]; then
		lookup="$host"
	else
		lookup="[$host]:$port"
	fi

	touch "$HOME/.ssh/known_hosts"
	chmod 644 "$HOME/.ssh/known_hosts"
	if ssh-keygen -F "$lookup" -f "$HOME/.ssh/known_hosts" >/dev/null; then
		echo "$lookup is already in known_hosts — leaving it as-is."
		return
	fi

	# ssh-keyscan trusts whatever key answers, which undercuts the mount's
	# StrictHostKeyChecking=yes — so show the fingerprint and make a human confirm it.
	scanned="$(ssh-keyscan -p "$port" "$host" 2>/dev/null)"
	[[ -n "$scanned" ]] || fail "ssh-keyscan got no host key from $lookup."
	echo "Host key fingerprints offered by $lookup:"
	ssh-keygen -lf - <<<"$scanned"
	local answer
	read -rp "Do these match the Storage Box fingerprints from the provider? [y/N] " answer
	[[ "$answer" == [yY] ]] || fail "Host key not confirmed — nothing was added to known_hosts."
	printf '%s\n' "$scanned" >>"$HOME/.ssh/known_hosts"
}

step_sshfs_mount() {
	log "Installing the SSHFS camera mount"
	# The unit carries @RUN_USER@/@RUN_GROUP@ placeholders so no account name is committed.
	# Fill them in for this account; a leftover placeholder would only fail at boot.
	local unit
	unit="$(mktemp)"
	sed -e "s/@RUN_USER@/$RUN_USER/g" -e "s/@RUN_GROUP@/$RUN_GROUP/g" \
		"$PROJECT_ROOT/systemd/cameras-sshfs.service" >"$unit"
	if grep -q '@RUN_' "$unit"; then
		rm -f "$unit"
		fail "systemd/cameras-sshfs.service still has placeholders after substitution."
	fi
	sudo mkdir -p /mnt/cameras
	sudo install -m 755 "$PROJECT_ROOT/scripts/cameras-sshfs-preflight" /usr/local/sbin/cameras-sshfs-preflight
	sudo install -m 644 "$unit" /etc/systemd/system/cameras-sshfs.service
	rm -f "$unit"
	sudo systemctl daemon-reload
	sudo systemctl enable --now cameras-sshfs.service
}

step_apache() {
	log "Enabling the Apache vhost"
	require_file /etc/apache2/sites-available/zeitraffer.conf
	sudo test -f /etc/apache2/.htpasswd || fail "Missing expected file: /etc/apache2/.htpasswd"
	sudo a2ensite zeitraffer.conf
	sudo a2dissite 000-default.conf 2>/dev/null || true
	sudo apache2ctl configtest || fail "Apache config test failed — not reloading."
	sudo systemctl reload apache2
}

step_web_bridge() {
	log "Installing the web-to-Python bridge wrappers"
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/timelapse-web-trigger" /usr/local/sbin/timelapse-web-trigger
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/timelapse-web-delete" /usr/local/sbin/timelapse-web-delete
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/timelapse-web-delete-highlight" /usr/local/sbin/timelapse-web-delete-highlight
	sudo mkdir -p /usr/local/libexec
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/timelapse-web-worker" /usr/local/libexec/timelapse-web-worker
	sudo install -m 644 -o root -g root "$PROJECT_ROOT/scripts/timelapse-web-status.sh" /usr/local/libexec/timelapse-web-status.sh
	sudo test -f /etc/sudoers.d/timelapse-web || fail "Missing expected file: /etc/sudoers.d/timelapse-web"
}

step_permissions() {
	log "Setting website-only permissions for www-data"
	# www-data is deliberately not in the login user's group. It gets pass-through on
	# the path down to the project and read access only to what the PHP code
	# touches: web/, videos/, config/config.json and state/web-jobs/.
	# Debian 13 creates homes as 0700 and git clone makes everything
	# world-readable, so both have to be corrected here.
	chmod o+x "$HOME"
	# Pass-through on $HOME makes every world-readable file in it reachable by
	# name — including pi-backup.tar.gz with the SSH key — so close everything
	# at the top of $HOME except the project itself.
	find "$HOME" -mindepth 1 -maxdepth 1 ! -path "$PROJECT_ROOT" -perm /o=rwx -exec chmod o-rwx {} +
	cd "$PROJECT_ROOT"

	# Pre-create runtime dirs closed; Python's later mkdir(exist_ok) keeps the mode.
	mkdir -p -m 770 logs temp reports
	mkdir -p videos state

	local entry
	while IFS= read -r -d '' entry; do
		case "${entry#./}" in
			web | videos | config | state) ;;
			*) chmod o-rwx "$entry" ;;
		esac
	done < <(find . -mindepth 1 -maxdepth 1 -print0)

	chmod o=x . config state
	find web videos -type d -exec chmod o+rx,o-w {} +
	find web videos -type f -exec chmod o+r,o-wx {} +

	find config -mindepth 1 ! -name config.json -exec chmod o-rwx {} +
	chmod o=r config/config.json

	# web-jobs/ itself is created 755/644 by timelapse-web-status.sh; everything
	# else in state/ (lock, run marker) stays closed.
	find state -mindepth 1 -maxdepth 1 ! -name web-jobs -exec chmod o-rwx {} +
}

step_disable_wifi() {
	if [[ "$DISABLE_WIFI" != "1" ]]; then
		warn "Skipping WiFi disable (DISABLE_WIFI=0 set)."
		return
	fi
	log "Disabling WiFi (this Pi runs on Ethernet)"

	# Turning the radio off would drop an SSH session that came in over WiFi
	# and abort the script mid-run, so check the incoming interface first.
	if [[ -n "${SSH_CONNECTION:-}" ]]; then
		local client_ip session_iface
		client_ip="${SSH_CONNECTION%% *}"
		session_iface="$(ip route get "$client_ip" 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}')"
		if [[ "$session_iface" == wl* ]]; then
			warn "This SSH session runs over $session_iface — skipping WiFi disable. Reconnect via Ethernet and run: $0 disable_wifi"
			return
		fi
	fi

	sudo nmcli radio wifi off || warn "nmcli could not turn the WiFi radio off."

	local boot_config="/boot/firmware/config.txt"
	if [[ -f "$boot_config" ]] && ! grep -q "^dtoverlay=disable-wifi" "$boot_config"; then
		echo "dtoverlay=disable-wifi" | sudo tee -a "$boot_config" >/dev/null
		warn "WiFi disabled at the hardware level in $boot_config — takes full effect after a reboot."
	fi
}

step_verify() {
	log "Verification"
	cd "$PROJECT_ROOT"
	"$PROJECT_ROOT/.venv/bin/python3" -m pytest -q || warn "Tests failed — check before relying on this in production."

	systemctl is-active --quiet cameras-sshfs.service \
		&& echo "cameras-sshfs: active" || warn "cameras-sshfs is not running."
	mountpoint -q /mnt/cameras \
		&& echo "/mnt/cameras: mounted" || warn "/mnt/cameras is not mounted."
	crontab -l | grep -q "src.main" \
		&& echo "crontab: restored" || warn "crontab does not look restored."

	# 401 means Apache reached the docroot and is asking for Basic Auth; 403 is
	# the classic sign that www-data cannot traverse into the project.
	local http_code
	http_code="$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ || true)"
	if [[ "$http_code" == "401" ]]; then
		echo "Dashboard: 401 (auth prompt, as expected)"
	else
		warn "Dashboard returned HTTP $http_code, expected 401 — check /var/log/apache2/zeitraffer-error.log."
	fi

	local path
	for path in web/public/index.php web/src/video-library.php config/config.json; do
		sudo -u www-data test -r "$PROJECT_ROOT/$path" \
			&& echo "www-data can read $path" || warn "www-data cannot read $path"
	done
	sudo -u www-data test -x "$PROJECT_ROOT/videos" \
		&& echo "www-data can enter videos/" || warn "www-data cannot enter videos/"
	for path in src/main.py config/mount.env.example .git .venv; do
		sudo -u www-data test -r "$PROJECT_ROOT/$path" \
			&& warn "www-data can read $path — it should not" || echo "www-data blocked from $path"
	done
	sudo -u www-data test -r "$PROJECT_ROOT" \
		&& warn "www-data can list the project root — it should not" || echo "www-data cannot list the project root"

	local sudo_rules
	sudo_rules="$(sudo -l -U www-data 2>/dev/null || true)"
	grep -q "timelapse-web-trigger" <<<"$sudo_rules" \
		&& echo "sudoers: trigger rule active" || warn "sudoers: trigger rule missing for www-data."
	grep -Eq "timelapse-web-delete([[:space:],]|$)" <<<"$sudo_rules" \
		&& echo "sudoers: delete rule active" || warn "sudoers: delete rule missing for www-data."
	grep -Eq "timelapse-web-delete-highlight([[:space:],]|$)" <<<"$sudo_rules" \
		&& echo "sudoers: highlight delete rule active" \
		|| warn "sudoers: highlight delete rule missing for www-data."
	[[ -x /usr/local/sbin/timelapse-web-delete-highlight ]] \
		&& echo "highlight delete wrapper: installed" \
		|| warn "/usr/local/sbin/timelapse-web-delete-highlight is not installed."

	if [[ "$DISABLE_WIFI" == "1" ]]; then
		[[ "$(nmcli radio wifi 2>/dev/null)" == "disabled" ]] \
			&& echo "WiFi radio: disabled" || warn "WiFi radio is still enabled."
	fi
}

main() {
	local steps=("$@")
	if ((${#steps[@]} == 0)); then
		steps=("${ALL_STEPS[@]}")
	fi

	local step
	for step in "${steps[@]}"; do
		declare -F "step_$step" >/dev/null \
			|| fail "Unknown step: $step (available: ${ALL_STEPS[*]})"
	done
	for step in "${steps[@]}"; do
		"step_$step"
	done

	log "Done. Log in to the dashboard in a browser, play a video and start a test job."
}

main "$@"
