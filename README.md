# Zeitraffer

Zeitraffer macht aus den Bildern unserer Webcams automatisch Zeitraffer-Videos. Die Kameras laden
den ganzen Tag Bilder auf einen Online-Speicher (die „Storage Box“). Jede Nacht holt sich das
Programm diese Bilder, wählt die passenden aus und setzt sie zu Videos zusammen: ein Video pro
Kamera für den Vortag, die letzte Woche, die letzten 30 Tage und das letzte Jahr.

Das Programm läuft derzeit auf einem Raspberry Pi im Büro. Über eine Weboberfläche im
Büronetz lassen sich zusätzlich Videos für beliebige vergangene Tage erstellen, ansehen und
herunterladen.

**Die Originalbilder der Kameras werden dabei niemals verändert.**

Die Kapitel **Installation** und **Konfiguration** sind für die technische Einrichtung. Alle
anderen Kapitel beschreiben in einfachen Worten, was das Programm tut; die technischen Einzelheiten
stehen jeweils in einer eigenen Datei im Ordner [`docs/`](docs/), die am Ende jedes Kapitels
verlinkt ist.

---
## Inhalt

- [Installation](#installation)
  - [Systempakete installieren](#systempakete-installieren)
  - [Python-Umgebung einrichten](#python-umgebung-einrichten)
  - [SSHFS-Mount installieren](#sshfs-mount-installieren)
  - [Cron installieren oder prüfen](#cron-installieren-oder-prüfen)
  - [Weboberfläche einrichten](#weboberfläche-einrichten)
- [Konfiguration](#konfiguration)
  - [Umgebungsvariablen](#umgebungsvariablen)
- [Betrieb im Alltag](#betrieb-im-alltag)
- [Weboberfläche](#weboberfläche)
- [Highlights-Flagger](#highlights-flagger)
- [Verpixelung](#verpixelung)
- [WordPress-Seite](#wordpress-seite)
- [Kommandozeile](#kommandozeile)
- [Werkzeuge](#werkzeuge)
- [Raspberry Pi](#raspberry-pi)
- [Technik für Entwickler](#technik-für-entwickler)
- [Aktueller Stand](#aktueller-stand)
- [Noch offen](#noch-offen)
- [Dokumentation](#dokumentation)

---

## Installation

*Für die technische Einrichtung.*

Platzhalter in den folgenden Beispielen:

| Platzhalter | Bedeutung |
|---|---|
| `<benutzer>` | Linux-Konto, unter dem das Projekt läuft |
| `<projektpfad>` | Projektordner, z. B. `/home/<benutzer>/timelapse` |
| `<login>` | Benutzername der Apache-Basisauthentifizierung |

Die folgenden Abschnitte beschreiben die Einrichtung von Hand. Für einen neu installierten Pi mit vorhandenem Backup übernimmt `migrate.sh` alle Schritte; siehe [Neuinstallation des Raspberry Pi](docs/raspberry-pi.md#neuinstallation-des-raspberry-pi).

### Systempakete installieren

Dieselbe Paketliste installiert auch `migrate.sh` (Schritt `packages`):

```bash
sudo apt-get update
sudo apt-get install -y \
  git python3 python3-venv python3-pip \
  ffmpeg sshfs openssl rsync \
  apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache
```

Weil der SSHFS-Mount `allow_other` verwendet, muss in `/etc/fuse.conf` die Zeile `user_allow_other` aktiv sein:

```bash
grep -qx user_allow_other /etc/fuse.conf || echo user_allow_other | sudo tee -a /etc/fuse.conf
```

### Python-Umgebung einrichten

Voraussetzung ist **Python 3.13** (`python3 --version`); Debian 13 (trixie) bringt es mit. Auf
Systemen mit älterem Python, etwa Ubuntu 24.04 (3.12), muss Python 3.13 zusätzlich installiert
und die virtuelle Umgebung damit angelegt werden (`python3.13 -m venv .venv`); das ist bisher
nicht getestet.

Virtuelle Umgebung erstellen und aktivieren:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Abhängigkeiten installieren:

```bash
python3 -m pip install -r requirements.txt
```

`requirements.txt` enthält auch die Entwicklungswerkzeuge pytest und Ruff. Ruff ist auf eine feste
Version gepinnt, damit lokal, im Pre-Push-Hook und in GitHub Actions identisch formatiert wird;
die Konfiguration liegt in `pyproject.toml`.

Für die Verpixelung von Personen wird zusätzlich ein Erkennungsmodell im Ordner `models/`
benötigt. Es ist zu groß für das Repository und wird einmal heruntergeladen; Anleitung siehe
[Verpixelung – Installation](docs/verpixelung.md#installation). Ohne Modell laufen alle anderen
Funktionen normal.

### SSHFS-Mount installieren

Die Originalbilder werden unter `/mnt/cameras` bereitgestellt. Der systemd-Service mountet den entfernten Storage mit SSHFS ausschließlich lesend (`-o ro`). Die Option `allow_other` erlaubt dem Apache-Benutzer `www-data`, den Mount im Rahmen der normalen Dateirechte zu lesen. Sie erteilt keine Schreibrechte. Vor dem Mount prüft das Preflight-Skript, ob bereits ein erreichbarer Mount existiert oder ein nicht erreichbarer FUSE-Mount bereinigt werden muss.

Das Repository enthält dafür:

- `systemd/cameras-sshfs.service`
- `scripts/cameras-sshfs-preflight`
- `config/mount.env.example`

Voraussetzungen:

- `sshfs` und `fusermount3` (Paket `fuse3`, wird als Abhängigkeit von `sshfs` installiert)
- Mountpoint `/mnt/cameras` existiert
- SSH-Schlüssel für die Storage Box im Konto `<benutzer>`; der Pfad steht in
  `/etc/timelapse/mount.env` (`REMOTE_SSH_KEY`)
- passender `known_hosts`-Eintrag für den Storage-Host, weil der Service `StrictHostKeyChecking=yes` verwendet
- `user_allow_other` in `/etc/fuse.conf` (siehe [Systempakete installieren](#systempakete-installieren))

Repository-Dateien installieren:

```bash
sudo install -m 755 scripts/cameras-sshfs-preflight /usr/local/sbin/cameras-sshfs-preflight
sed -e "s/@RUN_USER@/$(id -un)/g" -e "s/@RUN_GROUP@/$(id -gn)/g" systemd/cameras-sshfs.service \
  | sudo tee /etc/systemd/system/cameras-sshfs.service >/dev/null
sudo install -d -m 755 /etc/timelapse
sudo install -m 600 config/mount.env.example /etc/timelapse/mount.env
```

Die Unit enthält statt des Kontonamens die Platzhalter `@RUN_USER@` und `@RUN_GROUP@`; der
`sed`-Befehl setzt das eigene Konto ein (als `<benutzer>` ausführen, nicht als root). Ohne diesen
Schritt startet systemd den Service nicht. `migrate.sh` erledigt das automatisch.

Danach `/etc/timelapse/mount.env` mit den produktiven Verbindungswerten befüllen. Die Datei liegt außerhalb des Repositories und wird nicht versioniert. Erwartete Variablen:

```text
REMOTE_USER=
REMOTE_HOST=
REMOTE_PORT=
REMOTE_SSH_KEY=
```

Service aktivieren:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cameras-sshfs.service
```

Status und Mount prüfen:

```bash
systemctl status cameras-sshfs.service
mountpoint /mnt/cameras
```

### Cron installieren oder prüfen

Die beiden Einträge aus [Zeitplanung mit Cron](docs/betrieb.md#zeitplanung-mit-cron) werden über

```bash
crontab -e
```

für den Benutzer `<benutzer>` installiert. Anschließend prüfen:

```bash
crontab -l
```

### Weboberfläche einrichten

Die Weboberfläche ist eine kleine PHP-Anwendung ohne Datenbank und ohne separates API-Framework. Sie ist für das vertrauenswürdige lokale Netzwerk vorgesehen.

```text
Browser
  → Apache und PHP
  → eingeschränkter Wrapper
  → bestehende Python-CLI
  → Timelapse-Jobs und FFmpeg
  → videos/ + logs/ + temp/ + state/
```

#### Apache-Konfiguration

Die aktive Site verwendet sinngemäß folgende Konfiguration:

```apache
<VirtualHost *:80>
    ServerName <hostname>.local

    DocumentRoot <projektpfad>/web/public
    DirectoryIndex index.php

    <Directory <projektpfad>/web/public>
        Options -Indexes
        AllowOverride None
        AuthType Basic
        AuthName "Zeitraffer"
        AuthUserFile /etc/apache2/.htpasswd
        Require valid-user
    </Directory>

    Alias /videos/ <projektpfad>/videos/

    <Directory <projektpfad>/videos>
        Options -Indexes
        AllowOverride None
        AuthType Basic
        AuthName "Zeitraffer"
        AuthUserFile /etc/apache2/.htpasswd
        Require valid-user
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/zeitraffer-error.log
    CustomLog ${APACHE_LOG_DIR}/zeitraffer-access.log combined
</VirtualHost>
```

Die Konfiguration wird als `/etc/apache2/sites-available/zeitraffer.conf` gespeichert und anschließend aktiviert:

```bash
sudo a2dissite 000-default.conf
sudo a2ensite zeitraffer.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Die Site wird unter `http://<hostname>.local/` oder über die IP-Adresse des Raspberry Pi geöffnet. Der Alias `/videos/` stellt MP4-Dateien bereit und unterstützt die Browser-Wiedergabe. Er umfasst derzeit den gesamten Verzeichnisbaum `videos/`, auch wenn die PHP-Bibliothek nur `manual-runs` auflistet.

Apache läuft als `www-data`. Dieser Benutzer wird nicht in die Gruppe `<benutzer>` aufgenommen. Der SSHFS-Mount nutzt `allow_other`, und die lokalen Projektpfade erhalten nur die für Website, Videos und Web-Status erforderlichen Leserechte (Details unter [Dateirechte für `www-data`](#dateirechte-für-www-data)). Die Wrapper werden als root-eigene, für `www-data` nicht beschreibbare Kopien unter `/usr/local` installiert.

Die Site verwendet Apache-Basisauthentifizierung, aber weiterhin HTTP statt HTTPS. Zugangsdaten werden dadurch nicht auf dem Transportweg verschlüsselt; die Site darf deshalb weiterhin nicht ohne zusätzliche Transportverschlüsselung aus einem nicht vertrauenswürdigen Netzwerk erreichbar sein.

#### Basisauthentifizierung einrichten

Beide Verzeichnisse (`web/public` und der `/videos/`-Alias) werden per `AuthType Basic` geschützt. Die Zugangsdaten liegen in `/etc/apache2/.htpasswd`, außerhalb des Dokumenten-Stammverzeichnisses und damit über HTTP nicht erreichbar; die Datei wird nicht versioniert und darf nicht ins Repository gelangen.

```bash
sudo htpasswd -cB /etc/apache2/.htpasswd <login>
```

`-B` erzwingt bcrypt-Hashing (laut `htpasswd --help` „very secure“) anstelle des schwächeren MD5-Standards. `-c` legt die Datei neu an und darf nur beim ersten Benutzer verwendet werden; weitere Benutzer werden ohne `-c` ergänzt.

Nach jeder Änderung an der Apache-Konfiguration:

```bash
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Prüfung:

```bash
curl -i http://localhost/            # erwartet: 401 Unauthorized
curl -i http://localhost/videos/     # erwartet: 401 Unauthorized
curl -i -u <login> http://localhost/  # erwartet: 200 OK nach Passworteingabe
```

#### Wrapper installieren

Die versionierten Skripte werden als geschützte Laufzeitkopien installiert:

```bash
sudo install -d -o root -g root -m 755 /usr/local/libexec
sudo install -o root -g root -m 644 \
  scripts/timelapse-web-status.sh \
  /usr/local/libexec/timelapse-web-status.sh
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-worker \
  /usr/local/libexec/timelapse-web-worker
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-trigger \
  /usr/local/sbin/timelapse-web-trigger
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-delete \
  /usr/local/sbin/timelapse-web-delete
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-delete-highlight \
  /usr/local/sbin/timelapse-web-delete-highlight
```

Die sudoers-Regeln erlauben ausschließlich den festen Trigger und die beiden festen Lösch-Wrapper, jeweils als `<benutzer>`:

```sudoers
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight
```

Eine sudoers-Regel ohne Argumentliste erlaubt beliebige Argumente. `timelapse-web-delete` erwartet genau Kamera, Job-Typ und Dateiname, prüft diese selbst (kein `/`, nur `.mp4`, keine Symlinks) und löscht ausschließlich unter `videos/<camera>/manual-runs/<job>/`. `timelapse-web-delete-highlight` erwartet genau Kamera, Datum und Dateiname (nur `.jpg`, keine Symlinks) und löscht ausschließlich ein Bild unter `videos/<camera>/highlights/<datum>/`, nie die `manifest.json`.

Die Regeln werden mit folgendem Befehl in einer eigenen Datei sicher bearbeitet und geprüft:

```bash
sudo visudo -f /etc/sudoers.d/timelapse-web
```

Eingaben werden zusätzlich in PHP und in den Wrappern validiert; die sudoers-Regeln allein ersetzen diese Prüfungen nicht.

Nach Änderungen an den versionierten Wrappern müssen die Laufzeitkopien erneut mit `sudo install` aktualisiert werden.

#### Dateirechte für `www-data`

`www-data` wird nicht in die Gruppe `<benutzer>` aufgenommen und erhält nur Zugriff auf das, was die Weboberfläche tatsächlich liest. Alles andere – Python-Code, Skripte, Tests, `.git`, `.venv`, Logs, temporäre Dateien und alle übrigen Dateien im Home-Verzeichnis – bleibt für `www-data` gesperrt.

| Pfad | Rechte für „andere“ | Zweck |
|---|---|---|
| `/home/<benutzer>` | nur Durchgang (`--x`) | Weg zum Projekt |
| übrige Einträge in `/home/<benutzer>` | keine | z. B. Backups, `.ssh` |
| `timelapse/` | nur Durchgang (`--x`) | kein Auflisten des Projekts |
| `web/` | lesen (`r-x` / `r--`) | PHP-Dateien und CSS |
| `videos/` | lesen (`r-x` / `r--`) | Bibliothek, Wiedergabe, Speicheranzeige |
| `config/` | nur Durchgang (`--x`) | – |
| `config/config.json` | lesen (`r--`) | `ignored_cameras`, `flagger.cameras`, Zeitzone |
| `state/` | nur Durchgang (`--x`) | – |
| `state/web-jobs/` | lesen (vom Status-Skript als `755`/`644` angelegt) | Job-Status-Polling |
| alle übrigen Einträge in `timelapse/` | keine | – |

`logs/`, `temp/` und `reports/` werden mit Modus `770` vorab angelegt, damit die Python-Jobs sie später nicht weltlesbar erzeugen.

Die Rechte setzt der Schritt `permissions` von `migrate.sh`. Er ist wiederholbar und kann jederzeit einzeln ausgeführt werden, etwa nachdem Videos von Hand kopiert wurden:

```bash
~/timelapse/migrate.sh permissions verify
```

Warum das nötig ist: Debian 13 legt Home-Verzeichnisse mit Modus `0700` an (`HOME_MODE` in `/etc/login.defs`), und `git clone` erzeugt alle Dateien weltlesbar. Ohne diesen Schritt antwortet Apache mit `403 Forbidden`, und im Fehlerlog steht `AH00035: ... search permissions are missing on a component of the path`.

Die Rechte für „andere“ gelten technisch für alle lokalen Benutzer, nicht nur für `www-data`. Eine Beschränkung auf genau `www-data` wäre nur über ACLs (Paket `acl`) möglich.

Neue Dateien der Python-Jobs sind durch die Standard-`umask` `0002` weltlesbar. Unter `videos/` ist das gewollt; in gesperrten Verzeichnissen wie `logs/` bleibt der Inhalt trotzdem unerreichbar, weil der Durchgang durch das Verzeichnis selbst fehlt.

---

## Konfiguration

*Für die technische Einrichtung.*

Die produktive Konfiguration liegt fest unter:

```text
config/config.json
```

Beispiel:

```json
{
  "location": {
    "latitude": 52.472,
    "longitude": 9.333,
    "timezone": "Europe/Berlin"
  },
  "daylight_buffer_minutes": 90,
  "automatic_daylight_buffer_minutes": {
    "1": 30, "2": 60, "3": 60, "4": 60, "5": 90, "6": 90,
    "7": 90, "8": 60, "9": 60, "10": 60, "11": 30, "12": 30
  },
  "interval_window": {
    "target_time": "12:00",
    "tolerance_minutes": 90
  },
  "min_coverage_days": {
    "monthly": 25,
    "yearly": 300
  },
  "image_scan_stall_timeout_seconds": 60,
  "log_retention_days": 30,
  "ignored_cameras": [
    "Reolink",
    "Wunstorf-Marktplatz",
    "SVG"
  ],
  "timelapse": {
    "daily_framerate": 10,
    "monthly_framerate": 20,
    "yearly_framerate": 20,
    "ffmpeg_threads": 2
  },
  "privacy": {
    "blur_cameras": ["…"],
    "ignore_boxes": {"…": [[703, 557, 742, 643]]},
    "ignore_top_share": 0.333,
    "skip_labels": {"…": ["vehicle", "plate"]},
    "min_person_score": {"…": 0.35},
    "detector_command": [
      ".venv/bin/python3", "-I", "src/privacy/detect.py",
      "--model", "models/object_detection_yolox_2022nov.onnx",
      "--tiles", "2",
      "--threshold", "0.25",
      "--vehicle-plate-share", "0.55",
      "--vehicle-threshold", "0.15",
      "--plate-search",
      "--vehicle-block-ratio", "0.0133"
    ],
    "blur": {
      "strength": 0.08,
      "padding_ratio": 0.05,
      "feather": 0.5
    }
  },
  "flagger": {
    "cameras": ["Strandallee", "SLSV", "BSV-Steinhude", "SKM-Mardorf", "Kitestrand"],
    "retention_days": 30
  }
}
```

`automatic_daylight_buffer_minutes` ist der Zeitpuffer vor Sonnenaufgang und nach
Sonnenuntergang für das automatische Daily, abhängig vom Monat des Zieltags (Schlüssel `"1"` bis
`"12"`, alle zwölf müssen vorhanden sein): Mai bis Juli 90, März, April, August und September 60, sonst 30 Minuten.
Das automatische Weekly wird aus den Dailys zusammengesetzt und übernimmt den Puffer damit pro Tag.
Historische Daily- und Weekly-Läufe nutzen dagegen immer den festen Wert `daylight_buffer_minutes`
(oder den per CLI/Weboberfläche gewählten), weil dieser im Dateinamen steht.
`--daylight-buffer-minutes` überschreibt für einen Lauf beide Werte, auch bei automatischen Jobs.

`interval_window` ist das tägliche Bildfenster für Monthly und Yearly: Zielzeit
`target_time` (`HH:MM` oder `sunset`) ± `tolerance_minutes`. Automatische Läufe verwenden immer
diesen Wert; historische Läufe können ihn per CLI überschreiben (siehe „Zeitfenster für
historisches Monthly und Yearly"). Ein Fenster darf nicht über Mitternacht reichen.

`min_coverage_days` legt fest, wie viele Tage mit mindestens einem Bild im Zeitfenster ein
Monthly bzw. Yearly braucht (automatisch und historisch gleich). Erlaubt sind ganze Zahlen von 1
bis zur Fensterlänge (30 bzw. 365, mit 29. Februar im Zeitraum 366).

`image_scan_stall_timeout_seconds` (Sekunden): Meldet der Bildscan einer Kamera so lange keinen
Fortschritt, wird er abgebrochen und die Kamera übersprungen. Gemessen wird Stillstand, nicht
die Gesamtdauer. `log_retention_days` (Tage): ältere Logdateien werden beim Start gelöscht.
`timelapse.*_framerate` (Bilder pro Sekunde im Video; Weekly nutzt den Daily-Wert) und
`timelapse.ffmpeg_threads` (Threads pro FFmpeg-Aufruf) steuern die Videoerstellung.

`privacy` steuert die Verpixelung von Personen und Kennzeichen: `detector_command` ist die
Befehlszeile der Erkennung (als Liste, Pfade relativ zum Projektordner), `blur` das Aussehen
(Blockgröße, Rand, weicher Übergang), `ignore_boxes` und `ignore_top_share` verwerfen bekannte
Fehlerkennungen, `skip_labels` schaltet pro Kamera die Fahrzeug- und Kennzeichenverpixelung ab
(z. B. Boote auf Trailern), `min_person_score` verwirft pro Kamera unsichere Personen-Boxen
(z. B. Bootsplanen; kann entfernte Personen unverpixelt lassen). Ungültige Werte brechen einen Lauf mit Verpixelung ab, bevor ein Bild bearbeitet
wird. Alle Werte und Grenzen:
[docs/verpixelung.md](docs/verpixelung.md#konfiguration).

`flagger` steuert den Highlights-Flagger: `cameras` sind die Kameras, die jede Nacht geprüft
werden (leer = keine), `retention_days` ist die Aufbewahrung der Berichte in Tagen (mindestens
7). Details: [docs/flagger.md](docs/flagger.md#konfiguration).

Die Tests prüfen unter anderem:

- erwarteten Config-Pfad
- Existenz der Datei
- gültige JSON-Syntax
- erwartete Schlüssel
- grundlegende Datentypen

### Umgebungsvariablen

Für besondere Hosts lassen sich einige Pfade und Einstellungen über Umgebungsvariablen setzen. Im
normalen Betrieb auf dem Pi ist keine davon nötig.

| Variable | Standard | Wirkung |
|---|---|---|
| `TIMELAPSE_CAMERA_ROOT` | `/mnt/cameras` | Ordner mit den Kamerabildern, z. B. ein Staging-Ordner statt des SSHFS-Mounts |
| `TIMELAPSE_STORAGE_BOX` | aus dem SSHFS-Mount | Storage Box für Speicherfilter, Verpixelung und Staging auf Hosts ohne Mount: `<ssh-alias>[:<basisordner>]`. Benutzer, Port und Schlüssel stehen in `~/.ssh/config` unter dem Alias, nie im Repository |
| `TIMELAPSE_X264_PRESET` | x264-Standard (`medium`) | Encoder-Preset (`ultrafast` … `placebo`): schneller, aber größere Dateien; `ultrafast` braucht deutlich weniger Arbeitsspeicher |
| `TIMELAPSE_PROJECT_ROOT` | `~/timelapse` des ausführenden Benutzers | Projektordner für die Web-Wrapper und `timelapse-nightly-staged` |
| `TIMELAPSE_NIGHTLY_PYTHON` | `.venv/bin/python3` im Projekt | Python für `timelapse-nightly-staged` |

Nur für Tests gedacht sind `TIMELAPSE_DISABLE_FILE_LOGGING` (setzt `tests/conftest.py`) und
`TIMELAPSE_WEB_*` (`PYTHON`, `LOCK_FILE`, `STATUS_HELPER`, `STATUS_ROOT`, `WORKER`), mit denen die
Tests die Web-Wrapper umleiten; `sudo` setzt die Umgebung im Betrieb ohnehin zurück.

---

## Betrieb im Alltag

Im Alltag muss niemand etwas tun. Jede Nacht um 2 Uhr startet der Raspberry Pi den Lauf von
selbst und erstellt für jede Kamera neu:

- ein **Tagesvideo** vom Vortag, nur mit den Bildern zwischen Sonnenaufgang und Sonnenuntergang,
- ein **Wochenvideo** aus den Tagesvideos der letzten 7 Tage,
- ein **Monatsvideo** aus den letzten 30 Tagen, jeweils mit den Bildern um die Mittagszeit,
- ein **Jahresvideo** aus dem letzten Jahr, mit bis zu fünf Mittagsbildern pro Tag.

Aufbewahrt werden die Tagesvideos der letzten 7 Tage und jeweils das neueste Wochen-, Monats- und
Jahresvideo; ältere werden automatisch gelöscht. Fehlen einer Kamera zu viele Tage, etwa weil sie
ausgefallen war, wird ihr Monats- oder Jahresvideo in dieser Nacht übersprungen.

Fällt der Strom während eines Laufs aus, wiederholt der Pi den Lauf nach dem Neustart von selbst.
Jeder Lauf schreibt ein Protokoll, in dem sich Fehler nachlesen lassen.

Details zu Zeitplan, Videotypen, Ablage, Aufbewahrung und Protokollen: [docs/betrieb.md](docs/betrieb.md).

---

## Weboberfläche

Die Weboberfläche ist im Büronetz im Browser erreichbar (Adresse des Raspberry Pi, mit
Benutzername und Passwort). Dort lässt sich:

- für eine Kamera ein **Video für einen vergangenen Zeitraum** erstellen: Tag, Woche, Monat oder
  Jahr, jeweils bis zu einem gewählten Datum. Monats- und Jahresvideos können statt der Mittagszeit
  auch die Zeit um den **Sonnenuntergang** zeigen. Das Video entsteht im Hintergrund; ein Fenster
  meldet, wenn es fertig ist.
- ein so erstelltes Video **ansehen, herunterladen oder löschen**.
- auf der Seite **Highlights** die Bilder ansehen, auf denen das Programm Tiere oder Flugobjekte
  gefunden hat (siehe nächstes Kapitel).

Die nächtlich erstellten Videos werden in der Weboberfläche derzeit nicht angezeigt.

Details zu Funktionen, Dateien und Abläufen: [docs/weboberflaeche.md](docs/weboberflaeche.md).
Wie man sie einrichtet, steht unter [Weboberfläche einrichten](#weboberfläche-einrichten).

---

## Highlights-Flagger

Der Highlights-Flagger sucht in den Tagesbildern ausgewählter Kameras nach **Tieren und
Flugobjekten** (Vögel, Flugzeuge, Drachen) und legt die Treffer auf der Seite **Highlights** der
Weboberfläche ab. Dort lassen sich die Bilder groß ansehen, herunterladen oder löschen, zum
Beispiel um gute Motive für YouTube oder die Website auszuwählen.

- Geprüft werden derzeit Strandallee, SLSV, BSV-Steinhude, SKM-Mardorf und Kitestrand.
- Dinge, die den ganzen Tag an derselben Stelle stehen, etwa ein Boot am Ufer oder eine Boje,
  werden erkannt und nicht angezeigt.
- Das Programm rät, was es sieht („Flugzeug?“) und irrt sich dabei auch; ein Mensch entscheidet.
- Treffer bleiben 30 Tage erhalten.
- **Stand:** fertig und getestet, läuft aber noch nicht jede Nacht automatisch.

Details zu Erkennung, Schwellen, Aufruf und Protokoll: [docs/flagger.md](docs/flagger.md),
zur Seite: [docs/highlights-seite.md](docs/highlights-seite.md).


---

## Verpixelung

Auf den Kamerabildern sind manchmal Menschen und Autokennzeichen zu sehen. Das Programm kann sie
erkennen und verpixeln:

- **In Videos:** Beim Erstellen eines Tagesvideos per Befehl (nicht über die Weboberfläche) lassen
  sich Personen und Kennzeichen verpixeln. Das dauert deutlich länger und ist bisher ein Test.
- **Direkt auf dem Online-Speicher:** Ein eigener Ablauf soll neue Bilder verpixeln, bevor die
  Website sie abholt. Er ist gebaut und getestet, läuft aber noch nicht im Dauerbetrieb.

Im Zweifel verweigert das Programm lieber ein Video, als ein ungeprüftes Bild zu verwenden.
Keine Erkennung findet aber jeden Menschen.

Details: [docs/verpixelung.md](docs/verpixelung.md) (Videos) und
[docs/verpixelung-box.md](docs/verpixelung-box.md) (Online-Speicher).

---

## WordPress-Seite

Ein WordPress-Plugin namens „Zeitraffer“ zeigt die fertigen Videos auf einer WordPress-Website an,
pro Kamera oder als Übersicht. Es wird derzeit auf einem Testsystem auf dem Mac entwickelt.

Die Videos gelangen noch nicht automatisch auf die echte Website; dieser Schritt fehlt noch (siehe
[Noch offen](#noch-offen)).

Details zu Einrichtung, Entwicklung und Fehlerbehebung: [docs/wordpress.md](docs/wordpress.md).

---

## Kommandozeile

Alles, was die Weboberfläche kann, und noch etwas mehr, lässt sich auch direkt auf dem Pi per
Befehl starten. Das ist für Technikerinnen und Techniker gedacht, etwa um einen Lauf zu wiederholen:

```bash
.venv/bin/python3 -m src.main                                         # vollständiger nächtlicher Lauf
.venv/bin/python3 -m src.main --jobs daily --target-date 2026-10-20   # Tagesvideo für einen bestimmten Tag
.venv/bin/python3 -m src.main --jobs yearly --target-date 2025-12-31 --cameras SLSV
```

Vorher prüfen, ob gerade ein anderer Lauf aktiv ist: Es läuft immer nur ein Lauf zur selben Zeit.

Alle Aufrufe und Optionen: [docs/cli.md](docs/cli.md).

---

## Werkzeuge

Neben dem nächtlichen Lauf gibt es Hilfsprogramme, die bei Bedarf von Hand gestartet werden:

- **Speicherfilter:** findet auf dem Online-Speicher leere Bilder und Bilder, die am selben Tag
  doppelt hochgeladen wurden, und schreibt eine Liste. Er löscht nichts.
- **Yearly-Backfill:** erstellt Jahresvideos für ganze Kalenderjahre, auch wenn einzelne Tage
  fehlen.
- **NAS-Archiv:** holt Bilder vergangener Jahre aus dem Archiv auf dem NAS, um damit Videos zu
  erstellen.
- **Staging:** ein Weg für einen Server, der den Online-Speicher nicht einbinden kann. Er kopiert
  die nötigen Bilder vorher herüber. Vorhanden, derzeit nicht im Einsatz.

Details: [docs/werkzeuge.md](docs/werkzeuge.md) (Speicherfilter, Yearly-Backfill, Staging) und
[docs/nas.md](docs/nas.md) (NAS-Archiv).

---

## Raspberry Pi

Das Programm läuft derzeit auf einem Raspberry Pi im Büro. Damit er nach einem Defekt, etwa einer
kaputten Speicherkarte, schnell wieder läuft:

- **Sicherung:** Von einem eigenen Rechner (Mac, Linux oder Windows) aus holt ein Skript alles, was
  nicht im Code steckt: Zugangsdaten (verschlüsselt mit einer Passphrase), Einstellungen,
  Erkennungsmodelle und Videos.
- **Wiederherstellung:** Ein zweites Skript richtet einen frisch installierten Pi mit dieser
  Sicherung wieder vollständig ein.
- **Absturzprotokoll:** Der Pi schreibt laufend auf, wie viel Speicher und Rechenleistung er
  braucht, damit sich unerwartete Neustarts im Nachhinein erklären lassen.

Ob das Programm dauerhaft auf dem Pi bleibt, ist noch offen.

Details zu Sicherung, Neuinstallation und Absturzprotokoll: [docs/raspberry-pi.md](docs/raspberry-pi.md).

---

## Technik für Entwickler

Das Programm ist in Python geschrieben, die Videos erzeugt FFmpeg, die Weboberfläche ist in PHP.
Bei jeder Änderung prüfen automatische Tests und eine Stilprüfung den Code, sowohl vor dem
Hochladen als auch auf GitHub.

Aufbau des Codes, Ordnerstruktur, Sicherheitsprinzipien, Tests und Linting:
[docs/architektur.md](docs/architektur.md).

---

## Aktueller Stand

Fertig und im täglichen Einsatz:

- nächtliche Tages-, Wochen-, Monats- und Jahresvideos für alle Kameras
- Videos für vergangene Zeiträume, per Weboberfläche oder Befehl, auch mit Sonnenuntergang
- Weboberfläche mit Anmeldung: Videos erstellen, ansehen, herunterladen, löschen
- Highlights-Seite mit Großansicht, Download und Löschen
- automatische Wiederholung nach Stromausfall, Protokolle, Aufräumen alter Videos
- Erkennung leerer, abgeschnittener und doppelter Bilder
- Sicherung (verschlüsselt) und Wiederherstellung des Raspberry Pi
- Speicherfilter, Yearly-Backfill und Werkzeuge für das NAS-Archiv
- automatische Tests bei jeder Änderung

Fertig, aber noch nicht im Dauerbetrieb:

- Highlights-Flagger (läuft bisher nur von Hand)
- Verpixelung von Personen und Kennzeichen (siehe [Verpixelung](#verpixelung))
- WordPress-Plugin (auf dem Testsystem)

---

## Noch offen

- die fertigen Videos automatisch auf die echte Website bringen
- Highlights-Flagger und Verpixelung jede Nacht automatisch starten
- eine Installationsanleitung und ein Installationsskript für einen beliebigen Server, falls das
  Programm vom Raspberry Pi umzieht

---

## Dokumentation

Alle ausführlichen Beschreibungen liegen im Ordner [`docs/`](docs/):

| Datei | Inhalt |
|---|---|
| [handbuch.md](docs/handbuch.md) | **Handbuch für Entwickler:** Installation als Checkliste, alle Jobs starten, Fehlerfälle und was zu tun ist |
| [betrieb.md](docs/betrieb.md) | Zeitplan, Videotypen, Ablage, Aufbewahrung, Wiederanlauf, Protokolle |
| [weboberflaeche.md](docs/weboberflaeche.md) | Funktionen und Abläufe der Weboberfläche |
| [highlights-seite.md](docs/highlights-seite.md) | die Highlights-Seite |
| [flagger.md](docs/flagger.md) | der Highlights-Flagger |
| [verpixelung.md](docs/verpixelung.md) | Verpixelung in Videos |
| [verpixelung-box.md](docs/verpixelung-box.md) | Verpixelung direkt auf dem Online-Speicher |
| [wordpress.md](docs/wordpress.md) | das WordPress-Plugin |
| [cli.md](docs/cli.md) | alle Befehle und Optionen |
| [werkzeuge.md](docs/werkzeuge.md) | Speicherfilter, Yearly-Backfill, Staging für Hosts ohne Mount |
| [nas.md](docs/nas.md) | Werkzeuge für das NAS-Archiv |
| [raspberry-pi.md](docs/raspberry-pi.md) | Sicherung, Neuinstallation, Absturzprotokoll |
| [docker.md](docs/docker.md) | Versuch mit Docker (derzeit nicht im Einsatz) |
| [architektur.md](docs/architektur.md) | Code, Ordnerstruktur, Sicherheit, Tests |
| [youtube-description-prompt.md](docs/youtube-description-prompt.md), [youtube-texts.md](docs/youtube-texts.md) | Texte für YouTube-Beschreibungen |

Pläne und Entwürfe für neue Funktionen liegen in `docs/plans/` und `docs/superpowers/`.
