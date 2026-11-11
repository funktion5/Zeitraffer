# Einen VPS einrichten

Einrichtung eines Hosts (Debian 13) für den Zeitraffer. Der Betrieb lief zuerst auf einem
Raspberry Pi und ist seit dem 30.10.2026 auf dem VPS; der Pi ist stillgelegt. `install.sh` im
Projektordner richtet einen frischen Host ein; dieser Ablauf sagt, was davor und danach von Hand
passiert. Platzhalter: `<vps>` ist der ssh-Alias des neuen Hosts in `~/.ssh/config` des Macs,
`<alter-host>` der ssh-Alias des bisherigen Hosts. Die Sicherung liegt standardmäßig in
`~/timelapse-backup` (auf dem Mac wie auf dem neuen Host). Wird ein anderer Ordner gewählt, sollte
er nicht unter `~/Documents` liegen: Ist dort die iCloud-Synchronisierung an, würden auch die
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

## 1. Auf dem Mac: Sicherung vom bisherigen Host (optional)

Solange der bisherige Host noch läuft, sichert `backup.sh` (im Repository-Ordner auf dem Mac
gestartet), was der neue Host braucht und nicht im Git liegt: das Erkennungsmodell (`models/`), den
Status (`state/` ohne Sperrdateien, Laufmarke und `web-jobs/`, darin der Status der Verpixelung), die
beiden Einstellungsdateien der Weboberfläche (`config/settings.json` und `config/settings-privacy.json`,
falls vorhanden; sonst nichts aus `config/`) und die Crontab zum Nachlesen; mit `VIDEOS=1` auch die Videos
(ohne versteckte Dateien). Es liest nur
vom Host (ssh und rsync, kein sudo) und schreibt dort nichts.

```bash
BACKUP_HOST=<alter-host> ./backup.sh              # models/, state/, die beiden settings-Dateien, crontab.txt
BACKUP_HOST=<alter-host> VIDEOS=1 ./backup.sh     # zusätzlich videos/
```

