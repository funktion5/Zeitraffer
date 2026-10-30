#!/bin/bash
# Host-neutral installer for a fresh Debian/Ubuntu host (a VPS now, a Pi or any other machine
# later). Run it from inside the cloned repo, as the login user (not root), after the two
# preparations below (details: docs/vps.md):
#   1. A Storage Box key on this host (ssh-keygen, ssh-copy-id) and a Host entry for it in
#      ~/.ssh/config, named by BOX_ALIAS. The old host's key is deliberately not carried over.
#   2. The backup of the old host copied into $HOME:
#        pi-backup.tar.gz.enc   encrypted htpasswd, made by backup.sh
#        config.json            optional; a local edit made on the old host
# The repo must live in ~/timelapse: the installed web wrappers look there.
#
# The jobs read the frames over ssh from the Storage Box (a FrameSource in src/images.py), so there
# is no SSHFS mount, no /mnt/cameras and no @reboot recovery here.
#
# Usage:
#   ./install.sh                  run every step in order
#   ./install.sh permissions verify
#                                 run only the named step(s), e.g. after rsyncing videos
#
# Settings (environment):
#   BOX_ALIAS     Host name of the Storage Box in ~/.ssh/config (default: storagebox)
#   SERVER_NAME   vhost name, the subdomain (default: localhost)
#   WEB_PORT      port of the vhost (default: 80). TLS is not set up here.
#   BACKUP_TAR    default ~/pi-backup.tar.gz.enc
#   BACKUP_CONFIG default ~/config.json
#   REWRITE_VHOST=1  overwrite an existing, different vhost file (it is kept by default, so a
#                    later TLS setup is not undone by a re-run)
#
# Not done here, on purpose: the crontab (printed at the end, you paste it) and the copy of
# models/, state/ and videos/ (rsync from the Mac, see docs/vps.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
SERVER_NAME="${SERVER_NAME:-localhost}"
WEB_PORT="${WEB_PORT:-80}"
BACKUP_TAR="${BACKUP_TAR:-$HOME/pi-backup.tar.gz.enc}"
BACKUP_CONFIG="${BACKUP_CONFIG:-$HOME/config.json}"
REWRITE_VHOST="${REWRITE_VHOST:-0}"
# Must match backup.sh; change both together.
CIPHER=(-aes-256-cbc -pbkdf2 -iter 600000 -md sha256)
# The ssh alias the code uses for the Storage Box (handed over as TIMELAPSE_STORAGE_BOX); user,
# host, port and key live in ~/.ssh/config, so none of them is in the repository.
BOX_ALIAS="${BOX_ALIAS:-storagebox}"

ALL_STEPS=(
	preflight
	packages
	venv
	restore_backup
	known_hosts
	apache
	web_bridge
	permissions
	verify
	cron_hint
)

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
fail() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

require_file() {
	[[ -f "$1" ]] || fail "Missing expected file: $1"
}

has_box_alias() {
	grep -qsE "^Host[[:space:]]+$BOX_ALIAS([[:space:]]|$)" "$HOME/.ssh/config"
}

step_preflight() {
	log "Preflight checks"
	[[ "$(id -u)" != "0" ]] || fail "Run this as the login user, not root."
	[[ "$PROJECT_ROOT" == "$HOME/timelapse" ]] \
		|| fail "The repo is in $PROJECT_ROOT, but the web wrappers expect $HOME/timelapse. Move it there."
	[[ -f "$PROJECT_ROOT/requirements.txt" ]] || fail "$PROJECT_ROOT is not the Zeitraffer repo."
	command -v apt-get >/dev/null || fail "apt-get not found: this installer is for Debian/Ubuntu."
	python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
		|| fail "Python 3.11 or newer is required."
	python3 -c 'import sys; sys.exit(sys.version_info < (3, 13))' \
		|| warn "Python is older than 3.13 (CI runs 3.13); src/ is meant to stay runnable on 3.11."
	[[ "$WEB_PORT" =~ ^[0-9]+$ ]] || fail "WEB_PORT must be a number."
	[[ "$SERVER_NAME" =~ ^[A-Za-z0-9.-]+$ ]] || fail "SERVER_NAME has characters a hostname cannot have."
	require_file "$BACKUP_TAR"
	[[ -f "$BACKUP_CONFIG" ]] || warn "$BACKUP_CONFIG not found: using config/config.json from git."
	# Checked now so a missing entry or key does not cost a package install and a passphrase first.
	has_box_alias \
		|| fail "~/.ssh/config has no Host $BOX_ALIAS entry (HostName, User, Port, IdentityFile). See docs/vps.md, or set BOX_ALIAS."
	local key
	key="$(ssh -G "$BOX_ALIAS" | awk '$1 == "identityfile" {print $2; exit}')"
	# ssh -G prints the path as written in the config, so a leading ~ is still a literal ~.
	key="${key/#\~/$HOME}"
	[[ -f "$key" ]] || fail "The key of Host $BOX_ALIAS ($key) does not exist."
	sudo -v || fail "sudo access is required."
}

