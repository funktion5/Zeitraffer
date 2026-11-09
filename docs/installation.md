# Installation

Die Einrichtung eines Servers von Hand: Pakete, Python-Umgebung, Zugriff auf die Storage Box, Cron,
Apache, Wrapper und Dateirechte. Einstellungen und Umgebungsvariablen stehen in
[konfiguration.md](konfiguration.md).

*Für die technische Einrichtung.*

Platzhalter in den folgenden Beispielen:

| Platzhalter | Bedeutung |
|---|---|
| `<benutzer>` | Linux-Konto, unter dem das Projekt läuft |
| `<projektpfad>` | Projektordner, z. B. `/home/<benutzer>/timelapse` |
| `<login>` | Benutzername der Apache-Basisauthentifizierung |

Die folgenden Abschnitte beschreiben die Einrichtung von Hand. Für einen frischen Debian- oder Ubuntu-Host übernimmt `install.sh` die Schritte: Pakete, Python-Umgebung, Anmeldung der Weboberfläche, leere Login-Datei für den Upload, auf Wunsch das Zurückspielen einer Sicherung, Apache, Wrapper, sudoers und Dateirechte. Die Bilder liest das Programm bei jedem Lauf per ssh von der Storage Box; einen eingebundenen Ordner gibt es nicht. Ablauf und Vorbereitung: [Einen VPS einrichten](vps.md).

## Systempakete installieren

`install.sh` installiert dieselbe Paketliste (Schritt `packages`):

```bash
sudo apt-get update
sudo apt-get install -y \
  git python3 python3-venv python3-pip \
  ffmpeg rsync curl cron \
  apache2 apache2-utils libapache2-mod-php php-cli php-common php-opcache
```