Statt der Variablen geht auch eine Datei `backup.env` neben dem Skript (Vorlage:
`backup.env.example`, nicht versioniert); `PROJECT_DIR` und `DEST` stellen den Projektordner auf dem
Host und das Ziel um; ein geändertes `DEST` muss beim Kopieren (Schritt 3) und als `BACKUP_DIR` beim
Installieren (Schritt 5) wieder auftauchen. Die Sicherung ist nur für den eigenen Benutzer lesbar.
Fehlermeldungen:
[Handbuch](handbuch.md#fehler-sicherung-und-wiederherstellung).

**Was nicht in der Sicherung ist, mit Absicht:** keine Geheimnisse. Die Anmeldung der Weboberfläche
legt `install.sh` neu an, das Passwort des Uploads trägt man von Hand ein (beides siehe Schritt 4),
und der ssh-Schlüssel für die Storage Box ist pro Host ein neuer (Schritt 2).

- **`state/` nicht weglassen:** Ohne `state/privacy/box/` kennt der neue Host keinen bestätigten
  Frame, und die [Sperre](verpixelung-box.md#sperre-in-automatischen-videos) lässt dann die Monats-
  und Jahresvideos der Blur-Kameras aus, bis die Bilder neu bestätigt sind.
- **Die Einstellungsdateien** enthalten die Änderungen der Kolleginnen und Kollegen auf der Seite
  „Einstellungen“ ([konfiguration.md](konfiguration.md#einstellungen-der-weboberfläche)). Ohne sie
  zeigt der neue Host wieder die Werte aus `config.json`, auch bei den Verpixelungs-Kameras. Sie
  liegen nur auf dem Host, nicht im Git.
- **Das Modell** lässt sich auch neu laden ([verpixelung.md](verpixelung.md#installation)).
- **Die Videos** sind groß (bei der Planung 4,6 GB) und optional: Der nächtliche Lauf baut neue. Der
  Weekly-Job fügt aber nur vorhandene Daily-Videos zusammen und braucht keine eigenen Bilder; ohne
  gesicherte Videos fehlen ihm anfangs die Dailys.

## 2. Auf dem VPS: Repo, Schlüssel und Eintrag für die Storage Box

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

## 3. Sicherung auf den neuen Host kopieren (optional)

Vom Mac aus, in den Ordner, den `install.sh` standardmäßig liest:

```bash
rsync -a ~/timelapse-backup/ <vps>:~/timelapse-backup/
```

Mit Videos dauert das länger; der Befehl lässt sich nach einem Abbruch einfach wiederholen. Prüfen,
ob alles angekommen ist (`install.sh verify` prüft das nicht):

```bash
ssh <vps> 'du -sh ~/timelapse-backup/*'
```

## 4. Zugangsdaten der Weboberfläche und des Uploads

Hier ist nichts zu kopieren: `install.sh` legt beides selbst an.

- **Weboberfläche:** Im Schritt `web_login` fragt es nach einem Benutzernamen (oder nimmt
  `HTPASSWD_USER`) und danach nach dem Passwort; das Passwort landet weder in einem Argument noch in
  einer Datei oder im Protokoll. Gibt es `/etc/apache2/.htpasswd` schon, bleibt die Datei
  unverändert. Weitere Benutzer später: `sudo htpasswd -B /etc/apache2/.htpasswd <login>`.
- **Upload auf die Website:** Im Schritt `upload_login` kopiert es die Vorlage
  `config/siteground.env.example` nach `config/siteground.env` (nur für den Benutzer lesbar). Die
  Datei ist **leer**: die drei Werte `SITEGROUND_HOST`, `SITEGROUND_USER` und `SITEGROUND_PASS`
  trägt man von Hand ein. Bis dahin schlägt der nächtliche Upload fehl, und `./install.sh verify`
  warnt. Eine vorhandene Datei bleibt bei jedem Lauf unverändert.

Die Cron-Zeilen des bisherigen Hosts dürfen nicht auf den neuen Host.

## 5. Auf dem VPS: `install.sh`

```bash
cd ~/timelapse
SERVER_NAME=<subdomain> WEB_PORT=55222 ./install.sh
```

`install.sh` ist nicht an diesen VPS gebunden: Es braucht nur ein frisches Debian oder Ubuntu mit
sudo, nimmt Name, Port und ssh-Alias aus Variablen und leitet den Projektpfad aus seinem eigenen
Ort ab. Auf einem anderen Rechner (etwa einem Pi 5) laufen dieselben Schritte. Pi-spezifisches wie
WLAN abschalten oder Absturzprotokolle gehört nicht dazu.

Der Installer prüft zuerst, ob der `Host`-Eintrag und sein Schlüssel existieren. Dann fragt er nach
dem sudo-Passwort und führt der Reihe nach aus: Pakete installieren, virtuelle Umgebung anlegen,
Anmeldung der Weboberfläche anlegen (`web_login`), Login-Datei des Uploads anlegen (`upload_login`),
eine Sicherung zurückspielen (`restore`), den Host-Fingerabdruck der Box bestätigen
(`known_hosts`), Apache (HTTP mit Basisauthentifizierung), Wrapper und sudoers einrichten und die
Dateirechte setzen. Zum Schluss prüft `verify` das Ergebnis, und die Cron-Zeile steht in der
Ausgabe; installiert wird sie nicht. Der Installer ist wiederholbar, einzelne Schritte laufen mit
`./install.sh <schritt> [<schritt> ...]`.

`restore` liest `~/timelapse-backup` (`BACKUP_DIR` nennt einen anderen absoluten Pfad). Gibt es den
Ordner nicht, wird der Schritt übersprungen und der Host fängt leer an. Sonst kopiert er `models/`,
`state/`, `videos/` und die beiden Einstellungsdateien aus der Sicherung ins Projekt, überschreibt dabei nie eine vorhandene Datei
und löscht nichts; die Crontab aus der Sicherung wird nicht installiert. Wurde die Sicherung erst
nach dem Installieren kopiert: `./install.sh restore permissions verify`.

Außer dem Inhalt der Sicherung wird nichts vom bisherigen Host übernommen; `config/config.json`
kommt aus Git. Absichtlich auch nicht: Crontab, sudoers- und vhost-Datei des bisherigen Hosts (sie nennen dessen Benutzer) und
alle seine SSH-Schlüssel.

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

Einen Tag wählen, zu dem der bisherige Host schon ein Video hat, und beide vergleichen.
Historische Läufe mit `--target-date` landen getrennt von den automatischen Videos (siehe
[betrieb.md](betrieb.md)). Erst wenn das passt: die Cron-Zeilen des bisherigen Hosts entfernen, die
drei Werte in `config/siteground.env` eintragen (die Datei hat `install.sh` aus der Vorlage
angelegt) und den Upload als Trockenlauf prüfen (`scripts/copy_zeitraffer_videos_vps2siteground.sh`
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
  Die Laufzeit des Nachtlaufs mit CRF 28 zeigen die ersten Nächte ([Plan](plans/done/2026-10-30-video-crf.md)).
