# Raspberry Pi: Neuinstallation und Absturzprotokollierung

Alles, was nur den Raspberry Pi als Host betrifft: Sicherung und Wiederherstellung bei einer Neuinstallation und die Protokollierung, die stille Neustarts nachvollziehbar macht.


## Absturzprotokollierung einrichten

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

## Neuinstallation des Raspberry Pi

Bei einer Neuinstallation des Betriebssystems gehen alle Dateien verloren, die nicht im Git-Repository liegen. Zwei Skripte übernehmen Sicherung und Wiederherstellung:

| Skript | Läuft auf | Aufgabe |
|---|---|---|
| `backup.sh` | dem eigenen Rechner (macOS, Linux oder Windows mit WSL), **vor** der Neuinstallation | holt alle nicht versionierten Dateien vom Pi in einen lokalen Backup-Ordner; die Geheimnisse verschlüsselt |
| `migrate.sh` | dem Pi, **nach** der Neuinstallation | installiert Pakete, klont das Repository, stellt das Backup wieder her und richtet alle Dienste ein |

Modelle, Zustand und Videos sind nicht Teil von `migrate.sh`, sondern werden nach der Migration von Hand zurückkopiert (Schritt 6).

### Was gesichert wird

| Datei auf dem Pi | Im Backup | Wird wiederhergestellt nach |
|---|---|---|
| Ordner `~/.ssh` (Schlüssel, `config`, `known_hosts`) | `pi-backup.tar.gz.enc` | `~/.ssh/` (`600`, `.pub`-Dateien `644`); `known_hosts` wird zusammengeführt, `authorized_keys` nicht wiederhergestellt |
| `/etc/timelapse/mount.env` | `pi-backup.tar.gz.enc` | `root:root 600` |
| `/etc/sudoers.d/timelapse-web` | `pi-backup.tar.gz.enc` | `root:root 440`, nur nach erfolgreicher `visudo`-Prüfung |
| `/etc/apache2/.htpasswd` | `pi-backup.tar.gz.enc` | `root:www-data 640` |
| `/etc/apache2/sites-available/zeitraffer.conf` | `pi-backup.tar.gz.enc` | `root:root 644` |
| Crontab des Login-Benutzers | `pi-crontab.txt` | Crontab des Login-Benutzers |
| `config/config.json` | `config.json` | `config/config.json` (überschreibt die Git-Version) |
| `models/` (Erkennungsmodelle, nicht im Git) | `models/` | von Hand, siehe Schritt 6 |
| `state/` (ohne Laufsperre und „Lauf läuft“-Marker) | `state/` | von Hand, siehe Schritt 6 |
| `videos/` | `videos/` | von Hand, siehe Schritt 6 |

`pi-backup.tar.gz.enc` enthält einen privaten SSH-Schlüssel, die Zugangsdaten des Kamera-Storage und einen Passwort-Hash. Es ist deshalb **mit einer Passphrase verschlüsselt** (AES-256, `openssl`), die `backup.sh` bei jedem Lauf zweimal abfragt und nirgends speichert. Das unverschlüsselte Archiv landet nie auf dem eigenen Rechner. **Ohne die Passphrase ist das Backup wertlos**: sie gehört in einen Passwortmanager.

Der Backup-Ordner wird zusätzlich mit Modus `700` angelegt und darf nicht in Cloud-Sync-Ordner oder ins Repository gelangen. Der Standardordner `~/timelapse-backup` liegt bewusst außerhalb von `Documents` und `Desktop`: Ist in den macOS-Einstellungen die iCloud-Option „Schreibtisch & Dokumente“ aktiv, würde alles dort in die iCloud hochgeladen. Unter Windows/WSL gehört der Ordner ins WSL-Home, nicht auf ein Windows-Laufwerk (`/mnt/c/...`), wo Dateirechte nicht gelten; das Skript warnt in dem Fall. Wer über `DEST` einen anderen Ordner wählt, verwendet in den folgenden Befehlen denselben Pfad.

Bewusst nicht gesichert:

- `logs/` und `temp/` – reine Laufzeitdaten
- die SSH-Hostschlüssel des Pi – der neu installierte Pi erhält neue; siehe Schritt 3
- WLAN-Konfiguration – der Pi läuft ausschließlich über Ethernet, WLAN wird deaktiviert

### Voraussetzungen

