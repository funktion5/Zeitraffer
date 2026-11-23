# Archiv

Stillgelegter Code und Dokumentation, die für den laufenden Betrieb nicht mehr gebraucht wird. Nichts
davon wird ausgeführt, gepflegt oder von `pytest` und `ruff` erfasst (siehe `pyproject.toml`). Die
Dateien liegen mit ihrem ursprünglichen relativen Pfad im jeweiligen Unterordner.

Seit 2026-11-23 ist dieser Ordner nicht mehr im Repository (`.gitignore`); er liegt nur lokal und als
Zip-Datei. In der Git-Historie stehen die Dateien bis Commit `55c7219`, etwa
`git show 55c7219:archive/pi/migrate.sh`. `pi/docker/pull-videos.sh` kam erst danach dazu und steht dort
unter seinem alten Pfad: `git show 55c7219:docker/pull-videos.sh`.

| Ordner | Inhalt | Grund |
|---|---|---|
| `pi/` | SSHFS-Mount (`systemd/cameras-sshfs.service`, `scripts/cameras-sshfs-preflight`, `config/mount.env.example`), Absturz-Protokollierung, `migrate.sh`, `docs/raspberry-pi.md`, der Handbuch-Abschnitt „Pi: Stabilität“, `docker/pull-videos.sh` (holte die Videos vom Pi für die WordPress-Testumgebung; seit dem VPS werden sie von Hand kopiert, `docs/wordpress.md`) | Der Raspberry Pi ist abgelöst; alle Jobs lesen die Bilder per ssh |
| `docker-trial/` | Container-Testbetrieb (`Dockerfile`, `compose.yaml`, `.dockerignore`, `docker/entrypoint.sh`, `docker/storage-box.env.example`, `docs/docker.md`) | Der Docker-Betrieb auf dem NAS ist eingestellt; der WordPress-Testaufbau in `docker/` bleibt aktiv |
| `staging/` | `scripts/stage-frames.py` und seine Tests, alter Plan `docs/plans/web-server-nightly-run.md`, der Staging-Abschnitt aus `docs/werkzeuge.md` | Der Nachtlauf holt die Bilder über `FrameSource` per ssh, ein Zwischenordner entfällt |

Die Tests im Archiv laufen nicht automatisch. Wer sie ausprobieren will, ruft den Ordner ausdrücklich auf,
zum Beispiel `python -m pytest archive/staging`. Ob sie noch bestehen, ist nicht zugesichert.
