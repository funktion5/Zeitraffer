# Zeitraffer

Automatisierte Erstellung von Timelapse-Videos aus den Bildbeständen mehrerer Kameras auf einem Raspberry Pi.

Das System liest Originalbilder aus den unter `/mnt/cameras` eingebundenen Kameraordnern, wählt je nach Timelapse-Typ passende Frames aus und erzeugt daraus MP4-Videos mit FFmpeg.

**Die Originalbilder unter `/mnt/cameras` werden niemals verändert.**

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

## Projektstruktur

```text
timelapse/
├── config/
│   ├── config.json
│   └── mount.env.example
├── scripts/
│   ├── cameras-sshfs-preflight
│   ├── test_workflow.sh
│   ├── timelapse-web-status.sh
│   ├── timelapse-web-trigger
│   └── timelapse-web-worker
├── src/
│   ├── jobs/
│   │   ├── daily.py
│   │   ├── weekly.py
│   │   ├── monthly.py
│   │   └── yearly.py
│   ├── config.py
│   ├── date_coverage.py
│   ├── diagnostics.py
│   ├── image_worker.py
│   ├── images.py
│   ├── logger.py
│   ├── main.py
│   ├── run_state.py
│   ├── solar.py
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
│   ├── logger_test.py
│   ├── main_test.py
│   ├── monthly_test.py
│   ├── run_state_test.py
│   ├── video_test.py
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
│       │   └── header.php
│       ├── job-runner.php
│       └── video-library.php
├── logs/
├── state/
├── temp/
├── videos/
├── create_test_video.py
├── monthly_range_test.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

Runtime-Daten unter `logs/`, `state/`, `temp/` und `videos/` werden nicht als Quelldaten behandelt.

`create_test_video.py`, `monthly_range_test.py` und `scripts/test_workflow.sh` sind ältere, manuell ausgeführte Entwicklungs- und Diagnoseskripte. Sie gehören nicht zum produktiven Workflow und nicht zur automatisierten pytest-Suite. `create_test_video.py` verwendet noch eine inzwischen entfernte `create_video`-Schnittstelle und ist im aktuellen Stand nicht lauffähig.

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
- berücksichtigt alle ausgewählten Bilder im täglichen Zielzeitfenster um 12:00 Uhr
- Toleranz: ±90 Minuten

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
- Duplicate-Diagnose und job-spezifische Duplicate-Filterung

Unbekannte Dateinamensformate werden nicht geraten.

### `src/image_worker.py`

Gemeinsame Infrastruktur für isolierte Worker-Prozesse.

Der Supervisor übernimmt:

- `Process` und `Queue`
- Fortschrittsmeldungen
- Stall-Timeout
- `terminate()`
- bei Bedarf `kill()`
- Erkennung unerwartet beendeter Worker
- Weitergabe erwarteter `OSError`

Der Timeout misst **Inaktivität**, nicht die Gesamtlaufzeit. Lange Scans dürfen weiterlaufen, solange Fortschritt gemeldet wird.

### `src/date_coverage.py`

Gemeinsame Datumslogik für exakte rollierende Fenster:

- Weekly: 7 Kalendertage inklusive Enddatum
- Monthly: 30 Kalendertage inklusive Enddatum
- Yearly: 365 Kalendertage inklusive Enddatum
- Ermittlung fehlender Kalendertage
- kompakte Darstellung aufeinanderfolgender fehlender Tage für Logs

### `src/yearly_selection.py`

Yearly-spezifische Frame-Auswahl.

Pro Kalendertag:

1. Kandidaten nach Abstand zu 12:00 Uhr priorisieren.
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

### `src/logger.py`

- gemeinsamer Anwendungslogger
- INFO-Ausgabe auf der Konsole
- DEBUG-Ausgabe in tagesbasierten Job-Logs
- Wechsel des File-Handlers zwischen Job-Typen
- Run-ID pro Prozess
- konfigurierbare Log-Retention

### `src/run_state.py`

Verwaltet den persistenten Marker `state/run-in-progress` für den vollständigen automatischen Produktionslauf. Details stehen im Abschnitt „Run-State und Wiederanlauf“.

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
  "image_scan_stall_timeout_seconds": 60,
  "log_retention_days": 30,
  "ignored_cameras": [
    "Reolink"
  ],
  "timelapse": {
    "daily_framerate": 10,
    "monthly_framerate": 20,
    "yearly_framerate": 20,
    "ffmpeg_threads": 2
  }
}
```

Die Tests prüfen unter anderem:

- erwarteten Config-Pfad
- Existenz der Datei
- gültige JSON-Syntax
- erwartete Schlüssel
- grundlegende Datentypen

---

## Kameraerkennung

### Kamera-Storage über SSHFS

Die Originalbilder werden unter `/mnt/cameras` bereitgestellt. Das Repository enthält dafür:

- `systemd/cameras-sshfs.service`
- `scripts/cameras-sshfs-preflight`
- `config/mount.env.example`

Der systemd-Service mountet den entfernten Storage mit SSHFS ausschließlich lesend (`-o ro`). Die Option `allow_other` erlaubt dem Apache-Benutzer `www-data`, den Mount im Rahmen der normalen Dateirechte zu lesen. Sie erteilt keine Schreibrechte. Vor dem Mount prüft das Preflight-Skript, ob bereits ein erreichbarer Mount existiert oder ein nicht erreichbarer FUSE-Mount bereinigt werden muss.

Die produktiven Verbindungswerte liegen außerhalb des Repositories unter:

```text
/etc/timelapse/mount.env
```

Erwartete Variablen:

```text
REMOTE_USER=
REMOTE_HOST=
REMOTE_PORT=
REMOTE_SSH_KEY=
```

Der Service erwartet außerdem den SSH-Schlüssel unter `/home/zruser/.ssh/storagebox_ed25519` und den vorhandenen Mountpoint `/mnt/cameras`.

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

---

## Bildvalidierung und Duplikate

0-Byte-Dateien werden vor der weiteren Verarbeitung ausgeschlossen und geloggt. Die Quelldateien bleiben unverändert.

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

## Timelapse-Typen

### Daily

- Zieldatum: standardmäßig gestern
- optional: explizites Zieldatum über `--target-date`
- Quelle: Originalbilder
- Auswahl: Sunrise-/Sunset-Fenster inklusive Buffer für den Zieltag; der vollständige Vortag dient als Duplicate-Referenz
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
- täglich 10:30 bis 13:30 Uhr
- verwendet alle ausgewählten Intervallbilder
- filtert byte-identische Bilder innerhalb jedes einzelnen Tages
- Framerate: `monthly_framerate`

### Yearly

- Fenster: rollierende 365 Tage inklusive Enddatum
- Enddatum: standardmäßig gestern oder explizites `--target-date`
- Quelle: Originalbilder
- tägliche Kandidaten aus 10:30 bis 13:30 Uhr
- Zielzeit: 12:00 Uhr
- bis zu 5 eindeutige Frames pro Tag
- bei Duplikaten werden weitere Kandidaten nachgezogen
- Framerate: `yearly_framerate`

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
```

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
```

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

## Zeitplanung mit Cron

Die Zeitplanung erfolgt über Linux-Cron. Es gibt keinen internen Python-Scheduler.

### Nächtlicher Produktionslauf

Die installierte Crontab startet den vollständigen Workflow täglich um 02:00 Uhr:

```cron
0 2 * * * flock -n /home/zruser/timelapse/state/zeitraffer-run.lock -c 'cd /home/zruser/timelapse && /home/zruser/timelapse/.venv/bin/python3 -m src.main'
```

`flock -n` verwendet einen nicht blockierenden Lock. Läuft bereits ein Prozess mit demselben Lock, wird kein zweiter Produktionslauf gestartet.

### Wiederanlauf nach Neustart

Beim Booten wird der Workflow nur gestartet, wenn `state/run-in-progress` existiert. Da der Kamera-Storage eventuell noch nicht bereit ist, wartet Cron zunächst auf einen echten Mount unter `/mnt/cameras`:

```cron
@reboot if [ -f /home/zruser/timelapse/state/run-in-progress ]; then until mountpoint -q /mnt/cameras; do sleep 5; done; flock -n /home/zruser/timelapse/state/zeitraffer-run.lock -c 'cd /home/zruser/timelapse && /home/zruser/timelapse/.venv/bin/python3 -m src.main'; fi
```

Der nächtliche Lauf und die Reboot-Wiederherstellung verwenden beide:

```text
/home/zruser/timelapse/state/zeitraffer-run.lock
```

Dadurch können sie nicht überlappen. Es ist keine zusätzliche Cron-Logdatei konfiguriert; die Anwendung schreibt ihre eigenen Job-Logs.

Installierte Einträge prüfen:

```bash
crontab -l
```

---

## Logging

Logs werden nach Job-Typ getrennt:

```text
logs/
├── daily/YYYY-MM-DD.log
├── weekly/YYYY-MM-DD.log
├── monthly/YYYY-MM-DD.log
└── yearly/YYYY-MM-DD.log
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

### Aktueller Funktionsumfang

Die Startseite listet die unter `/mnt/cameras` gefundenen Kameraverzeichnisse auf. Die Kameraseite bietet:

- Anzeige von gesamtem, verwendetem und freiem Speicherplatz des Dateisystems von `videos/`
- Bibliothek der historischen Videos unter `videos/<camera>/manual-runs/`
- Wiedergabe des ausgewählten MP4 direkt im Browser
- Formular für genau eine Kamera, einen Job-Typ und ein Zieldatum
- historische Daily-, Weekly-, Monthly- und Yearly-Läufe
- Live-Status per Polling im Abstand von fünf Sekunden
- Abschlussdialog nach erfolgreichem oder fehlgeschlagenem Job

Die Bibliothek zeigt derzeit ausschließlich `manual-runs`. Automatische Videos werden noch nicht in der Oberfläche aufgelistet. Eine Löschfunktion ist nicht implementiert.

Die Kameraerkennung der Weboberfläche ignoriert versteckte Verzeichnisse, wertet `ignored_cameras` aus `config/config.json` derzeit aber nicht aus. Dadurch kann eine global ignorierte Kamera in der Oberfläche erscheinen; die Python-CLI lehnt einen Job für diese Kamera anschließend ab.

### Webdateien

```text
web/public/index.php              Kameraübersicht
web/public/camera.php             Player, Bibliothek, Formular und Status-Polling
web/public/job-status.php         read-only JSON-Status-Endpunkt
web/public/style.css              Darstellung und responsives Layout
web/src/components/header.php     gemeinsamer Header und Speicheranzeige
web/src/video-library.php         Kamera-, Video- und Speicherermittlung
web/src/job-runner.php            Aufruf des fest installierten Triggers
```

`web/public/` ist der einzige Apache-DocumentRoot. PHP-Quellcode außerhalb dieses Verzeichnisses, Python-Code, Konfiguration, Logs, temporäre Dateien und Statusdateien werden nicht direkt durch Apache veröffentlicht.

### Job-Ausführung und Status

Ein gültiger Formular-POST wird durch einen Session-basierten CSRF-Token geschützt. PHP prüft Kamera, Job-Typ und ISO-Datum und ruft anschließend ohne Shell-Auswertung diesen festen Befehl auf:

```text
sudo -n -u zruser /usr/local/sbin/timelapse-web-trigger \
  <job-id> <job> <zieldatum> <kamera>
```

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

Erlaubte Inhalte sind ausschließlich `running`, `completed` und `failed`. `job-status.php` akzeptiert nur eine 32-stellige, kleingeschriebene hexadezimale Job-ID und liefert den Zustand als JSON. Der Browser speichert nur das einmalige Endergebnis in `sessionStorage`, lädt danach die Kameraseite neu und öffnet einen nativen `<dialog>`.

Ein Neuladen der Seite während eines laufenden Jobs verwirft derzeit das aktive Browser-Polling. Der Job läuft weiter und seine Statusdatei bleibt erhalten. Eine automatische Bereinigung alter Web-Statusdateien ist noch nicht implementiert.

Der Trigger verwendet denselben Lock wie Cron:

```text
/home/zruser/timelapse/state/zeitraffer-run.lock
```

Dadurch können ein Web-Job, der nächtliche Produktionslauf und der Wiederanlauf nach einem Neustart nicht gleichzeitig arbeiten. Ist der Lock bereits belegt, meldet die Oberfläche, dass ein anderer Timelapse-Job läuft.

### Apache-Konfiguration

Die aktive Site verwendet sinngemäß folgende Konfiguration:

```apache
<VirtualHost *:80>
    ServerName zeitraffer.local

    DocumentRoot /home/zruser/timelapse/web/public
    DirectoryIndex index.php

    <Directory /home/zruser/timelapse/web/public>
        Options -Indexes
        AllowOverride None
        AuthType Basic
        AuthName "Zeitraffer"
        AuthUserFile /etc/apache2/.htpasswd
        Require valid-user
    </Directory>

    Alias /videos/ /home/zruser/timelapse/videos/

    <Directory /home/zruser/timelapse/videos>
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

Die Site wird unter `http://zeitraffer.local/` oder über die IP-Adresse des Raspberry Pi geöffnet. Der Alias `/videos/` stellt MP4-Dateien bereit und unterstützt die Browser-Wiedergabe. Er umfasst derzeit den gesamten Verzeichnisbaum `videos/`, auch wenn die PHP-Bibliothek nur `manual-runs` auflistet.