- ein eigener Rechner mit macOS, Linux oder Windows mit WSL, darauf `bash`, `ssh`, `rsync` und `openssl` (unter WSL ggf. `sudo apt install rsync openssl`), mit Zugriff auf den Pi per SSH (Passwort-Login als Login-Benutzer des Pi)
- ein Checkout dieses Repositorys auf diesem Rechner, damit `migrate.sh` von dort auf den Pi kopiert werden kann
- die Passphrase des Backups (Passwortmanager)
- das `sudo`-Passwort dieses Benutzers auf dem Pi
- die offiziellen Host-Key-Fingerprints der Storage Box beim Anbieter (nur nötig, wenn das Backup noch kein `known_hosts` enthält)
- Netzwerkkabel am Pi: `migrate.sh` schaltet WLAN ab

### Schritt 1: Backup erstellen

Im Repository-Checkout auf dem eigenen Rechner einmalig die lokale Einstellungsdatei anlegen und Hostname bzw. IP und Benutzer des Pi eintragen. `backup.env` ist per `.gitignore` ausgeschlossen, damit weder IP noch Benutzername oder lokale Pfade im öffentlichen Repository landen:

```bash
cp backup.env.example backup.env
nano backup.env
./backup.sh
```

In den folgenden Befehlen stehen `<pi-host>` und `<pi-user>` für `BACKUP_HOST` und `BACKUP_USER` aus `backup.env`.

Das Skript fragt zuerst zweimal nach der Passphrase für die Verschlüsselung, dann einmal nach dem SSH-Passwort und einmal nach dem `sudo`-Passwort auf dem Pi. Anschließend:

1. packt es die Geheimnisse auf dem Pi mit `umask 077` in eine Datei mit Zufallsnamen im Home-Verzeichnis, streamt sie verschlüsselt nach `pi-backup.tar.gz.enc` und löscht sie auf dem Pi wieder, auch wenn ein späterer Schritt fehlschlägt. Fehlt eine Datei auf dem Host oder ist sie ohne `sudo` nicht lesbar, wird sie mit einer Warnung übersprungen; ohne `sudo` auf dem Host wird nur `~/.ssh` gesichert,
2. speichert die Crontab und `config.json`,
3. synchronisiert `models/`, `state/` und `videos/` per `rsync`,
4. entschlüsselt das Archiv zur Probe, listet seinen Inhalt auf und gibt die Befehle für die Wiederherstellung aus.

Optionen in `backup.env` oder als Umgebungsvariable (die Umgebungsvariable hat Vorrang, z. B. `BACKUP_HOST=<pi-ip> ./backup.sh`, falls der `.local`-Name nicht aufgelöst wird):

| Variable | Standard | Bedeutung |
|---|---|---|
| `BACKUP_HOST` | – (Pflicht) | Hostname oder IP des Hosts |
| `BACKUP_USER` | – (Pflicht) | Login-Benutzer auf dem Host |
| `PROJECT_DIR` | `~/timelapse` auf dem Host | Projektordner auf dem Host; `~` und `$HOME` meinen das Home-Verzeichnis **auf dem Host** |
| `DEST` | `~/timelapse-backup` | Backup-Ordner auf dem eigenen Rechner |
| `SKIP_VIDEOS` | `0` | `1` überspringt die Videos |

Die früheren Namen `PI_HOST` und `PI_USER` funktionieren weiter. `backup.env` wird gelesen, nicht ausgeführt: nur `NAME=Wert`-Zeilen mit diesen Namen zählen.

Danach prüfen, ob der Backup-Ordner vollständig ist:

```bash
ls -la ~/timelapse-backup
# erwartet: pi-backup.tar.gz.enc, pi-crontab.txt, config.json, models/, state/, videos/
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 \
  -in ~/timelapse-backup/pi-backup.tar.gz.enc | tar tzf -     # fragt nach der Passphrase
# erwartet: der Ordner home/<pi-user>/.ssh/ mit Schlüssel, config und known_hosts,
# außerdem mount.env, sudoers, .htpasswd und die Apache-Site
```

Erst weitermachen, wenn das Backup vollständig ist.

### Schritt 2: Betriebssystem neu installieren

Mit dem Raspberry Pi Imager ein 64-Bit-Raspberry-Pi-OS auf Basis von Debian 13 (trixie) schreiben und in den erweiterten Einstellungen festlegen:

- Hostname: derselbe wie vor der Neuinstallation (`BACKUP_HOST` in `backup.env`)
- Benutzer: derselbe wie vor der Neuinstallation (`BACKUP_USER`) – der Name ist im systemd-Service, in den Web-Wrappern, in Cron, sudoers und Apache hinterlegt, und das Backup enthält seine Pfade
- SSH aktivieren, Anmeldung per Passwort
- kein WLAN nötig

