# Archiv

Stillgelegter Code und Dokumentation, die für den laufenden Betrieb nicht mehr gebraucht wird. Nichts
davon wird ausgeführt, gepflegt oder von `pytest` und `ruff` erfasst (siehe `pyproject.toml`). Die
Dateien liegen mit ihrem ursprünglichen relativen Pfad im jeweiligen Unterordner, damit die Git-Historie
erhalten bleibt und ein Zurückholen ein einfaches `git mv` ist.

| Ordner | Inhalt | Grund |
|---|---|---|
| `pi/` | SSHFS-Mount (`systemd/cameras-sshfs.service`, `scripts/cameras-sshfs-preflight`, `config/mount.env.example`), Absturz-Protokollierung, `migrate.sh`, `docs/raspberry-pi.md` | Der Raspberry Pi ist abgelöst; alle Jobs lesen die Bilder per ssh |
| `docker-trial/` | Container-Testbetrieb (`Dockerfile`, `compose.yaml`, `.dockerignore`, `docker/entrypoint.sh`, `docker/storage-box.env.example`, `docs/docker.md`) | Der Docker-Betrieb auf dem NAS ist eingestellt; der WordPress-Testaufbau in `docker/` bleibt aktiv |
| `staging/` | `scripts/stage-frames.py` und seine Tests, alter Plan `docs/plans/web-server-nightly-run.md` | Der Nachtlauf holt die Bilder über `FrameSource` per ssh, ein Zwischenordner entfällt |

Die Tests im Archiv laufen nicht automatisch. Wer sie ausprobieren will, ruft den Ordner ausdrücklich auf,
zum Beispiel `python -m pytest archive/staging`. Ob sie noch bestehen, ist nicht zugesichert.

Die Texte in `docs/` und im README verweisen teils noch auf die alten Pfade; die Pfade im Archiv gelten.
