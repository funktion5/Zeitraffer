# Umzug auf den VPS

Einmaliger Umzug vom Raspberry Pi auf den VPS (Debian 13). Der Pi wird danach stillgelegt, deshalb
ist das Backup einmalig und es gibt keinen Rückweg. `install.sh` im Projektordner richtet den VPS
ein; dieser Ablauf sagt, was davor und danach von Hand passiert. Platzhalter: `<vps>` ist der
ssh-Alias des VPS in `~/.ssh/config` des Macs, `<pi-user>@<pi-host>` der Pi und `<backup-ordner>`
der Ordner `DEST` aus `backup.env` (Standard `~/timelapse-backup`). Er sollte nicht unter
`~/Documents` liegen: Ist dort die iCloud-Synchronisierung an, würden auch die unverschlüsselten
Videos hochgeladen.

**Stand 09.11.2026:** Der Umzug ist abgeschlossen, der VPS läuft seit dem 30.10.2026. Die Crontab
des Pi ist leer, die Crontab des VPS enthält eine Zeile (02:00: Verpixelung nachholen, Nachtlauf,
Upload der Videos auf die Website, danach der Flagger); es ist dieselbe Zeile, die
`./install.sh cron_hint` druckt ([betrieb.md](betrieb.md#nächtlicher-produktionslauf)). Die
Läufe vom 7. bis 9.11.2026 gingen mit allen 17 Kameras ohne Fehler durch.

Der Unterschied zum Pi: Es gibt keinen SSHFS-Mount. Die Jobs lesen die Bilder per ssh von der
Storage Box und holen sie bei jedem Lauf per rsync (`scripts/timelapse-nightly-staged`; der frühere
Plan liegt im [Archiv](../archive/staging/docs/plans/web-server-nightly-run.md)).
Das Projekt muss in `~/timelapse` liegen, weil die installierten Web-Wrapper dort suchen.

## 1. Auf dem Mac: Backup (einmalig)

Videos zuerst in den Backup-Ordner holen, dann der Rest (Geheimnisse, Modell, `state/`):

```bash
rsync -a --progress <pi-user>@<pi-host>:~/timelapse/videos/ <backup-ordner>/videos/
SKIP_VIDEOS=1 ./backup.sh
```

`backup.sh` fragt eine Passphrase ab (Passwortmanager, ohne sie ist das Backup wertlos) und das
sudo-Passwort des Pi. Nichts wird auf dem Pi zurückgelassen.

## 2. Auf dem VPS: Repo, Schlüssel und Eintrag für die Storage Box

```bash
git clone https://github.com/funktion5/Zeitraffer.git ~/timelapse
ssh-keygen -t ed25519 -f ~/.ssh/<schluessel> -N ""
```

Ohne Passphrase, weil Cron den Schlüssel ohne Eingabe braucht. Der Schlüssel dient nur der Storage
Box; der Schlüssel des Pi wird nicht übernommen. Dann in `~/.ssh/config` einen Eintrag anlegen
(Benutzer, Host und Port der Box stehen in `/etc/timelapse/mount.env` auf dem Pi):

```text
Host storagebox
    HostName <box-host>
    User <box-user>
    Port <box-port>
    IdentityFile ~/.ssh/<schluessel>
    IdentitiesOnly yes
```

Der Name hinter `Host` ist frei; `install.sh` erwartet `storagebox`, ein anderer Name kommt als
`BOX_ALIAS=<name> ./install.sh`. Den öffentlichen Teil auf die Box bringen, bei Hetzner laut deren
Doku über SFTP:

```bash
ssh-copy-id -s -i ~/.ssh/<schluessel>.pub storagebox
```

Die Option `-s` bitte gegen die aktuelle Hetzner-Doku prüfen; die Box muss dafür Passwort-Login
erlauben. Den angezeigten Host-Fingerabdruck mit dem aus der Hetzner-Oberfläche vergleichen. Wenn der
Pi stillgelegt ist, seinen Schlüssel auf der Box entfernen.

## 3. Backup auf den VPS kopieren

Vom Mac aus, in den Home-Ordner des VPS:

```bash
scp <backup-ordner>/pi-backup.tar.gz.enc <backup-ordner>/config.json <vps>:~/
```

`pi-crontab.txt` wird nicht gebraucht: Die Pi-Cron-Zeilen dürfen nicht auf den VPS.

## 4. Auf dem VPS: `install.sh`

```bash
cd ~/timelapse
SERVER_NAME=<subdomain> WEB_PORT=55222 ./install.sh
```

`install.sh` ist nicht an diesen VPS gebunden: Es braucht nur ein frisches Debian oder Ubuntu mit
sudo, nimmt Name, Port und ssh-Alias aus Variablen und leitet den Projektpfad aus seinem eigenen
Ort ab. Auf einem anderen Rechner (etwa einem Pi 5) laufen dieselben Schritte. Pi-spezifisches wie
WLAN abschalten oder Absturzprotokolle gehört nicht dazu.

Der Installer prüft zuerst, ob der `Host`-Eintrag und sein Schlüssel existieren. Dann fragt er nach
dem sudo-Passwort und der Backup-Passphrase, installiert Pakete, legt die virtuelle Umgebung an,
bestätigt den Host-Fingerabdruck der Box, richtet Apache (HTTP mit Basisauthentifizierung, die
htpasswd kommt aus dem Backup), Wrapper und sudoers ein und setzt die Dateirechte. Er ist
wiederholbar, einzelne Schritte laufen mit `./install.sh <schritt> [<schritt> ...]`. Zum Schluss
steht die Cron-Zeile in der Ausgabe; installiert wird sie nicht.

Aus dem Backup kommt nur die htpasswd (und optional `config.json`). Absichtlich nicht übernommen:
Pi-Crontab, sudoers- und vhost-Datei des Pi (sie nennen den Pi-Benutzer und HTTP ohne Namen) und
alle SSH-Schlüssel des Pi.

## 5. Modell, Status und Videos kopieren

Vom Mac aus:

```bash
rsync -a <backup-ordner>/models/ <vps>:~/timelapse/models/
rsync -a <backup-ordner>/state/ <vps>:~/timelapse/state/
rsync -a --progress <backup-ordner>/videos/ <vps>:~/timelapse/videos/
```

Die Videos zuletzt: Sie sind groß (bei der Planung 4,6 GB) und der Befehl lässt sich nach einem
Abbruch einfach wiederholen. Prüfen, ob alles angekommen ist (`install.sh verify` prüft das nicht):

```bash
ssh <vps> 'du -sh ~/timelapse/videos ~/timelapse/state ~/timelapse/models'
```

Danach auf dem VPS `./install.sh permissions verify`. Die Videos müssen vor dem ersten nächtlichen
Lauf da sein: Der Weekly-Job fügt vorhandene Daily-Videos zusammen und braucht keine eigenen Bilder.

## 6. Weboberfläche ansehen

Der vhost ist HTTP mit Basisauthentifizierung, das Passwort ginge also unverschlüsselt über das
Netz. Bis es HTTPS gibt, die Seite über einen ssh-Tunnel öffnen (lokaler Port 8055, weil 8080 der
lokale WordPress-Entwicklungsstack belegt):

```bash
ssh -L 8055:localhost:55222 <vps>
```

Dann im Browser `http://localhost:8055/` öffnen. Der Port 55222 muss dafür in der Firewall nicht
offen sein.

## 7. Von Hand prüfen, dann Cron

Ein Tag, eine Kamera, vom Menschen ausgeführt. Auf dem VPS im Projektordner:

```bash
export TIMELAPSE_STORAGE_BOX=storagebox
.venv/bin/python3 -m src.camera_list
.venv/bin/python3 -m src.main --jobs daily --target-date <JJJJ-MM-TT> --cameras <kamera>
```

`src.camera_list` listet die Kameras und schreibt die Kameraliste der Weboberfläche. `src.main` holt
die Bilder des Tages per rsync nach `temp/frame-cache/` und räumt sie nach der Kamera wieder weg.
Danach als Gesamtprobe den ganzen Nachtlauf einmal von Hand starten
([Handbuch](handbuch.md#nächtlicher-lauf)). Der Lauf vom 29.10.2026 ging mit 16 Kameras ohne Fehler
durch und dauerte rund 41 Minuten (Preset `medium`, zwei Kerne).

Einen Tag wählen, zu dem der Pi schon ein Video hat, und beide vergleichen. Historische Läufe mit
`--target-date` landen getrennt von den automatischen Videos (siehe [betrieb.md](betrieb.md)).
Erst wenn das passt: Pi-Cron entfernen, die Zugangsdaten für den Upload in `config/siteground.env`
anlegen und den Upload als Trockenlauf prüfen (`scripts/copy_zeitraffer_videos_vps2siteground.sh`
ohne `--run`, siehe [betrieb.md](betrieb.md#upload-auf-die-website)), dann die Zeile aus
`./install.sh cron_hint` in `crontab -e` einfügen. Dieselbe Aufgabe darf nie auf beiden Hosts
laufen.

## Code auf den VPS bringen

Das Repository ist öffentlich, der VPS holt den Code mit `git pull` über HTTPS vom Zweig `main`
(ohne Deploy-Schlüssel). Auf dem Mac speichern und pushen, dann auf dem VPS:

```bash
cd ~/timelapse && git pull
```

Danach auf dem VPS die Tests und die Stilprüfung laufen lassen:

```bash
.venv/bin/python3 -m pytest -q && .venv/bin/python3 -m ruff check . && .venv/bin/python3 -m ruff format --check .
```

- **Läuft gerade ein Job?** Prüfen mit `ps -eo pid,etime,cmd | grep "[s]rc.main"`. Dann vorher
  `git fetch && git diff --stat HEAD origin/main` ansehen: Änderungen nur in Dokumenten, Tests und
  Plänen sind unkritisch. Betrifft der Unterschied `src/`, `scripts/` oder `config/`, erst nach dem
  Job pullen, denn der laufende Job liest diese Dateien.
- **Neue Ordner:** danach einmal `./install.sh permissions`.
- **Geänderte Dateien in `scripts/web/`:** `./install.sh web_bridge` kopiert sie neu nach
  `/usr/local` (die Web-Wrapper laufen als root-eigene Kopien).
- `./install.sh` nur starten, wenn kein Job läuft.
- Wurden Dateien verschoben oder gelöscht, entfernt `git pull` sie auch auf dem VPS; liegen bleiben
  nur ignorierte Dateien (`temp/`, `logs/`, `state/`, `videos/`).

## Bekannte Lücken (nach dem Umzug klären)

- **TLS und Port:** Der vhost ist HTTP. Zertifikat per DNS-Prüfung über Hetzner kommt später; bis dahin
  die Seite nicht öffentlich erreichbar machen (Basic Auth ist ohne TLS unverschlüsselt).
- **Port 80:** Bei `WEB_PORT` ungleich 80 lauscht Apache weiter auf 80 (Debian-Standard in
  `ports.conf`) und zeigt dort die Debian-Standardseite. Auf dem VPS sperrt das die Hetzner-Firewall.
  Auf einem Host ohne Firewall `Listen 80` in `/etc/apache2/ports.conf` auskommentieren.
- **Flagger und laufende Verpixelung:** Der Flagger steht am Ende der 02:00-Zeile und startet damit
  erst nach dem Nachtlauf und dem Upload, ohne feste Uhrzeit. Die laufende Verpixelung neuer Bilder
  ist nicht in Cron (Entwurf: [Plan](plans/2026-10-30-live-blur-cron.md)).
- **Zugangsdaten für den Upload:** `install.sh` legt `config/siteground.env` nicht an (die Datei
  ist nicht im Repository). Auf einem frisch eingerichteten Host muss sie von Hand entstehen
  ([Upload auf die Website](betrieb.md#upload-auf-die-website)); `./install.sh verify` warnt, wenn
  sie oder einer ihrer drei Werte fehlt.
- **Upload ohne Verschlüsselung:** Das Upload-Skript nutzt einfaches FTP (`ftp://`). Die Zugangsdaten
  stehen in `config/siteground.env`, nicht im Repository.
- **Weboberfläche für das Team:** Die Oberfläche des Pi zeigt seit dem Umzug keine neuen Videos
  mehr. Der Zugang zur Oberfläche des VPS (HTTP auf `WEB_PORT`, HTTPS steht aus) ist für die
  Kolleginnen und Kollegen noch zu klären.
- **x264-Qualität und Dateigröße:** Die Cron-Zeile setzt das Preset `medium` (FFmpeg-Standard, wie auf
  dem Pi); der Nachtlauf dauerte damit rund 41 Minuten (Lauf vom 29.10., noch mit dem früheren CRF).
  Die Qualität steht seit dem 30.10.2026 auf CRF 28 (`timelapse.crf` in `config/config.json`); an
  einem Jahresvideo (Uferstrasse) gemessen ist die Datei damit rund 53 % kleiner (9,9 statt 21,2 MiB).
  Die Laufzeit des Nachtlaufs mit CRF 28 zeigen die ersten Nächte ([Plan](plans/2026-10-30-video-crf.md)).
