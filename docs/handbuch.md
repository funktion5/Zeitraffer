# Handbuch

Für Entwicklerinnen und Entwickler, die Zeitraffer betreuen: wie es installiert wird, wie man jeden
Job startet und was bei Fehlern zu tun ist. Die ausführlichen Beschreibungen stehen im
[README](../README.md) und in den anderen Dateien in diesem Ordner; dieses Handbuch verweist dorthin,
statt sie zu wiederholen.

In den Befehlen steht `~/timelapse` für den Projektordner und `<Kamera>`, `<Datum>` (JJJJ-MM-TT)
für die jeweiligen Werte.

## Inhalt

- [Überblick](#überblick)
- [Installation](#installation)
- [Jobs starten](#jobs-starten)
- [Fehler: nächtlicher Lauf](#fehler-nächtlicher-lauf)
- [Fehler: Weboberfläche](#fehler-weboberfläche)
- [Fehler: Erkennung, Highlights und Verpixelung](#fehler-erkennung-highlights-und-verpixelung)
- [Fehler: Sicherung und Wiederherstellung](#fehler-sicherung-und-wiederherstellung)
- [Fehler: Entwicklung und CI](#fehler-entwicklung-und-ci)
- [Raspberry Pi: Stabilität](#raspberry-pi-stabilität)

---

## Überblick

### Was wann läuft

| Was | Wann | Gestartet von |
|---|---|---|
| Nächtlicher Lauf (Daily, Weekly, Monthly, Yearly für alle Kameras) | 02:00 Uhr | Cron |
| Wiederholung des nächtlichen Laufs | nach einem Neustart, wenn der Lauf unterbrochen war | Cron (`@reboot`) |
| Videos für vergangene Zeiträume | bei Bedarf | Weboberfläche oder Befehl |
| Highlights-Flagger | direkt nach dem nächtlichen Lauf (ca. 03:30–04:10) | Cron |
| Verpixelung auf der Storage Box | bei Bedarf (noch nicht in Cron) | Befehl |
| Speicherfilter, Yearly-Backfill, NAS-Werkzeuge, Sicherung | bei Bedarf | Befehl |

### Wo was liegt

| Was | Wo |
|---|---|
| Kamerabilder (Original, **nur lesen**) | `/mnt/cameras/<Kamera>/` (SSHFS-Mount der Storage Box) |
| Einstellungen | `config/config.json` |
| Nächtliche Videos | `videos/<Kamera>/{daily,weekly,monthly,yearly}/` |
| Videos aus Weboberfläche und Befehl | `videos/<Kamera>/manual-runs/<job>/` |
| Highlights | `videos/<Kamera>/highlights/<Datum>/` |
| Protokolle | `logs/<job>/<Datum des Laufs>.log`, z. B. `logs/daily/`, `logs/flagger/` |
| Laufsperre | `state/zeitraffer-run.lock` |
| Marker „nächtlicher Lauf unterbrochen“ | `state/run-in-progress` |
| Status der Web-Aufträge | `state/web-jobs/` |
| Zwischendateien | `temp/` |
| Installierte Web-Wrapper | `/usr/local/sbin/`: `timelapse-web-trigger` (Video-Auftrag starten), `timelapse-web-delete` (Video löschen), `timelapse-web-delete-highlight` (Highlight-Bild löschen); `/usr/local/libexec/`: `timelapse-web-worker`, `timelapse-web-status.sh` |
| Weitere installierte Skripte | `/usr/local/sbin/cameras-sshfs-preflight` (räumt vor dem Mount auf), `/usr/local/sbin/pi-health-logger` (nur wenn das Absturz-Logging eingerichtet ist) |
| Apache-Fehlerprotokoll | `/var/log/apache2/zeitraffer-error.log` |

### Grundregeln

- **Immer nur ein Lauf auf einmal.** Nächtlicher Lauf, Web-Aufträge, Flagger, Speicherfilter,
  Backfill und Verpixelung teilen sich die Sperre `state/zeitraffer-run.lock`. Wer sie nicht
  bekommt, bricht ab oder überspringt.
- **Nie auf `/mnt/cameras` schreiben.** Der Mount ist schreibgeschützt; die Originale bleiben
  unverändert.
- **Ein Lauf kann „erfolgreich“ enden, obwohl Kameras fehlten.** Der Exit-Code ist dann trotzdem 0.
  Maßgeblich ist die Zusammenfassung am Ende jedes Jobs (siehe unten).
- **Die Web-Wrapper laufen aus installierten Kopien.** Eine Änderung unter `scripts/` wirkt erst nach
  `sudo install` (siehe [README: Wrapper installieren](../README.md#wrapper-installieren)).
- **Ein Neustart von Apache beendet einen laufenden Web-Auftrag.** Vorher `ls state/web-jobs/*.pid`
  prüfen.

### Läuft gerade etwas?

```bash
cd ~/timelapse
flock -n state/zeitraffer-run.lock -c true && echo "Sperre frei" || echo "Sperre belegt"
pgrep -af "src.main|src.flagger|storage_filter|yearly-backfill|blur_box|stage-frames"
```

### Zusammenfassung eines Laufs lesen

Jeder Job endet mit einer Zeile wie:

```text
2026-10-22 02:05:21,134 | INFO | Daily timelapse job finished for 2026-10-21 | created=10 | skipped=4 | failed=0 | run_id=20261022T020002-1278463
```

`created` = neue Videos, `skipped` = Kameras ohne genug Bilder (meist harmlos, siehe unten),
`failed` = Kameras mit einem echten Fehler. Alle Zusammenfassungen eines Tages:

```bash
grep -h "job finished" ~/timelapse/logs/*/$(date +%F).log
```

---

## Installation

Kurzfassung als Checkliste. Die vollständigen Schritte stehen im
[README unter Installation](../README.md#installation); für einen Raspberry Pi mit vorhandener
Sicherung erledigt `migrate.sh` alles ([raspberry-pi.md](raspberry-pi.md)).

| # | Schritt | Funktioniert, wenn |
|---|---|---|
| 1 | Systempakete installieren ([README](../README.md#systempakete-installieren)) | `ffmpeg -version`, `sshfs -V`, `php -v`, `rsync --version` antworten |
| 2 | Python 3.13 und virtuelle Umgebung ([README](../README.md#python-umgebung-einrichten)) | `.venv/bin/python3 --version` zeigt 3.13 |
| 3 | Erkennungsmodelle nach `models/` ([verpixelung.md](verpixelung.md#installation)) | `ls models/` zeigt `object_detection_yolox_2022nov.onnx` |
| 4 | `config/config.json` anpassen ([README](../README.md#konfiguration)) | `.venv/bin/python3 -m pytest tests/config_test.py` grün |
| 5 | SSHFS-Mount einrichten ([README](../README.md#sshfs-mount-installieren)) | `mountpoint /mnt/cameras` meldet „is a mountpoint“ und `ls /mnt/cameras` zeigt die Kameras |
| 6 | Cron eintragen ([README](../README.md#cron-installieren-oder-prüfen)) | `crontab -l` zeigt die 02:00-Zeile und die `@reboot`-Zeile |
| 7 | Apache, Anmeldung, Wrapper, Dateirechte ([README](../README.md#weboberfläche-einrichten)) | `curl -s -o /dev/null -w '%{http_code}' http://localhost/` ergibt `401`; `./migrate.sh verify` (prüft nur, repariert nichts) zeigt kein `WARNING` |
| 8 | Tests | `.venv/bin/python3 -m pytest` grün |
| 9 | Ersten Lauf von Hand starten (siehe unten) | in `logs/daily/<Datum>.log` steht eine Zusammenfassung mit `created` > 0 |

---

## Jobs starten

Alle Befehle im Projektordner (`cd ~/timelapse`). Vorher prüfen, ob gerade etwas läuft (siehe
[Überblick](#läuft-gerade-etwas)). Lange Läufe, die das Schließen des Terminals überleben sollen,
abgekoppelt starten:

```bash
setsid nohup <befehl> > logs/manuell-$(date +%F_%H%M).out 2>&1 < /dev/null &
kill -TERM -- -<PID>      # abgekoppelten Lauf beenden (PID aus pgrep)
```

### Nächtlicher Lauf

Startet automatisch um 02:00 Uhr über Cron mit Sperre:

```text
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'
```

Von Hand (alle Kameras, alle vier Jobs, Zieltag gestern):

```bash
flock -n state/zeitraffer-run.lock -c '.venv/bin/python3 -m src.main'
```

### Einzelne Jobs und vergangene Zeiträume

```bash
.venv/bin/python3 -m src.main --jobs daily weekly                                # nur diese automatischen Jobs
.venv/bin/python3 -m src.main --jobs daily --target-date <Datum> --cameras <Kamera>
.venv/bin/python3 -m src.main --jobs weekly --target-date <Datum> --cameras <Kamera>   # genau eine Kamera
.venv/bin/python3 -m src.main --jobs monthly --target-date <Datum> --window-time sunset --window-tolerance-minutes 60
```

Videos mit `--target-date` landen unter `videos/<Kamera>/manual-runs/` und werden nie automatisch
gelöscht. Alle Optionen und unzulässigen Kombinationen: [cli.md](cli.md).

### Über die Weboberfläche

Kamera wählen, Videotyp und Zieldatum eintragen, „Video erstellen“. Das Ergebnis meldet ein Fenster;
der Auftrag schreibt in dasselbe Protokoll wie der entsprechende Befehl. Siehe
[weboberflaeche.md](weboberflaeche.md).

### Highlights-Flagger

```bash
.venv/bin/python3 -m src.flagger.run                                               # Kameras aus der Config, gestern
.venv/bin/python3 -m src.flagger.run --cameras <Kamera> --target-date <Datum>
tail -f logs/flagger/$(date +%F).log                                               # Fortschritt
```

Ein neuer Lauf für denselben Tag ersetzt dessen Ordner; vorher gelöschte Bilder kommen zurück.
Details: [flagger.md](flagger.md).

### Verpixelung

- In einem Tagesvideo: `--blur-people` an einen historischen Daily-Lauf anhängen
  ([verpixelung.md](verpixelung.md)).
- Direkt auf der Storage Box: `.venv/bin/python3 -m src.privacy.blur_box --cameras <Kamera>`
  ([verpixelung-box.md](verpixelung-box.md)). Schreibt auf die Box; vorher die dortige Anleitung
  lesen.

### Werkzeuge

```bash
.venv/bin/python3 -m src.storage_filter --cameras <Kamera>          # Liste leerer/doppelter Bilder, löscht nichts
.venv/bin/python3 scripts/yearly-backfill.py --years 2026 --cameras <Kamera>
```

Details: [werkzeuge.md](werkzeuge.md); NAS-Archiv: [nas.md](nas.md).

### Sicherung

Auf dem eigenen Rechner (macOS, Linux, Windows mit WSL) im Repository-Ordner:

```bash
./backup.sh                  # mit Videos
SKIP_VIDEOS=1 ./backup.sh    # ohne Videos
```

Wiederherstellung: [raspberry-pi.md](raspberry-pi.md).

---

## Fehler: nächtlicher Lauf

### Heute Nacht lief nichts, es gibt kein Protokoll

**Symptom:** Für heute fehlt `logs/daily/<heute>.log`; in `videos/<Kamera>/daily/` gibt es kein Video
von gestern.

**Prüfen:**

```bash
crontab -l                                   # 02:00-Zeile vorhanden?
uptime                                       # lief der Rechner um 02:00?
flock -n ~/timelapse/state/zeitraffer-run.lock -c true && echo frei || echo belegt
pgrep -af "src.main|src.flagger|storage_filter|yearly-backfill|blur_box"
```

**Ursache:** Cron startet den Lauf mit `flock -n`. Ist die Sperre um 02:00 belegt (Web-Auftrag,
Flagger, Speicherfilter, ein hängender Lauf), beendet sich der Lauf **ohne jede Meldung**. Seltener:
Crontab fehlt oder der Rechner war aus.

**Lösung:** Den blockierenden Prozess abwarten oder beenden, dann den
[Lauf von Hand starten](#nächtlicher-lauf). Fehlt die Crontab, sie nach
[README](../README.md#cron-installieren-oder-prüfen) wieder eintragen.

### Kamera-Speicher nicht erreichbar

**Symptom:** Im Protokoll steht direkt am Anfang `Failed to access camera storage.` mit einem
`OSError`, und es entstehen gar keine Videos.

**Prüfen:**

```bash
mountpoint /mnt/cameras
timeout 10 ls /mnt/cameras > /dev/null && echo "Mount antwortet" || echo "Mount hängt oder fehlt"
systemctl status cameras-sshfs.service
journalctl -u cameras-sshfs.service --since today
```

**Ursache:** Der SSHFS-Mount ist weg oder hängt: Netzwerk, Storage Box nicht erreichbar, Host-Key
oder Schlüssel passt nicht mehr.

**Lösung:** `sudo systemctl restart cameras-sshfs.service`; das Preflight-Skript räumt dabei einen
hängenden Mount auf. Danach den Lauf von Hand starten. Bleibt der Dienst rot, die Meldung im Journal
lesen (häufig: `Host key verification failed` oder leere `mount.env`).

Zeigt `systemctl status` nicht rot, sondern `inactive (dead)` mit einer Zeile `condition failed`, fehlt
der Ordner `/mnt/cameras` selbst. Der Dienst startet dann gar nicht erst (Bedingung
`ConditionPathIsDirectory` in der Unit). Ordner anlegen (`sudo mkdir /mnt/cameras`) und den Dienst
neu starten.

### Bildsuche bricht ab („stalled“)

**Symptom:** `TimeoutError: ... stalled for camera: <Kamera>` im Protokoll; diese Kamera fehlt, die
anderen laufen weiter.

**Prüfen:** wie bei [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar), dazu
`timeout 20 ls /mnt/cameras/<Kamera> | wc -l`.

**Ursache:** Der Mount antwortet für diesen Ordner nicht mehr rechtzeitig (Netzwerk, überlastete
Storage Box, sehr viele Dateien). Der Lauf bricht die Suche nach `image_scan_stall_timeout_seconds`
ohne Fortschritt ab, statt ewig zu hängen.

**Lösung:** Mount prüfen und neu starten, die Kamera mit `--target-date` nachholen. Tritt es bei
einer Kamera dauerhaft auf, mit dem [Speicherfilter](werkzeuge.md) prüfen, ob ihr Ordner
ungewöhnlich voll ist.

### Eine Kamera hat keine Bilder

**Symptom:**

```text
WARNING | Found 0 images - skipping camera.
WARNING | No recognized image files available.
WARNING | Available image range: 2026-09-14 - 2026-10-02
```

**Prüfen:**

```bash
ls -t /mnt/cameras/<Kamera> | head -5        # neueste Dateien
```

**Ursache:** Die Kamera lädt nichts hoch (offline, Strom, Netz, Speicherkarte) oder liefert ein
unbekanntes Dateinamenformat. `Available image range` zeigt, bis wann zuletzt Bilder kamen.

**Lösung:** Kein Programmfehler. Kamera bzw. Upload prüfen lassen. Ist die Kamera dauerhaft außer
Betrieb, sie in `ignored_cameras` eintragen. Ein neues Dateinamenformat muss in `src/images.py`
ergänzt werden; Dateien mit unbekanntem Namen werden nie geraten, sondern übersprungen.

### Monats- oder Jahresvideo übersprungen

**Symptom:**

```text
WARNING | Monthly coverage too low: 18 of 30 days available (minimum 25) - skipping camera: Strandallee
WARNING | Yearly coverage partial: 331 of 365 days available (minimum 300) | missing: 2026-02-03 to 2026-02-12
```

**Ursache:** Für ein Monatsvideo braucht es Bilder an mindestens 25 von 30 Tagen, für ein
Jahresvideo an 300 Tagen (`min_coverage_days`), jeweils im Mittagsfenster. „partial“ heißt: Video
entsteht, die genannten Tage fehlen darin. „too low“ heißt: kein Video.

**Lösung:** Meist nichts tun; das Video entsteht wieder, sobald genug Tage da sind. Für ein
Jahresvideo trotz Lücken gibt es den [Yearly-Backfill](werkzeuge.md).

### Wochenvideo mit fehlenden Tagen

**Symptom:**

```text
WARNING | Missing Daily video: videos/BSV-Steinhude/daily/BSV-Steinhude_2026-10-18.mp4
WARNING | Weekly will be created with 5 of 7 Daily videos.
WARNING | No Daily videos available - skipping Weekly for camera: Bootshaus
```

**Ursache:** Das Wochenvideo besteht aus den Tagesvideos der letzten 7 Tage. Fehlt ein Tagesvideo
(Kamera ohne Bilder, Lauf ausgefallen), fehlt der Tag auch in der Woche.

**Lösung:** Die nächtliche Woche nutzt nur `videos/<Kamera>/daily/`; nachträglich erstellte
Tagesvideos landen unter `manual-runs/` und zählen dort nicht. Für eine vollständige Woche ein
historisches Weekly erstellen (`--jobs weekly --target-date <letzter Tag> --cameras <Kamera>`).

### Leere oder abgeschnittene Bilder

**Symptom:**

```text
WARNING | Camera SKM-Mardorf: excluded 6 empty image files
WARNING | Skipping truncated image (no JPEG end marker): /mnt/cameras/Uferstrasse/uferstrasse_….jpg
```

**Ursache:** Ein Upload der Kamera brach ab (0 Byte oder ohne JPEG-Ende). Das Programm lässt solche
Bilder weg; ohne diesen Filter würde ein halbes Bild mit dem Rest des Vortags im Video landen.

**Lösung:** Nichts, solange es vereinzelt bleibt. Häuft es sich bei einer Kamera, deren Upload prüfen
lassen; der [Speicherfilter](werkzeuge.md) listet alle betroffenen Dateien.

### FFmpeg: `Permission denied`

**Symptom:**

```text
Error opening output files: Permission denied
ERROR | FFmpeg failed with exit code 243:
ERROR | Failed to process timelapse for camera: SKM-Mardorf
```

**Prüfen:**

```bash
ls -ld ~/timelapse/videos ~/timelapse/videos/<Kamera> ~/timelapse/videos/<Kamera>/*/
```

**Ursache:** Ein Ordner unter `videos/` gehört nicht dem Projektbenutzer, z. B. weil Videos als
`root` kopiert oder ein Befehl mit `sudo` gestartet wurde.

**Lösung:**

```bash
sudo chown -R "$(id -un):$(id -gn)" ~/timelapse/videos   # Eigentümer zurück auf den Projektbenutzer
~/timelapse/migrate.sh permissions verify                  # Leserechte für www-data, dann prüfen
```

`permissions` allein reicht hier nicht: es ändert nur Rechte, nicht den Eigentümer.

Dann die Kamera mit `--target-date` nachholen. Läufe nie mit `sudo` starten.

### Festplatte voll

**Symptom:** FFmpeg meldet `No space left on device`, oder Python `OSError: [Errno 28]`.

**Prüfen:**

```bash
df -h ~/timelapse
du -sh ~/timelapse/videos/*/manual-runs ~/timelapse/temp ~/timelapse/logs | sort -h | tail
```

**Ursache:** Meist viele Videos unter `manual-runs/` (werden nie automatisch gelöscht) oder Reste in
`temp/` nach einem abgebrochenen Lauf.

**Lösung:** Nicht mehr benötigte Videos über die Weboberfläche löschen. Ordner in `temp/` dürfen
gelöscht werden, wenn kein Lauf aktiv ist. Nach dem Aufräumen die betroffenen Kameras nachholen.

### Lauf meldet Erfolg, aber Kameras fehlen

**Symptom:** Der Lauf endet ohne Fehler, trotzdem fehlen Videos.

**Prüfen:** die Zusammenfassungen (`grep -h "job finished" logs/*/<Datum>.log`); bei `failed=` > 0
die Zeilen mit `ERROR` und den Traceback davor lesen.

**Ursache:** Fehler einzelner Kameras (Mount, FFmpeg, Dateirechte) werden abgefangen, damit die
übrigen Kameras weiterlaufen; der Exit-Code bleibt 0.

**Lösung:** Ursache aus dem Traceback beheben (siehe die Fälle oben), Kamera nachholen.

### Lauf wurde nach einem Neustart wiederholt

**Symptom:** Im Protokoll beginnt nach einer Unterbrechung ein zweiter Lauf mit neuer `run_id`.

**Ursache:** Gewollt. Der nächtliche Lauf legt `state/run-in-progress` an; fehlt am Ende das
„fertig“, wiederholt Cron (`@reboot`) den Lauf nach dem nächsten Start.

**Lösung:** Nichts. Startet der Rechner bei jedem Lauf neu, siehe
[Raspberry Pi: Stabilität](#raspberry-pi-stabilität).

---

## Fehler: Weboberfläche

### Anmeldung klappt nicht

**Symptom:** Der Browser fragt immer wieder nach Benutzername und Passwort.

**Lösung:** Passwort neu setzen: `sudo htpasswd -B /etc/apache2/.htpasswd <login>` (`-B` für
bcrypt, ohne `-c`, sonst wird die Datei mit allen anderen Logins überschrieben)
([README](../README.md#basisauthentifizierung-einrichten)).

### `403 Forbidden`

**Prüfen:** `tail /var/log/apache2/zeitraffer-error.log`; typisch ist
`AH00035: ... search permissions are missing on a component of the path`.

**Ursache:** `www-data` kommt nicht mehr ins Projekt, z. B. nach einer Neuinstallation oder nachdem
Dateien von Hand kopiert wurden.

**Lösung:** `~/timelapse/migrate.sh permissions verify`. `permissions` setzt die Leserechte für
`www-data` neu (nur Rechte, nicht den Eigentümer); `verify` repariert nichts, sondern prüft danach
alles und meldet jedes Problem als `WARNING` (führt dabei die Tests aus und fragt nach dem
`sudo`-Passwort).

### Kameraliste leer

**Prüfen:** `ls /mnt/cameras` als Projektbenutzer und `sudo -u www-data ls /mnt/cameras`.

**Ursache:** Mount weg (siehe [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar)),
alle Kameras in `ignored_cameras`, oder `www-data` darf den Mount nicht lesen (`allow_other` bzw.
`user_allow_other` in `/etc/fuse.conf` fehlt).

**Lösung:** Mount bzw. Konfiguration richten; für `allow_other` siehe
[README](../README.md#sshfs-mount-installieren).

### „Es läuft bereits ein anderer Zeitraffer-Auftrag.“

**Ursache:** Die gemeinsame Sperre ist belegt: nächtlicher Lauf, Flagger, Speicherfilter, Backfill
oder ein anderer Web-Auftrag.

**Lösung:** [Prüfen, was läuft](#läuft-gerade-etwas), abwarten, erneut starten.

### „Der Videoauftrag konnte nicht gestartet werden.“

**Prüfen:**

```bash
sudo -l -U www-data                                    # Regeln für trigger, delete und delete-highlight?
cmp scripts/timelapse-web-trigger /usr/local/sbin/timelapse-web-trigger
tail /var/log/apache2/zeitraffer-error.log
```

**Ursache:** sudoers-Regel fehlt, installierter Wrapper fehlt oder veraltet, oder der Projektordner
gehört `root` (dann verweigert die Seite den Start bewusst).

**Lösung:** Wrapper und sudoers nach [README](../README.md#wrapper-installieren) neu einrichten.

### „Der Videoauftrag wurde abgelehnt oder konnte nicht gestartet werden.“

**Prüfen:** `grep "Video wrapper failed with exit code" /var/log/apache2/zeitraffer-error.log | tail -3`

**Ursache:** Der Wrapper lief, hat den Auftrag aber abgelehnt. Der Exit-Code im Protokoll sagt warum:

| Code | Bedeutung |
|---|---|
| 66 | Kameraordner fehlt unter `/mnt/cameras`, meist weil der Mount weg ist |
| 64 | Ungültige Eingabe (Datum, Job, Zeitpuffer oder Zeitfenster) |
| 69 | Worker oder Status-Hilfsskript unter `/usr/local/libexec/` fehlt |

**Lösung:** Bei 66 [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar); bei 69
die Wrapper neu installieren; bei 64 prüfen, ob installierter Wrapper und Weboberfläche zueinander
passen (`cmp` wie oben).

### „Videoerstellung fehlgeschlagen“

**Symptom:** Das Abschlussfenster meldet „… konnte nicht erstellt werden. Bitte das
Anwendungsprotokoll prüfen.“

**Prüfen:** `logs/<job>/<heute>.log` (das Protokoll trägt das Datum des Auftrags, nicht das
Zieldatum), dort die Zeilen zur gewählten Kamera.

**Ursache:** Fast immer zu wenige Bilder: Kamera ohne Bilder an dem Tag, Monat/Jahr unter der
Mindestabdeckung, oder ein historisches Weekly ohne Bilder an allen 7 Tagen (das ist Pflicht).
Der Auftrag gilt als fehlgeschlagen, sobald kein neues Video entsteht.

**Lösung:** Anderes Datum, Fenster oder anderen Videotyp wählen; sonst den Fehler wie beim
[nächtlichen Lauf](#fehler-nächtlicher-lauf) suchen.

### Auftrag scheint zu hängen

**Prüfen:**

```bash
ls -l ~/timelapse/state/web-jobs/                       # <id>.pid, <id>.status
pgrep -af "src.main"
```

**Ursache:** Entweder rendert er noch, oder der Prozess ist gestorben. Ein toter Prozess wird beim
nächsten Abfragen als fehlgeschlagen gemeldet.

**Lösung:** Läuft `src.main` noch, abwarten. Wurde Apache in der Zwischenzeit neu gestartet, ist der
Auftrag beendet worden; neu starten.

### Löschen schlägt fehl

**Symptom:** „Das Video konnte nicht gelöscht werden.“ bzw. „Das Bild konnte nicht gelöscht werden.“

**Prüfen:** `sudo -l -U www-data` muss `timelapse-web-delete` bzw. `timelapse-web-delete-highlight`
zeigen; Details im Apache-Fehlerprotokoll.

**Lösung:** Fehlenden Wrapper und sudoers-Zeile nach
[README](../README.md#wrapper-installieren) ergänzen.

### „Die Anfrage ist ungültig (Sicherheitstoken).“

**Ursache:** Die Sitzung ist abgelaufen (nach 24 Minuten ohne Aktivität).

**Lösung:** Seite neu laden und erneut absenden.

### Änderungen an einem Wrapper wirken nicht

**Ursache:** Apache ruft die installierten Kopien unter `/usr/local/` auf, nicht `scripts/`.

**Lösung:** Den geänderten Wrapper mit `sudo install` neu installieren
([README](../README.md#wrapper-installieren)).

---

## Fehler: Erkennung, Highlights und Verpixelung

Flagger und Verpixelung nutzen das Erkennungsmodell YOLOX (`models/`, über `onnxruntime`).

### Modelldatei fehlt

**Symptom:** `Flagger not started: model file missing: models/object_detection_yolox_2022nov.onnx`;
bei der Verpixelung bricht der Lauf ab, statt ein ungeprüftes Video zu erzeugen.

**Lösung:** `models/` aus der Sicherung zurückkopieren (bevorzugt: dieselbe Datei hält
zwischengespeicherte Ergebnisse gültig) oder neu herunterladen
([verpixelung.md](verpixelung.md#installation)).

### Modell lässt sich nicht laden

**Prüfen:**

```bash
.venv/bin/python3 -c "import onnxruntime, cv2; print(onnxruntime.__version__, cv2.__version__)"
```

**Ursache:** `onnxruntime` oder OpenCV fehlen in der virtuellen Umgebung oder passen nicht zur
Plattform; seltener eine beschädigte Modelldatei.

**Lösung:** `.venv/bin/python3 -m pip install -r requirements.txt`; Modelldatei mit der aus der
Sicherung vergleichen (`sha256sum models/*.onnx`).

### Erkennung liegt falsch

**Symptom:** Highlights zeigen Unsinn (ein Busch als „Giraffe?“, ein Kondensstreifen als „Drachen?“)
oder übersehen Tiere; die Verpixelung trifft Schilder oder übersieht Personen.

**Ursache:** YOLOX erkennt Alltagsklassen, keine Rehe, Schwäne oder Ballons, und rät bei kleinen,
fernen Objekten. Einzelne Fehltreffer sind normal.

**Lösung:**

- Flagger: Feststehende Objekte filtert er selbst. Schwellen und den Filter für feststehende Objekte
  in `src/flagger/groups.py` nur mit echten Beispielbildern ändern ([flagger.md](flagger.md)).
- Verpixelung: bekannte Fehlerkennungen über `ignore_boxes`, `ignore_top_share`, `skip_labels` und
  `min_person_score` in der Config ausschließen
  ([verpixelung.md](verpixelung.md#ignore_boxes-ignore_top_share-skip_labels-und-min_person_score)).

### Ein feststehendes Objekt wird immer wieder verpixelt

**Symptom:** Auf der Storage Box ist in vielen Bildern einer Kamera dasselbe Objekt verpixelt
(Beispiel 2026-10-23: die Ankerkette vor dem Gebäude bei Scheunenviertel).

**Ursache:** Der Detektor hält das Objekt für eine Person, meist mit niedriger Sicherheit
(0,25–0,6). Weil es sich nicht bewegt, trifft es jedes Mal dieselbe Stelle.

**Prüfen:** Welche Boxen an derselben Stelle wiederkehren, steht in der Statusdatei:

```bash
grep -h '"status": "blurred"' state/privacy/box/<Kamera>/*.jsonl | head -3
```

Jede Box ist `[x0, y0, x1, y1, Sicherheit, Label]` in Pixeln des Originalbilds.

**Lösung:** Die wiederkehrenden Stellen als `ignore_boxes` der Kamera in `config/config.json`
eintragen. Wirkt ab dem nächsten Lauf, ohne Neustart. Vorher prüfen, dass keine echte Person
mitfällt: eine Box wird verworfen, wenn sie eine Ignorierfläche zu mindestens 50 % überlappt.

**Mit Claude (empfohlen):** In einer Claude-Sitzung im Projekt etwa so beauftragen:

> Bei `<Kamera>` wird `<Objekt>` (`<wo im Bild>`) fälschlich verpixelt. Werte die Boxen in
> `state/privacy/box/<Kamera>/` aus, prüfe an einem Original aus `original/` auf der Box, dass es
> das Objekt ist und keine Person, und schlage `ignore_boxes` vor. Zeig, wie viele der bisherigen
> Treffer sie verwerfen und welche echten Personen bleiben.

Claude wertet die Statusdatei aus, schaut sich einen Bildausschnitt an, prüft die Flächen gegen
alle bisherigen Boxen und trägt sie nach Freigabe in die Config ein. Aufwand am Beispiel
Ankerkette: rund 10 Minuten, ca. 15–20k Tokens (Schätzung). Ergebnis dort: 28 von 35 Treffern
verworfen, die übrigen 7 waren echte Personen neben der Kette.

**Grenzen:**

- Bereits verpixelte Bilder behalten die Verpixelung; sie stehen als `blurred` in der
  Statusdatei und werden nicht neu bearbeitet. Das Original liegt in `<Kamera>/original/`.
- Die Flächen sind feste Pixel. Verschiebt sich die Kamera um mehr als etwa ein Drittel der
  Boxbreite (bei der Kette ca. 15 Pixel), wird das Objekt wieder verpixelt. Dann die Flächen
  neu bestimmen, wie oben.
- Steht eine Person genau vor dem Objekt, bleibt sie unverpixelt (wie beim Wegweiser).

### Flagger startet nicht oder überspringt

| Meldung | Ursache | Lösung |
|---|---|---|
| `Skipped: ...` | Sperre belegt | später erneut starten |
| `Flagger not started: ...` mit unbekannter oder ignorierter Kamera | Kamera in `flagger.cameras` existiert nicht oder steht in `ignored_cameras` | Config korrigieren |
| `[<Kamera>] no images for <Datum> - nothing written` | keine Tagesbilder | wie [Eine Kamera hat keine Bilder](#eine-kamera-hat-keine-bilder) |
| gelöschtes Highlight ist wieder da | der Tag wurde neu geprüft, der Ordner ersetzt | erneut löschen |

Highlights-Seite: [highlights-seite.md](highlights-seite.md#fehlersuche).

### Verpixelung

Fehlerbilder und Lösungen stehen in den eigenen Tabellen:
[verpixelung.md](verpixelung.md#fehlersuche) (Videos) und
[verpixelung-box.md](verpixelung-box.md#fehlersuche) (Storage Box). Grundsatz: Im Zweifel bricht
die Verpixelung ab und schreibt nichts; ein Abbruch ist also kein Datenverlust.

### Speicherfilter

`Storage filter needs the SSHFS camera mount to be up.` heißt: Mount fehlt (siehe
[Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar)). Auf einem Host ohne Mount
die Storage Box über `TIMELAPSE_STORAGE_BOX` angeben ([README](../README.md#umgebungsvariablen)).

### WordPress

Siehe [wordpress.md](wordpress.md#fehlerbehebung-wordpress-frontend).

---

## Fehler: Sicherung und Wiederherstellung

| Meldung | Ursache | Lösung |
|---|---|---|
| `Missing tool on this computer: rsync` (oder `openssl`) | Werkzeug fehlt auf dem eigenen Rechner | installieren, unter WSL `sudo apt install rsync openssl` |
| `rsync: command not found` während der Sicherung | `rsync` fehlt auf dem Host | dort installieren |
| `No project folder at ... on the host (set PROJECT_DIR)` | Projekt liegt woanders | `PROJECT_DIR` in `backup.env` setzen |
| `skipped (missing or not readable): ...` | Datei fehlt auf dem Host oder ist ohne `sudo` nicht lesbar | auf einem Host ohne diese Datei normal; sonst `sudo`-Zugang prüfen |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Host neu installiert | `ssh-keygen -R <host>` |
| `Could not decrypt ... (wrong passphrase?)` bei `migrate.sh` | falsche Passphrase | erneut starten; die Passphrase gilt pro Sicherung |

Weitere Fälle der Neuinstallation: [raspberry-pi.md](raspberry-pi.md#fehlerbehebung).

---

## Fehler: Entwicklung und CI

### CI ist rot, lokal ist alles grün

**Prüfen:** den fehlschlagenden Test im Log der GitHub Action.

**Ursache:** Die CI-Umgebung unterscheidet sich vom Pi:

- **kein FFmpeg/ffprobe:** Ein Test, der ohne es nicht läuft, braucht die Markierung
  `requires_ffmpeg` oder muss den FFmpeg-Aufruf ersetzen.
- **Xdebug ist geladen:** Eine Exception aus einem PHP-Konstruktor (z. B. `new DateTimeZone(...)`)
  wird dort zu einem `Error`, den `catch (Exception)` nicht fängt. Eingaben vorher prüfen statt
  Exceptions zu fangen.
- **PHP-Version nicht festgelegt:** CI nimmt das PHP von `ubuntu-latest` (mindestens 8.3). Im
  Web-Code nichts verwenden, was nur in neueren Versionen existiert (z. B. `array_any`).

**Lösung:** Lokal ohne FFmpeg testen, indem `ffmpeg`/`ffprobe` aus dem `PATH` genommen werden, und
den Test entsprechend anpassen.

### Push wird blockiert

**Ursache:** Der lokale Pre-Push-Hook führt `ruff check`, `ruff format --check` und `pytest` aus und
bricht bei einem Fehler ab.

**Lösung:** `ruff format .` und den Fehler beheben. `git push --no-verify` nur im Notfall; CI prüft
dasselbe ohnehin.

---

## Raspberry Pi: Stabilität

Gilt nur für den Raspberry Pi als Host.

### Der Pi ist unbemerkt neu gestartet

**Prüfen:**

```bash
uptime                                              # seit wann läuft er?
journalctl --list-boots | tail -3                   # Neustarts
journalctl -b -1 -p warning --no-pager | tail -50   # Warnungen vor dem letzten Neustart
grep "<Uhrzeit vor dem Neustart>" /var/log/pi-health.log   # Speicher und Last
```

**Ursache:** Meist ist der Arbeitsspeicher voll gelaufen: großes Video plus weitere Last (VS Code
Remote, ein zweiter Job). Der Pi friert ein, der Hardware-Watchdog startet ihn neu, ohne Meldung.
Danach wiederholt Cron einen unterbrochenen nächtlichen Lauf.

**Lösung:** Gleichzeitige schwere Arbeiten vermeiden (siehe nächster Fall). Fehlen
`/var/log/pi-health.log` oder ein dauerhaftes Journal, die Absturzprotokollierung einrichten
([raspberry-pi.md](raspberry-pi.md)).

### Arbeitsspeicher knapp

**Prüfen:**

```bash
free -m
ps -eo rss,args --sort=-rss | head -10
```

**Ursache:** Neben dem Lauf belegen oft VS-Code-Server Speicher, die nach einer abgebrochenen
Verbindung (Mac im Ruhezustand) oder einem VS-Code-Update weiterlaufen.

**Lösung:**

- Alte VS-Code-Server beenden, z. B. über „Remote-SSH: Kill VS Code Server on Host…“ in VS Code.
- Während eines großen Renders keine weiteren Läufe oder Tests starten.
- `TIMELAPSE_X264_PRESET=ultrafast` senkt den Speicherbedarf des Encoders deutlich (größere
  Dateien; [README](../README.md#umgebungsvariablen)).
