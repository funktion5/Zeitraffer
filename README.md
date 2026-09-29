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
- Backup- und Migrationsskripte für eine Neuinstallation des Raspberry Pi
- Speicherfilter: Bericht über leere und am selben Tag doppelte Bilder pro Kamera (löscht nichts)

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
│   ├── storage-filter-all
│   ├── test_workflow.sh
│   ├── timelapse-web-delete
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
│   ├── logger_test.py
│   ├── main_test.py
│   ├── monthly_test.py
│   ├── run_state_test.py
│   ├── storage_filter_test.py
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
│       │   ├── header.php
│       │   └── job-watcher.php
│       ├── job-runner.php
│       ├── process-runner.php
│       ├── video-delete.php
│       └── video-library.php
├── logs/
├── reports/
├── state/
├── temp/
├── videos/
├── backup-from-mac.sh
├── create_test_video.py
├── migrate.sh
├── monthly_range_test.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

Runtime-Daten unter `logs/`, `reports/`, `state/`, `temp/` und `videos/` werden nicht als Quelldaten behandelt.

`backup-from-mac.sh` und `migrate.sh` sichern bzw. stellen einen Raspberry Pi bei einer Neuinstallation wieder her; siehe „Neuinstallation des Raspberry Pi“.

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

- Fenster: exaktes Kalenderjahr bis einschließlich Enddatum — 365 oder 366 Tage, je nachdem ob ein Schalttag (29. Februar) im Zeitraum liegt; kein fest codiertes 365-Tage-Fenster mehr
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

Die Startseite listet die unter `/mnt/cameras` gefundenen Kameraverzeichnisse auf. Die gesamte Oberfläche ist auf Deutsch; interne Bezeichner (`daily`/`weekly`/`monthly`/`yearly` in Formularwerten, URLs und der CLI) bleiben davon unberührt. Die Kameraseite bietet:

- Anzeige von gesamtem, verwendetem und freiem Speicherplatz des Dateisystems von `videos/`
- Bibliothek der historischen Videos unter `videos/<camera>/manual-runs/`, mit kurzem deutschem Datum statt Dateiname (plus Zeitpuffer in Minuten, sofern der Dateiname einen trägt, z. B. „24.09.2026 (60 Min.)“); die Liste bleibt für den Job-Typ des gerade ausgewählten Videos aufgeklappt
- Wiedergabe des ausgewählten MP4 direkt im Browser, mit Download- und Löschen-Button (Icon + Beschriftung), beide mit Bestätigungsdialog vor dem Absenden
- Formular für genau eine Kamera, einen Job-Typ und ein Zieldatum; bei Daily/Weekly zusätzlich ein Zeitpuffer (30/60/90 Minuten) als Radiogruppe, die nur für diese beiden Job-Typen eingeblendet wird — Monthly/Yearly nutzen keinen Zeitpuffer und erhalten ihn serverseitig auch dann nicht, wenn einer übermittelt würde
- kurzer Hinweistext über dem Formular: Zieldatum ist immer der letzte Tag des Zeitraums, und bei Monthly/Yearly führt ein einziger fehlender Tag im Zeitraum zum Überspringen der Kamera
- historische Daily-, Weekly-, Monthly- und Yearly-Läufe
- Live-Status per Polling im Abstand von fünf Sekunden; der Abschlussdialog übersteht auch einen Seitenwechsel weg von der auslösenden Seite (Fortsetzung des Pollings über `sessionStorage`) und bietet einen direkten Link zum fertigen Video an
- Löschen eines historischen Videos über denselben eingeschränkten Wrapper-Mechanismus wie die Job-Erstellung

Die Bibliothek zeigt derzeit ausschließlich `manual-runs`. Automatische Videos werden noch nicht in der Oberfläche aufgelistet, und eine Status-Datei-Bereinigung ist nicht implementiert.

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