Den Pi per Netzwerkkabel anschließen und starten.

### Schritt 3: Alten Host-Key entfernen

Der neu installierte Pi hat neue SSH-Hostschlüssel. Auf dem eigenen Rechner die alten entfernen; ohne diesen Schritt bricht SSH mit `REMOTE HOST IDENTIFICATION HAS CHANGED` ab:

```bash
ssh-keygen -R <pi-host>
ssh-keygen -R <pi-ip>          # zusätzlich die IP des Pi
ssh <pi-user>@<pi-host>        # neuen Fingerprint mit "yes" bestätigen
```

### Schritt 4: Backup und Installer auf den Pi kopieren

Im Repository-Checkout auf dem eigenen Rechner:

```bash
scp ~/timelapse-backup/pi-backup.tar.gz.enc \
    ~/timelapse-backup/pi-crontab.txt \
    ~/timelapse-backup/config.json \
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
| `packages` | installiert Git, Python, FFmpeg, SSHFS, OpenSSL, Apache und PHP; aktiviert `user_allow_other` in `/etc/fuse.conf` |
| `clone` | klont das Repository nach `~/timelapse`; bricht ab, wenn dort bereits ein fremder oder nicht leerer Ordner liegt |
| `venv` | legt `.venv` an und installiert `requirements.txt` |
| `restore_backup` | fragt nach der Passphrase, entschlüsselt das Backup direkt in einen temporären Ordner, prüft die sudoers-Datei mit `visudo` und auf die Trigger- und Lösch-Regel (fehlt die Regel für Highlight-Bilder, nur eine Warnung), installiert alle Dateien mit festen Eigentümern und Rechten, übernimmt `config.json` und die Crontab |
| `known_hosts` | überspringt, wenn der Storage-Box-Host bereits bekannt ist; sonst werden die Fingerprints angezeigt und müssen mit `y` bestätigt werden |
| `sshfs_mount` | prüft, dass `User=` im systemd-Service der aktuelle Benutzer ist; installiert Preflight-Skript und systemd-Service und mountet `/mnt/cameras` |
| `apache` | aktiviert `zeitraffer.conf`, deaktiviert die Standardseite, führt `apache2ctl configtest` aus und lädt Apache neu |
| `web_bridge` | installiert Trigger, beide Lösch-Wrapper, Worker und Status-Skript unter `/usr/local` |
| `permissions` | setzt die Dateirechte aus [Dateirechte für `www-data`](../README.md#dateirechte-für-www-data) |
| `disable_wifi` | schaltet WLAN per `nmcli` ab und trägt `dtoverlay=disable-wifi` in `/boot/firmware/config.txt` ein; wird übersprungen, wenn die SSH-Sitzung selbst über WLAN läuft |
| `verify` | führt die Testsuite aus und prüft Mount, Crontab, HTTP-Status `401`, Lese- und Sperrrechte von `www-data`, die sudoers-Regeln, den Highlight-Lösch-Wrapper und den WLAN-Status |

Interaktive Abfragen während des Laufs:

- `sudo`-Passwort in `preflight`
- Passphrase des Backups in `restore_backup`
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
| `BACKUP_TAR` | `~/pi-backup.tar.gz.enc`, sonst `~/pi-backup.tar.gz` | Geheimnis-Archiv; ein unverschlüsseltes Archiv aus älteren Backups wird ohne Passphrase gelesen |
| `BACKUP_CRONTAB` | `~/pi-crontab.txt` | Crontab-Sicherung |
| `BACKUP_CONFIG` | `~/config.json` | optionale `config.json`; fehlt sie, bleibt die Git-Version |
| `DISABLE_WIFI` | `1` | `0` lässt WLAN unverändert |

Am Ende des Laufs die Ausgabe von `verify` durchsehen: Jede Zeile mit `WARNING` muss geklärt werden, bevor der Pi als fertig gilt.

### Schritt 6: Modelle, Zustand und Videos zurückkopieren

Vom eigenen Rechner aus:

```bash
rsync -a ~/timelapse-backup/models/ <pi-user>@<pi-host>:timelapse/models/
rsync -a ~/timelapse-backup/state/ <pi-user>@<pi-host>:timelapse/state/
rsync -a --progress ~/timelapse-backup/videos/ \
    <pi-user>@<pi-host>:timelapse/videos/
```

Ohne `models/` verweigern Verpixelung und Highlights-Flagger den Start.

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
   rm ~/pi-backup.tar.gz.enc ~/pi-crontab.txt ~/config.json
   ```

   Das Backup auf dem eigenen Rechner bleibt als Sicherung erhalten.

