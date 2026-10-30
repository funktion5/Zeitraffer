# Docker (Testbetrieb)

Zeitraffer läuft hier in einem Container statt direkt auf dem Raspberry Pi. **Stand:** Der Test auf
einem Mac ist gelungen (Oktober 2026). Der geplante Betrieb auf dem Synology-NAS ist **eingestellt**
(22.10.2026); Docker bleibt nur eine Möglichkeit für einen späteren Host. Der Pi bleibt produktiv;
der Container läuft nur, wenn man ihn von Hand startet.

Alle Pfade sind relativ zum Projektordner.

## Was ist was

| Datei | Zweck |
|---|---|
| `Dockerfile` | Bauanleitung für das Image: schlankes Debian 13 wie auf dem Pi (gleiches FFmpeg 7.1 und PHP 8.4), FFmpeg, sshfs, PHP nur für die Tests der Weboberfläche (kein Webserver), Python mit den Paketen aus `requirements.txt`, der Projektcode |
| `.dockerignore` | was **nicht** ins Image kommt: Videos, Logs, Status, Modelle, Schlüssel, lokale Notizen |
| `docker/entrypoint.sh` | Start jedes Containers: SSH-Dateien vorbereiten, Kamerabilder schreibgeschützt einhängen (wenn gewünscht), dann den Befehl als Benutzer `app` ausführen, nie als root |
| `docker/storage-box.env.example` | Vorlage für die Zugangsdaten der Storage Box (Benutzer, Host, Port, Schlüssel) |
| `compose.yaml` | Starteinstellungen: Ordner, die in den Container verbunden werden, FUSE für den Mount, Sperren |

- **Image:** das gepackte Programm samt Linux-Grundsystem. Wird einmal gebaut.
- **Container:** ein laufendes Image. Er startet für einen Befehl und ist danach weg.
- **Volumes:** Ordner auf dem Rechner, die im Container erscheinen. Nur dort bleibt etwas
  erhalten: Videos, Status, Logs landen in `docker-data/` (nicht im Repository).

## Sicherheitsregeln im Testbetrieb

- **Kamerabilder nur lesend:** Der Mount nutzt dieselben Optionen wie auf dem Pi (`-o ro`,
  strenge Host-Key-Prüfung).
- **Kein Verpixelungs-Job:** `python3 -m src.privacy.blur_box` würde auf die Storage Box
  schreiben. Der Container verweigert ihn, solange `ALLOW_BOX_WRITES` nicht `1` ist; in
  `compose.yaml` steht `0`. Erst wenn der Container den Pi ersetzt, wird das freigegeben.
- **Kein Cron, kein Neustart:** Nichts läuft von allein (`restart: "no"`).
- **Ergebnisse bleiben lokal:** Videos gehen nach `docker-data/videos/`, nicht in die
  Weboberfläche und nirgends hin, wo sie veröffentlicht werden.
- **Kein voller Lauf ohne Argumente:** `python3 -m src.main` ohne Optionen ist der komplette
  nächtliche Lauf (Stunden). Im Test nur gezielte historische Läufe starten.

## Test auf dem Mac

Voraussetzungen:

- **Docker Desktop** (für das Team kostenlos, unter 250 Mitarbeitenden) oder Colima.
- **Modelldatei** `models/object_detection_yolox_2022nov.onnx` vom Pi in den Ordner `models/`
  kopieren (steht nicht im Repository).
- **SSH-Zugang zur Storage Box** in `docker-data/ssh/`:
  - der private Schlüssel (dieselbe Datei wie auf dem Pi oder ein eigener mit Lesezugriff),
  - `config` mit einem Eintrag für die Box (`Host`, `Port 23`, `IdentityFile ~/.ssh/<datei>`;
    `~` ist im Container `/home/app`),
  - `known_hosts` mit dem Eintrag der Box (z. B. von `ssh-keyscan -p 23 <host>`, Fingerabdruck
    mit dem auf dem Pi vergleichen).
- `docker/storage-box.env.example` nach `docker/storage-box.env` kopieren und ausfüllen
  (dieselben Werte wie `/etc/timelapse/mount.env` auf dem Pi). Die Datei bleibt lokal.

Die Schritte, jeweils im Projektordner im Terminal:

```bash
# 1. Image bauen (APP_UID = eigener Benutzer, damit die Ergebnisse einem selbst gehören)
APP_UID=$(id -u) docker compose build

# 2. Funktioniert die Umgebung? Läuft die Testsuite (mehrere hundert Tests)
docker compose run --rm timelapse

# 3. Sieht der Container die Kamerabilder, nur lesend?
MOUNT_CAMERAS=1 docker compose run --rm timelapse ls /mnt/cameras

# 4. Ein historisches Tagesvideo mit Verpixelung, Ergebnis in docker-data/videos/
MOUNT_CAMERAS=1 docker compose run --rm timelapse \
	python3 -m src.main --date 2026-08-16 --cameras Scheunenviertel --blur-people
```