Apache läuft als `www-data`. Dieser Benutzer wird nicht in die Gruppe `zruser` aufgenommen. Der SSHFS-Mount nutzt `allow_other`, und die lokalen Projektpfade erhalten nur die für Website, Videos und Web-Status erforderlichen Leserechte (Details unter „Dateirechte für `www-data`“). Die Wrapper werden als root-eigene, für `www-data` nicht beschreibbare Kopien unter `/usr/local` installiert.

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
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-delete \
  /usr/local/sbin/timelapse-web-delete
```

Die sudoers-Regeln erlauben ausschließlich den festen Trigger und den festen Lösch-Wrapper, jeweils als `zruser`:

```sudoers
www-data ALL=(zruser) NOPASSWD: /usr/local/sbin/timelapse-web-trigger *
www-data ALL=(zruser) NOPASSWD: /usr/local/sbin/timelapse-web-delete
```

Eine sudoers-Regel ohne Argumentliste erlaubt beliebige Argumente. `timelapse-web-delete` erwartet genau Kamera, Job-Typ und Dateiname, prüft diese selbst (kein `/`, nur `.mp4`, keine Symlinks) und löscht ausschließlich unter `videos/<camera>/manual-runs/<job>/`.

Die Regeln werden mit folgendem Befehl in einer eigenen Datei sicher bearbeitet und geprüft:

```bash
sudo visudo -f /etc/sudoers.d/timelapse-web
```

Eingaben werden zusätzlich in PHP und in den Wrappern validiert; die sudoers-Regeln allein ersetzen diese Prüfungen nicht.

Nach Änderungen an den versionierten Wrappern müssen die Laufzeitkopien erneut mit `sudo install` aktualisiert werden.

### Dateirechte für `www-data`

`www-data` wird nicht in die Gruppe `zruser` aufgenommen und erhält nur Zugriff auf das, was die Weboberfläche tatsächlich liest. Alles andere – Python-Code, Skripte, Tests, `.git`, `.venv`, Logs, temporäre Dateien und alle übrigen Dateien im Home-Verzeichnis – bleibt für `www-data` gesperrt.

| Pfad | Rechte für „andere“ | Zweck |
|---|---|---|
| `/home/zruser` | nur Durchgang (`--x`) | Weg zum Projekt |
| übrige Einträge in `/home/zruser` | keine | z. B. `pi-backup.tar.gz`, `.ssh`, `Claude-Brain` |
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

### Webtests

Die Status-, Lock- und Worker-Logik sowie der PHP-Status-Endpunkt werden mit pytest geprüft:

```bash
python3 -m pytest tests/web_status_test.py tests/web_status_endpoint_test.py
```

Die Tests prüfen unter anderem atomare Statuswechsel, ungültige Job-IDs, den gemeinsamen Lock, erfolgreiche Videoveröffentlichung und fehlgeschlagene Jobs.

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

Das Skript startet den Speicherfilter per `nohup` im Hintergrund und gibt die PID sowie den Pfad der Konsolenausgabe aus (`logs/filter/run_YYYY-MM-DD_HHMMSS.out`). Fortschritt verfolgen mit `tail -f` auf diese Datei, abbrechen mit `kill -INT <PID>`. Die `.out`-Dateien fallen nicht unter die Log-Retention und müssen bei Bedarf von Hand gelöscht werden.

Der Speicherfilter nimmt denselben Lock wie Cron und die Weboberfläche (`state/zeitraffer-run.lock`). Läuft bereits ein Timelapse-Lauf, bricht er sofort ab. Er schreibt kein `state/run-in-progress` und wird nach einem Neustart nicht automatisch fortgesetzt.

Fehler einer Kamera (`OSError`, `TimeoutError`) werden protokolliert; die übrigen Kameras laufen weiter. Der Exit-Code ist dann `1`.

### Ablauf

1. **Liste per SSH:** Ein einziges `ls -l` auf der Storage Box liefert alle Dateinamen mit Größe (Uferstrasse, ca. 189.000 Dateien: rund 3,5 Sekunden). Benutzer und Host kommen aus dem laufenden SSHFS-Mount (`/proc/mounts`); Port `23` und der Schlüssel `~/.ssh/storagebox_ed25519` sind im Code hinterlegt. Ändern sie sich in `/etc/timelapse/mount.env`, müssen sie in `src/storage_filter.py` mitgeändert werden. Ohne aktiven Mount bricht der Speicherfilter ab.
2. **Leere Dateien:** Alle JPGs mit 0 Byte laut Liste.
3. **Duplikate pro Tag:** Nur Dateien, die am selben Aufnahmetag (laut Dateiname) dieselbe Größe haben, werden verglichen. Die SHA-256-Hashes berechnet die Storage Box selbst (`sha256sum`, 1.000 Dateien pro Aufruf, 4 Aufrufe parallel); über das Netz kommen nur die Hashes, nicht die Bilder. Behalten wird die erste Datei des Tages in Dateinamen-Reihenfolge; gemeldet werden alle späteren Kopien.

Der Speicherfilter liest keine Bilddateien über `/mnt/cameras`; der Mount wird nur benötigt, um Benutzer und Host der Storage Box zu ermitteln. Fehlt beim Hashen eine Datei oder ist sie nicht lesbar, schlägt die Kamera fehl, statt die Datei als eindeutig zu behandeln.

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

## Installation

Die folgenden Abschnitte beschreiben die Einrichtung von Hand. Für einen neu installierten Pi mit vorhandenem Backup übernimmt `migrate.sh` alle Schritte; siehe „Neuinstallation des Raspberry Pi“.

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
| `~/.ssh/storagebox_ed25519` und `.pub` | `pi-backup.tar.gz` | `~/.ssh/` (`600` / `644`) |
| `~/.ssh/known_hosts` | `pi-backup.tar.gz` | wird zusammengeführt, keine doppelten Zeilen |
| `/etc/timelapse/mount.env` | `pi-backup.tar.gz` | `root:root 600` |
| `/etc/sudoers.d/timelapse-web` | `pi-backup.tar.gz` | `root:root 440`, nur nach erfolgreicher `visudo`-Prüfung |
| `/etc/apache2/.htpasswd` | `pi-backup.tar.gz` | `root:www-data 640` |
| `/etc/apache2/sites-available/zeitraffer.conf` | `pi-backup.tar.gz` | `root:root 644` |
| Crontab von `zruser` | `pi-crontab.txt` | Crontab von `zruser` |
| `config/config.json` | `config.json` | `config/config.json` (überschreibt die Git-Version) |
| `videos/` | `videos/` | von Hand, siehe Schritt 6 |

`pi-backup.tar.gz` enthält einen privaten SSH-Schlüssel, die Zugangsdaten des Kamera-Storage und einen Passwort-Hash. Der Backup-Ordner auf dem Mac wird deshalb mit Modus `700` angelegt und darf nicht in Cloud-Sync-Ordner oder ins Repository gelangen. Achtung: Der Standardordner liegt unter `~/Documents`. Ist in den macOS-Einstellungen die iCloud-Option „Schreibtisch & Dokumente“ aktiv, wird er in die iCloud hochgeladen – dann über `DEST` einen Ordner außerhalb von `Documents` und `Desktop` wählen und in den folgenden Befehlen denselben Pfad verwenden.

Bewusst nicht gesichert:

- `logs/`, `temp/` und `state/` – reine Laufzeitdaten
- die SSH-Hostschlüssel des Pi – der neu installierte Pi erhält neue; siehe Schritt 3
- WLAN-Konfiguration – der Pi läuft ausschließlich über Ethernet, WLAN wird deaktiviert

### Voraussetzungen

- Mac mit Zugriff auf den Pi per SSH (Passwort-Login als `zruser`)
- ein Checkout dieses Repositorys auf dem Mac, damit `migrate.sh` von dort auf den Pi kopiert werden kann
- das `sudo`-Passwort von `zruser` auf dem Pi
- die offiziellen Host-Key-Fingerprints der Storage Box beim Anbieter (nur nötig, wenn das Backup noch kein `known_hosts` enthält)
- Netzwerkkabel am Pi: `migrate.sh` schaltet WLAN ab

### Schritt 1: Backup auf dem Mac erstellen

Im Repository-Checkout auf dem Mac:

```bash
./backup-from-mac.sh
```

Das Skript fragt einmal nach dem SSH-Passwort und einmal nach dem `sudo`-Passwort auf dem Pi. Anschließend:

1. packt es die Geheimnisse auf dem Pi mit `umask 077` nach `/tmp/pi-backup.tar.gz`, lädt das Archiv herunter und löscht es auf dem Pi wieder, auch wenn ein späterer Schritt fehlschlägt,
2. speichert die Crontab und `config.json`,
3. synchronisiert `videos/` per `rsync`,
4. listet den Inhalt des Archivs auf und gibt die Befehle für die Wiederherstellung aus.

Optionen über Umgebungsvariablen:

| Variable | Standard | Bedeutung |
|---|---|---|
| `PI_HOST` | `zr-pi.local` | Hostname oder IP des Pi, z. B. `PI_HOST=192.168.178.41`, falls `.local` nicht aufgelöst wird |
| `PI_USER` | `zruser` | Login-Benutzer auf dem Pi |
| `DEST` | `/Users/praktikant/Documents/Migration` | Backup-Ordner auf dem Mac |
| `SKIP_VIDEOS` | `0` | `1` überspringt die Videos |

Danach prüfen, ob der Backup-Ordner vollständig ist:

```bash
ls -la /Users/praktikant/Documents/Migration
# erwartet: pi-backup.tar.gz, pi-crontab.txt, config.json, videos/
tar tzf /Users/praktikant/Documents/Migration/pi-backup.tar.gz
# erwartet: 7 Einträge, darunter home/zruser/.ssh/known_hosts
```

Erst weitermachen, wenn das Backup vollständig ist.

### Schritt 2: Betriebssystem neu installieren

Mit dem Raspberry Pi Imager ein 64-Bit-Raspberry-Pi-OS auf Basis von Debian 13 (trixie) schreiben und in den erweiterten Einstellungen festlegen:

- Hostname: `zr-pi`
- Benutzer: `zruser` – der Name ist in Skripten, Cron, sudoers und Apache fest hinterlegt
- SSH aktivieren, Anmeldung per Passwort
- kein WLAN nötig

Den Pi per Netzwerkkabel anschließen und starten.

### Schritt 3: Alten Host-Key auf dem Mac entfernen

Der neu installierte Pi hat neue SSH-Hostschlüssel. Ohne diesen Schritt bricht SSH mit `REMOTE HOST IDENTIFICATION HAS CHANGED` ab:

```bash
ssh-keygen -R zr-pi.local
ssh-keygen -R 192.168.178.41   # IP des Pi
ssh zruser@zr-pi.local          # neuen Fingerprint mit "yes" bestätigen
```

### Schritt 4: Backup und Installer auf den Pi kopieren

Im Repository-Checkout auf dem Mac:

```bash
scp /Users/praktikant/Documents/Migration/pi-backup.tar.gz \
    /Users/praktikant/Documents/Migration/pi-crontab.txt \
    /Users/praktikant/Documents/Migration/config.json \
    migrate.sh \
    zruser@zr-pi.local:~/