4. Der erste nächtliche Lauf um 02:00 Uhr erzeugt die automatischen Videos. Am nächsten Tag `logs/daily/<datum>.log` prüfen.

### Migration ohne Neuinstallation testen

Nach Änderungen an `migrate.sh` oder `backup.sh` lassen sich die Skripte auf dem laufenden Pi prüfen, ohne ihn neu aufzusetzen. Fast alle Schritte schreiben dort dieselben Inhalte, die bereits vorhanden sind; ein erfolgreicher Test endet deshalb mit einem unveränderten System. Nicht ausführen gegen 02:00 Uhr oder während ein Web-Job läuft.

Der Schritt `packages` wird dabei ausgelassen: `apt-get install` aktualisiert die genannten Pakete, wenn neuere Versionen verfügbar sind, und wäre damit eine echte Änderung am System.

1. Frisches Backup erstellen (siehe Schritt 1) und vom eigenen Rechner auf den Pi kopieren:

   ```bash
   scp ~/timelapse-backup/{pi-backup.tar.gz.enc,pi-crontab.txt,config.json} <pi-user>@<pi-host>:~/
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

Zum Schluss die Test- und Backup-Dateien auf dem Pi löschen, da sie Geheimnisse enthalten. Das Original bleibt auf dem eigenen Rechner:

```bash
rm ~/pre-test-crontab.txt ~/pre-test.sha256 ~/pi-backup.tar.gz.enc ~/pi-crontab.txt ~/config.json
sudo rm ~/pre-test-rollback.tar.gz
```

Nicht abgedeckt sind der Schritt `packages` und ein Lauf auf einem wirklich leeren System; das lässt sich nur mit einer zweiten SD-Karte oder einem zweiten Pi prüfen.

### Fehlerbehebung

| Symptom | Ursache und Lösung |
|---|---|
| Browser zeigt `403 Forbidden` | `www-data` kommt nicht ins Projekt: `~/migrate.sh permissions verify`; Details in `/var/log/apache2/zeitraffer-error.log` |
| Video-Bibliothek leer oder Videos laden nicht | Videos nach dem Kopieren nicht lesbar: `~/migrate.sh permissions` |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` auf dem eigenen Rechner | Schritt 3 ausführen |
| `Could not decrypt ... (wrong passphrase?)` | falsche Passphrase; `~/migrate.sh` erneut starten. Ohne die richtige Passphrase lässt sich das Archiv nicht öffnen |
| `Backed-up sudoers file does not parse` oder `lacks the ... rule` | sudoers-Datei im Backup beschädigt oder unvollständig; aus dem Backup wurde noch nichts installiert. Archiv reparieren (siehe unten) und `~/migrate.sh` erneut ausführen |
| `Host key not confirmed` | Fingerprints stimmten nicht oder wurden abgelehnt. Mit dem Anbieter klären, dann `~/migrate.sh known_hosts sshfs_mount` |
| `cameras-sshfs is not running` | `systemctl status cameras-sshfs.service` und `journalctl -u cameras-sshfs.service`; häufig fehlt der Host-Key oder `mount.env` ist leer |
| `skipping WiFi disable` | Sitzung lief über WLAN. Per Kabel neu verbinden und `~/migrate.sh disable_wifi` |
| Web-Job startet nicht oder Löschen schlägt fehl | `sudo -l -U www-data` muss beide Wrapper zeigen; sonst sudoers wie unter [Wrapper installieren](../README.md#wrapper-installieren) prüfen |
| `is already a git repo, but its origin ... doesn't match` | unter `~/timelapse` liegt ein anderes Repository; verschieben oder `REPO_URL` korrigieren |

sudoers-Datei im Backup-Archiv reparieren (auf dem Pi). Das Ergebnis ist ein unverschlüsseltes `~/pi-backup.tar.gz`, das `migrate.sh` liest, sobald die `.enc`-Datei entfernt ist; nach der Migration löschen:

```bash
mkdir ~/backup-fix
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -in ~/pi-backup.tar.gz.enc \
  | sudo tar xzf - -C ~/backup-fix
sudo nano ~/backup-fix/etc/sudoers.d/timelapse-web   # beide Regeln aus „Wrapper installieren“
sudo visudo -cf ~/backup-fix/etc/sudoers.d/timelapse-web
sudo tar czf ~/pi-backup.tar.gz -C ~/backup-fix .
sudo chown "$(id -un):$(id -gn)" ~/pi-backup.tar.gz
sudo rm -rf ~/backup-fix
rm ~/pi-backup.tar.gz.enc
~/migrate.sh
```