Variablen, die `compose.yaml` beim Aufruf liest:

| Variable | Standard | Bedeutung |
|---|---|---|
| `APP_UID` | `1000` | Benutzer-ID von `app` im Image (nur beim Bauen); sollte dem eigenen Benutzer entsprechen |
| `MOUNT_CAMERAS` | `0` | `1` hängt die Kamerabilder schreibgeschützt unter `/mnt/cameras` ein |
| `SSH_DIR` | `./docker-data/ssh` | Ordner mit Schlüssel, `config` und `known_hosts` für die Storage Box |

Schritt 4 dauert ca. 10 Minuten (Erkennung von rund 70 Bildern). Das Video kann man mit dem
auf dem Pi vergleichen; es sollte gleich aussehen.

## Auf dem NAS (eingestellt)

Der Betrieb auf dem Synology-NAS ist eingestellt. Die Hinweise bleiben für den Fall, dass ein
ähnlicher Host in Frage kommt.

- **Voraussetzung:** Synology mit **Container Manager** (DSM 7.2, meist „+"-Modelle mit
  x86-64-Prozessor, einige ARM64-Modelle) und mindestens 4 GB Arbeitsspeicher. Installieren
  und bedienen dürfen das nur Administratoren.
- **Aufgaben des Admins:** Container Manager installieren, einen freigegebenen Ordner für das
  Projekt anlegen, das Projekt dort als „Projekt" mit `compose.yaml` anlegen. Der Container
  braucht `/dev/fuse` und `SYS_ADMIN` (steht in `compose.yaml`) für den schreibgeschützten Mount.
- **Prozessor:** Ein Mac mit Apple-Chip baut für ARM64, die meisten Synology-NAS sind x86-64.
  Am einfachsten baut der NAS das Image selbst aus dem `Dockerfile`. Alternativ auf dem Mac:
  `docker buildx build --platform linux/amd64 -t zeitraffer:trial .`
- **Zuerst prüfen (Admin, per SSH auf dem NAS):** `ls -l /dev/fuse`. Fehlt das Gerät, kann der
  Container die Kamerabilder nicht einhängen; dann bräuchte der nächtliche Lauf einen anderen
  Weg an die Bilder (z. B. die tägliche NAS-Sicherung), was eine größere Änderung ist.
- **Compose-Version:** `env_file` mit `required: false` braucht Docker Compose 2.24 oder neuer.
  Meldet Container Manager einen Fehler in dieser Zeile, `required: false` entfernen und die
  Datei `docker/storage-box.env` immer anlegen.
- **Netz:** Der NAS muss die Storage Box per SSH erreichen (Port 23).
- **`APP_UID`** auf den Benutzer setzen, dem der Projektordner auf dem NAS gehört.

## Was noch fehlt, bevor der Container den Pi ersetzt

- Cron im Container (nächtlicher Lauf um 02:00, Verpixelung jede Minute) und der Wiederanlauf
  nach einem Neustart (heute `@reboot` auf dem Pi).
- Der Verpixelungs-Job (`ALLOW_BOX_WRITES=1`), erst nachdem der Pi ihn abgegeben hat.
- Die Weboberfläche: Auf dem Pi startet sie Jobs über `sudo`-Wrapper; im Container braucht das
  einen anderen Weg (eigener Container oder vorerst ohne Weboberfläche).
- Videos von dort, wo sie veröffentlicht werden, auf den neuen Ort umstellen.

## Fehlersuche

| Meldung | Ursache | Lösung |
|---|---|---|
| `REMOTE_… is not set` | `docker/storage-box.env` fehlt oder ist unvollständig | Vorlage kopieren und ausfüllen |
| `Camera images could not be mounted` bzw. `fuse: device not found` | FUSE im Container nicht erlaubt | `devices`/`cap_add` in `compose.yaml` prüfen; unter Docker Desktop hilft notfalls `privileged: true` |
| `Host key verification failed` | `known_hosts` fehlt oder passt nicht | Eintrag der Box in `docker-data/ssh/known_hosts` |
| `Permission denied (publickey)` | Schlüssel fehlt oder falscher Pfad in `REMOTE_SSH_KEY`/`config` | Dateinamen prüfen; im Container liegt alles unter `/home/app/.ssh/` |
| `The live blur job … is off in this container` | Absicht im Testbetrieb | nichts |
| Videos gehören root bzw. falschem Benutzer | `APP_UID` beim Bauen falsch | mit `APP_UID=$(id -u)` neu bauen |

**Getestet:** Auf einem Mac mit Docker Desktop (2026-10-16) liefen alle vier Schritte:
Image gebaut, Testsuite im Container, Kamerabilder schreibgeschützt eingehängt, ein
historisches Tagesvideo (Scheunenviertel 16.08.2026) mit Verpixelung erstellt. Auf dem NAS
noch nicht getestet.
