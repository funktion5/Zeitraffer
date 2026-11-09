#!/bin/bash
# Host-neutral installer for a fresh Debian/Ubuntu host (a VPS now, a Pi or any other machine
# later). Run it from inside the cloned repo, as the login user (not root), after one
# preparation (details: docs/vps.md): a Storage Box key on this host (ssh-keygen, ssh-copy-id) and
# a Host entry for it in ~/.ssh/config, named by BOX_ALIAS. The old host's key is deliberately not
# carried over. Nothing from the old host's backup is needed: the web UI login is created here.
# The repo must live in ~/timelapse: the installed web wrappers look there.
#
# The jobs read the frames over ssh from the Storage Box (a FrameSource in src/frame_source.py),
# so there is no SSHFS mount, no /mnt/cameras and no @reboot recovery here.
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
#   HTPASSWD_USER login name of the web UI, used only when /etc/apache2/.htpasswd does not exist
#                 yet (asked for when unset; the password is always asked for by htpasswd)
#   BACKUP_DIR    absolute path of a backup made by backup.sh (default ~/timelapse-backup); the
#                 step restore copies its models/, state/ and videos/ into the project if the
#                 folder exists, and never overwrites a file that is already there
#   REWRITE_VHOST=1  overwrite an existing, different vhost file (it is kept by default, so a
#                    later TLS setup is not undone by a re-run)
#
# Not done here, on purpose: the crontab (printed at the end, you paste it), the FTP password of
# the nightly upload (the step upload_login only creates config/siteground.env from the template
# config/siteground.env.example; the values are filled in by hand, see docs/betrieb.md). The
# models/, state/ and videos/ come from a backup made by backup.sh (step restore), see docs/vps.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
SERVER_NAME="${SERVER_NAME:-localhost}"
WEB_PORT="${WEB_PORT:-80}"
REWRITE_VHOST="${REWRITE_VHOST:-0}"
# The ssh alias the code uses for the Storage Box (handed over as TIMELAPSE_STORAGE_BOX); user,
# host, port and key live in ~/.ssh/config, so none of them is in the repository.
BOX_ALIAS="${BOX_ALIAS:-storagebox}"

ALL_STEPS=(
	preflight
	packages
	venv
	web_login
	upload_login
	restore
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
		ffmpeg rsync curl cron \
		apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache
	sudo systemctl enable --now cron
}

step_venv() {
	log "Setting up the Python virtualenv"
	cd "$PROJECT_ROOT"
	python3 -m venv .venv
	"$PROJECT_ROOT/.venv/bin/pip" install -r requirements.txt
}

step_web_login() {
	log "Setting up the web UI login (Apache Basic Auth)"
	# An existing file is never touched: a re-run must not replace the logins that are in use.
	if sudo test -f /etc/apache2/.htpasswd; then
		echo "/etc/apache2/.htpasswd exists: leaving it as it is."
		return
	fi

	local login="${HTPASSWD_USER:-}"
	if [[ -z "$login" ]]; then
		read -rp "Login name for the web UI: " login
	fi
	[[ "$login" =~ ^[A-Za-z0-9._-]+$ ]] \
		|| fail "The login may only contain letters, digits, '.', '_' and '-'."

	# htpasswd asks for the password itself (twice, on the terminal): it never appears in an
	# argument, a file or the log. -B is bcrypt, -c creates the file.
	sudo htpasswd -cB /etc/apache2/.htpasswd "$login" || fail "htpasswd could not create the login."
	# Only Apache needs to read the password hashes, not every local user.
	sudo chown root:www-data /etc/apache2/.htpasswd
	sudo chmod 640 /etc/apache2/.htpasswd
}

step_upload_login() {
	log "Preparing the login file of the nightly upload"
	local file="$PROJECT_ROOT/config/siteground.env"
	local template="$PROJECT_ROOT/config/siteground.env.example"
	# An existing file holds the real login and is never touched.
	if [[ -f "$file" ]]; then
		echo "config/siteground.env exists: leaving it as it is."
		return
	fi
	[[ -f "$template" ]] || fail "Missing the template config/siteground.env.example."
	cp "$template" "$file"
	chmod 600 "$file"
	warn "config/siteground.env was created from the template and is EMPTY: fill in SITEGROUND_HOST, SITEGROUND_USER and SITEGROUND_PASS by hand. Until then the nightly upload fails."
}