step_packages() {
	log "Installing packages"
	# cron is not part of a minimal Debian image; without it no timer would ever fire.
	sudo apt-get update
	sudo apt-get install -y \
		git python3 python3-venv python3-pip \
		ffmpeg openssl rsync curl cron \
		apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache
	sudo systemctl enable --now cron
}

step_venv() {
	log "Setting up the Python virtualenv"
	cd "$PROJECT_ROOT"
	python3 -m venv .venv
	"$PROJECT_ROOT/.venv/bin/pip" install -r requirements.txt
}

step_restore_backup() {
	log "Restoring from the backup (htpasswd, config.json)"
	# Extract to a staging dir, not onto /, and install only the one file this host needs. The
	# sudoers file and the vhost are generated for this host below, and the Storage Box key is
	# a new one made here, so none of the old host's system files or SSH keys are involved.
	local staging
	staging="$(mktemp -d)"
	# EXIT, not RETURN: fail() exits from inside this function, and a RETURN trap would not
	# fire then, leaving the extracted secret in /tmp.
	# shellcheck disable=SC2064
	trap "sudo rm -rf '$staging'" EXIT

	local passphrase
	read -rsp "Passphrase of the backup: " passphrase
	echo
	# Through a pipe, never as an argument or a file; the plain archive is never written.
	openssl enc -d "${CIPHER[@]}" -pass fd:3 -in "$BACKUP_TAR" 3< <(printf '%s' "$passphrase") \
		| sudo tar xzf - -C "$staging" \
		|| fail "Could not decrypt $BACKUP_TAR (wrong passphrase?)."
	unset passphrase

	# Only Apache needs to read the password hashes, not every local user.
	sudo test -f "$staging/etc/apache2/.htpasswd" || fail "Backup has no etc/apache2/.htpasswd."
	sudo install -o root -g www-data -m 640 "$staging/etc/apache2/.htpasswd" /etc/apache2/.htpasswd

	sudo rm -rf "$staging"
	trap - EXIT

	# A local edit made on the old host would otherwise be lost; git already provides the base file.
	if [[ -f "$BACKUP_CONFIG" ]]; then
		cp "$BACKUP_CONFIG" "$PROJECT_ROOT/config/config.json"
	fi
}

step_known_hosts() {
	log "Checking the Storage Box host key"
	local host port lookup scanned
	has_box_alias || fail "~/.ssh/config has no Host $BOX_ALIAS entry. See docs/vps.md, or set BOX_ALIAS."
	host="$(ssh -G "$BOX_ALIAS" | awk '$1 == "hostname" {print $2}')"
	port="$(ssh -G "$BOX_ALIAS" | awk '$1 == "port" {print $2}')"
	if [[ "$port" == "22" ]]; then
		lookup="$host"
	else
		lookup="[$host]:$port"
	fi

	touch "$HOME/.ssh/known_hosts"
	chmod 644 "$HOME/.ssh/known_hosts"
	if ssh-keygen -F "$lookup" -f "$HOME/.ssh/known_hosts" >/dev/null; then
		echo "$lookup is already in known_hosts: leaving it as it is."
		return
	fi

	# ssh-keyscan trusts whatever key answers, which undercuts StrictHostKeyChecking=yes in the
	# code, so show the fingerprint and make a human confirm it.
	scanned="$(ssh-keyscan -p "$port" "$host" 2>/dev/null)"
	[[ -n "$scanned" ]] || fail "ssh-keyscan got no host key from $lookup."
	echo "Host key fingerprints offered by $lookup:"
	ssh-keygen -lf - <<<"$scanned"
	local answer
	read -rp "Do these match the Storage Box fingerprints from the provider? [y/N] " answer
	[[ "$answer" == [yY] ]] || fail "Host key not confirmed: nothing was added to known_hosts."
	printf '%s\n' "$scanned" >>"$HOME/.ssh/known_hosts"
}

