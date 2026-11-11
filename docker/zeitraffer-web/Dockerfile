# A test copy of the VPS web stack for localhost: the same distribution (Debian 13) and the same
# packages that install.sh puts on the VPS, so the web UI can be tried without touching production.
# Dev use only: HTTP, a dev login. Details and commands: docs/docker-web.md.
#
# Pinned to a dated tag (the VPS is Debian 13 too). The CPU differs: the VPS is arm64, this builds
# for the machine it runs on.
FROM debian:trixie-20261104-slim

# What step_packages in install.sh installs for the web UI and the jobs (no git, no cron).
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		ca-certificates python3 python3-venv python3-pip ffmpeg rsync curl openssh-client sudo procps \
		apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache \
	&& rm -rf /var/lib/apt/lists/*

# The account the wrappers run as. The PHP runs them as the OWNER of the project folder, so that
# folder is a real folder owned by this account (see compose.yaml for why it is not one big mount).
ARG RUN_USER=zeitraffer
ARG RUN_UID=1000
ENV RUN_USER=${RUN_USER}

# www-data must reach the project through the home folder (Debian 13 creates homes as 0700). The
# mount points of the runtime volumes are made here: a new volume takes the owner of its mount point.
RUN useradd --create-home --uid "${RUN_UID}" --shell /bin/bash "${RUN_USER}" \
	&& chmod o+x "/home/${RUN_USER}" \
	&& mkdir -p /home/${RUN_USER}/timelapse/state /home/${RUN_USER}/timelapse/videos \
		/home/${RUN_USER}/timelapse/logs /home/${RUN_USER}/timelapse/temp \
		/home/${RUN_USER}/timelapse/reports /home/${RUN_USER}/timelapse/.venv \
	&& chown -R "${RUN_USER}:${RUN_USER}" "/home/${RUN_USER}/timelapse"

COPY entrypoint.sh /usr/local/bin/docker-entrypoint
COPY seed-demo-data.sh /usr/local/bin/seed-demo-data
RUN chmod 755 /usr/local/bin/docker-entrypoint /usr/local/bin/seed-demo-data

EXPOSE 55222
ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