step_restore() {
	log "Restoring models, state and videos from the backup folder"
	local backup="${BACKUP_DIR:-$HOME/timelapse-backup}"
	# rsync reads "host:path" as a remote source, so only an absolute path is accepted.
	[[ "$backup" == /* ]] || fail "BACKUP_DIR must be an absolute path: $backup"
	if [[ ! -d "$backup" ]]; then
		echo "No backup folder at $backup: nothing to restore (docs/vps.md)."
		return
	fi

	local name restored=0
	for name in models state videos; do
		[[ -d "$backup/$name" ]] || continue
		mkdir -p "$PROJECT_ROOT/$name"
		# Never overwrite and never delete: a file that already exists here is newer than the
		# backup's, so a re-run on a working host changes nothing that is in use. The modes are set
		# by the permissions step afterwards.
		rsync -a --no-perms --ignore-existing "$backup/$name/" "$PROJECT_ROOT/$name/"
		echo "Restored $name/"
		restored=$((restored + 1))
	done

	if ((restored == 0)); then
		warn "$backup holds no models/, state/ or videos/: nothing restored."
	fi
	if [[ -f "$backup/crontab.txt" ]]; then
		echo "crontab.txt is for reference only: it is not installed."
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
	sudo test -f /etc/apache2/.htpasswd \
		|| fail "Missing /etc/apache2/.htpasswd: run './install.sh web_login' first."

	local vhost
	vhost="$(mktemp)"
	# shellcheck disable=SC2064
	trap "rm -f '$vhost'" EXIT
	# Same layout as docs/installation.md, "Apache-Konfiguration"; only the name, port and path are filled in.
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
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-rebuild" /usr/local/sbin/timelapse-web-rebuild
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-publish" /usr/local/sbin/timelapse-web-publish
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-delete" /usr/local/sbin/timelapse-web-delete
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-delete-highlight" /usr/local/sbin/timelapse-web-delete-highlight
	sudo install -d -o root -g root -m 755 /usr/local/libexec
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-worker" /usr/local/libexec/timelapse-web-worker
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-worker-rebuild" /usr/local/libexec/timelapse-web-worker-rebuild
	sudo install -m 755 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-worker-publish" /usr/local/libexec/timelapse-web-worker-publish
	sudo install -m 644 -o root -g root "$PROJECT_ROOT/scripts/web/timelapse-web-status.sh" /usr/local/libexec/timelapse-web-status.sh

	# Generated for this account, then checked by visudo before it can lock sudo out.
	local sudoers
	sudoers="$(mktemp)"
	# shellcheck disable=SC2064
	trap "rm -f '$sudoers'" EXIT
	cat >"$sudoers" <<EOF
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-rebuild *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-publish *
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
	# any file copied there, so close everything at the top of $HOME except the project itself.
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
	grep -q "timelapse-web-rebuild" <<<"$sudo_rules" \
		&& echo "sudoers: rebuild rule active" || warn "sudoers: rebuild rule missing for www-data."
	grep -q "timelapse-web-publish" <<<"$sudo_rules" \
		&& echo "sudoers: publish rule active" || warn "sudoers: publish rule missing for www-data."
	grep -Eq "timelapse-web-delete([[:space:],]|$)" <<<"$sudo_rules" \
		&& echo "sudoers: delete rule active" || warn "sudoers: delete rule missing for www-data."
	grep -Eq "timelapse-web-delete-highlight([[:space:],]|$)" <<<"$sudo_rules" \
		&& echo "sudoers: highlight delete rule active" \
		|| warn "sudoers: highlight delete rule missing for www-data."

	# The nightly upload to the website reads its FTP login from here. Only the names are tested,
	# the values are never printed.
	local login_key
	for login_key in SITEGROUND_HOST SITEGROUND_USER SITEGROUND_PASS; do
		grep -qs "^${login_key}=." "$PROJECT_ROOT/config/siteground.env" \
			&& echo "upload login: $login_key is set" \
			|| warn "config/siteground.env has no $login_key: the nightly upload would fail (docs/betrieb.md)."
	done
}

step_cron_hint() {
	log "Crontab: nothing was installed"
	cat <<EOF
Paste this line into 'crontab -e' yourself, and only after the old host's cron lines are gone: the
same job must never run on both hosts. Run each command once by hand first (docs/vps.md). If an
older separate 04:00 flagger line is still there, delete it: the flagger would run twice.

# Blur the last 48 h on the Storage Box, then the nightly run, then the upload of the new videos
# to the website, then the highlights flagger. The run reads the frames over ssh (no copy step) and
# takes the run lock itself. The upload needs config/siteground.env (docs/betrieb.md); without it
# the step only logs an error. The flagger starts only when the videos are done, however long that
# takes, so it needs no time of its own; it takes the run lock itself too, so it stays outside
# flock. The steps are joined with ';', so a failing step never stops the next one.
# TIMELAPSE_X264_PRESET=medium is FFmpeg's default, i.e. what the old Pi produced; the wrapper
# would otherwise fall back to ultrafast.
0 2 * * * cd ${PROJECT_ROOT} && export TIMELAPSE_STORAGE_BOX=${BOX_ALIAS} && flock -n ${PROJECT_ROOT}/state/zeitraffer-run.lock -c '${PROJECT_ROOT}/.venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras --catch-up'; TIMELAPSE_X264_PRESET=medium ${PROJECT_ROOT}/scripts/timelapse-nightly-staged; /bin/bash ${PROJECT_ROOT}/scripts/copy_zeitraffer_videos_vps2siteground.sh --run >> ${PROJECT_ROOT}/logs/siteground-delivery.log 2>&1; TIMELAPSE_FRAME_SOURCE=ssh ${PROJECT_ROOT}/.venv/bin/python3 -m src.flagger.run

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

	log "Done. Missing models/, state/ or videos/? Put a backup of backup.sh into ~/timelapse-backup and run './install.sh restore permissions verify'. Then log in to the dashboard."
}

main "$@"