step_apache() {
	log "Installing the Apache vhost (HTTP, Basic Auth; TLS comes later)"
	sudo test -f /etc/apache2/.htpasswd || fail "Missing expected file: /etc/apache2/.htpasswd"

	local vhost
	vhost="$(mktemp)"
	# shellcheck disable=SC2064
	trap "rm -f '$vhost'" EXIT
	# Same layout as README "Apache-Konfiguration"; only the name, port and path are filled in.
	cat >"$vhost" <<EOF
<VirtualHost *:${WEB_PORT}>
    ServerName ${SERVER_NAME}

    DocumentRoot ${PROJECT_ROOT}/web/public
    DirectoryIndex index.php

    <Directory ${PROJECT_ROOT}/web/public>
        Options -Indexes
        AllowOverride None
        AuthType Basic
        AuthName "Zeitraffer"
        AuthUserFile /etc/apache2/.htpasswd
        Require valid-user
    </Directory>

    Alias /videos/ ${PROJECT_ROOT}/videos/

    <Directory ${PROJECT_ROOT}/videos>
        Options -Indexes
        AllowOverride None
        AuthType Basic
        AuthName "Zeitraffer"
        AuthUserFile /etc/apache2/.htpasswd
        Require valid-user
    </Directory>

    ErrorLog \${APACHE_LOG_DIR}/zeitraffer-error.log
    CustomLog \${APACHE_LOG_DIR}/zeitraffer-access.log combined
</VirtualHost>
EOF

	local target=/etc/apache2/sites-available/zeitraffer.conf
	if [[ -f "$target" ]] && ! cmp -s "$vhost" "$target" && [[ "$REWRITE_VHOST" != "1" ]]; then
		warn "$target differs from the generated one: kept (REWRITE_VHOST=1 overwrites it)."
	else
		sudo install -o root -g root -m 644 "$vhost" "$target"
	fi
	rm -f "$vhost"
	trap - EXIT

	# Apache only listens on 80 by default; another port needs its own Listen line.
	if [[ "$WEB_PORT" != "80" ]]; then
		echo "Listen ${WEB_PORT}" | sudo tee /etc/apache2/conf-available/zeitraffer-port.conf >/dev/null
		sudo a2enconf zeitraffer-port
	fi

	sudo a2ensite zeitraffer.conf
	sudo a2dissite 000-default.conf 2>/dev/null || true
	sudo apache2ctl configtest || fail "Apache config test failed: not reloading."
	sudo systemctl enable apache2
	sudo systemctl reload apache2 || sudo systemctl restart apache2
}

step_web_bridge() {
	log "Installing the web-to-Python bridge wrappers and the sudoers rules"
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-trigger" /usr/local/sbin/timelapse-web-trigger
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-delete" /usr/local/sbin/timelapse-web-delete
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-delete-highlight" /usr/local/sbin/timelapse-web-delete-highlight
	sudo install -d -o root -g root -m 755 /usr/local/libexec
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-worker" /usr/local/libexec/timelapse-web-worker
	sudo install -m 644 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-status.sh" /usr/local/libexec/timelapse-web-status.sh

	# Generated for this account, then checked by visudo before it can lock sudo out.
	local sudoers
	sudoers="$(mktemp)"
	# shellcheck disable=SC2064
	trap "rm -f '$sudoers'" EXIT
	cat >"$sudoers" <<EOF
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-delete
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight
EOF
	sudo visudo -cf "$sudoers" >/dev/null || fail "The generated sudoers file does not parse: not installing it."
	sudo install -o root -g root -m 440 "$sudoers" /etc/sudoers.d/timelapse-web
	rm -f "$sudoers"
	trap - EXIT
}

step_permissions() {
	log "Setting website-only permissions for www-data"
	# www-data is deliberately not in the login user's group. It gets pass-through on the path
	# down to the project and read access only to what the PHP code touches: web/, videos/,
	# config/config.json and state/web-jobs/. Debian 13 creates homes as 0700 and git clone
	# makes everything world-readable, so both have to be corrected here.
	chmod o+x "$HOME"
	# Pass-through on $HOME makes every world-readable file in it reachable by name, including
	# the backup archive, so close everything at the top of $HOME except the project itself.
	find "$HOME" -mindepth 1 -maxdepth 1 ! -path "$PROJECT_ROOT" -perm /o=rwx -exec chmod o-rwx {} +
	cd "$PROJECT_ROOT"

	# Runtime dirs closed; Python's later mkdir(exist_ok) keeps the mode.
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

	# web-jobs/ itself is created 755/644 by timelapse-web-status.sh; everything else in
	# state/ (lock, run marker) stays closed.
	find state -mindepth 1 -maxdepth 1 ! -name web-jobs -exec chmod o-rwx {} +
}

