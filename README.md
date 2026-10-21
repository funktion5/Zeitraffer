# Zeitraffer

Automatisierte Erstellung von Timelapse-Videos aus den Bildbeständen mehrerer Kameras auf einem Raspberry Pi.

Das System liest Originalbilder aus den unter `/mnt/cameras` eingebundenen Kameraordnern, wählt je nach Timelapse-Typ passende Frames aus und erzeugt daraus MP4-Videos mit FFmpeg.

**Die Originalbilder unter `/mnt/cameras` werden niemals verändert.**

---

## Inhalt

- [Installation](#installation)
  - [Systempakete installieren](#systempakete-installieren)
  - [Python-Umgebung einrichten](#python-umgebung-einrichten)
  - [SSHFS-Mount installieren](#sshfs-mount-installieren)
  - [Cron installieren oder prüfen](#cron-installieren-oder-prüfen)
  - [Absturzprotokollierung einrichten](#absturzprotokollierung-einrichten)
- [Konfiguration](#konfiguration)
- [Zeitplanung mit Cron](#zeitplanung-mit-cron)
  - [Nächtlicher Produktionslauf](#nächtlicher-produktionslauf)
  - [Wiederanlauf nach Neustart](#wiederanlauf-nach-neustart)
  - [Highlights-Flagger (geplant)](#highlights-flagger-geplant)
- [Lokale Weboberfläche](#lokale-weboberfläche)
  - [Apache-Konfiguration](#apache-konfiguration)
  - [Basisauthentifizierung einrichten](#basisauthentifizierung-einrichten)
  - [Wrapper installieren](#wrapper-installieren)
  - [Dateirechte für www-data](#dateirechte-für-www-data)
  - [Aktueller Funktionsumfang](#aktueller-funktionsumfang)
  - [Webdateien](#webdateien)
  - [Job-Ausführung und Status](#job-ausführung-und-status)
  - [Webtests](#webtests)
- [WordPress-Frontend](#wordpress-frontend)
  - [Voraussetzungen für das Frontend](#voraussetzungen-für-das-frontend)
  - [Schritt 1: Umgebung konfigurieren](#schritt-1-umgebung-konfigurieren)
  - [Schritt 2: Videos vom Pi holen](#schritt-2-videos-vom-pi-holen)
  - [Schritt 3: Container starten](#schritt-3-container-starten)
  - [Schritt 4: WordPress installieren](#schritt-4-wordpress-installieren)
  - [Schritt 5: Plugin aktivieren](#schritt-5-plugin-aktivieren)
  - [Schritt 6: Kameras anlegen und Shortcode einbauen](#schritt-6-kameras-anlegen-und-shortcode-einbauen)
  - [Täglicher Betrieb](#täglicher-betrieb)
  - [Fehlerbehebung (WordPress-Frontend)](#fehlerbehebung-wordpress-frontend)
- [CLI und Job-Auswahl](#cli-und-job-auswahl)
  - [Vollständiger automatischer Lauf](#vollständiger-automatischer-lauf)
  - [Einzelne automatische Jobs](#einzelne-automatische-jobs)
  - [Beliebige Job-Kombination](#beliebige-job-kombination)
  - [Historische Job-Läufe](#historische-job-läufe)
  - [Kurzform für historisches Daily](#kurzform-für-historisches-daily)
- [Speicherfilter](#speicherfilter)
  - [Aufruf](#aufruf)
  - [Ablauf](#ablauf)
  - [Laufzeit und Fortschritt](#laufzeit-und-fortschritt)
  - [Bericht](#bericht)
- [Yearly-Backfill für Kalenderjahre](#yearly-backfill-für-kalenderjahre)
- [Highlights-Flagger](#highlights-flagger)
- [Neuinstallation des Raspberry Pi](#neuinstallation-des-raspberry-pi)
  - [Was gesichert wird](#was-gesichert-wird)
  - [Voraussetzungen](#voraussetzungen)
  - [Schritt 1: Backup auf dem Mac erstellen](#schritt-1-backup-auf-dem-mac-erstellen)
  - [Schritt 2: Betriebssystem neu installieren](#schritt-2-betriebssystem-neu-installieren)
  - [Schritt 3: Alten Host-Key auf dem Mac entfernen](#schritt-3-alten-host-key-auf-dem-mac-entfernen)
  - [Schritt 4: Backup und Installer auf den Pi kopieren](#schritt-4-backup-und-installer-auf-den-pi-kopieren)
  - [Schritt 5: Migration auf dem Pi ausführen](#schritt-5-migration-auf-dem-pi-ausführen)
  - [Schritt 6: Videos zurückkopieren](#schritt-6-videos-zurückkopieren)
  - [Schritt 7: Abschluss und Aufräumen](#schritt-7-abschluss-und-aufräumen)
  - [Migration ohne Neuinstallation testen](#migration-ohne-neuinstallation-testen)
  - [Fehlerbehebung](#fehlerbehebung)
- [Aktueller Stand](#aktueller-stand)
- [Timelapse-Typen](#timelapse-typen)
- [Kameraerkennung](#kameraerkennung)
- [Bildvalidierung und Duplikate](#bildvalidierung-und-duplikate)
- [Ausgabe- und Arbeitsverzeichnisse](#ausgabe--und-arbeitsverzeichnisse)
- [Automatische Retention](#automatische-retention)
- [Run-State und Wiederanlauf](#run-state-und-wiederanlauf)
- [Logging](#logging)
- [Tests](#tests)
  - [GitHub Actions und Pre-Push-Hook](#github-actions-und-pre-push-hook)
- [Linting und Formatierung](#linting-und-formatierung)
- [Projektstruktur](#projektstruktur)
- [Architektur](#architektur)
- [Sicherheit und Datenintegrität](#sicherheit-und-datenintegrität)
- [Noch offen](#noch-offen)

---

## Installation

Platzhalter in den folgenden Beispielen:

| Platzhalter | Bedeutung |
|---|---|
| `<benutzer>` | Linux-Konto, unter dem das Projekt läuft |
| `<projektpfad>` | Projektordner, z. B. `/home/<benutzer>/timelapse` |
| `<login>` | Benutzername der Apache-Basisauthentifizierung |

Die folgenden Abschnitte beschreiben die Einrichtung von Hand. Für einen neu installierten Pi mit vorhandenem Backup übernimmt `migrate.sh` alle Schritte; siehe [Neuinstallation des Raspberry Pi](#neuinstallation-des-raspberry-pi).

### Systempakete installieren

Dieselbe Paketliste installiert auch `migrate.sh` (Schritt `packages`):

```bash
sudo apt-get update
sudo apt-get install -y \
  git python3 python3-venv python3-pip \
  ffmpeg sshfs \
  apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache
```

Weil der SSHFS-Mount `allow_other` verwendet, muss in `/etc/fuse.conf` die Zeile `user_allow_other` aktiv sein:

```bash
grep -qx user_allow_other /etc/fuse.conf || echo user_allow_other | sudo tee -a /etc/fuse.conf
```

### Python-Umgebung einrichten

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

Die beiden Einträge aus [Zeitplanung mit Cron](#zeitplanung-mit-cron) werden über

```bash
crontab -e
```

für den Benutzer `<benutzer>` installiert. Anschließend prüfen:

```bash
crontab -l
```

### Absturzprotokollierung einrichten

Pi OS hält das systemd-Journal nur im RAM (`40-rpi-volatile-storage.conf`), und der Hardware-Watchdog setzt den Pi ohne jeden Logeintrag zurück. Nach einem stillen Neustart ist deshalb standardmäßig nichts mehr zu sehen. `scripts/pi-crash-logging-setup` sorgt dafür, dass Spuren auf der SD-Karte bleiben:

```bash
sudo ~/timelapse/scripts/pi-crash-logging-setup           # installieren und starten
sudo ~/timelapse/scripts/pi-crash-logging-setup --remove  # alles rückgängig machen
```

Den vollen Pfad verwenden: Als root zeigt `~` auf `/root`, deshalb nicht erst per `sudo -i` wechseln.

Das Skript richtet ein:

| Was | Wo | Zweck |
|---|---|---|
| persistentes Journal | `/etc/systemd/journald.conf.d/99-persistent.conf` | `Storage=persistent`, max. 200 MB, Schreiben auf die SD alle 30 Sekunden |
| Health-Logger | `/usr/local/sbin/pi-health-logger` + `pi-health-logger.service` | alle 10 Sekunden eine Zeile mit freiem Speicher, Swap, Last, größtem Prozess, Throttling und Temperatur |
| Health-Log | `/var/log/pi-health.log` | wird nach jeder Zeile gesynct; ab 10 MB nach `.1` rotiert |

Das 30-Sekunden-Intervall des Journals ist ein Kompromiss mit dem Verschleiß der SD-Karte; die letzten Sekunden vor einem Reset kann das Journal deshalb verlieren. Das Health-Log ist höchstens ein Intervall älter als der Reset.

Nach dem nächsten unerwarteten Neustart:

```bash
journalctl -b -1 -e                  # Ende des vorherigen Boots
tail -30 /var/log/pi-health.log      # letzte Messwerte vor dem Reset
```

`--remove` stellt das flüchtige Journal wieder her, lässt aber `/var/log/pi-health.log` und `/var/log/journal` liegen. `migrate.sh` richtet die Absturzprotokollierung nicht ein; nach einer Neuinstallation muss das Skript erneut ausgeführt werden.

---

## Konfiguration

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
    "1": 30, "2": 30, "3": 60, "4": 60, "5": 90, "6": 90,
    "7": 90, "8": 60, "9": 60, "10": 30, "11": 30, "12": 30
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
    "cameras": [],
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
bis zur Fensterlänge (30 bzw. 365).

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

---

## Zeitplanung mit Cron

Die Zeitplanung erfolgt über Linux-Cron. Es gibt keinen internen Python-Scheduler.

### Nächtlicher Produktionslauf

Die installierte Crontab startet den vollständigen Workflow täglich um 02:00 Uhr:

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'
```

`flock -n` verwendet einen nicht blockierenden Lock. Läuft bereits ein Prozess mit demselben Lock, wird kein zweiter Produktionslauf gestartet.

### Wiederanlauf nach Neustart

Beim Booten wird der Workflow nur gestartet, wenn `state/run-in-progress` existiert. Da der Kamera-Storage eventuell noch nicht bereit ist, wartet Cron zunächst auf einen echten Mount unter `/mnt/cameras`:

```cron
@reboot if [ -f <projektpfad>/state/run-in-progress ]; then until mountpoint -q /mnt/cameras; do sleep 5; done; flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'; fi
```

Der nächtliche Lauf und die Reboot-Wiederherstellung verwenden beide:

```text
<projektpfad>/state/zeitraffer-run.lock
```

Dadurch können sie nicht überlappen. Es ist keine zusätzliche Cron-Logdatei konfiguriert; die Anwendung schreibt ihre eigenen Job-Logs.

### Highlights-Flagger (geplant)

Noch nicht eingerichtet. Der [Highlights-Flagger](#highlights-flagger) soll direkt nach dem
nächtlichen Lauf starten, in derselben Zeile, aber außerhalb von `flock -c`: Er nimmt die Sperre
selbst und würde sonst an der von Cron scheitern.

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'; cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.flagger.run
```

Installierte Einträge prüfen:

```bash
crontab -l
```

---

## Lokale Weboberfläche

Die Weboberfläche ist eine kleine PHP-Anwendung ohne Datenbank und ohne separates API-Framework. Sie ist für das vertrauenswürdige lokale Netzwerk vorgesehen.

```text
Browser
  → Apache und PHP
  → eingeschränkter Wrapper
  → bestehende Python-CLI
  → Timelapse-Jobs und FFmpeg
  → videos/ + logs/ + temp/ + state/
```

### Apache-Konfiguration

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

### Basisauthentifizierung einrichten

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

### Wrapper installieren

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
```

Die sudoers-Regeln erlauben ausschließlich den festen Trigger und den festen Lösch-Wrapper, jeweils als `<benutzer>`:

```sudoers
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete
```

Eine sudoers-Regel ohne Argumentliste erlaubt beliebige Argumente. `timelapse-web-delete` erwartet genau Kamera, Job-Typ und Dateiname, prüft diese selbst (kein `/`, nur `.mp4`, keine Symlinks) und löscht ausschließlich unter `videos/<camera>/manual-runs/<job>/`.

Die Regeln werden mit folgendem Befehl in einer eigenen Datei sicher bearbeitet und geprüft:

```bash
sudo visudo -f /etc/sudoers.d/timelapse-web
```

Eingaben werden zusätzlich in PHP und in den Wrappern validiert; die sudoers-Regeln allein ersetzen diese Prüfungen nicht.

Nach Änderungen an den versionierten Wrappern müssen die Laufzeitkopien erneut mit `sudo install` aktualisiert werden.

### Dateirechte für `www-data`

`www-data` wird nicht in die Gruppe `<benutzer>` aufgenommen und erhält nur Zugriff auf das, was die Weboberfläche tatsächlich liest. Alles andere – Python-Code, Skripte, Tests, `.git`, `.venv`, Logs, temporäre Dateien und alle übrigen Dateien im Home-Verzeichnis – bleibt für `www-data` gesperrt.

| Pfad | Rechte für „andere“ | Zweck |
|---|---|---|
| `/home/<benutzer>` | nur Durchgang (`--x`) | Weg zum Projekt |
| übrige Einträge in `/home/<benutzer>` | keine | z. B. Backups, `.ssh` |
| `timelapse/` | nur Durchgang (`--x`) | kein Auflisten des Projekts |
| `web/` | lesen (`r-x` / `r--`) | PHP-Dateien und CSS |
| `videos/` | lesen (`r-x` / `r--`) | Bibliothek, Wiedergabe, Speicheranzeige |
| `config/` | nur Durchgang (`--x`) | – |
| `config/config.json` | lesen (`r--`) | `ignored_cameras` |
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

### Aktueller Funktionsumfang

Die Startseite listet die unter `/mnt/cameras` gefundenen Kameraverzeichnisse auf. Die gesamte Oberfläche ist auf Deutsch; interne Bezeichner (`daily`/`weekly`/`monthly`/`yearly` in Formularwerten, URLs und der CLI) bleiben davon unberührt. Die Kameraseite bietet:

- Anzeige von gesamtem, verwendetem und freiem Speicherplatz des Dateisystems von `videos/`
- Bibliothek der historischen Videos unter `videos/<camera>/manual-runs/`, mit kurzem deutschem Datum statt Dateiname (plus Zeitpuffer in Minuten, sofern der Dateiname einen trägt, z. B. „24.09.2026 (60 Min.)“, bzw. das Zeitfenster bei Monthly/Yearly, z. B. „30.06.2025 (Sonnenuntergang ±60 Min.)“); die Liste bleibt für den Job-Typ des gerade ausgewählten Videos aufgeklappt
- Wiedergabe des ausgewählten MP4 direkt im Browser, mit Download- und Löschen-Button (Icon + Beschriftung), beide mit Bestätigungsdialog vor dem Absenden
- Formular für genau eine Kamera, einen Job-Typ und ein Zieldatum; bei Daily/Weekly zusätzlich ein Zeitpuffer (30/60/90 Minuten) als Radiogruppe, die nur für diese beiden Job-Typen eingeblendet wird — Monthly/Yearly nutzen keinen Zeitpuffer und erhalten ihn serverseitig auch dann nicht, wenn einer übermittelt würde
- bei Monthly/Yearly eine Radiogruppe „Zeitfenster“: „Mittag (Standard)“ übergibt nichts (es gilt `interval_window` aus der Config), „Sonnenuntergang“ übergibt `sunset` plus eine Fensterbreite von ±30/60/90 Minuten (eigene Radiogruppe, nur bei Sonnenuntergang sichtbar); serverseitig sind nur diese Werte erlaubt
- kurzer Hinweistext über dem Formular: Zieldatum ist immer der letzte Tag des Zeitraums; Monthly braucht mindestens 25 der 30 Tage, Yearly mindestens 300 Tage mit Bildern im gewählten Zeitfenster (`min_coverage_days`), fehlende Tage werden im Video übersprungen
- historische Daily-, Weekly-, Monthly- und Yearly-Läufe
- Live-Status per Polling im Abstand von fünf Sekunden; der Abschlussdialog übersteht auch einen Seitenwechsel weg von der auslösenden Seite (Fortsetzung des Pollings über `sessionStorage`) und bietet einen direkten Link zum fertigen Video an
- Löschen eines historischen Videos über denselben eingeschränkten Wrapper-Mechanismus wie die Job-Erstellung

Die Bibliothek zeigt derzeit ausschließlich `manual-runs`. Versteckte Dateien werden nicht gelistet, darunter `.<name>.tmp.mp4` eines laufenden Renderings, das so weder abgespielt noch gelöscht werden kann. Automatische Videos werden noch nicht in der Oberfläche aufgelistet, und eine Status-Datei-Bereinigung ist nicht implementiert.

Die Kameraerkennung der Weboberfläche ignoriert versteckte Verzeichnisse und blendet zusätzlich alle Kameras aus `ignored_cameras` in `config/config.json` aus (`getIgnoredCameras()` in `web/src/video-library.php`). Die Weboberfläche benötigt deshalb Lesezugriff auf `config/config.json`.

### Webdateien

```text
web/public/index.php               Kameraübersicht
web/public/camera.php              Player, Bibliothek, Formular und Status-Polling
web/public/job-status.php          read-only JSON-Status-Endpunkt (inkl. Tote-Prozess-Erkennung)
web/public/style.css               Darstellung und responsives Layout
web/src/components/header.php      gemeinsamer Header und Speicheranzeige
web/src/components/job-watcher.php gemeinsamer Abschlussdialog, seitenübergreifendes Polling
web/src/video-library.php          Kamera-, Video- und Speicherermittlung
web/src/job-runner.php             Aufruf des fest installierten Triggers
web/src/video-delete.php           Aufruf des fest installierten Lösch-Wrappers
web/src/process-runner.php         gemeinsame proc_open-Hilfsfunktion (Trigger und Löschen)
```

`web/public/` ist der einzige Apache-DocumentRoot. PHP-Quellcode außerhalb dieses Verzeichnisses, Python-Code, Konfiguration, Logs, temporäre Dateien und Statusdateien werden nicht direkt durch Apache veröffentlicht.

### Job-Ausführung und Status

Ein gültiger Formular-POST wird durch einen Session-basierten CSRF-Token geschützt. PHP prüft Kamera, Job-Typ und ISO-Datum und ruft anschließend ohne Shell-Auswertung diesen festen Befehl auf:

```text
sudo -n -u <benutzer> /usr/local/sbin/timelapse-web-trigger \
  <job-id> <job> <zieldatum> <kamera> [<zeitpuffer> | <fenster-zeit> <fenster-toleranz>]
```

Daily/Weekly verlangen genau einen Zeitpuffer (30/60/90). Monthly/Yearly erhalten entweder
nichts oder Fensterzeit (`HH:MM` oder `sunset`) plus Toleranz in Minuten (1–999); Trigger und
Worker prüfen das Format, `src.main` lehnt Fenster über Mitternacht ab. Der Worker übergibt
`--window-time` / `--window-tolerance-minutes` und erwartet die Datei
`<kamera>_<zieldatum>_<HHMM|sunset>-<toleranz>min.mp4`.

Die weitere Kette lautet:

```text
timelapse-web-trigger
  → validiert Job-ID, Job, Datum und Kamera
  → belegt state/zeitraffer-run.lock ohne Warten
  → schreibt running
  → startet timelapse-web-worker im Hintergrund

timelapse-web-worker
  → startet python3 -m src.main --jobs ... --target-date ... --cameras ...
  → prüft, ob die erwartete MP4 neu veröffentlicht oder atomar ersetzt wurde
  → schreibt completed oder failed
```

Statusdateien liegen unter:

```text
state/web-jobs/<32-stellige-job-id>.status
```

Erlaubte Inhalte sind ausschließlich `running`, `completed` und `failed`. `job-status.php` akzeptiert nur eine 32-stellige, kleingeschriebene hexadezimale Job-ID und liefert den Zustand als JSON. Der Browser legt den laufenden Job in `sessionStorage` ab (`job-watcher.php`); nach einem Neuladen oder Seitenwechsel setzt er das Polling dort fort. Sobald `completed` oder `failed` vorliegt, wird der Eintrag entfernt und ein nativer `<dialog>` mit dem Ergebnis geöffnet.

Eine automatische Bereinigung alter Web-Statusdateien ist noch nicht implementiert.

Der Trigger verwendet denselben Lock wie Cron:

```text
<projektpfad>/state/zeitraffer-run.lock
```

Dadurch können ein Web-Job, der nächtliche Produktionslauf und der Wiederanlauf nach einem Neustart nicht gleichzeitig arbeiten. Ist der Lock bereits belegt, meldet die Oberfläche, dass ein anderer Timelapse-Job läuft.

### Webtests

Wrapper, PHP-Helfer und Status-Endpunkt werden mit pytest geprüft (benötigt `php` auf der Kommandozeile):

```bash
python3 -m pytest tests/web_status_test.py tests/web_status_endpoint_test.py \
  tests/web_delete_test.py tests/web_php_test.py
```

- `web_status_test.py`: atomare Statuswechsel, ungültige Job-IDs, gemeinsamer Lock, Trigger-Validierung, erfolgreiche Videoveröffentlichung und fehlgeschlagene Jobs
- `web_status_endpoint_test.py`: JSON-Antworten von `job-status.php`
- `web_delete_test.py`: Lösch-Wrapper, u. a. Pfad-Traversal, Dateityp, Symlinks und dass automatische Videos unangetastet bleiben
- `web_php_test.py`: `video-library.php`, `process-runner.php`, `job-runner.php` und `video-delete.php`; die Tests kopieren `web/src` nach `tmp_path`, ersetzen dort die festen Pfade und verwenden ein Fake-`sudo`, sodass weder echte Videos noch installierte Wrapper berührt werden

Nicht automatisiert getestet sind `camera.php` und die Speicheranzeige (`getStorageUsage`), weil beide feste Pfade ohne Umleitungsmöglichkeit verwenden.

---

## WordPress-Frontend

Zusätzlich zur PHP-Weboberfläche gibt es ein WordPress-Plugin (`frontend/`), das die fertigen Videos auf einer WordPress-Seite zeigt. Es ist **nur lesend**: Es startet keine Jobs, schreibt keine Dateien und hat keine Formulare, AJAX- oder REST-Endpunkte. Entwickelt wird es lokal auf dem Mac in einer Docker-Umgebung; die Pi-Weboberfläche bleibt davon unberührt.

```text
Pi: videos/<Kamera>/<Zeitraum>/*.mp4
  → docker/pull-videos.sh (rsync, nur Lesen auf dem Pi)
  → Mac: videos/
  → Docker-Container "wordpress": wp-content/uploads/zeitraffer/ (schreibgeschützt)
  → Plugin frontend/plugin-timelapse.php
  → Shortcodes [tl] und [zeitraffer]
```

### Voraussetzungen für das Frontend

- Docker Desktop (mit `docker compose`) auf dem Mac
- SSH-Zugang zum Pi per Schlüssel; Benutzer und Adresse stehen in `docker/.env` (Variable `PI`, siehe Schritt 1); der Pi muss im Netz erreichbar sein
- `rsync` auf dem Mac (bei macOS vorhanden)
- Port `8080` auf dem Mac ist frei

### Ablauf in Kurzform

```bash
cd docker
cp .env.example .env         # danach die Werte eintragen, siehe unten
docker compose up -d
cd ..
docker/pull-videos.sh        # Videos vom Pi holen
```

Danach WordPress einmalig installieren, das Plugin aktivieren und den Shortcode in eine Seite einbauen (Details unten).

### Schritt 1: Umgebung konfigurieren

`docker/.env.example` ist die Vorlage; `docker/.env` ist per `.gitignore` ausgeschlossen und darf nie committet werden.

```bash
cd docker
cp .env.example .env
```

Alle Werte in `docker/.env` ausfüllen. Die Datenbankwerte sind frei wählbar, es ist nur eine lokale Entwicklungsdatenbank:

| Variable | Bedeutung |
|---|---|
| `DB_NAME` | Name der Datenbank, z. B. `wordpress` |
| `DB_USER` | Datenbankbenutzer für WordPress |
| `DB_PASSWORD` | Passwort dieses Benutzers |
| `DB_ROOT_PASSWORD` | Root-Passwort der MariaDB |
| `PI` | Benutzer und Adresse des Pi für `pull-videos.sh`, Format `benutzer@adresse` |

Bleibt ein Wert leer, startet die Datenbank nicht oder WordPress kann sich nicht verbinden. Compose liest die `.env` aus dem Ordner `docker/` und löst alle Pfade relativ zu diesem Ordner auf.

Die Konfiguration lässt sich vorab prüfen:

```bash
docker compose config
```

### Schritt 2: Videos vom Pi holen

Der Container erwartet die Videos unter `videos/` im Projektordner, in derselben Struktur wie auf dem Pi:

```text
videos/<Kamera>/<daily|weekly|monthly|yearly>/<Kamera>_<Datum>.mp4
```

Ohne Videos zeigt das Plugin keine Kameras an.

```bash
cd /pfad/zum/projekt
docker/pull-videos.sh -n     # Probelauf: zeigt nur, was passieren würde
docker/pull-videos.sh        # Probelauf anzeigen, nach Bestätigung (y) wirklich spiegeln
```

Das Skript **spiegelt** den Ordner `~/timelapse/videos/` des Pi-Logins nach `videos/`:

- Neue und geänderte Dateien werden kopiert.
- Dateien, die auf dem Pi nicht mehr existieren, werden lokal **gelöscht**, damit keine veralteten Videos übrig bleiben. Deshalb zeigt das Skript immer zuerst einen Probelauf und fragt nach, bevor es etwas ändert.
- `manual-runs/` und versteckte Dateien (z. B. unfertige Renderings) werden weder kopiert noch gelöscht.
- Auf dem Pi wird nichts verändert.

`PI` wird aus der Umgebung oder aus `docker/.env` gelesen; ein einmaliger anderer Wert lässt sich so übergeben:

```bash
PI=benutzer@<Pi-Adresse> docker/pull-videos.sh
```

Achtung bei eigenen Testvideos in `videos/`: Sie stehen im Probelauf unter den Löschungen, sofern sie auf dem Pi nicht existieren.

### Schritt 3: Container starten

```bash
cd docker
docker compose up -d
```

Der Stack besteht aus zwei Containern:

| Container | Image | Aufgabe |
|---|---|---|
| `db` | `mariadb:11` | Datenbank, Daten im benannten Volume `db` |
| `wordpress` | `wordpress:php8.4-apache` | WordPress, erreichbar unter http://localhost:8080 |

Eingebunden werden:

| Host (Mac) | Container | Zweck |
|---|---|---|
| `frontend/` | `/var/www/html/wp-content/plugins/zeitraffer` | Das Plugin, schreibgeschützt (`:ro`). Änderungen am Code sind sofort sichtbar. |
| `videos/` | `/var/www/html/wp-content/uploads/zeitraffer/` | Die Videos, schreibgeschützt. Nach jedem `pull-videos.sh` ohne Neustart sichtbar. |
| Volume `wordpress` | `/var/www/html` | WordPress-Dateien und Uploads |
| Volume `db` | `/var/lib/mysql` | Datenbank |

Status prüfen:

```bash
docker compose ps
docker compose logs -f wordpress
```

### Schritt 4: WordPress installieren

1. http://localhost:8080 öffnen. Beim ersten Start erscheint der Installationsassistent.
2. Sprache wählen, Seitentitel, Admin-Benutzer, **ein starkes Passwort** und eine E-Mail-Adresse angeben und installieren. Die Daten bleiben nur in der lokalen Umgebung.
3. Unter **Einstellungen → Permalinks** die Struktur **Beitragsname** wählen und speichern. Das Plugin funktioniert auch mit „Einfach“, aber mit Beitragsname entsprechen die URLs der späteren Live-Seite (`/zeitraffer/?camera=...`).

Die Installation überlebt `docker compose down` und einen Neustart des Macs, da sie in den benannten Volumes liegt.

### Schritt 5: Plugin aktivieren

Unter **Plugins** erscheint **Zeitraffer** (Datei `frontend/plugin-timelapse.php`). Auf **Aktivieren** klicken. Erscheint das Plugin nicht, ist der Mount nicht angekommen; siehe [Fehlerbehebung](#fehlerbehebung-wordpress-frontend).

### Schritt 6: Kameras anlegen und Shortcode einbauen

Namen und Beschreibungen der Kameras werden im WordPress-Admin gepflegt, nicht im Code und nicht in den Seiten. Der Shortcode nennt nur den Kameraordner.

#### Kameras anlegen (einmalig, danach bei neuen Ordnern)

1. Im Admin **Zeitraffer → Alle Kameras** öffnen.
2. Auf **Kameras aus Ordnern anlegen** klicken. Für jeden Ordner unter `uploads/zeitraffer/` mit mindestens einem Video entsteht ein Eintrag **als Entwurf**; vorhandene Einträge bleiben unverändert, der Button kann beliebig oft gedrückt werden. Neue Kameraordner werden später genauso übernommen.
3. Einen Eintrag öffnen, ausfüllen und, wenn die Kamera getestet ist, **veröffentlichen**:
   - **Titel:** der Anzeigename auf der Seite, z. B. „Hafenstraße“ (zunächst der Ordnername).
   - **Auszug:** die Beschreibung der Szene als Textalternative zum Video (siehe unten).
   - Rechts zeigt der Kasten **Zeitraffer** den Ordner (nicht änderbar) und den passenden Shortcode.

Die Einträge sind nicht öffentlich: Sie haben keine eigene Adresse und erscheinen nur im Admin. Die Liste zeigt je Kamera den Ordner; fehlt der Ordner (umbenannt oder gelöscht), steht dort „Ordner nicht gefunden“. Neue Einträge lassen sich nicht von Hand anlegen, weil jeder Eintrag zu einem Ordner gehört.

#### Shortcode einbauen

Das Plugin wird in eine bestehende Kameraseite eingefügt (z. B. `/webcams/hafenstrasse/`). Die Seite behält ihr Bild, ihre Texte, den Geolink und die Werbung; der Player erscheint dort, wo der Shortcode steht.

```text
[zeitraffer camera="tim-meuter"]
```

Die Seiten-URL und der Kameraordner heißen oft unterschiedlich (die Seite `hafenstrasse` gehört zum Ordner `tim-meuter`). Deshalb wird die Kamera immer ausdrücklich im Shortcode genannt und nicht aus der URL abgeleitet. Anlegen: Seite öffnen, an der gewünschten Stelle einen **Shortcode-Block** einfügen, den Shortcode hineinschreiben, speichern.

| Attribut | Pflicht | Bedeutung |
|---|---|---|
| `camera` | ja | Der Ordner der Kamera, klein geschrieben und bereinigt (nur `a-z`, `0-9`, `_`, `-`). Aus `Nordufer_tele` wird `nordufer_tele`; der Kasten „Zeitraffer“ im Kameraeintrag zeigt den richtigen Wert. Ohne dieses Attribut wird `?camera=` aus der URL verwendet. |
| `title` | nein | Überschreibt den Titel des Kameraeintrags. Normalerweise nicht nötig. |
| `description` | nein | Überschreibt den Auszug des Kameraeintrags. Normalerweise nicht nötig. |
| `heading` | nein | Ebene der Überschrift des Players, `2` bis `6`, Standard `2`. So lässt sich die Überschrift in die Struktur der Seite einpassen, z. B. `heading="4"` für Seiten, deren Abschnittstitel `h4` sind. Ungültige Werte ergeben `2`. |

Vorrang: Attribut im Shortcode, dann Kameraeintrag, dann Ordnername bzw. nur der Hinweis „Zeitraffer ohne Ton“. Texte aus einem Entwurf werden nur Redakteuren in der Vorschau gezeigt (siehe nächster Abschnitt).

#### Sichtbarkeit: Entwurf und veröffentlicht

Ob eine Kamera für Besucher erscheint, entscheidet allein der Status ihres Eintrags:

| Eintrag | Besucher | Redakteure (Recht „Beiträge anderer bearbeiten“) |
|---|---|---|
| veröffentlicht | Player, Tabs, Texte | wie Besucher |
| Entwurf, ausstehend, privat | nichts (auch kein Link in `[tl]`) | Player mit Hinweis „nicht veröffentlicht“ |
| kein Eintrag (Ordner noch nicht angelegt) | nichts | Player mit Hinweis |

So kann eine neue Kamera auf ihrer echten Seite getestet werden, ohne dass sie öffentlich ist: Entwurf anlegen, die Seite als angemeldeter Redakteur prüfen, dann veröffentlichen. Wichtig: Schaltet ein bereits veröffentlichter Eintrag zurück auf Entwurf, verschwindet die Kamera sofort. Texte bearbeitet man deshalb am besten im veröffentlichten Eintrag und speichert mit „Aktualisieren“.

Hinweis zum Caching: Sieht ein Zwischenspeicher (Cache-Plugin, CDN) eine für angemeldete Redakteure erzeugte Seite, könnte er den Entwurf an Besucher ausliefern. Angemeldete Nutzer werden normalerweise nicht gecacht; auf der Testseite prüfen.

Hinweise:

- **Tippfehler:** Stimmt `camera` nicht mit einem Ordner überein, sehen Besucher nichts. Angemeldete Redakteure (Recht „Seiten bearbeiten“) sehen einen Hinweis mit den verfügbaren Kameras.
- **Auszug und Barrierefreiheit:** Ein Zeitraffer ohne Ton braucht eine Textalternative (WCAG 1.2.1). Mit Auszug beschreibt der Text die Szene („Blick über den Hafen auf Boote und Steg“); ohne ihn steht nur der Hinweis „Zeitraffer ohne Ton“. Der Auszug sollte deshalb für jede Kamera gesetzt werden. Er ist reiner Text, HTML erscheint wörtlich.
- **Ein Player pro Seite:** Der Player verwendet feste Element-IDs; mehrere `[zeitraffer]` auf derselben Seite funktionieren nicht.
- **Überschrift:** Das Plugin gibt eine eigene Überschrift aus („Zeitraffer – Zeitraum“, ohne Kameranamen, weil die Seite die Kamera schon im Titel nennt). Standard ist `<h2>`; die Ebene lässt sich mit `heading` anpassen. Ob sie zur Überschriftenstruktur der Seite passt, sollte auf einer Testseite geprüft werden.

#### Optional: gemeinsame Übersicht und Playerseite

Der ältere Aufbau mit zwei Seiten funktioniert weiter. Er wird für die Kameraseiten nicht gebraucht.

| Seite | Titel / Slug | Inhalt | Funktion |
|---|---|---|---|
| Kameraübersicht | z. B. „Kameras“ | `[tl]` | Liste aller Kameras mit Videos, jede verlinkt auf die Playerseite |
| Player | **„Zeitraffer“, Slug `zeitraffer`** | `[zeitraffer]` | Zeigt das Video der Kamera aus `?camera=` (`http://localhost:8080/zeitraffer/?camera=<slug>`, optional `&period=daily|weekly|monthly|yearly`) |

Die Übersicht sucht die Playerseite über den Slug `zeitraffer`. Ist sie nicht vorhanden, verlinkt die Übersicht auf die aktuelle Seite. Der Slug lässt sich per Filter ändern, ohne das Plugin zu bearbeiten:

```php
add_filter( 'zeitraffer_camera_page_slug', fn() => 'mein-slug' );
```

### So funktioniert das Plugin

- **Kameras** sind die Unterordner von `videos/`. Ein Ordner erscheint nur, wenn er in mindestens einem Zeitraum ein `.mp4` enthält **und** sein Kameraeintrag veröffentlicht ist. Der Slug in der URL ist der Ordnername, durch `sanitize_key()` bereinigt (nur `a-z`, `0-9`, `_`, `-`).
- **Das neueste Video** je Zeitraum ist die Datei, die nach Dateinamen zuletzt kommt. Das setzt voraus, dass das Datum im Dateinamen steht (`<Kamera>_<JJJJ-MM-TT>.mp4`), wie es die Pipeline erzeugt.
- Die Überschrift zeigt „Zeitraffer“ und den Zeitraum, den das Video abdeckt. Das Enddatum steht im Dateinamen (`<Kamera>_<JJJJ-MM-TT>.mp4`; ohne Datum im Namen gilt das Änderungsdatum der Datei), der Anfang ergibt sich aus dem Typ wie in der Pipeline: Tag = dieser Tag, Woche = 7 Kalendertage, Monat = 30 Tage, Jahr = das Kalenderjahr bis zum Enddatum (365 oder 366 Tage), jeweils einschließlich Enddatum. Beispiel Woche: „Zeitraffer – 15.09.2026 bis 21.09.2026“. Das Datumsformat folgt der Einstellung von WordPress (Einstellungen → Allgemein), und der Zeitraum wechselt mit dem Tab.
- Hat der angefragte Zeitraum kein Video, springt der Player auf den ersten Zeitraum, der eines hat.
- Versteckte Dateien und `manual-runs/` werden nicht angezeigt.
- Die Tabs funktionieren auch ohne JavaScript als normale Links; `assets/script.js` schaltet nur ohne Seitenneuladen um und zeigt dabei ein Lade-Skelett (`assets/style.css`).
- Das Plugin lädt **nichts von Dritten**: keine externen Schriften, Skripte oder Tracker, keine Cookies und kein Browser-Speicher. Es sind also keine Einwilligung und keine Datenschutzanpassung nötig.
- Farben folgen der Palette des Avada-Themes (`--awb-color*`), mit denselben Hex-Werten als Rückfallwert in der lokalen Umgebung. Schrift und Textfarbe erbt das Plugin vom Theme.

### Täglicher Betrieb

```bash
cd docker
docker compose up -d       # starten
docker compose down        # stoppen, Daten bleiben erhalten
docker compose down -v     # stoppen UND Volumes löschen: WordPress-Installation und Datenbank sind weg
```

- Neue Videos: `docker/pull-videos.sh` ausführen und die Seite neu laden. Ein Neustart ist nicht nötig.
- Code ändern: Datei in `frontend/` speichern und neu laden. Die Versionsnummer von CSS und JS ist deren Änderungszeit, daher gibt es keine Cache-Probleme; bei Zweifeln Strg/Cmd+Shift+R.
- Mac ausschalten: nichts zu tun. Die Container starten mit Docker Desktop wieder (`restart: always`) oder per `docker compose up -d`; Installation und Videos bleiben erhalten.
- `down -v` entspricht einem Zurücksetzen auf eine frische WordPress-Installation (Schritt 4 beginnt wieder von vorn). Videos und Plugin-Code sind nicht betroffen, weil sie nur eingebunden sind.

### Syntaxprüfung des Plugins

Ohne lokale PHP-Installation über den Container:

```bash
docker run --rm -v "$PWD/frontend":/w php:8.4-cli php -l /w/plugin-timelapse.php
```

Für das Plugin gibt es keine automatisierten Tests; die GitHub-Action prüft nur die Python-Pipeline und die PHP-Weboberfläche.

### Fehlerbehebung (WordPress-Frontend)

| Symptom | Ursache und Lösung |
|---|---|
| Das Plugin „Zeitraffer“ fehlt in der Pluginliste | Der Mount fehlt. `docker compose exec wordpress ls /var/www/html/wp-content/plugins/zeitraffer` muss `plugin-timelapse.php` zeigen. Compose muss aus dem Ordner `docker/` gestartet werden, weil der Pfad `../frontend` relativ dazu aufgelöst wird. |
| Die Seite zeigt nichts oder „Derzeit sind keine Zeitraffer-Videos verfügbar“ | `videos/` ist leer, oder es gibt keine `.mp4` unter `videos/<Kamera>/<Zeitraum>/`. Mit `docker compose exec wordpress ls /var/www/html/wp-content/uploads/zeitraffer` prüfen und `docker/pull-videos.sh` ausführen. |
| Das Video lädt, lässt sich aber nicht abspielen (z. B. 403 „Forbidden“) | Dateirechte oder Mount prüfen: `docker compose exec wordpress ls -l /var/www/html/wp-content/uploads/zeitraffer/<Kamera>/<Zeitraum>`. Die Dateien müssen für den Webserver lesbar sein. |
| Kamera ist in der Übersicht, aber der Link zeigt keinen Player | Die Seite mit `[zeitraffer]` fehlt oder hat nicht den Slug `zeitraffer` (siehe Schritt 6). |
| Port 8080 belegt | In `docker/docker-compose.yml` den linken Teil von `"8080:80"` ändern, z. B. `"8081:80"`, und neu starten. |
| Datenbankfehler beim Start | `docker/.env` unvollständig. Alle `DB_*`-Werte setzen. Wurden Werte nach dem ersten Start geändert, bleibt die Datenbank mit den alten Zugangsdaten bestehen; dann `docker compose down -v` und neu installieren. |
| `pull-videos.sh` bricht ab oder hängt | Pi nicht erreichbar oder kein SSH-Schlüssel eingerichtet. Verbindung mit `ssh benutzer@<Pi-Adresse>` prüfen; fehlt `PI`, bricht das Skript mit einem Hinweis ab. |

### Wichtig für den Live-Betrieb

Diese Anleitung beschreibt nur die lokale Entwicklungsumgebung. Auf der Live-Seite werden Plugin und Videos nicht von Docker bereitgestellt. Das Plugin erwartet die Videos unter `wp-content/uploads/zeitraffer/` in genau der Ordnerstruktur oben. Deployment auf die Live-Seite oder den Pi gehört nicht zu diesem Ablauf und passiert nie automatisch.

---

## CLI und Job-Auswahl

Alle Befehle werden im Projektverzeichnis und innerhalb der virtuellen Umgebung ausgeführt:

```bash
cd ~/timelapse
source .venv/bin/activate
```

### Vollständiger automatischer Lauf

Ohne weitere Argumente werden alle automatischen Jobs ausgeführt:

```bash
python3 -m src.main
```

Reihenfolge:

```text
Daily
→ Weekly
→ Monthly
→ Yearly
```

### Einzelne automatische Jobs

Ohne `--target-date` verwenden die ausgewählten Jobs standardmäßig den letzten abgeschlossenen Kalendertag. Die Ausgaben werden unter `videos/<camera>/<job>/` gespeichert und die jeweilige automatische Retention wird angewendet.

Nur Daily für alle verfügbaren Kameras:

```bash
python3 -m src.main --jobs daily
```

Nur Weekly für alle verfügbaren Kameras:

```bash
python3 -m src.main --jobs weekly
```

Dieses automatische Weekly wird aus den vorhandenen Daily-Videos des rollierenden Sieben-Tage-Fensters erstellt.

Nur Monthly für alle verfügbaren Kameras:

```bash
python3 -m src.main --jobs monthly
```

Nur Yearly für alle verfügbaren Kameras:

```bash
python3 -m src.main --jobs yearly
```

### Beliebige Job-Kombination

```bash
python3 -m src.main --jobs daily monthly
```

oder:

```bash
python3 -m src.main --jobs weekly yearly
```

Die Reihenfolge der Argumente ändert die Workflow-Reihenfolge nicht.

Beispiel:

```bash
python3 -m src.main --jobs yearly daily
```

wird intern trotzdem ausgeführt als:

```text
Daily
→ Yearly
```

Doppelt angegebene Jobs werden nicht doppelt ausgeführt.

### Historische Job-Läufe

`--target-date` setzt das Zieldatum bzw. Enddatum der ausgewählten Jobs. Historische Ausgaben werden unter `videos/<camera>/manual-runs/<job>/` gespeichert und lösen keine automatische Retention aus.

Historisches Daily für alle verfügbaren Kameras:

```bash
python3 -m src.main \
	--jobs daily \
	--target-date 2026-09-15
```

Historisches Daily für ausgewählte Kameras:

```bash
python3 -m src.main \
	--jobs daily \
	--target-date 2026-09-15 \
	--cameras Scheunenviertel Nordufer_wide
```

Historisches Weekly für genau eine Kamera:

```bash
python3 -m src.main \
	--jobs weekly \
	--target-date 2026-09-15 \
	--cameras Scheunenviertel
```

Das Weekly deckt `2026-09-09` bis `2026-09-15` ab, wird direkt aus Originalbildern erstellt und nur erzeugt, wenn alle sieben Tage abgedeckt sind.

Historisches Monthly für alle verfügbaren Kameras:

```bash
python3 -m src.main \
	--jobs monthly \
	--target-date 2026-09-15
```

Das Monthly deckt `2026-08-17` bis `2026-09-15` ab.

Historisches Monthly für eine bestimmte Kamera:

```bash
python3 -m src.main \
	--jobs monthly \
	--target-date 2026-09-15 \
	--cameras Scheunenviertel
```

Historisches Yearly für alle verfügbaren Kameras:

```bash
python3 -m src.main \
	--jobs yearly \
	--target-date 2026-09-15
```

Das Yearly deckt `2025-09-16` bis `2026-09-15` ab.

Historisches Yearly für ausgewählte Kameras:

```bash
python3 -m src.main \
	--jobs yearly \
	--target-date 2026-09-15 \
	--cameras Scheunenviertel Nordufer_wide
```

Mehrere historische Jobs können gemeinsam ausgeführt werden, solange kein historisches Weekly enthalten ist:

```bash
python3 -m src.main \
	--jobs daily monthly \
	--target-date 2026-09-15 \
	--cameras Scheunenviertel
```

Bedeutung:

```text
Daily
→ 2026-09-15

Monthly
→ 2026-08-17 bis 2026-09-15
```

`--target-date` ist nur gemeinsam mit `--jobs` gültig.

### Zeitfenster für historisches Monthly und Yearly

Standardmäßig wählen Monthly und Yearly Bilder aus `interval_window` in `config/config.json`
(12:00 ± 90 Minuten). Für historische Läufe lässt sich das Fenster verschieben:

```bash
python3 -m src.main \
	--jobs yearly \
	--target-date 2025-12-31 \
	--cameras Scheunenviertel \
	--window-time 18:30 \
	--window-tolerance-minutes 60
```

- `--window-time HH:MM` setzt die Mitte des täglichen Fensters.
- `--window-time sunset` verwendet den Sonnenuntergang des jeweiligen Tages (berechnet aus
  `location` mit `astral`). Das Fenster wandert damit mit der Jahreszeit.
- `--window-tolerance-minutes N` setzt die Minuten vor und nach der Mitte (mindestens 1).
- Fehlt eines der beiden Flags, gilt der Wert aus `interval_window`.
- Yearly wählt die fünf Frames pro Tag nach Abstand zu derselben Fenstermitte aus.
- Ein Fenster, das über Mitternacht reichen würde, wird vor dem Start abgelehnt.
- Die Ausgabe erhält das Fenster im Dateinamen, damit sie das 12:00-Video nicht überschreibt:
  `<camera>_<zieldatum>_1830-60min.mp4` bzw. `<camera>_<zieldatum>_sunset-60min.mp4`.

Die Flags gelten nur für historische Läufe (`--target-date`) mit `monthly` und/oder `yearly`.

### Kurzform für historisches Daily

`--date` ist ein rückwärtskompatibler Alias für `--jobs daily --target-date`. Ohne Kameraauswahl verarbeitet er alle verfügbaren Kameras:

```bash
python3 -m src.main --date 2026-08-15
```

Optional können bestimmte Kameras gewählt werden:

```bash
python3 -m src.main \
	--date 2026-08-15 \
	--cameras Scheunenviertel Nordufer_wide
```

`--cameras` ist gemeinsam mit `--date` oder `--target-date` gültig. Historische Daily-,
Monthly- und Yearly-Läufe können eine oder mehrere Kameras verarbeiten. Ohne `--cameras`
verarbeiten sie alle erkannten und nicht global ignorierten Kameras. Ein historisches Weekly
benötigt genau eine Kamera.

Angeforderte Kameras müssen unter `/mnt/cameras` vorhanden sein und dürfen nicht über
`ignored_cameras` ausgeschlossen sein. Ist mindestens eine angeforderte Kamera nicht verfügbar,
wird der vollständige Aufruf vor dem ersten Job abgebrochen.

Nicht gültig sind unter anderem:

```text
--date + --jobs
--date + --target-date
--target-date ohne --jobs
historisches Weekly ohne genau eine Kamera
historisches Weekly gemeinsam mit einem weiteren Job
--cameras ohne --date oder --target-date
--daylight-buffer-minutes mit monthly oder yearly
--window-time / --window-tolerance-minutes ohne --target-date
--window-time / --window-tolerance-minutes mit daily oder weekly
--blur-people außerhalb eines historischen Daily
```

### Personen verpixeln (Test)

`--blur-people` erkennt Personen in den Bildern eines historischen Daily und verpixelt sie vor
dem Encoding. Die Funktion ist ein Test und nur mit `--date` oder `--jobs daily --target-date`
erlaubt:

```bash
python3 -m src.main \
	--date 2026-06-28 \
	--cameras SLSV \
	--blur-people
```

- Das Video heißt dann zum Beispiel
  `videos/SLSV/manual-runs/daily/SLSV_2026-06-28_90min_blur.mp4`, damit es nie mit einem
  unbearbeiteten Video verwechselt wird.
- Bearbeitet werden nur die Kopien unter `temp/`, die Originale bleiben unverändert.
- **Fail closed:** Bei jedem Zweifel der Erkennung bricht der Lauf ab und es entsteht kein
  Video. Ein ungeprüftes Bild wird nie verwendet.
- Ergebnisse der Erkennung werden in `state/privacy/<Kamera>.jsonl` zwischengespeichert; ein
  erneuter Lauf prüft nur neue oder geänderte Bilder.
- Die Erkennung dauert auf dem Pi ca. 7,5–10 Sekunden pro Bild.

Noch nicht abgedeckt: automatische Läufe, Weekly, Monthly, Yearly und die Weboberfläche.

Installation des Modells, alle Einstellungen, Cache, Detektor-Protokoll und Fehlersuche:
[docs/verpixelung.md](docs/verpixelung.md).

---

## Speicherfilter

Die Jobs filtern leere und doppelte Bilder nur für das jeweilige Video; auf dem Kamera-Storage bleiben sie liegen. Der Speicherfilter geht deshalb einmal durch den kompletten Ordner einer Kamera und schreibt einen Bericht darüber, welche Dateien gelöscht werden können.

Der Speicherfilter **löscht nichts**. `/mnt/cameras` ist ohnehin read-only eingehängt. Das eigentliche Löschen erfolgt später separat anhand des Berichts.

### Aufruf

```bash
.venv/bin/python3 -m src.storage_filter --cameras Uferstrasse
.venv/bin/python3 -m src.storage_filter --cameras Uferstrasse Nordufer_wide
.venv/bin/python3 -m src.storage_filter --all-cameras
```

- `--cameras` prüft genau die genannten Kameras, auch solche aus `ignored_cameras`.
- `--all-cameras` prüft alle Kameras außer denen aus `ignored_cameras`.
- Eine der beiden Optionen ist Pflicht.

Für einen langen Lauf, der auch nach dem Schließen von VS Code oder der SSH-Verbindung weiterläuft:

```bash
scripts/storage-filter-all                                 # alle Kameras außer ignored_cameras
scripts/storage-filter-all --cameras Uferstrasse SVG       # beliebige Argumente wie oben
```

Das Skript startet den Speicherfilter per `nohup` im Hintergrund und gibt die PID sowie den Pfad der Konsolenausgabe aus (`logs/filter/run_YYYY-MM-DD_HHMMSS.out`). Fortschritt verfolgen mit `tail -f` auf diese Datei, abbrechen mit `kill -TERM -- -<PID>` (beendet auch laufende SSH-Aufrufe; `kill -INT` wirkt bei Hintergrundprozessen nicht). Der Bericht der gerade laufenden Kamera wird dann nicht geschrieben; fertige Kameras behalten ihren. Die `.out`-Dateien fallen nicht unter die Log-Retention und müssen bei Bedarf von Hand gelöscht werden.

Der Speicherfilter nimmt denselben Lock wie Cron und die Weboberfläche (`state/zeitraffer-run.lock`). Läuft bereits ein Timelapse-Lauf, bricht er sofort ab. Er schreibt kein `state/run-in-progress` und wird nach einem Neustart nicht automatisch fortgesetzt.

Fehler einer Kamera (`OSError`, `TimeoutError`) werden protokolliert; die übrigen Kameras laufen weiter. Der Exit-Code ist dann `1`.

### Ablauf

1. **Liste per SSH:** Ein einziges `ls -l` auf der Storage Box liefert alle Dateinamen mit Größe (Uferstrasse, ca. 189.000 Dateien: rund 3,5 Sekunden). Benutzer und Host kommen aus dem laufenden SSHFS-Mount (`/proc/mounts`), Port und Schlüssel aus `~/.ssh/config` (siehe unten). Ohne aktiven Mount bricht der Speicherfilter ab.
2. **Leere Dateien:** Alle JPGs mit 0 Byte laut Liste.
3. **Duplikate pro Tag:** Nur Dateien, die am selben Aufnahmetag (laut Dateiname) dieselbe Größe haben, werden verglichen. Die SHA-256-Hashes berechnet die Storage Box selbst (`sha256sum`, 1.000 Dateien pro Aufruf, 4 Aufrufe parallel); über das Netz kommen nur die Hashes, nicht die Bilder. Behalten wird die erste Datei des Tages in Dateinamen-Reihenfolge; gemeldet werden alle späteren Kopien.

Der Speicherfilter liest keine Bilddateien über `/mnt/cameras`; der Mount wird nur benötigt, um Benutzer und Host der Storage Box zu ermitteln.

Port und Schlüssel stehen bewusst nicht im Code, sondern in `~/.ssh/config` des Kontos `<benutzer>` (gleiche Werte wie `REMOTE_PORT` und `REMOTE_SSH_KEY` in `/etc/timelapse/mount.env`). Einmalig anlegen:

```text
Host <storage-host>
	Port <port>
	IdentityFile <schlüsselpfad>
	IdentitiesOnly yes
```

Danach `chmod 600 ~/.ssh/config`. Fehlt der Eintrag, bricht der Speicherfilter mit einem SSH-Fehler ab. Die Datei ist Teil des Backups und wird bei einer Neuinstallation wiederhergestellt. Fehlt beim Hashen eine Datei oder ist sie nicht lesbar, schlägt die Kamera fehl, statt die Datei als eindeutig zu behandeln.

Nicht geprüft werden:

- Bilder vom heutigen Tag – sie können noch im Upload sein und kurzzeitig 0 Byte haben.
- Dateien, deren Name keinem bekannten Format entspricht (Formate werden nie geraten).
- Dateien ohne `.jpg`-Endung, Unterordner und Symlinks.
- Identische Bilder an verschiedenen Tagen: Ein kameraweiter Vergleich müsste bei Uferstrasse rund 92 % aller Dateien über SSHFS lesen und dauert pro Kamera Stunden.

### Laufzeit und Fortschritt

Warum alles auf der Storage Box läuft (gemessen am 2026-09-28):

| Schritt | über SSHFS | auf der Storage Box |
|---|---|---|
| Liste + Größen, Uferstrasse (ca. 189.000 Dateien) | 2 bis ca. 45 Minuten, je nach Cache | ca. 3,5 Sekunden |
| Hashen pro Datei | ca. 43 ms | ca. 10 ms, mit 4 parallelen Aufrufen ca. 4 ms |

Wie lange ein Lauf dauert, hängt vor allem davon ab, wie viele Dateien am selben Tag gleich groß sind:

- Uferstrasse: ca. 1.800 von 189.000 Dateien (0,9 %).
- Segelsport-Club-Suedenmeer: ca. 180.000 von 244.000 Dateien (74 %). Die Bilder sind sehr klein (meist 13–22 KB), und an manchen Tagen hat die Kamera den ganzen Tag dasselbe eingefrorene Bild geliefert. Erwartete Laufzeit: ca. 12 Minuten.

Damit ein langer Lauf nicht wie hängend aussieht, meldet der Speicherfilter:

```text
Storage filter: camera <camera> | listed=… | empty=… | checking … files for duplicates
Storage filter: camera <camera> | checked …/… files for duplicates      (alle 30 Sekunden)
```

Den Speicherfilter trotzdem nicht kurz vor dem nächtlichen Lauf um 02:00 Uhr starten: Er hält währenddessen den gemeinsamen Lock.

### Bericht

Pro Kamera und Lauf entsteht eine Datei:

```text
reports/storage-filter/<camera>_YYYY-MM-DD_HHMMSS.csv
```

Format: CSV mit `;` als Trennzeichen und UTF-8 mit BOM, damit ein deutsches Excel oder LibreOffice die Datei per Doppelklick korrekt öffnet. Jede Zeile ist ein Löschkandidat:

```text
camera;path;reason
Cam;/mnt/cameras/Cam/cam_250101_120000.jpg;empty
Cam;/mnt/cameras/Cam/cam_250101_121500.jpg;duplicate
```

Der Bericht wird zuerst als temporäre Datei geschrieben und erst danach umbenannt; ein abgebrochener Lauf hinterlässt keine halbe Liste. `reports/` wird mit `770` angelegt und ist für `www-data` nicht lesbar.

Die Anzahl gefundener Dateien pro Kamera steht in `logs/filter/YYYY-MM-DD.log`.

---

## Yearly-Backfill für Kalenderjahre

`scripts/yearly-backfill.py` erstellt Yearly-Videos für ganze Kalenderjahre (1. Januar bis
31. Dezember, im laufenden Jahr bis gestern). Bildsuche, 0-Byte-Filter, Zeitfenster
(`interval_window`) und die Auswahl von bis zu fünf Bildern pro Tag sind dieselben wie beim
Yearly-Job, aber **ohne** Mindestabdeckung: Jede Kamera wird gerendert, fehlende Tage werden nur
protokolliert.

```bash
.venv/bin/python3 scripts/yearly-backfill.py
.venv/bin/python3 scripts/yearly-backfill.py --years 2024 2025 --cameras BSV-Steinhude
.venv/bin/python3 scripts/yearly-backfill.py --years 2025 --force
```

- `--years`: Kalenderjahre (Standard: 2026)
- `--cameras`: nur diese Kameras (Standard: alle außer `ignored_cameras`)
- `--force`: vorhandene Videos neu erstellen statt überspringen
- `--blur-people`: Personen und Kennzeichen verpixeln wie bei historischen Dailys (Einstellungen
  aus `privacy` in `config.json`, siehe [docs/verpixelung.md](docs/verpixelung.md)). Das Video
  bekommt die Endung `_blur`; das unverpixelte bleibt erhalten. Die Erkennung dauert ca. 8–9
  Sekunden pro Bild, ein ganzes Jahr (rund 1.640–1.830 Bilder) also ca. 4 Stunden. Weil das
  Skript den Lock belegt, so starten, dass es vor 02:00 fertig ist, sonst fällt der nächtliche
  Lauf aus.

Ausgabe wie bei historischen Läufen unter `videos/<camera>/manual-runs/yearly/<camera>_<Enddatum>.mp4`
mit `yearly_framerate`; Enddatum ist der 31. Dezember, im laufenden Jahr der gestrige Tag. Pro Lauf entsteht ein Bericht
`reports/yearly-coverage/backfill_YYYY-MM-DD_HHMMSS.csv` (`;`-getrennt, Spalten `camera`, `year`,
`covered`, `total`, `missing_ranges`, `status`, `video`), der nach jeder Zeile geschrieben wird.
Das Skript belegt denselben Lock wie Cron und Weboberfläche und wird nicht von pytest abgedeckt.

---

## Highlights-Flagger

Prüft jede Nacht die Daily-Bilder der Kameras aus `flagger.cameras` auf Tiere und Flugobjekte
(Vögel, Flugzeuge, Drachen) und legt Treffer als unveränderte Kopien mit einer `manifest.json`
unter `videos/<Kamera>/highlights/<JJJJ-MM-TT>/` ab, für die Highlights-Seite der
Weboberfläche. Liest nur, nimmt die gemeinsame Sperre `state/zeitraffer-run.lock` und löscht
Berichte nach `flagger.retention_days` (30) Tagen. Die Bilder sind nicht verpixelt.

**Stand:** gebaut und getestet, noch ohne Cron-Eintrag und ohne Kameras.

```bash
.venv/bin/python3 -m src.flagger.run                                   # Kameras aus der Config, Tag gestern
.venv/bin/python3 -m src.flagger.run --cameras Strandallee --target-date 2026-10-20
.venv/bin/python3 -m src.flagger.run --images <ordner> --out <ziel>    # Testmodus für einen Bildordner
```

Gruppen, Schwellen, Manifest-Felder, Exit-Codes und Messwerte: [docs/flagger.md](docs/flagger.md).

---

## Neuinstallation des Raspberry Pi

Bei einer Neuinstallation des Betriebssystems gehen alle Dateien verloren, die nicht im Git-Repository liegen. Zwei Skripte übernehmen Sicherung und Wiederherstellung:

| Skript | Läuft auf | Aufgabe |
|---|---|---|
| `backup-from-mac.sh` | dem Mac, **vor** der Neuinstallation | holt alle nicht versionierten Dateien vom Pi in einen lokalen Backup-Ordner |
| `migrate.sh` | dem Pi, **nach** der Neuinstallation | installiert Pakete, klont das Repository, stellt das Backup wieder her und richtet alle Dienste ein |

Die Videos sind nicht Teil von `migrate.sh`, sondern werden nach der Migration von Hand zurückkopiert.

### Was gesichert wird

| Datei auf dem Pi | Im Backup | Wird wiederhergestellt nach |
|---|---|---|
| Ordner `~/.ssh` (Schlüssel, `config`, `known_hosts`) | `pi-backup.tar.gz` | `~/.ssh/` (`600`, `.pub`-Dateien `644`); `known_hosts` wird zusammengeführt, `authorized_keys` nicht wiederhergestellt |
| `/etc/timelapse/mount.env` | `pi-backup.tar.gz` | `root:root 600` |
| `/etc/sudoers.d/timelapse-web` | `pi-backup.tar.gz` | `root:root 440`, nur nach erfolgreicher `visudo`-Prüfung |
| `/etc/apache2/.htpasswd` | `pi-backup.tar.gz` | `root:www-data 640` |
| `/etc/apache2/sites-available/zeitraffer.conf` | `pi-backup.tar.gz` | `root:root 644` |
| Crontab des Login-Benutzers | `pi-crontab.txt` | Crontab des Login-Benutzers |
| `config/config.json` | `config.json` | `config/config.json` (überschreibt die Git-Version) |
| `videos/` | `videos/` | von Hand, siehe Schritt 6 |

`pi-backup.tar.gz` enthält einen privaten SSH-Schlüssel, die Zugangsdaten des Kamera-Storage und einen Passwort-Hash. Der Backup-Ordner auf dem Mac wird deshalb mit Modus `700` angelegt und darf nicht in Cloud-Sync-Ordner oder ins Repository gelangen. Der Standardordner `~/pi-migration-backup` liegt bewusst außerhalb von `Documents` und `Desktop`: Ist in den macOS-Einstellungen die iCloud-Option „Schreibtisch & Dokumente“ aktiv, würde alles dort in die iCloud hochgeladen. Wer über `DEST` einen anderen Ordner wählt, verwendet in den folgenden Befehlen denselben Pfad.

Bewusst nicht gesichert:

- `logs/`, `temp/` und `state/` – reine Laufzeitdaten
- die SSH-Hostschlüssel des Pi – der neu installierte Pi erhält neue; siehe Schritt 3
- WLAN-Konfiguration – der Pi läuft ausschließlich über Ethernet, WLAN wird deaktiviert

### Voraussetzungen

- Mac mit Zugriff auf den Pi per SSH (Passwort-Login als Login-Benutzer des Pi)
- ein Checkout dieses Repositorys auf dem Mac, damit `migrate.sh` von dort auf den Pi kopiert werden kann
- das `sudo`-Passwort dieses Benutzers auf dem Pi
- die offiziellen Host-Key-Fingerprints der Storage Box beim Anbieter (nur nötig, wenn das Backup noch kein `known_hosts` enthält)
- Netzwerkkabel am Pi: `migrate.sh` schaltet WLAN ab

### Schritt 1: Backup auf dem Mac erstellen

Im Repository-Checkout auf dem Mac einmalig die lokale Einstellungsdatei anlegen und Hostname bzw. IP und Benutzer des Pi eintragen. `backup.env` ist per `.gitignore` ausgeschlossen, damit weder IP noch Benutzername oder lokale Pfade im öffentlichen Repository landen:

```bash
cp backup.env.example backup.env
nano backup.env
./backup-from-mac.sh
```

In den folgenden Befehlen stehen `<pi-host>` und `<pi-user>` für die Werte aus `backup.env`.

Das Skript fragt einmal nach dem SSH-Passwort und einmal nach dem `sudo`-Passwort auf dem Pi. Anschließend:

1. packt es die Geheimnisse auf dem Pi mit `umask 077` nach `/tmp/pi-backup.tar.gz`, lädt das Archiv herunter und löscht es auf dem Pi wieder, auch wenn ein späterer Schritt fehlschlägt,
2. speichert die Crontab und `config.json`,
3. synchronisiert `videos/` per `rsync`,
4. listet den Inhalt des Archivs auf und gibt die Befehle für die Wiederherstellung aus.

Optionen in `backup.env` oder als Umgebungsvariable (die Umgebungsvariable hat Vorrang, z. B. `PI_HOST=<pi-ip> ./backup-from-mac.sh`, falls der `.local`-Name nicht aufgelöst wird):

| Variable | Standard | Bedeutung |
|---|---|---|
| `PI_HOST` | – (Pflicht) | Hostname oder IP des Pi |
| `PI_USER` | – (Pflicht) | Login-Benutzer auf dem Pi |
| `DEST` | `~/pi-migration-backup` | Backup-Ordner auf dem Mac |
| `SKIP_VIDEOS` | `0` | `1` überspringt die Videos |

`backup.env` wird gelesen, nicht ausgeführt: nur `NAME=Wert`-Zeilen mit diesen vier Namen zählen.

Danach prüfen, ob der Backup-Ordner vollständig ist:

```bash
ls -la ~/pi-migration-backup
# erwartet: pi-backup.tar.gz, pi-crontab.txt, config.json, videos/
tar tzf ~/pi-migration-backup/pi-backup.tar.gz
# erwartet: der Ordner home/<pi-user>/.ssh/ mit Schlüssel, config und known_hosts,
# außerdem mount.env, sudoers, .htpasswd und die Apache-Site
```

Erst weitermachen, wenn das Backup vollständig ist.

### Schritt 2: Betriebssystem neu installieren

Mit dem Raspberry Pi Imager ein 64-Bit-Raspberry-Pi-OS auf Basis von Debian 13 (trixie) schreiben und in den erweiterten Einstellungen festlegen:

- Hostname: derselbe wie vor der Neuinstallation (`PI_HOST` in `backup.env`)
- Benutzer: derselbe wie vor der Neuinstallation (`PI_USER`) – der Name ist im systemd-Service, in den Web-Wrappern, in Cron, sudoers und Apache hinterlegt, und das Backup enthält seine Pfade
- SSH aktivieren, Anmeldung per Passwort
- kein WLAN nötig

Den Pi per Netzwerkkabel anschließen und starten.

### Schritt 3: Alten Host-Key auf dem Mac entfernen

Der neu installierte Pi hat neue SSH-Hostschlüssel. Ohne diesen Schritt bricht SSH mit `REMOTE HOST IDENTIFICATION HAS CHANGED` ab:

```bash
ssh-keygen -R <pi-host>
ssh-keygen -R <pi-ip>          # zusätzlich die IP des Pi
ssh <pi-user>@<pi-host>        # neuen Fingerprint mit "yes" bestätigen
```

### Schritt 4: Backup und Installer auf den Pi kopieren

Im Repository-Checkout auf dem Mac:

```bash
scp ~/pi-migration-backup/pi-backup.tar.gz \
    ~/pi-migration-backup/pi-crontab.txt \
    ~/pi-migration-backup/config.json \
    migrate.sh \
    <pi-user>@<pi-host>:~/
```

`migrate.sh` erwartet die drei Backup-Dateien direkt im Home-Verzeichnis. Benutzer und Pfade liest es aus der laufenden Sitzung; im Skript selbst steht nichts Pi-Spezifisches.

### Schritt 5: Migration auf dem Pi ausführen

Per SSH über Ethernet auf dem Pi:

```bash
chmod +x ~/migrate.sh
~/migrate.sh
```

Das Skript bricht beim ersten Fehler ab (`set -euo pipefail`). Die Schritte laufen in dieser Reihenfolge:

| Schritt | Was passiert |
|---|---|
| `preflight` | bricht ab, wenn als `root` gestartet; prüft die Backup-Dateien und `sudo`-Zugriff (Passwortabfrage) |
| `packages` | installiert Git, Python, FFmpeg, SSHFS, Apache und PHP; aktiviert `user_allow_other` in `/etc/fuse.conf` |
| `clone` | klont das Repository nach `~/timelapse`; bricht ab, wenn dort bereits ein fremder oder nicht leerer Ordner liegt |
| `venv` | legt `.venv` an und installiert `requirements.txt` |
| `restore_backup` | entpackt das Backup in einen temporären Ordner, prüft die sudoers-Datei mit `visudo` und auf beide Regeln, installiert alle Dateien mit festen Eigentümern und Rechten, übernimmt `config.json` und die Crontab |
| `known_hosts` | überspringt, wenn der Storage-Box-Host bereits bekannt ist; sonst werden die Fingerprints angezeigt und müssen mit `y` bestätigt werden |
| `sshfs_mount` | prüft, dass `User=` im systemd-Service der aktuelle Benutzer ist; installiert Preflight-Skript und systemd-Service und mountet `/mnt/cameras` |
| `apache` | aktiviert `zeitraffer.conf`, deaktiviert die Standardseite, führt `apache2ctl configtest` aus und lädt Apache neu |
| `web_bridge` | installiert Trigger, Lösch-Wrapper, Worker und Status-Skript unter `/usr/local` |
| `permissions` | setzt die Dateirechte aus [Dateirechte für `www-data`](#dateirechte-für-www-data) |
| `disable_wifi` | schaltet WLAN per `nmcli` ab und trägt `dtoverlay=disable-wifi` in `/boot/firmware/config.txt` ein; wird übersprungen, wenn die SSH-Sitzung selbst über WLAN läuft |
| `verify` | führt die Testsuite aus und prüft Mount, Crontab, HTTP-Status `401`, Lese- und Sperrrechte von `www-data`, beide sudoers-Regeln und den WLAN-Status |

Interaktive Abfragen während des Laufs:

- `sudo`-Passwort in `preflight`
- nur bei älteren Backups ohne `known_hosts`: Bestätigung der Storage-Box-Fingerprints – vorher mit den Angaben des Anbieters vergleichen und bei Abweichung mit `n` abbrechen
- `git clone` fragt nach Zugangsdaten, falls das Repository nicht öffentlich erreichbar ist

Nach einem Abbruch die Ursache beheben und `~/migrate.sh` einfach erneut starten. Alle Schritte sind wiederholbar: `clone` überspringt einen bereits vorhandenen Checkout desselben Repositorys, `known_hosts` einen bereits bekannten Host, und die übrigen Schritte überschreiben ihre Zieldateien mit denselben Inhalten.

Einzelne Schritte lassen sich auch gezielt ausführen:

```bash
~/migrate.sh permissions verify
~/migrate.sh apache
~/migrate.sh disable_wifi
```

Optionen über Umgebungsvariablen:

| Variable | Standard | Bedeutung |
|---|---|---|
| `REPO_URL` | `https://github.com/funktion5/Zeitraffer.git` | Quelle für `git clone` |
| `PROJECT_ROOT` | `~/timelapse` | Zielordner |
| `BACKUP_TAR` | `~/pi-backup.tar.gz` | Geheimnis-Archiv |
| `BACKUP_CRONTAB` | `~/pi-crontab.txt` | Crontab-Sicherung |
| `BACKUP_CONFIG` | `~/config.json` | optionale `config.json`; fehlt sie, bleibt die Git-Version |
| `DISABLE_WIFI` | `1` | `0` lässt WLAN unverändert |

Am Ende des Laufs die Ausgabe von `verify` durchsehen: Jede Zeile mit `WARNING` muss geklärt werden, bevor der Pi als fertig gilt.

### Schritt 6: Videos zurückkopieren

Vom Mac aus:

```bash
rsync -a --progress ~/pi-migration-backup/videos/ \
    <pi-user>@<pi-host>:timelapse/videos/
```

`rsync -a` übernimmt die Dateirechte aus dem Backup. Deshalb danach auf dem Pi die Rechte korrigieren und prüfen:

```bash
~/migrate.sh permissions verify
```

### Schritt 7: Abschluss und Aufräumen

1. Neustart, damit `dtoverlay=disable-wifi` greift, und danach prüfen:

   ```bash
   sudo reboot
   # nach dem Neustart:
   nmcli radio wifi                        # erwartet: disabled
   mountpoint /mnt/cameras                 # erwartet: is a mountpoint
   ```

2. Weboberfläche im Browser unter `http://<pi-host>/` oder `http://<pi-ip>/` öffnen, anmelden und prüfen:
   - die Kameraliste erscheint, ohne die Kameras aus `ignored_cameras`
   - ein historisches Video lässt sich abspielen und herunterladen
   - ein historischer Daily-Lauf läuft durch und öffnet den Abschlussdialog
   - ein Testvideo lässt sich löschen

3. Die Backup-Dateien auf dem Pi löschen. Sie werden nach der Migration nicht mehr gebraucht und enthalten Geheimnisse:

   ```bash
   rm ~/pi-backup.tar.gz ~/pi-crontab.txt ~/config.json
   ```

   Das Backup auf dem Mac bleibt als Sicherung erhalten.

4. Der erste nächtliche Lauf um 02:00 Uhr erzeugt die automatischen Videos. Am nächsten Tag `logs/daily/<datum>.log` prüfen.

### Migration ohne Neuinstallation testen

Nach Änderungen an `migrate.sh` oder `backup-from-mac.sh` lassen sich die Skripte auf dem laufenden Pi prüfen, ohne ihn neu aufzusetzen. Fast alle Schritte schreiben dort dieselben Inhalte, die bereits vorhanden sind; ein erfolgreicher Test endet deshalb mit einem unveränderten System. Nicht ausführen gegen 02:00 Uhr oder während ein Web-Job läuft.

Der Schritt `packages` wird dabei ausgelassen: `apt-get install` aktualisiert die genannten Pakete, wenn neuere Versionen verfügbar sind, und wäre damit eine echte Änderung am System.

1. Frisches Backup erstellen (siehe Schritt 1) und vom Mac auf den Pi kopieren:

   ```bash
   scp ~/pi-migration-backup/{pi-backup.tar.gz,pi-crontab.txt,config.json} <pi-user>@<pi-host>:~/
   ```

2. Auf dem Pi einen Rollback-Stand und Prüfsummen aller betroffenen Dateien anlegen:

   ```bash
   umask 077
   sudo tar czf ~/pre-test-rollback.tar.gz /etc/sudoers.d/timelapse-web /etc/timelapse/mount.env \
     /etc/apache2/.htpasswd /etc/apache2/sites-available/zeitraffer.conf ~/.ssh \
     /usr/local/sbin/timelapse-web-* /usr/local/libexec/timelapse-web-* /usr/local/sbin/cameras-sshfs-preflight \
     /etc/systemd/system/cameras-sshfs.service /boot/firmware/config.txt ~/timelapse/config/config.json
   crontab -l > ~/pre-test-crontab.txt
   sudo sha256sum /etc/sudoers.d/timelapse-web /etc/timelapse/mount.env /etc/apache2/.htpasswd \
     /etc/apache2/sites-available/zeitraffer.conf ~/.ssh/* /usr/local/sbin/timelapse-web-* \
     /usr/local/libexec/timelapse-web-* ~/timelapse/config/config.json > ~/pre-test.sha256
   ```

3. Alle Schritte außer `packages` ausführen:

   ```bash
   ~/timelapse/migrate.sh preflight clone venv restore_backup known_hosts sshfs_mount apache web_bridge permissions disable_wifi verify
   ```

   Erwartet: `clone` und `known_hosts` melden, dass bereits alles vorhanden ist, und `verify` gibt keine Zeile mit `WARNING` aus. Die Apache-Meldung `AH00558 ... fully qualified domain name` ist harmlos.

4. Vorher und nachher vergleichen:

   ```bash
   sudo sha256sum -c ~/pre-test.sha256          # erwartet: jede Zeile OK
   crontab -l | diff ~/pre-test-crontab.txt -   # erwartet: keine Ausgabe
   ```

Weicht etwas ab, stellt dieser Befehl den Zustand vor dem Test wieder her:

```bash
sudo tar xzf ~/pre-test-rollback.tar.gz -C / && crontab ~/pre-test-crontab.txt && sudo systemctl reload apache2
```

Zum Schluss die Test- und Backup-Dateien auf dem Pi löschen, da sie Geheimnisse enthalten. Das Original bleibt auf dem Mac:

```bash
rm ~/pre-test-crontab.txt ~/pre-test.sha256 ~/pi-backup.tar.gz ~/pi-crontab.txt ~/config.json
sudo rm ~/pre-test-rollback.tar.gz
```

Nicht abgedeckt sind der Schritt `packages` und ein Lauf auf einem wirklich leeren System; das lässt sich nur mit einer zweiten SD-Karte oder einem zweiten Pi prüfen.

### Fehlerbehebung

| Symptom | Ursache und Lösung |
|---|---|
| Browser zeigt `403 Forbidden` | `www-data` kommt nicht ins Projekt: `~/migrate.sh permissions verify`; Details in `/var/log/apache2/zeitraffer-error.log` |
| Video-Bibliothek leer oder Videos laden nicht | Videos nach dem Kopieren nicht lesbar: `~/migrate.sh permissions` |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` auf dem Mac | Schritt 3 ausführen |
| `Backed-up sudoers file does not parse` oder `lacks the ... rule` | sudoers-Datei im Backup beschädigt oder unvollständig; aus dem Backup wurde noch nichts installiert. Archiv reparieren (siehe unten) und `~/migrate.sh` erneut ausführen |
| `Host key not confirmed` | Fingerprints stimmten nicht oder wurden abgelehnt. Mit dem Anbieter klären, dann `~/migrate.sh known_hosts sshfs_mount` |
| `cameras-sshfs is not running` | `systemctl status cameras-sshfs.service` und `journalctl -u cameras-sshfs.service`; häufig fehlt der Host-Key oder `mount.env` ist leer |
| `skipping WiFi disable` | Sitzung lief über WLAN. Per Kabel neu verbinden und `~/migrate.sh disable_wifi` |
| Web-Job startet nicht oder Löschen schlägt fehl | `sudo -l -U www-data` muss beide Wrapper zeigen; sonst sudoers wie unter [Wrapper installieren](#wrapper-installieren) prüfen |
| `is already a git repo, but its origin ... doesn't match` | unter `~/timelapse` liegt ein anderes Repository; verschieben oder `REPO_URL` korrigieren |

sudoers-Datei im Backup-Archiv reparieren (auf dem Pi):

```bash
mkdir ~/backup-fix
sudo tar xzf ~/pi-backup.tar.gz -C ~/backup-fix
sudo nano ~/backup-fix/etc/sudoers.d/timelapse-web   # beide Regeln aus „Wrapper installieren“
sudo visudo -cf ~/backup-fix/etc/sudoers.d/timelapse-web
sudo tar czf ~/pi-backup.tar.gz -C ~/backup-fix .
sudo chown "$(id -un):$(id -gn)" ~/pi-backup.tar.gz
sudo rm -rf ~/backup-fix
~/migrate.sh
```

---

## Aktueller Stand

Implementiert sind:

- Daily-Timelapses
- Weekly-Timelapses
- Monthly-Timelapses
- Yearly-Timelapses
- freie Auswahl automatischer Jobs über `--jobs`
- historische automatische Läufe über `--target-date`
- konfigurierbare Framerates
- globale Kamera-Ausschlussliste
- daylight-basierte Bildauswahl
- mehrere historische Kamera-Dateinamensformate
- isolierte Worker mit Stall-Timeout
- 0-Byte-Validierung
- SHA-256-basierte Erkennung byte-identischer Quelldaten
- Duplicate-Filterung für Daily inklusive Vortagsreferenz, historische Weeklys und Monthly
- Duplicate-aware Yearly-Auswahl
- sichere temporäre Videoerstellung
- Log-Retention
- FFmpeg- und System-Performance-Logging
- protokollierte FFmpeg-Fehlerausgabe
- Run-IDs und Ergebniszusammenfassungen pro Job
- Config-Tests für Pfad, JSON-Syntax und Struktur
- Ruff für Linting und Formatierung
- lokale PHP-Weboberfläche für historische Daily-, Weekly-, Monthly- und Yearly-Läufe
- asynchrone Web-Jobs mit Statusabfrage und Abschlussdialog
- Backup- und Migrationsskripte für eine Neuinstallation des Raspberry Pi
- Speicherfilter: Bericht über leere und am selben Tag doppelte Bilder pro Kamera (löscht nichts)
- konfigurierbares Tagesfenster für Monthly/Yearly (`interval_window`), historisch auch per Sonnenuntergang, in CLI und Weboberfläche
- Mindestabdeckung für Monthly/Yearly (`min_coverage_days`) statt lückenloser Abdeckung
- Yearly-Backfill für ganze Kalenderjahre (`scripts/yearly-backfill.py`)
- GitHub Actions und lokaler Pre-Push-Hook für Ruff und pytest

Ohne Job-Auswahl läuft der automatische Workflow weiterhin in dieser Reihenfolge:

```text
Daily
→ Weekly
→ Monthly
→ Yearly
```

Mit `--jobs` kann jede beliebige Kombination dieser vier automatischen Jobs gewählt werden. Die tatsächliche Ausführungsreihenfolge bleibt immer:

```text
Daily
→ Weekly
→ Monthly
→ Yearly
```

Nicht ausgewählte Jobs werden dabei übersprungen.

`--date` ist ein rückwärtskompatibler Kurzweg für genau einen historischen Daily-Lauf. Historische Daily-, Weekly-, Monthly- und Yearly-Läufe können außerdem über `--jobs` zusammen mit `--target-date` gestartet werden.

---

## Timelapse-Typen

### Daily

- Zieldatum: standardmäßig gestern
- optional: explizites Zieldatum über `--target-date`
- Quelle: Originalbilder
- Auswahl: Sunrise-/Sunset-Fenster inklusive Buffer für den Zieltag (automatisch nach Monat aus `automatic_daylight_buffer_minutes`, historisch fest aus `daylight_buffer_minutes`); der vollständige Vortag dient als Duplicate-Referenz
- Zieltag und Vortag werden in einem gemeinsamen Verzeichnis-Scan gefunden
- der Vortag dient ausschließlich als Duplicate-Referenz und wird nicht ins Daily übernommen
- Zieltag-Frames mit byte-identischem Inhalt vom Vortag werden ausgeschlossen
- spätere byte-identische Bilder innerhalb des Zieltags werden ebenfalls ausgeschlossen
- bleibt danach kein Zieltag-Frame übrig, wird die Kamera übersprungen und ein vorhandenes Video bleibt erhalten
- Framerate: `daily_framerate`
- Retention: exaktes rollierendes 7-Tage-Fenster relativ zum Zieldatum

### Weekly

- Fenster: exakt 7 Kalendertage inklusive Enddatum
- automatischer Lauf: vorhandene Daily-Videos, Enddatum standardmäßig gestern
- fehlende automatische Dailys werden protokolliert
- der automatische Lauf benötigt mindestens ein Daily und verwendet kein älteres Backfill
- historischer Lauf: Originalbilder für genau eine Kamera und explizites `--target-date`
- historische Auswahl: Sunrise bis Sunset inklusive Buffer für jeden einzelnen Tag
- byte-identische Bilder werden aus der historischen Frame-Sequenz gefiltert
- ein historisches Weekly erfordert vollständige Bildabdeckung an allen 7 Tagen
- keine automatische Retention für historische Weeklys

### Monthly

- Fenster: rollierende 30 Tage inklusive Enddatum
- Enddatum: standardmäßig gestern oder explizites `--target-date`
- Quelle: Originalbilder
- täglich 10:30 bis 13:30 Uhr (`interval_window`, historisch per `--window-time` /
  `--window-tolerance-minutes` verschiebbar)
- verwendet alle ausgewählten Intervallbilder
- filtert byte-identische Bilder innerhalb jedes einzelnen Tages
- Mindestabdeckung: `min_coverage_days.monthly` (25 von 30 Tagen), automatisch und historisch;
  darunter wird die Kamera übersprungen. Ein Tag gilt als fehlend, wenn im gewählten Zeitfenster
  kein brauchbares Bild liegt. Fehlende Tage fehlen im Video und werden als Bereiche geloggt.
- Framerate: `monthly_framerate`

### Yearly

- Fenster: exaktes Kalenderjahr bis einschließlich Enddatum — 365 oder 366 Tage, je nachdem ob ein Schalttag (29. Februar) im Zeitraum liegt; kein fest codiertes 365-Tage-Fenster mehr
- Enddatum: standardmäßig gestern oder explizites `--target-date`
- Quelle: Originalbilder
- tägliche Kandidaten aus 10:30 bis 13:30 Uhr (`interval_window`, historisch verschiebbar)
- Zielzeit: 12:00 Uhr bzw. die Mitte des gewählten Fensters
- bis zu 5 eindeutige Frames pro Tag
- bei Duplikaten werden weitere Kandidaten nachgezogen
- Mindestabdeckung: `min_coverage_days.yearly` (300 Tage, auch im Schaltjahr), automatisch und
  historisch; darunter wird die Kamera übersprungen, bevor die Frame-Auswahl läuft. Fehlende
  Tage fehlen im Video und werden als Bereiche geloggt.
- Framerate: `yearly_framerate`

---

## Kameraerkennung

### Dynamische Kameraerkennung

Kameras werden dynamisch anhand ihrer Verzeichnisse unter

```text
/mnt/cameras
```

erkannt.

Beispiel:

```text
/mnt/cameras/
├── Alter-Winkel-Promenade/
├── BSV-Steinhude/
├── Nordufer_tele/
├── Nordufer_wide/
├── Scheunenviertel/
└── ...
```

Versteckte Verzeichnisse werden ignoriert.

Ist der globale Kamera-Storage nicht erreichbar, wird der Lauf abgebrochen. Operative Fehler einer einzelnen Kamera werden dagegen pro Kamera behandelt, sodass spätere Kameras weiterverarbeitet werden können.

### Alternative Bildquelle (NAS-Archiv)

Die Umgebungsvariable `TIMELAPSE_CAMERA_ROOT` ersetzt `/mnt/cameras` als Kamera-Wurzel. Ohne
die Variable (oder mit leerem Wert) gilt weiterhin `/mnt/cameras`; Cron und Weboberfläche
setzen sie nicht.

Damit lassen sich Kalenderjahr-Videos aus dem alten Webcam-Archiv auf dem NAS erstellen. Die
Werkzeuge dafür liegen im Ordner `nas/` und gehören nicht zum Produktionslauf. Anleitung:
[docs/nas.md](docs/nas.md).

Im Testbetrieb lässt sich das Programm auch in einem Docker-Container ausführen (Mac, später
Synology-NAS); der Pi bleibt dabei produktiv. Anleitung: [docs/docker.md](docs/docker.md).

---

## Bildvalidierung und Duplikate

0-Byte-Dateien werden vor der weiteren Verarbeitung ausgeschlossen und geloggt. Die Quelldateien bleiben unverändert.

Abgeschnittene Bilder (Upload der Kamera mittendrin abgebrochen, JPEG-Endmarke `FF D9` fehlt) werden ebenfalls ausgelassen und als Warnung geloggt. Ohne diese Prüfung würde FFmpeg den fehlenden unteren Teil mit dem vorherigen Bild füllen. Yearly prüft das schon bei der Auswahl und nimmt stattdessen das nächstgelegene vollständige Bild desselben Tages, damit der Tag seine fünf Bilder behält. Alle Jobs prüfen außerdem jede Kopie in `temp/` vor dem Encodieren; dort fällt ein abgeschnittenes Bild ersatzlos weg. Gelesen wird dafür nichts zusätzlich von der Storage Box.

Die Duplicate-Behandlung hängt vom Job ab:

- Daily scannt Zieltag und Vortag gemeinsam. Byte-identische Zieltag-Frames, deren Inhalt an irgendeinem Zeitpunkt des Vortags vorhanden war, werden entfernt. Danach werden spätere Duplikate innerhalb des Zieltags entfernt.
- Historische Weeklys filtern byte-identische Frames einmal über die vollständige Sieben-Tage-Sequenz.
- Monthly filtert byte-identische Frames unabhängig innerhalb jedes Kalendertages. Gleicher Inhalt an unterschiedlichen Tagen bleibt erhalten.
- Yearly wählt pro Tag bis zu fünf inhaltlich eindeutige Frames aus.

Yearly behandelt Duplikate anders:

```text
Kandidat nahe 12:00
→ Hash prüfen
→ bereits gleicher Inhalt an diesem Tag?
   → ja: nächsten Kandidaten prüfen
   → nein: Frame übernehmen
→ bis zu 5 eindeutige Frames
```

Dadurch muss Yearly nicht mehr sämtliche Bilder eines 365-Tage-Fensters vollständig hashen, bevor die eigentliche Auswahl stattfindet.

---

## Ausgabe- und Arbeitsverzeichnisse

### Automatische Videos

Automatische Ausgaben liegen unter:

```text
videos/<camera>/<job>/<camera>_<zieldatum>.mp4
```

Beispiele:

```text
videos/Scheunenviertel/daily/Scheunenviertel_2026-09-21.mp4
videos/Scheunenviertel/weekly/Scheunenviertel_2026-09-21.mp4
videos/Scheunenviertel/monthly/Scheunenviertel_2026-09-21.mp4
videos/Scheunenviertel/yearly/Scheunenviertel_2026-09-21.mp4
```

### Historische Ausgaben

Historische `--target-date`-Läufe und der `--date`-Alias werden getrennt von automatischen Ausgaben gespeichert:

```text
videos/<camera>/manual-runs/<job>/<camera>_<zieldatum>.mp4
```

Beispiele:

```text
videos/Scheunenviertel/manual-runs/daily/Scheunenviertel_2026-08-15.mp4
videos/Scheunenviertel/manual-runs/weekly/Scheunenviertel_2026-08-15.mp4
videos/Scheunenviertel/manual-runs/monthly/Scheunenviertel_2026-08-15.mp4
videos/Scheunenviertel/manual-runs/yearly/Scheunenviertel_2026-08-15.mp4
videos/Scheunenviertel/manual-runs/yearly/Scheunenviertel_2026-08-15_sunset-60min.mp4
```

Ein abweichendes Zeitfenster (`--window-time` / `--window-tolerance-minutes`) wird als Suffix
`_<HHMM|sunset>-<toleranz>min` angehängt.

Historische Ausgaben werden von automatischer Retention nicht verändert.

### Temporäre Frames

Bildbasierte Jobs kopieren ausgewählte Quellen nach:

```text
temp/<camera>/<zieldatum>/frame_000001.jpg
temp/<camera>/<zieldatum>/frame_000002.jpg
...
```

Automatische Weeklys verwenden für die Concat-Datei:

```text
temp/<camera>/weekly/<enddatum>/concat.txt
```

Temporäre Arbeitsverzeichnisse werden erst nach erfolgreicher Videoerstellung entfernt. Bei einem Fehler bleiben sie für die Diagnose erhalten.

### Atomarer Austausch

FFmpeg schreibt im Zielverzeichnis zunächst nach:

```text
.<dateiname>.tmp.mp4
```

Nur ein erfolgreicher FFmpeg-Lauf ersetzt die endgültige MP4-Datei. Eine fehlgeschlagene Neuerstellung lässt das vorherige Video unverändert.

---

## Automatische Retention

| Job | Aufbewahrung |
|---|---|
| Daily | Exaktes rollierendes Fenster der letzten 7 Kalendertage relativ zum Zieldatum |
| Weekly | Nur das neueste erfolgreich erstellte automatische Weekly pro Kamera |
| Monthly | Nur das neueste erfolgreich erstellte automatische Monthly pro Kamera |
| Yearly | Nur das neueste erfolgreich erstellte automatische Yearly pro Kamera |

Retention läuft ausschließlich nach erfolgreicher Videoerstellung. Fehlende Daily-Tage werden nicht durch ältere Videos aufgefüllt. Historische Ausgaben unter `manual-runs/` sind ausgeschlossen.

---

## Run-State und Wiederanlauf

Nur der vollständige Produktionslauf ohne Argumente

```bash
python3 -m src.main
```

verwendet den persistenten Marker:

```text
state/run-in-progress
```

Ablauf nach erfolgreicher Konfigurations-, Logging- und Kamera-Storage-Prüfung:

```text
vollständiger Produktionslauf startet
→ state/run-in-progress wird angelegt

Daily → Weekly → Monthly → Yearly laufen durch
→ Marker wird nach Abschluss entfernt

Prozessabbruch, Stromausfall oder Neustart vor Abschluss
→ Marker bleibt bestehen
```

Explizite `--jobs`-, `--target-date`- und `--date`-Aufrufe erzeugen keinen Marker und gelten nicht als wiederaufzunehmender Produktionslauf.

Der Status ist absichtlich einfach: Es gibt keinen Resume-Punkt pro Kamera oder Job. Bei einer Wiederherstellung startet der komplette automatische Workflow erneut. Bereits vorhandene Videos werden durch atomaren Austausch geschützt, und Retention erfolgt erst nach erfolgreicher Neuerstellung.

Der Marker liegt unter `state/` und nicht unter `/tmp`, damit er einen Neustart überlebt.

Kameralokale operative Fehler werden innerhalb des jeweiligen Jobs behandelt und lassen spätere Kameras weiterlaufen. Ein nicht behandelter Prozessabbruch oder globaler Fehler nach dem Anlegen des Markers lässt ihn für die Reboot-Wiederherstellung bestehen.

---

## Logging

Logs werden nach Job-Typ getrennt:

```text
logs/
├── daily/YYYY-MM-DD.log
├── weekly/YYYY-MM-DD.log
├── monthly/YYYY-MM-DD.log
├── yearly/YYYY-MM-DD.log
└── filter/YYYY-MM-DD.log
```

Bei einer gezielten Job-Auswahl wird vor dem ersten ausgeführten Job direkt dessen Log aktiviert. Bei mehreren Jobs wird vor jedem weiteren Job auf das passende Log gewechselt.

Die Konsole erhält Meldungen ab INFO. Die Dateien enthalten zusätzlich DEBUG-Meldungen wie ausgewählte Bildgrenzen, temporäre Pfade, FFmpeg-Befehle, fehlende Datumsbereiche und Retention-Cleanup.

Jeder Prozess erhält eine Run-ID. Startmeldungen enthalten Run-ID, Ausführungsmodus und Kameraauswahl. Die Abschlussmeldung jedes Jobs enthält die Anzahl erstellter, übersprungener und fehlgeschlagener Kameras.

Fehlende Monthly- und Yearly-Tage werden als kompakte Datumsbereiche protokolliert. Duplicate-Filter melden die Anzahl ausgeschlossener Frames. Bei einem FFmpeg-Fehler werden die letzten 40 Zeilen der FFmpeg-Fehlerausgabe in das Anwendungslog übernommen.

Während FFmpeg läuft, werden Spitzenwerte für folgende Ressourcen erfasst:

```text
FFmpeg CPU
FFmpeg RAM
System CPU
System RAM
```

Auf Mehrkernsystemen kann die FFmpeg-CPU-Auslastung von `psutil` über 100 Prozent liegen. Hohe CPU-Auslastung allein bedeutet daher keinen fehlgeschlagenen Lauf.

Die Aufbewahrungsdauer wird über `log_retention_days` konfiguriert.

Operative Fehler wie

```text
OSError
TimeoutError
subprocess.CalledProcessError
```

werden pro Kamera behandelt.

Programmierfehler wie `TypeError` oder `AttributeError` werden nicht pauschal verschluckt.

---

## Tests

Komplette Testsuite:

```bash
python3 -m pytest
```

Ausführlich:

```bash
python3 -m pytest -v
```

Einzelne Datei:

```bash
python3 -m pytest tests/main_test.py -v
```

Die `main.py`-Tests decken unter anderem ab:

- vollständigen Default-Workflow
- einzelne und kombinierte Job-Auswahl
- feste Workflow-Reihenfolge
- doppelte Job-Angaben
- Weitergabe von `target_date`
- `--date` als Alias für historische Daily-Läufe
- ungültige CLI-Kombinationen
- Kamera-Filterung
- Logging
- Storage-Fehler
- Log-Retention

Tests deaktivieren das produktive File-Logging über `tests/conftest.py`.

Drei Tests in `tests/images_test.py` lesen echte Bilder unter `/mnt/cameras`. Ist der Mount nicht
vorhanden (z. B. in GitHub Actions), werden sie mit Begründung übersprungen statt fehlzuschlagen.
Erscheint lokal auf dem Pi „3 skipped“, ist der SSHFS-Mount nicht erreichbar.

Die Web-Tests benötigen `php` auf der Kommandozeile, siehe [Webtests](#webtests).

### GitHub Actions und Pre-Push-Hook

`.github/workflows/test.yml` läuft bei jedem Push und Pull Request auf `ubuntu-latest` mit
Python 3.13 und führt nacheinander aus:

```text
ruff check .
→ ruff format --check .
→ python -m pytest
```

Schlägt ein Schritt fehl, laufen die folgenden nicht mehr; ein roter Lauf heißt also nicht
zwingend, dass Tests fehlgeschlagen sind. Ein neuerer Push auf denselben Branch bricht einen noch
laufenden älteren Lauf ab.

Lokal führt `.git/hooks/pre-push` (nicht versioniert) dieselben drei Prüfungen aus und blockiert
den Push bei einem Fehler. Er prüft den Arbeitsstand, also auch nicht committete Änderungen.
Notfalls umgehen mit:

```bash
git push --no-verify
```

---

## Linting und Formatierung

Das Projekt verwendet Ruff, gepinnt in `requirements.txt`, damit lokal und in GitHub Actions
dieselbe Version prüft.

Die Konfiguration liegt in:

```text
pyproject.toml
```

Python-Code wird mit Tabs eingerückt:

```toml
[tool.ruff.format]
indent-style = "tab"
```

Gemischte Tabs und Spaces werden über die Ruff-Regeln erkannt. `W191` ist bewusst deaktiviert, da Tabs im Projekt der gewünschte Einrückungsstil sind.

Code automatisch formatieren:

```bash
ruff format .
```

Linting ausführen:

```bash
ruff check .
```

Nur prüfen, ohne Dateien zu verändern:

```bash
ruff format --check .
ruff check .
```

Empfohlener Entwicklungsablauf:

```text
Code ändern
→ ruff format .
→ ruff check .
→ python3 -m pytest
```

---

## Projektstruktur

```text
timelapse/
├── .github/
│   └── workflows/
│       └── test.yml
├── config/
│   ├── config.json
│   └── mount.env.example
├── docs/
│   ├── plans/
│   │   └── custom-time-window.md
│   ├── nas.md
│   ├── verpixelung.md
│   ├── youtube-description-prompt.md
│   └── youtube-texts.md
├── nas/
│   ├── helpers/
│   ├── nas-extract.py
│   └── README.md
├── scripts/
│   ├── cameras-sshfs-preflight
│   ├── pi-crash-logging-setup
│   ├── storage-filter-all
│   ├── timelapse-web-delete
│   ├── timelapse-web-status.sh
│   ├── timelapse-web-trigger
│   ├── timelapse-web-worker
│   └── yearly-backfill.py
├── src/
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── daily.py
│   │   ├── weekly.py
│   │   ├── monthly.py
│   │   └── yearly.py
│   ├── privacy/
│   │   ├── __init__.py
│   │   ├── anonymize.py
│   │   └── detect.py
│   ├── config.py
│   ├── date_coverage.py
│   ├── diagnostics.py
│   ├── image_worker.py
│   ├── images.py
│   ├── interval_window.py
│   ├── logger.py
│   ├── main.py
│   ├── run_state.py
│   ├── solar.py
│   ├── storage_filter.py
│   ├── video.py
│   └── yearly_selection.py
├── systemd/
│   └── cameras-sshfs.service
├── tests/
│   ├── config_test.py
│   ├── daily_test.py
│   ├── date_coverage_test.py
│   ├── diagnostics_test.py
│   ├── image_worker_test.py
│   ├── images_test.py
│   ├── interval_window_test.py
│   ├── logger_test.py
│   ├── main_test.py
│   ├── monthly_test.py
│   ├── privacy_test.py
│   ├── run_state_test.py
│   ├── storage_filter_test.py
│   ├── video_test.py
│   ├── web_delete_test.py
│   ├── web_php_test.py
│   ├── web_status_endpoint_test.py
│   ├── web_status_test.py
│   ├── weekly_test.py
│   ├── yearly_selection_test.py
│   ├── yearly_test.py
│   └── conftest.py
├── web/
│   ├── public/
│   │   ├── camera.php
│   │   ├── index.php
│   │   ├── job-status.php
│   │   └── style.css
│   └── src/
│       ├── components/
│       │   ├── header.php
│       │   └── job-watcher.php
│       ├── job-runner.php
│       ├── process-runner.php
│       ├── video-delete.php
│       └── video-library.php
├── logs/
├── models/
├── reports/
├── state/
├── temp/
├── videos/
├── backup-from-mac.sh
├── migrate.sh
├── pyproject.toml
├── requirements.txt
└── README.md
```

Runtime-Daten unter `logs/`, `reports/`, `state/`, `temp/` und `videos/` werden nicht als Quelldaten behandelt.
`models/` enthält das Modell der Personenerkennung; es wird separat heruntergeladen und ist nicht
im Repository.

`docs/` enthält die ausführlichen Anleitungen zur Verpixelung (`verpixelung.md`) und zum
NAS-Archiv (`nas.md`), Pläne (`plans/custom-time-window.md`: geplantes `--from`/`--to`, noch
nicht umgesetzt) sowie Vorlage und fertige Texte für YouTube-Uploads.

`backup-from-mac.sh` und `migrate.sh` sichern bzw. stellen einen Raspberry Pi bei einer Neuinstallation wieder her; siehe [Neuinstallation des Raspberry Pi](#neuinstallation-des-raspberry-pi).

---

## Architektur

### `src/main.py`

Zentraler Koordinator.

Verantwortlich für:

- CLI-Argumente
- Konfiguration laden
- Kamera-Storage prüfen
- ignorierte Kameras filtern
- Logging konfigurieren
- historische oder automatische Workflows starten
- ausgewählte automatische Jobs koordinieren
- feste Workflow-Reihenfolge beibehalten
- optionales `target_date` an automatische Jobs weiterreichen
- Framerates aus der Config an die Jobs weiterreichen
- den persistenten Statusmarker des vollständigen Produktionslaufs verwalten

### `src/jobs/`

Enthält ausschließlich die Businesslogik der einzelnen Timelapse-Typen.

`daily.py`
- verarbeitet standardmäßig gestern
- kann optional ein explizites `target_date` verarbeiten
- nutzt Sunrise/Sunset inklusive konfigurierbarem Buffer
- liest Zieltag und Vortag gemeinsam in einem isolierten Scan
- entfernt Zieltag-Frames, deren Inhalt bereits am Vortag vorhanden war
- erstellt Daily-Videos
- hält ein exaktes rollierendes 7-Tage-Fenster relativ zum verarbeiteten Zieldatum

`weekly.py`
- erstellt automatische Weeklys aus vorhandenen Daily-Videos
- erstellt historische Weeklys direkt aus Originalbildern für genau eine Kamera
- verarbeitet ein exaktes rollierendes 7-Tage-Fenster
- füllt fehlende automatische Dailys nicht mit älteren Videos auf
- verlangt für historische Weeklys vollständige Bildabdeckung
- verwendet für automatische Weeklys FFmpeg-Concat ohne Re-Encoding

`monthly.py`
- verarbeitet ein rollierendes 30-Tage-Fenster
- Fenster endet standardmäßig gestern oder am expliziten `target_date`
- verwendet Originalbilder
- berücksichtigt alle ausgewählten Bilder im täglichen Zielzeitfenster aus `interval_window`
  (Standard 12:00 Uhr ±90 Minuten; historisch per CLI überschreibbar, auch `sunset`)

`yearly.py`
- verarbeitet ein rollierendes 365-Tage-Fenster
- Fenster endet standardmäßig gestern oder am expliziten `target_date`
- verwendet Originalbilder
- delegiert die Yearly-spezifische Frame-Auswahl an `yearly_selection.py`

### `src/images.py`

Allgemeine Bildlogik:

- Kameraerkennung
- `os.scandir()`-basierte Bildsuche für einzelne oder mehrere angeforderte Tage
- Datums- und Uhrzeitextraktion aus bekannten Dateinamensformaten
- daylight-basierte Auswahl
- Interval-Suche
- 0-Byte-Filterung
- SHA-256-Hashing
- job-spezifische Duplicate-Filterung

Unbekannte Dateinamensformate werden nicht geraten.

### `src/image_worker.py`

Gemeinsame Infrastruktur für isolierte Worker-Prozesse.

Der Supervisor übernimmt:

- `Process` und `Queue`
- Fortschrittsmeldungen, zentral auf höchstens eine pro Sekunde gedrosselt
- Stall-Timeout
- `terminate()`
- bei Bedarf `kill()`
- Erkennung unerwartet beendeter Worker
- Weitergabe erwarteter `OSError`

Der Timeout misst **Inaktivität**, nicht die Gesamtlaufzeit. Lange Scans dürfen weiterlaufen, solange Fortschritt gemeldet wird.

Eine Worker-Funktion ist eine normale Funktion mit `progress_callback`-Parameter, die ihr Ergebnis zurückgibt. `run_isolated_worker(camera, target, kwargs, ...)` startet sie im eigenen Prozess. Auch die Bildbereich-Diagnose (`src/diagnostics.py`) läuft darüber, mit 10 Sekunden Stall-Timeout.

### `src/date_coverage.py`

Gemeinsame Datumslogik für exakte rollierende Fenster:

- Weekly: 7 Kalendertage inklusive Enddatum
- Monthly: 30 Kalendertage inklusive Enddatum
- Yearly: 365 Kalendertage inklusive Enddatum
- Ermittlung fehlender Kalendertage
- Lesen und Prüfen der Mindestabdeckung (`get_min_coverage_days`)
- kompakte Darstellung aufeinanderfolgender fehlender Tage für Logs

### `src/yearly_selection.py`

Yearly-spezifische Frame-Auswahl.

Pro Kalendertag:

1. Kandidaten nach Abstand zur Fenstermitte priorisieren (Standard 12:00 Uhr, bei `sunset`
   der Sonnenuntergang des Tages).
2. Bildinhalt per SHA-256 prüfen.
3. Byte-identische Kandidaten überspringen.
4. Bei Duplikaten den nächsten Kandidaten nachziehen.
5. Bis zu fünf eindeutige Frames auswählen.
6. Ausgewählte Frames innerhalb des Tages chronologisch sortieren.

Die Hash-Auswahl läuft ebenfalls isoliert über den gemeinsamen Worker-Supervisor.

### `src/video.py`

Technische Video- und FFmpeg-Schicht:

- Frames lokal vorbereiten
- Bild-Timelapses erstellen
- Videos zusammenfügen
- temporäre Ausgabedateien
- bestehende Videos erst nach erfolgreicher Neuerstellung ersetzen
- CPU- und RAM-Messungen
- begrenzte FFmpeg-Fehlerausgabe bei fehlgeschlagenen Encodes

Ausgewählte Originalbilder werden zuerst nach `temp/` kopiert und dort als `frame_000001.jpg`, `frame_000002.jpg`, … normalisiert. FFmpeg schreibt zunächst eine versteckte temporäre MP4-Datei. Erst nach erfolgreichem Abschluss ersetzt diese atomar die endgültige Ausgabe.

### `src/privacy/`

Verpixelung von Personen und Kennzeichen (derzeit nur für historische Dailys, siehe
[docs/verpixelung.md](docs/verpixelung.md)):

- `anonymize.py`: ruft die Erkennung paketweise auf, prüft jedes Ergebnis, verwaltet den Cache,
  verwirft bekannte Fehlerkennungen und verpixelt die Kopien unter `temp/` mit FFmpeg; jeder
  Zweifel bricht den Lauf ab
- `detect.py`: Erkennung von Personen und Fahrzeugen (YOLOX), läuft als eigener Prozess

### `src/logger.py`

- gemeinsamer Anwendungslogger
- INFO-Ausgabe auf der Konsole
- DEBUG-Ausgabe in tagesbasierten Job-Logs
- Wechsel des File-Handlers zwischen Job-Typen
- Run-ID pro Prozess
- konfigurierbare Log-Retention

### `src/run_state.py`

Verwaltet den persistenten Marker `state/run-in-progress` für den vollständigen automatischen Produktionslauf. Details stehen im Abschnitt [Run-State und Wiederanlauf](#run-state-und-wiederanlauf).

---

## Sicherheit und Datenintegrität

Grundregeln des Projekts:

- Originalbilder unter `/mnt/cameras` niemals verändern.
- Frames nur lokal unter `temp/` vorbereiten.
- Unbekannte Dateinamensformate niemals erraten.
- Verpixelung schlägt im Zweifel fehl: lieber kein Video als ein ungeprüftes Bild.
- Bestehende Videos erst nach erfolgreicher Neuerstellung ersetzen.
- Daily-Retention erst nach erfolgreicher Videoerstellung anwenden.
- Fehler einer Kamera dürfen spätere Kameras nicht unnötig blockieren.
- Blockierende Dateisystemzugriffe möglichst in isolierten Workern ausführen.
- Automatische Jobs verwenden standardmäßig ausschließlich abgeschlossene Kalendertage.
- Historische automatische Läufe verwenden das explizit gewählte `--target-date` als Datumsanker.

---

## Noch offen

Für den produktiven Dauerbetrieb fehlen insbesondere noch:

- Upload der erzeugten Videos zum Webserver
- Synchronisierung und Lebenszyklus der Videos auf dem Zielserver
- weiterführende Deployment-Automatisierung

Die Architektur ist so aufgebaut, dass weitere periodische Jobs ergänzt werden können, ohne den zentralen Coordinator unnötig mit Businesslogik zu belasten.