Apache läuft als `www-data`. Dieser Benutzer wird nicht in die Gruppe `zruser` aufgenommen. Der SSHFS-Mount nutzt `allow_other`, und die lokalen Projektpfade erhalten nur die für Website, Videos und Web-Status erforderlichen Leserechte. Der Wrapper wird als root-eigene, für `www-data` nicht beschreibbare Kopie unter `/usr/local` installiert.

Die Site verwendet Apache-Basisauthentifizierung, aber weiterhin HTTP statt HTTPS. Zugangsdaten werden dadurch nicht auf dem Transportweg verschlüsselt; die Site darf deshalb weiterhin nicht ohne zusätzliche Transportverschlüsselung aus einem nicht vertrauenswürdigen Netzwerk erreichbar sein.

### Basisauthentifizierung einrichten

Beide Verzeichnisse (`web/public` und der `/videos/`-Alias) werden per `AuthType Basic` geschützt. Die Zugangsdaten liegen in `/etc/apache2/.htpasswd`, außerhalb des Dokumenten-Stammverzeichnisses und damit über HTTP nicht erreichbar; die Datei wird nicht versioniert und darf nicht ins Repository gelangen.

```bash
sudo htpasswd -cB /etc/apache2/.htpasswd zruser
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
curl -i -u zruser http://localhost/  # erwartet: 200 OK nach Passworteingabe
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
```

Die sudoers-Regel erlaubt ausschließlich den festen Trigger als `zruser`:

```sudoers
www-data ALL=(zruser) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
```

Die Regel wird mit folgendem Befehl in einer eigenen Datei sicher bearbeitet und geprüft:

```bash
sudo visudo -f /etc/sudoers.d/timelapse-web
```

Eingaben werden zusätzlich in PHP und im Trigger validiert; die sudoers-Regel allein ersetzt diese Prüfungen nicht.

Nach Änderungen an den versionierten Wrappern müssen die Laufzeitkopien erneut mit `sudo install` aktualisiert werden.

### Webtests

Die Status-, Lock- und Worker-Logik sowie der PHP-Status-Endpunkt werden mit pytest geprüft:

```bash
python3 -m pytest tests/web_status_test.py tests/web_status_endpoint_test.py
```

Die Tests prüfen unter anderem atomare Statuswechsel, ungültige Job-IDs, den gemeinsamen Lock, erfolgreiche Videoveröffentlichung und fehlgeschlagene Jobs.

## Installation

Virtuelle Umgebung erstellen und aktivieren:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Abhängigkeiten installieren:

```bash
python3 -m pip install -r requirements.txt
```

Ruff ist als Entwicklungswerkzeug über `pyproject.toml` konfiguriert. Falls es nicht bereits installiert ist:

```bash
python3 -m pip install ruff
```

FFmpeg muss systemweit verfügbar sein.

### SSHFS-Mount installieren

Voraussetzungen sind `sshfs`, `fusermount3`, ein vorhandener Mountpoint `/mnt/cameras`, ein SSH-Schlüssel und ein passender `known_hosts`-Eintrag für `StrictHostKeyChecking=yes`. Weil der Service `allow_other` verwendet, muss in `/etc/fuse.conf` außerdem die Zeile `user_allow_other` aktiviert sein.

Repository-Dateien installieren:

```bash
sudo install -m 755 scripts/cameras-sshfs-preflight /usr/local/sbin/cameras-sshfs-preflight
sudo install -m 644 systemd/cameras-sshfs.service /etc/systemd/system/cameras-sshfs.service
sudo install -d -m 755 /etc/timelapse
sudo install -m 600 config/mount.env.example /etc/timelapse/mount.env
```

Danach `/etc/timelapse/mount.env` mit den produktiven Verbindungswerten befüllen und den Service aktivieren:

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

Die beiden Einträge aus „Zeitplanung mit Cron“ werden über

```bash
crontab -e
```

für den Benutzer `zruser` installiert. Anschließend prüfen:

```bash
crontab -l
```

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

---

## Linting und Formatierung

Das Projekt verwendet Ruff.

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

## Sicherheit und Datenintegrität

Grundregeln des Projekts:

- Originalbilder unter `/mnt/cameras` niemals verändern.
- Frames nur lokal unter `temp/` vorbereiten.
- Unbekannte Dateinamensformate niemals erraten.
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