```

`migrate.sh` erwartet die drei Backup-Dateien direkt in `/home/zruser`.

### Schritt 5: Migration auf dem Pi ausführen

Per SSH über Ethernet auf dem Pi:

```bash
chmod +x ~/migrate.sh
~/migrate.sh
```

Das Skript bricht beim ersten Fehler ab (`set -euo pipefail`). Die Schritte laufen in dieser Reihenfolge:

| Schritt | Was passiert |
|---|---|
| `preflight` | prüft Benutzer `zruser`, die Backup-Dateien und `sudo`-Zugriff (Passwortabfrage) |
| `packages` | installiert Git, Python, FFmpeg, SSHFS, Apache und PHP; aktiviert `user_allow_other` in `/etc/fuse.conf` |
| `clone` | klont das Repository nach `/home/zruser/timelapse`; bricht ab, wenn dort bereits ein fremder oder nicht leerer Ordner liegt |
| `venv` | legt `.venv` an und installiert `requirements.txt` |
| `restore_backup` | entpackt das Backup in einen temporären Ordner, prüft die sudoers-Datei mit `visudo` und auf beide Regeln, installiert alle Dateien mit festen Eigentümern und Rechten, übernimmt `config.json` und die Crontab |
| `known_hosts` | überspringt, wenn der Storage-Box-Host bereits bekannt ist; sonst werden die Fingerprints angezeigt und müssen mit `y` bestätigt werden |
| `sshfs_mount` | installiert Preflight-Skript und systemd-Service und mountet `/mnt/cameras` |
| `apache` | aktiviert `zeitraffer.conf`, deaktiviert die Standardseite, führt `apache2ctl configtest` aus und lädt Apache neu |
| `web_bridge` | installiert Trigger, Lösch-Wrapper, Worker und Status-Skript unter `/usr/local` |
| `permissions` | setzt die Dateirechte aus „Dateirechte für `www-data`“ |
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
| `PROJECT_ROOT` | `/home/zruser/timelapse` | Zielordner |
| `BACKUP_TAR` | `~/pi-backup.tar.gz` | Geheimnis-Archiv |
| `BACKUP_CRONTAB` | `~/pi-crontab.txt` | Crontab-Sicherung |
| `BACKUP_CONFIG` | `~/config.json` | optionale `config.json`; fehlt sie, bleibt die Git-Version |
| `DISABLE_WIFI` | `1` | `0` lässt WLAN unverändert |

Am Ende des Laufs die Ausgabe von `verify` durchsehen: Jede Zeile mit `WARNING` muss geklärt werden, bevor der Pi als fertig gilt.

### Schritt 6: Videos zurückkopieren

Vom Mac aus:

```bash
rsync -a --progress /Users/praktikant/Documents/Migration/videos/ \
    zruser@zr-pi.local:/home/zruser/timelapse/videos/
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

