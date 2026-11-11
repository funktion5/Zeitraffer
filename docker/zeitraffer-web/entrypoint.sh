#!/bin/bash
# Prepares the container the way install.sh prepares the VPS (web_login, apache, web_bridge), then
# starts Apache. Safe to run on every start. It runs as root on purpose: it installs root-owned
# wrappers and sudoers rules, and Apache drops to www-data by itself; the Python work runs as the
# run account. Keep the vhost, the wrapper list and the sudoers rules in step with install.sh.
set -euo pipefail

RUN_USER="${RUN_USER:-zeitraffer}"
PROJECT="/home/${RUN_USER}/timelapse"
WEB_PORT=55222

log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

: "${DEV_LOGIN:?DEV_LOGIN is not set: copy .env.example to .env and fill it in}"
: "${DEV_PASSWORD:?DEV_PASSWORD is not set: copy .env.example to .env and fill it in}"

[[ -f "$PROJECT/requirements.txt" && -d "$PROJECT/web/public" ]] \
	|| fail "$PROJECT has no repo parts: the mounts in compose.yaml are missing."

# web_login: the Basic Auth login comes from the environment, so no password is baked into the image
# or put on a command line (htpasswd reads it from stdin).
log "Creating the web UI login"
htpasswd -ciB /etc/apache2/.htpasswd "$DEV_LOGIN" <<<"$DEV_PASSWORD" 2>/dev/null
chown root:www-data /etc/apache2/.htpasswd
chmod 640 /etc/apache2/.htpasswd

# The Python environment lives in a volume (the Mac's .venv is the wrong platform). It is rebuilt when
# requirements.txt changes, so a branch with other packages gets its own set.
log "Checking the Python environment"
stamp="$PROJECT/.venv/.requirements.sha256"
wanted="$(sha256sum "$PROJECT/requirements.txt" | cut -d' ' -f1)"
if [[ -x "$PROJECT/.venv/bin/python3" && -f "$stamp" && "$(cat "$stamp")" == "$wanted" ]]; then
	echo "Up to date."
else
	echo "Installing the Python packages (first start, or requirements.txt changed): a few minutes."
	runuser -u "$RUN_USER" -- bash -c "
		set -euo pipefail
		cd '$PROJECT'
		python3 -m venv --clear .venv
		.venv/bin/pip install --no-cache-dir -r requirements.txt
		echo '$wanted' > '$stamp'
	"
fi

# web_bridge: the wrappers and the sudoers rules, from the mounted repo, so a changed wrapper only
# needs a restart of the container.
log "Installing the web-to-Python wrappers and the sudoers rules"
install -d -o root -g root -m 755 /usr/local/sbin /usr/local/libexec
for name in trigger rebuild publish delete delete-highlight settings preview; do
	source_file="$PROJECT/scripts/web/timelapse-web-$name"
	if [[ -f "$source_file" ]]; then
		install -m 755 -o root -g root "$source_file" "/usr/local/sbin/timelapse-web-$name"
	else
		echo "WARNING: $source_file is missing on this branch: skipped."
	fi
done
for name in worker worker-rebuild worker-publish; do
	source_file="$PROJECT/scripts/web/timelapse-web-$name"
	if [[ -f "$source_file" ]]; then
		install -m 755 -o root -g root "$source_file" "/usr/local/libexec/timelapse-web-$name"
	else
		echo "WARNING: $source_file is missing on this branch: skipped."
	fi
done
install -m 644 -o root -g root "$PROJECT/scripts/web/timelapse-web-status.sh" /usr/local/libexec/timelapse-web-status.sh

sudoers="$(mktemp)"
cat >"$sudoers" <<EOF
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-rebuild *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-publish *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-delete
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-settings *
www-data ALL=(${RUN_USER}) NOPASSWD: /usr/local/sbin/timelapse-web-preview *
EOF
visudo -cf "$sudoers" >/dev/null || fail "The generated sudoers file does not parse: not installing it."
install -o root -g root -m 440 "$sudoers" /etc/sudoers.d/timelapse-web
rm -f "$sudoers"

# apache: the same vhost as install.sh writes (HTTP, Basic Auth), for this port and this project path.
log "Installing the Apache vhost"
cat >/etc/apache2/sites-available/zeitraffer.conf <<EOF
<VirtualHost *:${WEB_PORT}>
    ServerName localhost

    DocumentRoot ${PROJECT}/web/public
    DirectoryIndex index.php

    <Directory ${PROJECT}/web/public>
        Options -Indexes
        AllowOverride None
        AuthType Basic
        AuthName "Zeitraffer"
        AuthUserFile /etc/apache2/.htpasswd
        Require valid-user
    </Directory>

    Alias /videos/ ${PROJECT}/videos/

    <Directory ${PROJECT}/videos>
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
echo "Listen ${WEB_PORT}" >/etc/apache2/conf-available/zeitraffer-port.conf
a2enconf zeitraffer-port >/dev/null
# Silences the "could not determine the server's name" warning; the vhost has its own ServerName.
echo "ServerName localhost" >/etc/apache2/conf-available/zeitraffer-servername.conf
a2enconf zeitraffer-servername >/dev/null
a2ensite zeitraffer.conf >/dev/null
a2dissite 000-default.conf >/dev/null 2>&1 || true
# Dropped from ports.conf: the VPS listens on its one port only.
sed -i 's/^Listen 80$/# Listen 80/' /etc/apache2/ports.conf
apache2ctl configtest

# The Apache logs go to the container log (docker compose logs).
ln -sf /dev/stdout /var/log/apache2/zeitraffer-access.log
ln -sf /dev/stderr /var/log/apache2/zeitraffer-error.log

log "Ready: http://localhost:${WEB_PORT} (login: $DEV_LOGIN). Demo data: docker compose exec -u ${RUN_USER} web seed-demo-data"
mkdir -p /var/run/apache2 /var/lock/apache2
# envvars reads variables it does not set itself, so the unset-variable check must be off for it.
set +u
# shellcheck disable=SC1091
. /etc/apache2/envvars
exec apache2 -D FOREGROUND
