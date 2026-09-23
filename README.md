# Zeitraffer

Automatisierte Erstellung von Timelapse-Videos aus den Bildbeständen mehrerer Kameras auf einem Raspberry Pi.

Das System liest Originalbilder aus den unter `/mnt/cameras` eingebundenen Kameraordnern, wählt je nach Timelapse-Typ passende Frames aus und erzeugt daraus MP4-Videos mit FFmpeg.

**Die Originalbilder unter `/mnt/cameras` werden niemals verändert.**

---

## Aktueller Stand

Implementiert sind:

- Daily-Timelapses
- Manual-Timelapses
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
- Duplicate-Filterung für Daily, historische Weeklys und Monthly
- Duplicate-aware Yearly-Auswahl
- sichere temporäre Videoerstellung
- Log-Retention
- FFmpeg- und System-Performance-Logging
- protokollierte FFmpeg-Fehlerausgabe
- Run-IDs und Ergebniszusammenfassungen pro Job
- Config-Tests für Pfad, JSON-Syntax und Struktur
- Ruff für Linting und Formatierung

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

Manual-Läufe sind davon unabhängig und werden ausschließlich über `--date` gestartet.

---

## Projektstruktur

```text
timelapse/
├── config/
│   ├── config.json
│   └── mount.env.example
├── src/
│   ├── jobs/
│   │   ├── daily.py
│   │   ├── manual.py
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
├── tests/
│   ├── config_test.py
│   ├── daily_test.py
│   ├── date_coverage_test.py
│   ├── diagnostics_test.py
│   ├── images_test.py
│   ├── logger_test.py
│   ├── main_test.py
│   ├── manual_test.py
│   ├── monthly_test.py
│   ├── run_state_test.py
│   ├── video_test.py
│   ├── weekly_test.py
│   ├── yearly_selection_test.py
│   ├── yearly_test.py
│   └── conftest.py
├── logs/
├── temp/
├── videos/
├── pyproject.toml
├── requirements.txt
└── README.md
```

Runtime-Daten unter `logs/`, `temp/` und `videos/` werden nicht als Quelldaten behandelt.

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
- Manual- oder Automatic-Workflow starten
- ausgewählte automatische Jobs koordinieren
- feste Workflow-Reihenfolge beibehalten
- optionales `target_date` an automatische Jobs weiterreichen
- Framerates aus der Config an die Jobs weiterreichen

### `src/jobs/`

Enthält ausschließlich die Businesslogik der einzelnen Timelapse-Typen.

`daily.py`
- verarbeitet standardmäßig gestern
- kann optional ein explizites `target_date` verarbeiten
- nutzt Sunrise/Sunset inklusive konfigurierbarem Buffer
- erstellt Daily-Videos
- hält ein exaktes rollierendes 7-Tage-Fenster relativ zum verarbeiteten Zieldatum

`manual.py`
- verarbeitet ein explizites Datum
- kann auf bestimmte Kameras eingeschränkt werden
- behält historische Videos
- überspringt bereits vorhandene exakte Manual-Ausgaben

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
- `os.scandir()`-basierte Bildsuche
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
  "image_scan_stall_timeout_seconds": 10,
  "log_retention_days": 30,
  "ignored_cameras": [
    "Reolink"
  ],
  "timelapse": {
    "daily_framerate": 10,
    "manual_framerate": 10,
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

- Daily filtert spätere byte-identische Frames und behält das erste chronologische Bild.
- Manual erkennt und protokolliert byte-identische Quelldaten, entfernt sie aber nicht aus der Auswahl.
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
- Auswahl: Sunrise bis Sunset inklusive Buffer
- byte-identische Bilder werden vor der Erstellung gefiltert
- Framerate: `daily_framerate`
- Retention: exaktes rollierendes 7-Tage-Fenster relativ zum Zieldatum

### Manual

- Zieldatum: explizit über `--date`
- Quelle: Originalbilder
- zeitliche Auswahl: wie Daily
- byte-identische Bilder werden erkannt und protokolliert, aber nicht gefiltert
- Framerate: `manual_framerate`
- keine automatische Retention

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

Historisches Yearly für alle verfügbaren Kameras:

```bash
python3 -m src.main \
	--jobs yearly \
	--target-date 2026-09-15
```

Das Yearly deckt `2025-09-16` bis `2026-09-15` ab.

Mehrere historische Jobs können gemeinsam ausgeführt werden, solange kein historisches Weekly enthalten ist:

```bash
python3 -m src.main \
	--jobs daily monthly \
	--target-date 2026-09-15
```

Bedeutung:

```text
Daily
→ 2026-09-15

Monthly
→ 2026-08-17 bis 2026-09-15
```

`--target-date` ist nur gemeinsam mit `--jobs` gültig.

### Manual Daily

Manual Daily bleibt bewusst von den Job-Läufen getrennt und verarbeitet ein explizites Datum für alle verfügbaren Kameras:

```bash
python3 -m src.main --date 2026-08-15
```

Optional können bestimmte Kameras gewählt werden:

```bash
python3 -m src.main \
	--date 2026-08-15 \
	--cameras Scheunenviertel Nordufer_wide
```

`--cameras` ist gemeinsam mit `--date` gültig. Ein historisches Weekly benötigt ebenfalls
`--cameras`, wobei genau eine Kamera angegeben werden muss.

Nicht gültig sind unter anderem:

```text
--date + --jobs
--date + --target-date
--target-date ohne --jobs
historisches Weekly ohne genau eine Kamera
historisches Weekly gemeinsam mit einem weiteren Job
--cameras ohne --date oder historisches Weekly
```

---

## Logging

Logs werden nach Job-Typ getrennt:

```text
logs/
├── daily/YYYY-MM-DD.log
├── manual/YYYY-MM-DD.log
├── weekly/YYYY-MM-DD.log
├── monthly/YYYY-MM-DD.log
└── yearly/YYYY-MM-DD.log
```

Bei einer gezielten Job-Auswahl wird vor dem ersten ausgeführten Job direkt dessen Log aktiviert. Bei mehreren Jobs wird vor jedem weiteren Job auf das passende Log gewechselt.

Jeder Prozess erhält eine Run-ID. Startmeldungen enthalten Run-ID, Ausführungsmodus und Kameraauswahl. Die Abschlussmeldung jedes Jobs enthält die Anzahl erstellter, übersprungener und fehlgeschlagener Kameras.

Fehlende Monthly- und Yearly-Tage werden als kompakte Datumsbereiche protokolliert. Duplicate-Filter melden die Anzahl ausgeschlossener Frames. Bei einem FFmpeg-Fehler werden die letzten 40 Zeilen der FFmpeg-Fehlerausgabe in das Anwendungslog übernommen.

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
- Manual-Isolation
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