2. Weboberfläche im Browser unter `http://zeitraffer.local/` oder `http://192.168.178.41/` öffnen, anmelden und prüfen:
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
   scp /Users/praktikant/Documents/Migration/{pi-backup.tar.gz,pi-crontab.txt,config.json} zruser@zr-pi.local:~/
   ```

2. Auf dem Pi einen Rollback-Stand und Prüfsummen aller betroffenen Dateien anlegen:

   ```bash
   umask 077
   sudo tar czf ~/pre-test-rollback.tar.gz /etc/sudoers.d/timelapse-web /etc/timelapse/mount.env \
     /etc/apache2/.htpasswd /etc/apache2/sites-available/zeitraffer.conf /home/zruser/.ssh \
     /usr/local/sbin/timelapse-web-* /usr/local/libexec/timelapse-web-* /usr/local/sbin/cameras-sshfs-preflight \
     /etc/systemd/system/cameras-sshfs.service /boot/firmware/config.txt /home/zruser/timelapse/config/config.json
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
| Web-Job startet nicht oder Löschen schlägt fehl | `sudo -l -U www-data` muss beide Wrapper zeigen; sonst sudoers wie unter „Wrapper installieren“ prüfen |
| `is already a git repo, but its origin ... doesn't match` | unter `/home/zruser/timelapse` liegt ein anderes Repository; verschieben oder `REPO_URL` korrigieren |

sudoers-Datei im Backup-Archiv reparieren (auf dem Pi):

```bash
mkdir ~/backup-fix
sudo tar xzf ~/pi-backup.tar.gz -C ~/backup-fix
sudo nano ~/backup-fix/etc/sudoers.d/timelapse-web   # beide Regeln aus „Wrapper installieren“
sudo visudo -cf ~/backup-fix/etc/sudoers.d/timelapse-web
sudo tar czf ~/pi-backup.tar.gz -C ~/backup-fix .
sudo chown zruser:zruser ~/pi-backup.tar.gz
sudo rm -rf ~/backup-fix
~/migrate.sh
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
