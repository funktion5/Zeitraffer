# Zeitraffer in a container: the same program as on the Pi, for a trial on a Mac or a Synology NAS.
# Details and the trial steps: docs/docker.md. Builds for amd64 and arm64 alike.
FROM python:3.13.7-slim-bookworm

# FFmpeg encodes and blurs; sshfs + fuse3 mount the camera images read-only; openssh-client is
# what the storage filter and the box job call; util-linux brings findmnt and setpriv.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends ffmpeg sshfs fuse3 openssh-client util-linux \
	&& rm -rf /var/lib/apt/lists/*

# The program runs as this user; only the read-only camera mount at start needs root.
# APP_UID should match the owner of the host folders mounted as volumes.
ARG APP_UID=1000
RUN useradd --create-home --uid "${APP_UID}" app

WORKDIR /app

# The detector command in config.json calls .venv/bin/python3, so the venv sits where it does on
# the Pi and the configuration stays unchanged.
COPY requirements.txt .
RUN python3 -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /mnt/cameras videos logs state temp reports models \
	&& chown -R app:app videos logs state temp reports \
	&& chmod +x docker/entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}"
# Local time as on the Pi: log timestamps and "yesterday" must not run on UTC.
ENV TZ=Europe/Berlin

ENTRYPOINT ["docker/entrypoint.sh"]
# Without a command: run the test suite, the first trial step.
CMD ["python3", "-m", "pytest", "-q"]
