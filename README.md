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
- konfigurierbare Framerates
- globale Kamera-Ausschlussliste
- daylight-basierte Bildauswahl
- mehrere historische Kamera-Dateinamensformate
- isolierte Worker mit Stall-Timeout
- 0-Byte-Validierung
- SHA-256-basierte Erkennung byte-identischer Quelldaten
- Duplicate-aware Yearly-Auswahl
- sichere temporäre Videoerstellung
- Log-Retention
- FFmpeg- und System-Performance-Logging
- Config-Tests für Pfad, JSON-Syntax und Struktur
- Ruff für Linting und Formatierung

Der automatische Workflow läuft in dieser Reihenfolge:

```text
Daily
→ Weekly
→ Monthly
→ Yearly
```

Manual-Läufe sind davon unabhängig und werden nur über `--date` gestartet.

---

## Projektstruktur

```text
timelapse/
├── config/
│   ├── cameras.json
│   └── mount.env.example
├── src/
│   ├── jobs/
│   │   ├── daily.py
│   │   ├── manual.py
│   │   ├── weekly.py
│   │   ├── monthly.py
│   │   └── yearly.py
│   ├── config.py
│   ├── diagnostics.py
│   ├── image_worker.py
│   ├── images.py
│   ├── logger.py
│   ├── main.py
│   ├── solar.py
│   ├── video.py
│   └── yearly_selection.py
├── tests/
│   ├── config_test.py
│   ├── daily_test.py
│   ├── diagnostics_test.py
│   ├── images_test.py
│   ├── logger_test.py
│   ├── main_test.py
│   ├── manual_test.py
│   ├── monthly_test.py
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
- Framerates aus der Config an die Jobs weiterreichen

### `src/jobs/`

Enthält ausschließlich die Businesslogik der einzelnen Timelapse-Typen.

`daily.py`
- verarbeitet gestern
- nutzt Sunrise/Sunset inklusive konfigurierbarem Buffer
- erstellt Daily-Videos
- hält ein exaktes rollierendes 7-Tage-Fenster

`manual.py`
- verarbeitet ein explizites Datum
- kann auf bestimmte Kameras eingeschränkt werden
- behält historische Videos
- überspringt bereits vorhandene exakte Manual-Ausgaben

`weekly.py`
- verwendet ausschließlich vorhandene Daily-Videos
- verarbeitet das exakte rollierende 7-Tage-Fenster
- füllt fehlende Tage nicht mit älteren Videos auf
- verwendet FFmpeg-Concat ohne Re-Encoding

`monthly.py`
- verarbeitet ein rollierendes 30-Tage-Fenster
- Ende ist immer gestern in der konfigurierten Zeitzone
- verwendet Originalbilder
- berücksichtigt alle validen Bilder im täglichen Zielzeitfenster um 12:00 Uhr
- Toleranz: ±90 Minuten

`yearly.py`
- verarbeitet ein rollierendes 365-Tage-Fenster
- Ende ist immer gestern in der konfigurierten Zeitzone
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
- Duplicate-Diagnose

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

---

## Konfiguration

Die produktive Konfiguration liegt fest unter:

```text
config/cameras.json
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
    "yearly_framerate": 20
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

0-Byte-Dateien werden vor der weiteren Verarbeitung entfernt und geloggt.

Bei Daily und Manual werden byte-identische Quelldaten erkannt und protokolliert, aber nicht automatisch entfernt.

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

- Zieldatum: gestern
- Quelle: Originalbilder
- Auswahl: Sunrise bis Sunset inklusive Buffer
- Framerate: `daily_framerate`
- Retention: exaktes rollierendes 7-Tage-Fenster

### Manual

- Zieldatum: explizit per CLI
- Quelle: Originalbilder
- Auswahl: wie Daily
- Framerate: `manual_framerate`
- keine automatische Retention

### Weekly

- Fenster: letzte 7 abgeschlossene Kalendertage
- Quelle: vorhandene Daily-Videos
- fehlende Dailys werden protokolliert
- kein älteres Backfill
- mindestens ein Daily genügt für die Erstellung

### Monthly

- Fenster: rollierende 30 Tage
- Quelle: Originalbilder
- täglich 10:30 bis 13:30 Uhr
- verwendet alle validen Intervallbilder
- Framerate: `monthly_framerate`

### Yearly

- Fenster: rollierende 365 Tage
- Quelle: Originalbilder
- tägliche Kandidaten aus 10:30 bis 13:30 Uhr
- Zielzeit: 12:00 Uhr
- bis zu 5 eindeutige Frames pro Tag
- bei Duplikaten werden weitere Kandidaten nachgezogen
- Framerate: `yearly_framerate`

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

## Programm starten

Automatischer Produktionslauf:

```bash
python3 -m src.main
```

Ablauf:

```text
Daily
→ Weekly
→ Monthly
→ Yearly
```

Manual für ein bestimmtes Datum:

```bash
python3 -m src.main --date 2026-08-15
```

Manual nur für bestimmte Kameras:

```bash
python3 -m src.main --date 2026-08-15 --cameras Scheunenviertel Nordufer_wide
```

`--cameras` ist nur gemeinsam mit `--date` gültig.

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
python3 -m pytest tests/yearly_selection_test.py -v
```

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
- Automatische Jobs verwenden ausschließlich abgeschlossene Kalendertage.

---

## Noch offen

Für den produktiven Dauerbetrieb fehlen insbesondere noch:

- zeitgesteuerte automatische Ausführung
- Upload der erzeugten Videos zum Webserver
- endgültige Retention-/Dateinamensstrategie für rollierende Monthly- und Yearly-Ausgaben

Die Architektur ist so aufgebaut, dass weitere periodische Jobs ergänzt werden können, ohne den zentralen Coordinator unnötig mit Businesslogik zu belasten.
