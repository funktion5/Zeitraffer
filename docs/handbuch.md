# Handbuch

Für Entwicklerinnen und Entwickler, die Zeitraffer betreuen: wie es installiert wird, wie man jeden
Job startet und was bei Fehlern zu tun ist. Einen Überblick gibt das [README](../README.md), die
ausführlichen Beschreibungen stehen in den anderen Dateien in diesem Ordner; dieses Handbuch
verweist dorthin, statt sie zu wiederholen.

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
- [Arbeitsspeicher](#arbeitsspeicher)

---

## Überblick

Stand: Der Betrieb läuft seit dem 30.10.2026 auf einem VPS (Debian 13); der frühere Raspberry Pi
ist stillgelegt (Ablage: [archive/README.md](../archive/README.md)).

### Was wann läuft

| Was | Wann | Gestartet von |
|---|---|---|
| Nächtlicher Lauf (Daily, Weekly, Monthly, Yearly für alle Kameras) | 02:00 Uhr | Cron |
| Videos für vergangene Zeiträume | bei Bedarf | Weboberfläche oder Befehl |
| Upload der Videos auf die Website | direkt nach dem Nachtlauf, vor dem Flagger, in derselben Cron-Zeile ([betrieb.md](betrieb.md#upload-auf-die-website)) | Cron |
| Highlights-Flagger | direkt nach dem Upload, am Ende derselben Cron-Zeile (keine feste Uhrzeit) | Cron |
| Verpixelung auf der Storage Box | nachts vor dem Zeitraffer-Lauf (Nachholen der letzten 48 h); die laufende Runde noch nicht in Cron | Cron |
| Verpixelung der Bilder eines von Hand gestarteten Videos (Blur-Kameras) | bei jedem historischen Daily, Weekly, Monthly und Yearly dieser Kameras; dauert deutlich länger | Weboberfläche oder Befehl |
| Speicherfilter, Yearly-Backfill, NAS-Werkzeuge, Sicherung | bei Bedarf | Befehl |

### Wo was liegt

| Was | Wo |
|---|---|
| Kamerabilder (Original, **nur lesen**) | Storage Box; die Jobs holen die nötigen Bilder per rsync nach `temp/frame-cache/` |
| Einstellungen | `config/config.json` |
| Nächtliche Videos | `videos/<Kamera>/{daily,weekly,monthly,yearly}/` |
| Videos aus Weboberfläche und Befehl | `videos/<Kamera>/manual-runs/<job>/` |
| Highlights | `videos/<Kamera>/highlights/<Datum>/` |
| Protokolle | `logs/<job>/<Datum des Laufs>.log`, z. B. `logs/daily/`, `logs/flagger/` |
| Laufsperre | `state/zeitraffer-run.lock` |
| Sperre der Box-Verpixelung | `state/privacy-blur.lock` |
| Status der Box-Verpixelung | `state/privacy/box/<Kamera>/<JJJJ-MM>.jsonl` |
| Marker „nächtlicher Lauf unterbrochen“ | `state/run-in-progress` |
| Status der Web-Aufträge | `state/web-jobs/` |
| Zwischendateien | `temp/` |
| Bericht des Nachtlaufs | `logs/nightly/<Lauf>/report.txt` |
| Kameraliste der Weboberfläche | `state/web-jobs/cameras.json` |
| Installierte Web-Wrapper | `/usr/local/sbin/`: `timelapse-web-trigger` (Video-Auftrag starten), `timelapse-web-rebuild` (automatische Videos einer Kamera neu erstellen), `timelapse-web-publish` (Videos einer Kamera hochladen), `timelapse-web-delete` (Video löschen), `timelapse-web-delete-highlight` (Highlight-Bild löschen), `timelapse-web-settings` (Einstellungen speichern), `timelapse-web-preview` (Vorschaubild einer Verpixelungs-Kamera holen); `/usr/local/libexec/`: `timelapse-web-worker`, `timelapse-web-worker-rebuild`, `timelapse-web-worker-publish`, `timelapse-web-status.sh` |
| Apache-Fehlerprotokoll | `/var/log/apache2/zeitraffer-error.log` |

### Grundregeln

- **Immer nur ein Lauf auf einmal.** Nächtlicher Lauf, Web-Aufträge, Flagger, Speicherfilter und
  Backfill teilen sich die Sperre `state/zeitraffer-run.lock`; das nächtliche Nachholen der
  Verpixelung läuft unter derselben Sperre. Die Verpixelung auf der Storage Box hat zusätzlich
  eine eigene Sperre (`state/privacy-blur.lock`), damit sich zwei Runden nie überschneiden; ohne
  `flock` gestartet läuft sie auch parallel zum Zeitraffer-Lauf. Wer eine Sperre nicht bekommt,
  bricht ab oder überspringt.
- **Von Hand gestartete Videos von Blur-Kameras dauern lange.** Sie verpixeln zuerst ihre Bilder auf
  der Storage Box (gemessen: ein Monatsvideo mit 360 Bildern 55 Minuten) und halten die Laufsperre
  die ganze Zeit. Ein Auftrag, der über 02:00 hinausläuft, lässt den Nachtlauf ausfallen.
- **Die Originalbilder nie ändern.** Die Zeitraffer-Jobs lesen sie nur; die Verpixelung auf der
  Storage Box ist die einzige Ausnahme und sichert vorher das Original (auch bei von Hand
  gestarteten Videos von Blur-Kameras).
- **Ein Lauf kann „erfolgreich“ enden, obwohl Kameras fehlten.** Bei `src.main` ist der Exit-Code
  dann trotzdem 0; der Nachtlauf-Wrapper prüft das Ergebnis und endet in diesem Fall mit 1.
  Maßgeblich ist die Zusammenfassung am Ende jedes Jobs (siehe unten).
- **Die Web-Wrapper laufen aus installierten Kopien.** Eine Änderung unter `scripts/` wirkt erst nach
  `sudo install` (siehe [Installation](installation.md#wrapper-installieren)).
- **Ein Neustart von Apache beendet einen laufenden Web-Auftrag.** Vorher `ls state/web-jobs/*.pid`
  prüfen.

### Läuft gerade etwas?

```bash
cd ~/timelapse
flock -n state/zeitraffer-run.lock -c true && echo "Sperre frei" || echo "Sperre belegt"
pgrep -af "src.main|src.flagger|storage_filter|yearly-backfill|blur_box"
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
[Installation](installation.md); auf einem frischen Debian- oder
Ubuntu-Host erledigt `install.sh` die Schritte 1, 2, 7 und die Dateirechte, legt die leere
Login-Datei des Uploads an und spielt, wenn eine Sicherung bereitliegt, Modell, Status und Videos
zurück (Schritt 3); den Zugang zur Storage Box (Schritt 5) und Cron (Schritt 6) richtet man nach
[vps.md](vps.md) von Hand ein.

| # | Schritt | Funktioniert, wenn |
|---|---|---|
| 1 | Systempakete installieren ([Installation](installation.md#systempakete-installieren)) | `ffmpeg -version`, `php -v`, `rsync --version` antworten |
| 2 | Python 3.13 und virtuelle Umgebung ([Installation](installation.md#python-umgebung-einrichten)) | `.venv/bin/python3 --version` zeigt 3.13 |
| 3 | Erkennungsmodelle nach `models/` ([verpixelung.md](verpixelung.md#installation)) | `ls models/` zeigt `object_detection_yolox_2022nov.onnx` |
| 4 | `config/config.json` anpassen ([Konfiguration](konfiguration.md)) | `.venv/bin/python3 -m pytest tests/config_test.py` grün |
| 5 | Zugriff auf die Storage Box einrichten ([Installation](installation.md#zugriff-auf-die-storage-box)) | `TIMELAPSE_STORAGE_BOX=storagebox .venv/bin/python3 -m src.camera_list` listet die Kameras |
| 6 | Cron eintragen ([Installation](installation.md#cron-installieren-oder-prüfen)) | `crontab -l` zeigt die eine 02:00-Zeile mit Verpixelung, Nachtlauf, Upload und Flagger (`./install.sh cron_hint` druckt sie, siehe [betrieb.md](betrieb.md#nächtlicher-produktionslauf)) |
| 7 | Apache, Anmeldung, Wrapper, Dateirechte ([Installation](installation.md#weboberfläche-einrichten)) | `curl -s -o /dev/null -w '%{http_code}' http://localhost:<Port>/` ergibt `401`; `./install.sh verify` (prüft, repariert nichts) zeigt kein `WARNING` |
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

Auf dem Server liest jeder Befehl die Bilder per ssh; dafür muss `TIMELAPSE_STORAGE_BOX` gesetzt
sein. Die Cron-Zeilen setzen sie selbst, in der Shell einmal `export TIMELAPSE_STORAGE_BOX=<ssh-alias>`.
Alternativ liest `TIMELAPSE_CAMERA_ROOT` die Bilder aus einem lokalen Ordner (zum Beispiel dem
NAS-Archiv, [nas.md](nas.md)); `TIMELAPSE_FRAME_SOURCE` (`local` oder `ssh`) erzwingt eine der
beiden Quellen. Ohne `TIMELAPSE_STORAGE_BOX` und ohne `TIMELAPSE_CAMERA_ROOT` bricht ein Befehl
mit einer Fehlermeldung ab.

Der Lauf startet automatisch um 02:00 Uhr über Cron (Zeilen:
[betrieb.md](betrieb.md#nächtlicher-produktionslauf)). Von Hand (alle Kameras, alle vier Jobs, Zieltag
gestern) über denselben Wrapper wie Cron, der die Sperre selbst nimmt und das Ergebnis prüft:

```bash
setsid -f env TIMELAPSE_X264_PRESET=medium scripts/timelapse-nightly-staged > ~/nightly-console.log 2>&1 < /dev/null
cat logs/nightly/$(ls -t logs/nightly | head -1)/report.txt   # Bericht; die letzte Zeile nennt Kameras und Fehler
```

Nur `src.main` ohne die Prüfung des Wrappers:

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

Kamera wählen, Videotyp und Zieldatum (vorbelegt: gestern) eintragen, „Video erstellen“. Bis der
Auftrag fertig ist, bleibt der Button gesperrt; das Ergebnis meldet ein Fenster, bei einem
Fehlschlag mit dem Grund, sofern bekannt. Der Auftrag schreibt in dasselbe Protokoll wie der
entsprechende Befehl. Auf der Kameraseite stehen auch die nächtlichen Videos zum Ansehen und
Herunterladen (Liste „Automatische Videos“, ohne Löschen). Die Seite „Einstellungen“ ändert einen
Teil der Werte aus `config.json` ohne Handarbeit (Reiter „Allgemein“ und „Verpixelung“). Siehe
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

- Bei einem von Hand gestarteten Video (Weboberfläche oder `--target-date`) einer Blur-Kamera: nichts
  tun, es verpixelt seine Bilder selbst (Standard, kein Schalter,
  [verpixelung-box.md](verpixelung-box.md#verpixelung-bei-von-hand-gestarteten-videos)). Fortschritt:
  `tail -f logs/<job>/$(date +%F).log` (die Zeile `Blur:` nennt die Zahl der Bilder, jede
  `Replaced`-Zeile ist ein fertiges Bild).
- In einem Tagesvideo: `--blur-people` an einen historischen Daily-Lauf anhängen
  ([verpixelung.md](verpixelung.md)).
- Direkt auf der Storage Box: `.venv/bin/python3 -m src.privacy.blur_box --cameras <Kamera>`
  ([verpixelung-box.md](verpixelung-box.md)). Schreibt auf die Box; vorher die dortige Anleitung
  lesen. Mit `--catch-up` (45 Minuten pro Kamera) holt es die offenen Bilder der letzten 48 Stunden
  in einem Lauf nach; so läuft es nachts per Cron.

### Werkzeuge

```bash
.venv/bin/python3 -m src.storage_filter --cameras <Kamera>          # Liste leerer/doppelter Bilder, löscht nichts
.venv/bin/python3 scripts/yearly-backfill.py --years 2026 --cameras <Kamera>
```

Details: [werkzeuge.md](werkzeuge.md); NAS-Archiv: [nas.md](nas.md).

### Sicherung

Auf dem eigenen Rechner (macOS oder Linux) im Repository-Ordner, mit dem ssh-Alias des
Hosts, von dem gesichert wird:

```bash
BACKUP_HOST=<ssh-alias> ./backup.sh              # models/, state/, crontab.txt
BACKUP_HOST=<ssh-alias> VIDEOS=1 ./backup.sh     # zusätzlich videos/
```

Die Sicherung landet in `~/timelapse-backup`. Sie enthält das Erkennungsmodell, den Status
(darunter den der Verpixelung), die Crontab (nur zum Nachlesen) und mit `VIDEOS=1` die Videos, aber
keine Geheimnisse: Die Anmeldung der Weboberfläche legt `install.sh` neu an, das Passwort des
Uploads trägt man von Hand ein. Einspielen auf einem neuen Host (`./install.sh restore`):
[vps.md](vps.md).

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
[Installation](installation.md#cron-installieren-oder-prüfen) wieder eintragen.

### Kamera-Speicher nicht erreichbar

**Symptom:** Im Protokoll steht direkt am Anfang `Failed to access camera storage.` mit einem
`OSError` (zum Beispiel `Storage box listing failed ...` oder `TIMELAPSE_STORAGE_BOX is not set`)
oder einem `ValueError` (`No frame source configured: set TIMELAPSE_CAMERA_ROOT ... or
TIMELAPSE_STORAGE_BOX ...`), und es entstehen gar keine Videos.

**Prüfen:**

```bash
ssh <ssh-alias> ls | head -3                                                      # antwortet die Box?
TIMELAPSE_STORAGE_BOX=<ssh-alias> .venv/bin/python3 -m src.camera_list           # listet die Kameras
```

**Ursache:** Netzwerk oder Storage Box nicht erreichbar, Schlüssel oder Host-Key passt nicht mehr
(`Permission denied`, `Host key verification failed`), der Eintrag in `~/.ssh/config` fehlt, oder
`TIMELAPSE_STORAGE_BOX` ist nicht gesetzt (in der Cron-Zeile oder in der Shell).

**Lösung:** Die ssh-Verbindung von Hand prüfen und den Eintrag samt Schlüssel in `~/.ssh/config`
richten ([Installation](installation.md#zugriff-auf-die-storage-box), [vps.md](vps.md)). Meldet ssh einen
geänderten Host-Key (`REMOTE HOST IDENTIFICATION HAS CHANGED`), den Fingerabdruck mit der
Hetzner-Oberfläche vergleichen, bevor man ihn neu bestätigt (`ssh-keygen -R <host>`). Danach den Lauf von Hand starten.

### Bildsuche bricht ab („stalled“)

**Symptom:** `TimeoutError: ... stalled for camera: <Kamera>` im Protokoll; diese Kamera fehlt, die
anderen laufen weiter.

**Prüfen:** wie bei [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar), dazu
`time ssh <ssh-alias> ls <Kamera> | wc -l` (ein Ordner mit rund 190.000 Dateien braucht einige Sekunden).

**Ursache:** Die Storage Box antwortet für diesen Ordner nicht mehr rechtzeitig (Netzwerk,
überlastete Box, sehr viele Dateien). Der Lauf bricht die Suche nach `image_scan_stall_timeout_seconds`
ohne Fortschritt ab, statt ewig zu hängen. Beim Holen der Bilder wiederholt das Programm einen
fehlgeschlagenen rsync nach Pausen von 30 und 120 Sekunden.

**Lösung:** Verbindung prüfen, die Kamera mit `--target-date` nachholen. Tritt es bei einer Kamera
dauerhaft auf, mit dem [Speicherfilter](werkzeuge.md) prüfen, ob ihr Ordner ungewöhnlich voll ist.

### Eine Kamera hat keine Bilder

**Symptom:**

```text
WARNING | Found 0 images - skipping camera.
WARNING | No recognized image files available.
WARNING | Available image range: 2026-09-14 - 2026-10-02
```

**Prüfen:**

```bash
ssh <ssh-alias> ls -t <Kamera> | head -5     # neueste Dateien auf der Storage Box
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
WARNING | Skipping truncated image (no JPEG end marker): temp/frame-cache/<Lauf>/Uferstrasse/uferstrasse_….jpg
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
~/timelapse/install.sh permissions verify                  # Leserechte für www-data, dann prüfen
```

`permissions` allein reicht hier nicht: es ändert nur Rechte, nicht den Eigentümer.

Dann die Kamera mit `--target-date` nachholen. Läufe nie mit `sudo` starten.

### Video wirkt gestaucht oder hat schwarze Balken

**Symptom:** Ein Video ist schmaler oder breiter gestaucht als erwartet, oder die Bilder ab einem
Datum haben schwarze Balken. Im Protokoll steht `Frames of 2 different sizes (640x480, 1920x1080):
fitting every frame into 1920x1080`.

**Prüfen:**

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <Video>.mp4
```

**Ursache:** Eine Kamera wurde getauscht, die neuen Bilder haben eine andere Größe (Beispiel
Uferstrasse: 640×480 bis August 2026, danach 1920×1080). FFmpeg nimmt die Größe des ersten Bildes
und streckt alle anderen darauf; deshalb wirkte ein Jahresvideo über den Wechsel hinweg gestaucht.
Seit dem 30.10.2026 passt das Programm bei Daily, Monthly und Yearly alle Bilder in die größte
vorkommende Größe ein: Seitenverhältnis bleibt, schwarze Balken füllen den Rest (die alten
4:3-Bilder bekommen Balken links und rechts und sind etwas weicher, weil sie vergrößert werden).
Haben alle Bilder dieselbe Größe, ändert sich nichts.

**Lösung:** Meist nichts: die Balken sind gewollt, und sie verschwinden von selbst, wenn die alten
Bilder aus dem Zeitraum fallen (beim Yearly nach 365 Tagen). Ein Video, das vor der Korrektur
entstanden ist, bleibt gestaucht, bis es neu erstellt wird (das nächtliche Yearly ersetzt sich
selbst). **Bekannte Lücke:** Das Weekly setzt
fertige Tagesvideos zusammen und passt nichts an; liegt ein Kamerawechsel in den 7 Tagen, kann es
gestaucht sein.

### Videodateien zu groß oder Qualität nicht gut genug

**Hintergrund:** Die Qualität steuert x264 über den CRF-Wert: niedriger ist besser und größer,
höher ist kleiner. Der Standard ist seit dem 30.10.2026 **28** (`timelapse.crf` in
`config/config.json`). An einem Jahresvideo (Uferstrasse) gemessen ist die Datei damit rund 53 %
kleiner als bei CRF 23 (9,9 statt 21,2 MiB), bei der Durchsicht ohne sichtbaren Mangel.

**Lösung:** Dauerhaft `timelapse.crf` ändern (ganze Zahl 0 bis 51). Für einen einzelnen Lauf den
Wert vor den Befehl setzen:

```bash
TIMELAPSE_X264_CRF=23 .venv/bin/python3 -m src.main --jobs yearly --target-date <Datum> --cameras <Kamera>
```

Ein ungültiger Wert bricht das Encodieren mit `TIMELAPSE_X264_CRF must be a whole number from 0 to
51` (bzw. `timelapse.crf must be ...`) ab, es entsteht kein Video. Die Änderung gilt nur für neu
erstellte Videos. `TIMELAPSE_X264_PRESET` ändert dagegen Laufzeit, Speicherbedarf und Größe, nicht
den CRF-Wert ([Konfiguration](konfiguration.md#umgebungsvariablen)).

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

**Ursache:** Fehler einzelner Kameras (Zugriff auf die Storage Box, FFmpeg, Dateirechte) werden abgefangen, damit die
übrigen Kameras weiterlaufen; der Exit-Code von `src.main` bleibt 0 (der
Nachtlauf-Wrapper meldet es trotzdem: Exit-Code 1 und der Bericht).

**Lösung:** Ursache aus dem Traceback beheben (siehe die Fälle oben), Kamera nachholen.

### Lauf wurde nach einem Neustart nicht wiederholt

**Symptom:** Der Server wurde mitten im Lauf neu gestartet; die Videos dieser Nacht fehlen und es
beginnt kein zweiter Lauf.

**Ursache:** So eingerichtet: `install.sh` legt keine `@reboot`-Zeile an. Der Marker
`state/run-in-progress` bleibt bestehen und zeigt, dass ein Lauf unterbrochen wurde.

**Lösung:** Den Lauf von Hand wiederholen ([Nächtlicher Lauf](#nächtlicher-lauf)); vorher mit
`pgrep -af src.main` prüfen, dass keiner läuft. Startet der Rechner immer wieder neu, den
Arbeitsspeicher prüfen ([Arbeitsspeicher](#arbeitsspeicher)).

---

## Fehler: Weboberfläche

### Anmeldung klappt nicht

**Symptom:** Der Browser fragt immer wieder nach Benutzername und Passwort.

**Lösung:** Passwort neu setzen: `sudo htpasswd -B /etc/apache2/.htpasswd <login>` (`-B` für
bcrypt, ohne `-c`, sonst wird die Datei mit allen anderen Logins überschrieben)
([Installation](installation.md#basisauthentifizierung-einrichten)).

### `403 Forbidden`

**Prüfen:** `tail /var/log/apache2/zeitraffer-error.log`; typisch ist
`AH00035: ... search permissions are missing on a component of the path`.

**Ursache:** `www-data` kommt nicht mehr ins Projekt, z. B. nach einer Neuinstallation oder nachdem
Dateien von Hand kopiert wurden.

**Lösung:** `~/timelapse/install.sh permissions verify`. `permissions` setzt die Leserechte für
`www-data` neu (nur Rechte, nicht den Eigentümer); `verify` repariert nichts, sondern prüft danach
alles und meldet jedes Problem als `WARNING` (führt dabei die Tests aus und fragt nach dem
`sudo`-Passwort).

### Kameraliste leer

**Prüfen:** `cat state/web-jobs/cameras.json` als Projektbenutzer. Fehlt die Datei oder steht `[]`
darin, kennt die Weboberfläche keine Kamera.

**Ursache:** Die Liste schreibt der Nachtlauf und `python3 -m src.camera_list`; sie war noch nie
geschrieben, die Storage Box war beim letzten Versuch nicht erreichbar (die alte Liste bleibt dann
bestehen), oder alle Kameras stehen in `ignored_cameras`.

**Lösung:** Die Storage Box prüfen (siehe [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar))
und die Liste einmal von Hand schreiben:

```bash
TIMELAPSE_STORAGE_BOX=<ssh-alias> .venv/bin/python3 -m src.camera_list
```

### „Es läuft bereits ein anderer Zeitraffer-Auftrag.“

**Ursache:** Die gemeinsame Sperre ist belegt: nächtlicher Lauf, Flagger, Speicherfilter, Backfill
oder ein anderer Web-Auftrag.

**Lösung:** [Prüfen, was läuft](#läuft-gerade-etwas), abwarten, erneut starten.

### „Video erstellen“ ist grau

**Ursache:** In diesem Browser-Tab läuft noch ein Auftrag; die Statuszeile über dem Formular nennt
ihn. Der Button wird frei, sobald das Ergebnisfenster erscheint.

**Lösung:** Abwarten. Hängt es, siehe [Auftrag scheint zu hängen](#auftrag-scheint-zu-hängen); ein
Auftrag, dessen Worker nie gestartet ist, gilt nach einer Minute als fehlgeschlagen.

### „Das Löschen hat nicht geklappt. Bitte die Seite neu laden.“

**Ursache:** Die Löschanfrage im Hintergrund kam nicht an oder die Antwort war unbrauchbar
(Netz weg, Sitzung abgelaufen, Fehler auf dem Server). Andere Gründe (z. B. „Die Anfrage ist ungültig
(Sicherheitstoken).“) stehen ebenfalls im Bestätigungsdialog.

**Lösung:** Seite neu laden und erneut löschen; wenn es wieder scheitert,
`tail /var/log/apache2/zeitraffer-error.log`.

### „Der Videoauftrag konnte nicht gestartet werden.“

**Prüfen:**

```bash
sudo -l -U www-data                                    # Regeln für trigger, rebuild, publish, delete und delete-highlight?
cmp scripts/web/timelapse-web-trigger /usr/local/sbin/timelapse-web-trigger
tail /var/log/apache2/zeitraffer-error.log
```

**Ursache:** sudoers-Regel fehlt, installierter Wrapper fehlt oder veraltet, oder der Projektordner
gehört `root` (dann verweigert die Seite den Start bewusst).

**Lösung:** Wrapper und sudoers nach [Installation](installation.md#wrapper-installieren) neu einrichten.

### „Der Videoauftrag wurde abgelehnt oder konnte nicht gestartet werden.“

**Prüfen:** `grep -E "(Video|Rebuild|Publish) wrapper failed with exit code" /var/log/apache2/zeitraffer-error.log | tail -3` (die drei Namen stehen für das historische Video, das Neuerstellen und den Upload)

**Ursache:** Der Wrapper lief, hat den Auftrag aber abgelehnt. Der Exit-Code im Protokoll sagt warum:

| Code | Bedeutung |
|---|---|
| 66 | Die Kamera steht nicht in der Kameraliste `state/web-jobs/cameras.json` |
| 64 | Ungültige Eingabe (Datum, Job, Zeitpuffer oder Zeitfenster) |
| 69 | Worker oder Status-Hilfsskript unter `/usr/local/libexec/` fehlt |

**Lösung:** Bei 66 [Kameraliste leer](#kameraliste-leer); bei 69
die Wrapper neu installieren; bei 64 prüfen, ob installierter Wrapper und Weboberfläche zueinander
passen (`cmp` wie oben).

### „Videoerstellung fehlgeschlagen“

**Symptom:** Das Abschlussfenster meldet „… konnte nicht erstellt werden.“ Bekannte Gründe nennt
es selbst (z. B. „Zu wenige Tage mit Bildern im Zeitfenster: 21 von 30 (mindestens 25).“), sonst
steht dort „Bitte das Anwendungsprotokoll prüfen.“

**Prüfen:** `state/web-jobs/<id>.reason` (die Warnung, aus der der Grund stammt) und
`logs/<job>/<heute>.log` (das Protokoll trägt das Datum des Auftrags, nicht das
Zieldatum), dort die Zeilen zur gewählten Kamera.

**Ursache:** Fast immer zu wenige Bilder: Kamera ohne Bilder an dem Tag, Monat/Jahr unter der
Mindestabdeckung, oder ein historisches Weekly ohne Bilder an allen 7 Tagen (das ist Pflicht).
Der Auftrag gilt als fehlgeschlagen, sobald kein neues Video entsteht.

**Lösung:** Anderes Datum, Fenster oder anderen Videotyp wählen; sonst den Fehler wie beim
[nächtlichen Lauf](#fehler-nächtlicher-lauf) suchen.

### „Neu erstellen“: Ergebniszeile mit „übersprungen“ oder „fehlgeschlagen“

**Symptom:** Der Abschlussdialog („Neu erstellen abgeschlossen“) zeigt zum Beispiel
`Monatlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen`. Der Status ist trotzdem „abgeschlossen“:
Er sagt nur, dass `src.main` ohne Fehler endete.

**Prüfen:** `state/web-jobs/<id>.result` (dieselben Zeilen) und `logs/<job>/<heute>.log`, dort die
Zeilen zur Kamera. Das Protokoll trägt das Datum des Auftrags.

**Ursache:** *Übersprungen:* zu wenige Tage mit Bildern (Monthly mindestens 25 von 30, Yearly 300),
bei einer Blur-Kamera kein bestätigt verpixeltes Bild ([Sperre](verpixelung-box.md#sperre-in-automatischen-videos))
oder keine Bilder am Tag. *Fehlgeschlagen:* ein Fehler bei dieser Kamera (Bildabruf, FFmpeg,
Zeitüberschreitung); die Stelle steht im Protokoll.

**Lösung:** Bei Blur-Kameras das nächtliche Nachholen der Verpixelung abwarten und neu erstellen;
sonst den Fehler wie beim [nächtlichen Lauf](#fehler-nächtlicher-lauf) suchen. Ein übersprungenes
Video lässt das vorhandene stehen.

### Hochladen schlägt fehl

**Symptom:** Der Dialog meldet „Hochladen fehlgeschlagen“ („Bitte das Anwendungsprotokoll prüfen.“),
oder die Ergebniszeile zeigt `fehlgeschlagen` über 0, zum Beispiel
`Hochgeladen: 2, übersprungen: 0, fehlgeschlagen: 1, gelöscht: 0`.

**Prüfen:** `tail -n 60 ~/timelapse/logs/siteground-delivery.log` (die ausführliche Ausgabe enthält den
FTP-Zugang: nichts davon weitergeben). `./install.sh verify` zeigt, ob die drei `SITEGROUND_*`-Werte
gesetzt sind.

**Ursache:** Ohne Ergebniszeile: Die Zugangsdaten fehlen (Exit 2), die Liste der Videos ist leer, oder
für diese Kamera läuft schon ein Upload, zum Beispiel der nächtliche (Exit 3). Mit Ergebniszeile: Eine
Datei fehlte oder ließ sich nicht hochladen oder umbenennen (FTP-Fehler); dort wird dann auch nicht
aufgeräumt.

**Lösung:** Zugangsdaten in `config/siteground.env` ergänzen, nach einem laufenden Upload erneut
starten, bei FTP-Fehlern später noch einmal. Mehr zum Skript:
[Upload auf die Website](betrieb.md#upload-auf-die-website).

### Auftrag scheint zu hängen

**Prüfen:**

```bash
ls -l ~/timelapse/state/web-jobs/                       # <id>.pid, <id>.status, <id>.reason
pgrep -af "src.main"
```

**Ursache:** Entweder rendert er noch, oder der Prozess ist gestorben. Ein toter Prozess wird beim
nächsten Abfragen als fehlgeschlagen gemeldet, ebenso ein Auftrag, der nach einer Minute noch keine
`.pid` hat.

**Lösung:** Läuft `src.main` noch, abwarten. Wurde Apache in der Zwischenzeit neu gestartet, ist der
Auftrag beendet worden; neu starten.

### Löschen schlägt fehl

**Symptom:** „Das Video konnte nicht gelöscht werden.“ bzw. „Das Bild konnte nicht gelöscht werden.“

**Prüfen:** `sudo -l -U www-data` muss `timelapse-web-delete` bzw. `timelapse-web-delete-highlight`
zeigen; Details im Apache-Fehlerprotokoll.

**Lösung:** Fehlenden Wrapper und sudoers-Zeile nach
[Installation](installation.md#wrapper-installieren) ergänzen.

### „Die Anfrage ist ungültig (Sicherheitstoken).“

**Ursache:** Die Sitzung ist abgelaufen (nach 24 Minuten ohne Aktivität).

**Lösung:** Seite neu laden und erneut absenden.

### Einstellungen lassen sich nicht speichern

**Symptom:** Auf der Seite „Einstellungen“ bleibt die Speicherung aus, mit einer Meldung oben.

| Meldung | Ursache | Lösung |
|---|---|---|
| „Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden.“ | Jemand anderes hat im selben Reiter gespeichert, seit die Seite geladen wurde | Seite neu laden, die eigene Änderung erneut eintragen |
| Meldung mit dem Namen eines Feldes (Wert „muss …“) | Wert außerhalb der Grenzen; nichts wurde gespeichert | Wert korrigieren; die Grenzen stehen in der Meldung und in [konfiguration.md](konfiguration.md#einstellungen-der-weboberfläche) |
| „Mindestens eine Kamera muss angehakt bleiben.“ | Alle Kameras abgewählt | mindestens eine ankreuzen |
| „Unter „Kameras“ abgewählt, unter „Highlights“ aber noch angehakt: …“ | Eine Kamera ist nicht mehr zur Verarbeitung angehakt, aber noch für die Highlights; der Flagger würde für alle Kameras nicht mehr starten | die Kamera unter „Highlights“ ebenfalls abwählen |
| „Die Einstellungen konnten nicht gespeichert werden.“ | der Wrapper lief nicht oder scheiterte | siehe unten |
| „Bitte die Änderungen bestätigen.“ (Verpixelung) | der Bestätigungsdialog wurde umgangen oder das Kästchen ohne JavaScript fehlt | erneut speichern und im Dialog „Ja, speichern“ wählen |

**Prüfen (letzte Meldung):** `sudo -l -U www-data` muss `timelapse-web-settings` zeigen; im
Apache-Fehlerprotokoll steht `Settings wrapper failed with exit code <N>`. Exit 64: falsche Eingabe oder
zu großer Text, 69: die Python-Umgebung unter `~/timelapse/.venv` fehlt, 65 und 73 sind die beiden
Fälle oben. Schlägt auch das Schreiben fehl, prüfen, ob der Projektbenutzer in `config/` schreiben darf.

**Lösung:** Wrapper und sudoers-Zeile nach [Installation](installation.md#wrapper-installieren) ergänzen
bzw. mit `./install.sh web_bridge` neu installieren (nur wenn kein Auftrag läuft).

**Gespeichert, aber ohne Wirkung:** Die Werte gelten ab dem **nächsten** Auftrag; ein laufender hat seine
Config schon gelesen. Für eine Verpixelungs-Kamera greifen Streifen, Schwellen und Rahmen nur auf Bilder,
die danach verpixelt werden. Ein Wert, den jemand in `config.json` geändert hat, wirkt nicht, solange
derselbe Schlüssel in `config/settings.json` oder `config/settings-privacy.json` steht: dort gewinnt die
Einstellungsdatei. Auf der Seite zurücksetzen oder den Schlüssel aus der Datei löschen. Was gespeichert
wurde, zeigt `logs/settings.log` (eine Zeile je Speicherung, mit altem und neuem Wert).

### Das Vorschaubild fehlt oder lässt sich nicht aktualisieren

**Symptom:** Im Reiter „Verpixelung“ steht bei einer Kamera kein Bild, oder „Vorschau aktualisieren“ meldet einen Fehler.

| Meldung | Ursache | Lösung |
|---|---|---|
| „Für diese Kamera gibt es noch kein geprüftes Bild.“ | Die Verpixelung hat in den letzten drei Tagen noch kein Bild dieser Kamera geprüft (Nachtbilder zählen nicht, die notiert sie ohne Erkennung), etwa bei einer neu angehakten Kamera | nach der nächsten Nacht erneut versuchen; die Zahlenzeilen für Rahmen gehen auch ohne Bild |
| „Diese Kamera wird nicht verpixelt.“ | Die Kamera steht nicht in der gespeicherten Liste der Verpixelungs-Kameras | erst speichern, dann aktualisieren |
| „Die Speicherbox hat nicht rechtzeitig geantwortet.“ | Der Wrapper hat nach 90 Sekunden abgebrochen | später erneut; Verbindung zur Storage Box prüfen ([Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar)) |
| „Das Bild konnte nicht geholt werden.“ | Wrapper fehlt oder scheiterte, die Box antwortet nicht, oder das Bild ist beschädigt | Apache-Fehlerprotokoll: `Preview wrapper failed with exit code <N>`; `sudo -l -U www-data` muss `timelapse-web-preview` zeigen; im Anwendungsprotokoll `Preview failed` oder `not fit to show` |

Ein Bild, das PHP nicht als JPEG mit sinnvoller Größe lesen kann, wird nie angezeigt; dann steht dort der
Hinweis „noch kein Bild“, bis ein Bild geholt werden kann. Das Bild ist immer eins, das die Verpixelung schon
geprüft hat, nie ein Rohbild.

### Änderungen an einem Wrapper wirken nicht

**Ursache:** Apache ruft die installierten Kopien unter `/usr/local/` auf, nicht `scripts/`.

**Lösung:** Den geänderten Wrapper mit `sudo install` neu installieren
([Installation](installation.md#wrapper-installieren)).

---

## Fehler: Erkennung, Highlights und Verpixelung

Flagger und Verpixelung nutzen das Erkennungsmodell YOLOX (`models/`, über `onnxruntime`).

### Modelldatei fehlt

**Symptom:** `Flagger not started: model file missing: models/object_detection_yolox_2022nov.onnx`;
bei der Verpixelung bricht der Lauf ab, statt ein ungeprüftes Video zu erzeugen.

**Lösung:** `models/` aus der Sicherung zurückspielen (`./install.sh restore`; bevorzugt: dieselbe Datei hält
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
- Verpixelung: bekannte Fehlerkennungen ausschließen, am bequemsten auf der Weboberfläche im Reiter
  „Verpixelung“ (Rahmen auf dem Kamerabild ziehen, oberen Rand und Mindest-Sicherheit je Kamera
  einstellen); von Hand über `ignore_boxes`, `ignore_top_share`, `skip_labels` und
  `min_person_score` in der Config
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

**Lösung:** Die wiederkehrenden Stellen als `ignore_boxes` der Kamera eintragen: auf der Weboberfläche im
Reiter „Verpixelung“ mit „Rahmen bearbeiten“ ein Rechteck über die Stelle ziehen und speichern
([weboberflaeche.md](weboberflaeche.md#reiter-verpixelung-verpixelungphp)), oder von Hand in
`config/config.json`. Wirkt ab dem nächsten Lauf, ohne Neustart; auf der Seite eingetragene Rahmen stehen
in `config/settings-privacy.json`. Vorher prüfen, dass keine echte Person
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
| `Flagger not started: ...` mit unbekannter oder ignorierter Kamera | Kamera in `flagger.cameras` existiert nicht oder steht in `ignored_cameras`; dann startet der Flagger für **alle** Kameras nicht. Die Seite „Einstellungen“ speichert diese Kombination nicht, sie entsteht nur durch Handarbeit in einer Datei | die Kamera aus `flagger.cameras` oder aus `ignored_cameras` nehmen (in `config.json`, `config/settings.json` oder auf der Seite) |
| `Flagger not started: flagger.retention_days must be at least 7` | Wert unter einer Woche, von Hand eingetragen; die Seite lässt weniger als 7 nicht zu | Wert auf mindestens 7 setzen |
| `[<Kamera>] no images for <Datum> - nothing written` | keine Tagesbilder | wie [Eine Kamera hat keine Bilder](#eine-kamera-hat-keine-bilder) |
| gelöschtes Highlight ist wieder da | der Tag wurde neu geprüft, der Ordner ersetzt | erneut löschen |

Highlights-Seite: [highlights-seite.md](highlights-seite.md#fehlersuche).

### Verpixelung

Fehlerbilder und Lösungen stehen in den eigenen Tabellen:
[verpixelung.md](verpixelung.md#fehlersuche) (Videos) und
[verpixelung-box.md](verpixelung-box.md#fehlersuche) (Storage Box). Grundsatz: Im Zweifel bricht
die Verpixelung ab und schreibt nichts; ein Abbruch ist also kein Datenverlust.

`Unsafe storage box remote: '<Wert>'` heißt: Der Alias in `TIMELAPSE_STORAGE_BOX` (der Teil vor
einem `:`) enthält ein Zeichen, das die Verpixelung nicht akzeptiert. Erlaubt sind Buchstaben,
Ziffern, `.`, `_` und `-` (am Anfang ein Buchstabe oder eine Ziffer, damit der Wert nie als
ssh-Option gelesen wird), optional als `benutzer@host`. Den Eintrag in `~/.ssh/config` danach
benennen oder den Alias in der Cron-Zeile korrigieren.

Die Meldungen `[<Kamera>] Blur gate: left out N of M unconfirmed images: …` und
`[<Kamera>] Blur gate: no confirmed image - skipping camera.` kommen aus der Sperre der
automatischen Videos von Blur-Kameras.
Das erste heißt: N Bilder hat der Box-Job nicht bestätigt, das Video entsteht aus den übrigen; das
zweite: gar kein Bild war bestätigt, die Kamera wird übersprungen und ihr bisheriges Video bleibt.
Ursachen, Prüfung und Lösung:
[verpixelung-box.md](verpixelung-box.md#fehlersuche).

### Upload auf die Website

Das Protokoll steht in `logs/siteground-delivery.log`; je Kamera endet es mit
`Ergebnis: hochgeladen=… übersprungen=… fehlgeschlagen=… gelöscht=…`
([betrieb.md](betrieb.md#upload-auf-die-website)).

| Meldung | Ursache | Lösung |
|---|---|---|
| `Die Liste der freigegebenen Videos konnte nicht erstellt werden.` | `scripts/list-deliverable-videos.py` ist fehlgeschlagen, z. B. weil `videos/` fehlt | das Skript einzeln ausführen und die Meldung lesen |
| `Die Liste ist leer: Es wird nichts gesendet und nichts gelöscht.` oder `Die Liste ist leer: Für <Kamera> wird nichts gesendet und nichts gelöscht.` | keine freigegebenen Videos (alle Kameras in `ignored_cameras`, noch keine Videos) bzw. die genannte Kamera ist nicht freigegeben | Liste prüfen: `.venv/bin/python3 scripts/list-deliverable-videos.py` |
| `SITEGROUND_HOST, SITEGROUND_USER und SITEGROUND_PASS müssen ausgefüllt sein.` | `config/siteground.env` fehlt oder ist unvollständig | `./install.sh upload_login` legt sie aus der Vorlage an (leer), dann die drei Werte eintragen, siehe [betrieb.md](betrieb.md#upload-auf-die-website) |
| `Es läuft bereits ein anderer Lauf.` (Rückgabewert 3) | für diese Kamera läuft schon ein Upload | warten und wiederholen |
| `Upload fehlgeschlagen: …` oder `Umbenennen fehlgeschlagen: …` | FTP-Verbindung oder Rechte auf der Website | Aufgeräumt wird in diesem Ordner dann nicht (`Aufräumen von … übersprungen`); Verbindung prüfen, die nächste Nacht lädt erneut hoch |
| `Mindestens eine Kamera ist fehlgeschlagen.` | siehe die Zeilen darüber im Protokoll | je Kamera behandeln |

### Speicherfilter

`TIMELAPSE_STORAGE_BOX is not set` heißt: Die Storage Box ist nicht angegeben; die Variable setzen
([Konfiguration](konfiguration.md#umgebungsvariablen)). Kommt trotz gesetzter Variable `Storage box listing
failed`, siehe [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar).

### WordPress

Siehe [wordpress.md](wordpress.md#fehlerbehebung-wordpress-frontend).

---

## Fehler: Sicherung und Wiederherstellung

Meldungen von `backup.sh` und vom Schritt `restore` des Installers, dazu die ssh-Meldung bei
geändertem Host-Key, die rsync durchreicht.

| Meldung | Ursache | Lösung |
|---|---|---|
| `BACKUP_HOST is not set: …` | der ssh-Alias fehlt | `BACKUP_HOST=<alias> ./backup.sh` oder den Alias in `backup.env` eintragen |
| `Invalid BACKUP_HOST: …` | der Alias beginnt nicht mit Buchstabe oder Ziffer oder enthält andere Zeichen als Buchstaben, Ziffern, `.`, `_`, `@` und `-` | den Alias aus `~/.ssh/config` verwenden |
| `Invalid PROJECT_DIR (relative to the host's home, no '..'): …` | der Pfad ist absolut, enthält `..` oder Zeichen außer Buchstaben, Ziffern, `.`, `_`, `/` und `-` | relativ zum Home-Ordner des Hosts angeben, zum Beispiel `timelapse` |
| `VIDEOS must be 0 or 1.` | `VIDEOS` hat einen anderen Wert | `0` oder `1` setzen |
| `ssh was not found on this computer.` oder `rsync was not found on this computer.` | Werkzeug fehlt auf dem eigenen Rechner | installieren |
| `[WARN] models/ could not be saved.` und am Ende `Not saved: …` | rsync konnte den Ordner nicht holen (Ordner fehlt auf dem Host, `PROJECT_DIR` falsch, Verbindung) | die rsync-Meldung davor lesen, Alias und `PROJECT_DIR` prüfen; alles andere ist gesichert, der Lauf ist wiederholbar |
| `No crontab on <alias> (or it is not readable).` | der Host hat keine Crontab | nichts: `crontab.txt` bleibt leer, die Sicherung ist trotzdem vollständig |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Host neu installiert | Fingerabdruck prüfen, dann `ssh-keygen -R <host>` |
| `BACKUP_DIR must be an absolute path: …` (bei `install.sh`) | `BACKUP_DIR` ist relativ | absoluten Pfad angeben |
| `No backup folder at …: nothing to restore` | es liegt keine Sicherung bereit | bei einem Neuaufbau ohne Sicherung normal; sonst die Sicherung nach `~/timelapse-backup` kopieren und `./install.sh restore` starten |
| `… holds no models/, state/ or videos/: nothing restored.` | der Sicherungsordner enthält keinen dieser Ordner | Inhalt prüfen: `ls ~/timelapse-backup` |

Einrichtung des Servers: [vps.md](vps.md).

---

## Fehler: Entwicklung und CI

### CI ist rot, lokal ist alles grün

**Prüfen:** den fehlschlagenden Test im Log der GitHub Action.

**Ursache:** Die CI-Umgebung unterscheidet sich vom Server:

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

**Ursache:** Nur wenn lokal ein Pre-Push-Hook (`.git/hooks/pre-push`, nicht versioniert) eingerichtet
ist: Er führt `ruff check`, `ruff format --check` und `pytest` aus und bricht bei einem Fehler ab
([architektur.md](architektur.md#github-actions-und-pre-push-hook)). Im Klon auf dem Mac steht
Stand 30.10.2026 keiner; dort prüft erst CI.

**Lösung:** `ruff format .` und den Fehler beheben. `git push --no-verify` nur im Notfall; CI prüft
dasselbe ohnehin.

### Tests laufen auf dem Mac nicht vollständig durch

**Ursache:** Auf macOS schlagen rund 67 Tests aus Plattformgründen fehl (BSD-`ls` und BSD-`date`
statt GNU, `spawn` statt `fork`; Stand 29.10.2026: 897 bestanden, 67 fehlgeschlagen, ohne
`onnxruntime`). Das ist kein Fehler im Code.

**Lösung:** Maßgeblich sind der VPS und CI (beide Linux). Änderungen pushen und auf dem VPS mit
`git pull` holen ([vps.md](vps.md#code-auf-den-vps-bringen)) und dort
`.venv/bin/python3 -m pytest`, `ruff check .` und `ruff format --check .` ausführen. Fehlschläge,
die über die bekannten macOS-Fälle hinausgehen, sind echt.

---

## Arbeitsspeicher

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
  Dateien; [Konfiguration](konfiguration.md#umgebungsvariablen)).