## Python-Umgebung einrichten

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
[Verpixelung – Installation](verpixelung.md#installation). Ohne Modell laufen alle anderen
Funktionen normal.

## Zugriff auf die Storage Box

Die Originalbilder liegen auf der Storage Box. Die Zeitraffer-Jobs lesen sie nur: Sie holen die für
einen Lauf nötigen Bilder per rsync in einen Zwischenspeicher unter `temp/frame-cache/`, der nach
jeder Kamera wieder geleert wird. Es gibt keinen eingebundenen Ordner.

Voraussetzungen:

- ein SSH-Schlüssel nur für die Storage Box im Konto `<benutzer>`, ohne Passphrase (Cron braucht
  ihn ohne Eingabe)
- ein Eintrag in `~/.ssh/config` mit Benutzer, Host, Port und Schlüssel; `install.sh` erwartet den
  Namen `storagebox`:

```text
Host storagebox
    HostName <box-host>
    User <box-user>
    Port <box-port>
    IdentityFile ~/.ssh/<schluessel>
    IdentitiesOnly yes
```

- der öffentliche Schlüssel auf der Box und der Host-Fingerabdruck einmal bestätigt (Anleitung:
  [Einen VPS einrichten](vps.md))

Benutzer, Host, Port und Schlüssel stehen nur in `~/.ssh/config`, nie im Repository. Das Programm
kennt nur den Namen des Eintrags, über die Umgebungsvariable `TIMELAPSE_STORAGE_BOX` (siehe
[Umgebungsvariablen](konfiguration.md#umgebungsvariablen)).

Verbindung prüfen (listet die Kameras und schreibt die Kameraliste der Weboberfläche):

```bash
TIMELAPSE_STORAGE_BOX=storagebox .venv/bin/python3 -m src.camera_list
```

## Cron installieren oder prüfen

Der Eintrag aus [Zeitplanung mit Cron](betrieb.md#zeitplanung-mit-cron) wird über

```bash
crontab -e
```

für den Benutzer `<benutzer>` installiert. Anschließend prüfen:

```bash
crontab -l
```

## Weboberfläche einrichten

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

Die Site wird unter `http://<hostname>.local/` oder über die IP-Adresse des Servers geöffnet. Der Alias `/videos/` stellt MP4-Dateien bereit und unterstützt die Browser-Wiedergabe. Er umfasst derzeit den gesamten Verzeichnisbaum `videos/`.

Apache läuft als `www-data`. Dieser Benutzer wird nicht in die Gruppe `<benutzer>` aufgenommen. Die lokalen Projektpfade erhalten nur die für Website, Videos und Web-Status erforderlichen Leserechte (Details unter [Dateirechte für `www-data`](#dateirechte-für-www-data)). Die Wrapper werden als root-eigene, für `www-data` nicht beschreibbare Kopien unter `/usr/local` installiert.

Die Site verwendet Apache-Basisauthentifizierung, aber weiterhin HTTP statt HTTPS. Zugangsdaten werden dadurch nicht auf dem Transportweg verschlüsselt; die Site darf deshalb weiterhin nicht ohne zusätzliche Transportverschlüsselung aus einem nicht vertrauenswürdigen Netzwerk erreichbar sein.

### Basisauthentifizierung einrichten

Beide Verzeichnisse (`web/public` und der `/videos/`-Alias) werden per `AuthType Basic` geschützt. Die Zugangsdaten liegen in `/etc/apache2/.htpasswd`, außerhalb des Dokumenten-Stammverzeichnisses und damit über HTTP nicht erreichbar; die Datei wird nicht versioniert und darf nicht ins Repository gelangen. Auf einem frischen Host legt `install.sh` sie im Schritt `web_login` an.

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
  scripts/web/timelapse-web-status.sh \
  /usr/local/libexec/timelapse-web-status.sh
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-worker \
  /usr/local/libexec/timelapse-web-worker
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-trigger \
  /usr/local/sbin/timelapse-web-trigger
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-delete \
  /usr/local/sbin/timelapse-web-delete
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-delete-highlight \
  /usr/local/sbin/timelapse-web-delete-highlight
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-rebuild \
  /usr/local/sbin/timelapse-web-rebuild
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-publish \
  /usr/local/sbin/timelapse-web-publish
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-worker-rebuild \
  /usr/local/libexec/timelapse-web-worker-rebuild
sudo install -o root -g root -m 755 \
  scripts/web/timelapse-web-worker-publish \
  /usr/local/libexec/timelapse-web-worker-publish
```

Die sudoers-Regeln erlauben ausschließlich die drei festen Trigger (Video-Auftrag, Neu erstellen, Upload) und die beiden festen Lösch-Wrapper, jeweils als `<benutzer>`:

```sudoers
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-rebuild *
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-publish *
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight
```

Eine sudoers-Regel ohne Argumentliste erlaubt beliebige Argumente. `timelapse-web-delete` erwartet genau Kamera, Job-Typ und Dateiname, prüft diese selbst (kein `/`, nur `.mp4`, keine Symlinks) und löscht ausschließlich unter `videos/<camera>/manual-runs/<job>/`. `timelapse-web-delete-highlight` erwartet genau Kamera, Datum und Dateiname (nur `.jpg`, keine Symlinks) und löscht ausschließlich ein Bild unter `videos/<camera>/highlights/<datum>/`, nie die `manifest.json`.

`timelapse-web-rebuild` erwartet Job-ID, Kamera und ein bis vier Videoarten (`daily`, `weekly`, `monthly`, `yearly`), `timelapse-web-publish` genau Job-ID und Kamera. Beide prüfen die Kamera gegen `state/web-jobs/cameras.json` und nehmen dieselbe Laufsperre wie der Trigger; ihre Worker `timelapse-web-worker-rebuild` und `timelapse-web-worker-publish` müssen unter `/usr/local/libexec/` liegen (sonst endet der Trigger mit Exit 69). Der Upload-Worker liest keine Zugangsdaten: Er startet `scripts/copy_zeitraffer_videos_vps2siteground.sh`, das sie aus `config/siteground.env` liest. `./install.sh` installiert alles im Schritt `web_bridge`.

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
| `config/config.json` | lesen (`r--`) | `ignored_cameras`, `flagger.cameras`, Zeitzone |
| `state/` | nur Durchgang (`--x`) | – |
| `state/web-jobs/` | lesen (vom Status-Skript als `755`/`644` angelegt) | Job-Status-Polling |
| alle übrigen Einträge in `timelapse/` | keine | – |

`logs/`, `temp/` und `reports/` werden mit Modus `770` vorab angelegt, damit die Python-Jobs sie später nicht weltlesbar erzeugen.

Die Rechte setzt der Schritt `permissions` von `install.sh`. Er ist wiederholbar und kann jederzeit einzeln ausgeführt werden, etwa nachdem Videos von Hand kopiert wurden:

```bash
~/timelapse/install.sh permissions verify
```

Warum das nötig ist: Debian 13 legt Home-Verzeichnisse mit Modus `0700` an (`HOME_MODE` in `/etc/login.defs`), und `git clone` erzeugt alle Dateien weltlesbar. Ohne diesen Schritt antwortet Apache mit `403 Forbidden`, und im Fehlerlog steht `AH00035: ... search permissions are missing on a component of the path`.

Die Rechte für „andere“ gelten technisch für alle lokalen Benutzer, nicht nur für `www-data`. Eine Beschränkung auf genau `www-data` wäre nur über ACLs (Paket `acl`) möglich.

Neue Dateien der Python-Jobs sind durch die Standard-`umask` `0002` weltlesbar. Unter `videos/` ist das gewollt; in gesperrten Verzeichnissen wie `logs/` bleibt der Inhalt trotzdem unerreichbar, weil der Durchgang durch das Verzeichnis selbst fehlt.
