# Einen VPS einrichten

Einrichtung eines Hosts (Debian 13) für den Zeitraffer. Der Betrieb lief zuerst auf einem
Raspberry Pi und ist seit dem 30.10.2026 auf dem VPS; der Pi ist stillgelegt. `install.sh` im
Projektordner richtet einen frischen Host ein; dieser Ablauf sagt, was davor und danach von Hand
passiert. Platzhalter: `<vps>` ist der ssh-Alias des neuen Hosts in `~/.ssh/config` des Macs,
`<alter-host>` der bisherige Host und `<ordner>` ein Zwischenordner auf dem Mac. Er sollte nicht
unter `~/Documents` liegen: Ist dort die iCloud-Synchronisierung an, würden auch die
unverschlüsselten Videos hochgeladen.

**Stand 09.11.2026:** Der Umzug ist abgeschlossen, der VPS läuft seit dem 30.10.2026. Die Crontab
des Pi ist leer, die Crontab des VPS enthält eine Zeile (02:00: Verpixelung nachholen, Nachtlauf,
Upload der Videos auf die Website, danach der Flagger); es ist dieselbe Zeile, die
`./install.sh cron_hint` druckt ([betrieb.md](betrieb.md#nächtlicher-produktionslauf)). Die
Läufe vom 7. bis 9.11.2026 gingen mit allen 17 Kameras ohne Fehler durch.

Der Unterschied zum Pi: Es gibt keinen SSHFS-Mount. Die Jobs lesen die Bilder per ssh von der
Storage Box und holen sie bei jedem Lauf per rsync (`scripts/timelapse-nightly-staged`; der frühere
Plan liegt im [Archiv](../archive/staging/docs/plans/web-server-nightly-run.md)).
Das Projekt muss in `~/timelapse` liegen, weil die installierten Web-Wrapper dort suchen.

## 1. Auf dem VPS: Repo, Schlüssel und Eintrag für die Storage Box

```bash
git clone https://github.com/funktion5/Zeitraffer.git ~/timelapse
ssh-keygen -t ed25519 -f ~/.ssh/<schluessel> -N ""
```

Ohne Passphrase, weil Cron den Schlüssel ohne Eingabe braucht. Der Schlüssel dient nur der Storage
Box; der Schlüssel des bisherigen Hosts wird nicht übernommen. Dann in `~/.ssh/config` einen
Eintrag anlegen (Benutzer, Host und Port der Box stehen in der `~/.ssh/config` des bisherigen Hosts
oder in der Hetzner-Oberfläche):

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
erlauben. Den angezeigten Host-Fingerabdruck mit dem aus der Hetzner-Oberfläche vergleichen. Ist der
bisherige Host stillgelegt, seinen Schlüssel auf der Box entfernen.

## 2. Zugangsdaten der Weboberfläche

Hier ist nichts zu kopieren: `install.sh` legt die Anmeldung der Weboberfläche im Schritt
`web_login` selbst an. Es fragt nach einem Benutzernamen (oder nimmt `HTPASSWD_USER`) und danach
nach dem Passwort; das Passwort landet weder in einem Argument noch in einer Datei oder im
Protokoll. Gibt es `/etc/apache2/.htpasswd` schon, bleibt die Datei unverändert. Weitere Benutzer
später: `sudo htpasswd -B /etc/apache2/.htpasswd <login>`.

Die Cron-Zeilen des bisherigen Hosts dürfen nicht auf den neuen Host.

## 3. Auf dem VPS: `install.sh`

```bash
cd ~/timelapse
SERVER_NAME=<subdomain> WEB_PORT=55222 ./install.sh
```

`install.sh` ist nicht an diesen VPS gebunden: Es braucht nur ein frisches Debian oder Ubuntu mit
sudo, nimmt Name, Port und ssh-Alias aus Variablen und leitet den Projektpfad aus seinem eigenen
Ort ab. Auf einem anderen Rechner (etwa einem Pi 5) laufen dieselben Schritte. Pi-spezifisches wie
WLAN abschalten oder Absturzprotokolle gehört nicht dazu.

Der Installer prüft zuerst, ob der `Host`-Eintrag und sein Schlüssel existieren. Dann fragt er nach
dem sudo-Passwort, installiert Pakete, legt die virtuelle Umgebung an, legt die Anmeldung der
Weboberfläche an (Benutzername und Passwort, Schritt `web_login`), bestätigt den Host-Fingerabdruck
der Box, richtet Apache (HTTP mit Basisauthentifizierung), Wrapper und sudoers ein und setzt die
Dateirechte. Er ist
wiederholbar, einzelne Schritte laufen mit `./install.sh <schritt> [<schritt> ...]`. Zum Schluss
steht die Cron-Zeile in der Ausgabe; installiert wird sie nicht.

Vom bisherigen Host wird nichts übernommen; `config/config.json` kommt aus Git. Absichtlich
auch nicht: Crontab, sudoers- und vhost-Datei des bisherigen Hosts (sie nennen dessen Benutzer) und
alle seine SSH-Schlüssel.

## 4. Modell, Status und Videos vom bisherigen Host kopieren

Vom Mac aus, zuerst vom bisherigen Host in den Zwischenordner, dann auf den neuen Host (die beiden
Hosts sprechen nicht direkt miteinander). Es sind die Befehle des Umzugs vom Pi, nur mit dem
bisherigen Host als Quelle:

```bash
rsync -a <alter-host>:timelapse/models/ <ordner>/models/
rsync -a <alter-host>:timelapse/state/ <ordner>/state/
rsync -a --progress <alter-host>:timelapse/videos/ <ordner>/videos/

rsync -a <ordner>/models/ <vps>:~/timelapse/models/
rsync -a <ordner>/state/ <vps>:~/timelapse/state/
rsync -a --progress <ordner>/videos/ <vps>:~/timelapse/videos/
```

Das Modell lässt sich auch neu laden ([verpixelung.md](verpixelung.md#installation)). Den Status
(`state/`) nicht weglassen: Ohne `state/privacy/box/` kennt der neue Host keinen bestätigten Frame,
und die [Sperre](verpixelung-box.md#sperre-in-automatischen-videos) lässt dann die Monats- und
Jahresvideos der Blur-Kameras aus, bis die Bilder neu bestätigt sind.

Die Videos zuletzt: Sie sind groß (bei der Planung 4,6 GB) und der Befehl lässt sich nach einem
Abbruch einfach wiederholen. Prüfen, ob alles angekommen ist (`install.sh verify` prüft das nicht):

```bash
ssh <vps> 'du -sh ~/timelapse/videos ~/timelapse/state ~/timelapse/models'
```

Danach auf dem VPS `./install.sh permissions verify`. Die Videos müssen vor dem ersten nächtlichen
Lauf da sein: Der Weekly-Job fügt vorhandene Daily-Videos zusammen und braucht keine eigenen Bilder.

## 5. Weboberfläche ansehen

Der vhost ist HTTP mit Basisauthentifizierung, das Passwort ginge also unverschlüsselt über das
Netz. Bis es HTTPS gibt, die Seite über einen ssh-Tunnel öffnen (lokaler Port 8055, weil 8080 der
lokale WordPress-Entwicklungsstack belegt):

```bash
ssh -L 8055:localhost:55222 <vps>
```

Dann im Browser `http://localhost:8055/` öffnen. Der Port 55222 muss dafür in der Firewall nicht
offen sein.

## 6. Von Hand prüfen, dann Cron

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

Einen Tag wählen, zu dem der bisherige Host schon ein Video hat, und beide vergleichen. Historische Läufe mit
`--target-date` landen getrennt von den automatischen Videos (siehe [betrieb.md](betrieb.md)).
Erst wenn das passt: die Cron-Zeilen des bisherigen Hosts entfernen, die drei Werte in `config/siteground.env`
eintragen (die Datei hat `install.sh` aus der Vorlage angelegt) und den Upload als Trockenlauf prüfen (`scripts/copy_zeitraffer_videos_vps2siteground.sh`
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
- **Passwort des Uploads:** `install.sh` legt `config/siteground.env` im Schritt `upload_login` aus
  der Vorlage `config/siteground.env.example` an, aber leer. Die drei Werte trägt man von Hand ein
  ([Upload auf die Website](betrieb.md#upload-auf-die-website)); `./install.sh verify` warnt, solange
  einer fehlt.
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