step_verify() {
	log "Verification"
	cd "$PROJECT_ROOT"
	"$PROJECT_ROOT/.venv/bin/python3" -m pytest -q || warn "Tests failed: check before relying on this host."

	command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null \
		&& echo "ffmpeg/ffprobe: installed" || warn "ffmpeg or ffprobe is missing."
	[[ -f models/object_detection_yolox_2022nov.onnx ]] \
		&& echo "detector model: present" \
		|| warn "models/object_detection_yolox_2022nov.onnx is missing (blur and highlights need it)."

	# The real code path of the nightly run: lists the cameras over ssh, read-only on the box. It
	# also refreshes state/web-jobs/cameras.json for the web pages. The log goes to stderr, so it is
	# kept apart: only the camera names on stdout are counted.
	local cameras camera_errors
	camera_errors="$(mktemp)"
	if cameras="$(TIMELAPSE_FRAME_SOURCE=ssh TIMELAPSE_STORAGE_BOX="$BOX_ALIAS" "$PROJECT_ROOT/.venv/bin/python3" -m src.camera_list </dev/null 2>"$camera_errors")"; then
		echo "Storage Box: reachable, $(wc -l <<<"$cameras") cameras listed"
	else
		warn "Camera list failed (Storage Box alias '$BOX_ALIAS'): $(cat "$camera_errors")"
	fi
	rm -f "$camera_errors"

	# 401 means Apache reached the docroot and asks for Basic Auth; 403 is the classic sign
	# that www-data cannot traverse into the project.
	local http_code
	http_code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${WEB_PORT}/" || true)"
	if [[ "$http_code" == "401" ]]; then
		echo "Dashboard: 401 (auth prompt, as expected)"
	else
		warn "Dashboard returned HTTP $http_code, expected 401: check /var/log/apache2/zeitraffer-error.log."
	fi

	local path
	for path in web/public/index.php web/src/video-library.php config/config.json; do
		sudo -u www-data test -r "$PROJECT_ROOT/$path" \
			&& echo "www-data can read $path" || warn "www-data cannot read $path"
	done
	sudo -u www-data test -x "$PROJECT_ROOT/videos" \
		&& echo "www-data can enter videos/" || warn "www-data cannot enter videos/"
	for path in src/main.py .git .venv; do
		sudo -u www-data test -r "$PROJECT_ROOT/$path" \
			&& warn "www-data can read $path: it should not" || echo "www-data blocked from $path"
	done
	sudo -u www-data test -r "$PROJECT_ROOT" \
		&& warn "www-data can list the project root: it should not" || echo "www-data cannot list the project root"

	local sudo_rules
	sudo_rules="$(sudo -l -U www-data 2>/dev/null || true)"
	grep -q "timelapse-web-trigger" <<<"$sudo_rules" \
		&& echo "sudoers: trigger rule active" || warn "sudoers: trigger rule missing for www-data."
	grep -Eq "timelapse-web-delete([[:space:],]|$)" <<<"$sudo_rules" \
		&& echo "sudoers: delete rule active" || warn "sudoers: delete rule missing for www-data."
	grep -Eq "timelapse-web-delete-highlight([[:space:],]|$)" <<<"$sudo_rules" \
		&& echo "sudoers: highlight delete rule active" \
		|| warn "sudoers: highlight delete rule missing for www-data."
}

step_cron_hint() {
	log "Crontab: nothing was installed"
	cat <<EOF
Paste these into 'crontab -e' yourself, and only after the old host's cron lines are gone: the same
job must never run on both hosts. Run each command once by hand first (docs/vps.md).

# Blur the last 48 h on the Storage Box, then the nightly run. The run reads the frames over ssh
# (no copy step) and takes the run lock itself. TIMELAPSE_X264_PRESET=medium is FFmpeg's default,
# i.e. what the old Pi produced; the wrapper would otherwise fall back to ultrafast.
0 2 * * * cd ${PROJECT_ROOT} && export TIMELAPSE_STORAGE_BOX=${BOX_ALIAS} && flock -n ${PROJECT_ROOT}/state/zeitraffer-run.lock -c '${PROJECT_ROOT}/.venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras --catch-up'; TIMELAPSE_X264_PRESET=medium ${PROJECT_ROOT}/scripts/timelapse-nightly-staged

# The highlights flagger, on its own line so one job never blocks the other. It takes the same run
# lock and skips the night when the nightly run still holds it, so the time has to be late enough.
# 04:00 is a first guess: look at when the nightly run ends (logs/nightly/<run>/report.txt) and adjust.
0 4 * * * cd ${PROJECT_ROOT} && TIMELAPSE_FRAME_SOURCE=ssh TIMELAPSE_STORAGE_BOX=${BOX_ALIAS} ${PROJECT_ROOT}/.venv/bin/python3 -m src.flagger.run

Not included: the 5-minute live blur job (docs/verpixelung-box.md).
EOF
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

	log "Done. Copy models/, state/ and videos/ over, run './install.sh permissions verify', then log in to the dashboard."
}

main "$@"
