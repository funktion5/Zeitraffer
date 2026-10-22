# Architektur, Projektstruktur und Entwicklung

Für Entwickler: Aufbau des Codes, Ordnerstruktur, Sicherheitsprinzipien, Tests und Linting.


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
- berücksichtigt alle ausgewählten Bilder im täglichen Zielzeitfenster aus `interval_window`
  (Standard 12:00 Uhr ±90 Minuten; historisch per CLI überschreibbar, auch `sunset`)

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
- job-spezifische Duplicate-Filterung

Unbekannte Dateinamensformate werden nicht geraten.

### `src/image_worker.py`

Gemeinsame Infrastruktur für isolierte Worker-Prozesse.

Der Supervisor übernimmt:

- `Process` und `Queue`
- Fortschrittsmeldungen, zentral auf höchstens eine pro Sekunde gedrosselt
- Stall-Timeout
- `terminate()`
- bei Bedarf `kill()`
- Erkennung unerwartet beendeter Worker
- Weitergabe erwarteter `OSError`

Der Timeout misst **Inaktivität**, nicht die Gesamtlaufzeit. Lange Scans dürfen weiterlaufen, solange Fortschritt gemeldet wird.

Eine Worker-Funktion ist eine normale Funktion mit `progress_callback`-Parameter, die ihr Ergebnis zurückgibt. `run_isolated_worker(camera, target, kwargs, ...)` startet sie im eigenen Prozess. Auch die Bildbereich-Diagnose (`src/diagnostics.py`) läuft darüber, mit 10 Sekunden Stall-Timeout.

### `src/date_coverage.py`

Gemeinsame Datumslogik für exakte rollierende Fenster:

- Weekly: 7 Kalendertage inklusive Enddatum
- Monthly: 30 Kalendertage inklusive Enddatum
- Yearly: 365 Kalendertage inklusive Enddatum
- Ermittlung fehlender Kalendertage
- Lesen und Prüfen der Mindestabdeckung (`get_min_coverage_days`)
- kompakte Darstellung aufeinanderfolgender fehlender Tage für Logs

### `src/yearly_selection.py`

Yearly-spezifische Frame-Auswahl.

Pro Kalendertag:

1. Kandidaten nach Abstand zur Fenstermitte priorisieren (Standard 12:00 Uhr, bei `sunset`
   der Sonnenuntergang des Tages).
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

### `src/privacy/`

Verpixelung von Personen und Kennzeichen, in Videos (derzeit nur historische Dailys, siehe
[verpixelung.md](verpixelung.md)) und direkt auf der Storage Box ([verpixelung-box.md](verpixelung-box.md)):

- `anonymize.py`: ruft die Erkennung paketweise auf, prüft jedes Ergebnis, verwaltet den Cache,
  verwirft bekannte Fehlerkennungen und verpixelt die Kopien unter `temp/` mit FFmpeg; jeder
  Zweifel bricht den Lauf ab
- `detect.py`: Erkennung von Personen und Fahrzeugen (YOLOX), läuft als eigener Prozess
- `blur_box.py`: Runde über neue Bilder auf der Storage Box; liest und schreibt nur per SSH, nie
  über den Mount
- `box_writer.py`: einzige Stelle, die auf die Box schreibt (Sicherung des Originals, Upload,
  geprüfter Tausch)

### `src/flagger/`

Highlights-Flagger ([flagger.md](flagger.md)), unabhängig von der Verpixelung und ohne Import aus
`src/privacy` oder `src/video`:

- `run.py`: Aufruf, Bildauswahl wie beim Daily, Scan aller Bilder eines Tages, Bericht
- `yolox.py`: eigene YOLOX-Anbindung (ganzes Bild plus Ausschnitte)
- `groups.py`: Klassen, Schwellen und der Filter für feststehende Objekte (`pick_flags`)
- `report.py`: schreibt Kopien und `manifest.json` atomar, räumt alte Berichte auf
- `settings.py`: liest und prüft den `flagger`-Abschnitt der Config

### `src/logger.py`

- gemeinsamer Anwendungslogger
- INFO-Ausgabe auf der Konsole
- DEBUG-Ausgabe in tagesbasierten Job-Logs
- Wechsel des File-Handlers zwischen Job-Typen
- Run-ID pro Prozess
- konfigurierbare Log-Retention

### `src/run_state.py`

Verwaltet den persistenten Marker `state/run-in-progress` für den vollständigen automatischen Produktionslauf. Details stehen im Abschnitt [Run-State und Wiederanlauf](betrieb.md#run-state-und-wiederanlauf).

### `src/interval_window.py`

Tägliches Bildfenster für Monthly und Yearly: Mitte als Uhrzeit oder Sonnenuntergang (über
`astral`), plus/minus Toleranz, ohne Mitternachtsüberschreitung.

### `src/storage_filter.py`

Speicherfilter ([werkzeuge.md](werkzeuge.md)): listet leere und doppelte Bilder per `ls` und
`sha256sum` direkt auf der Storage Box, ohne Bilder über SSHFS zu lesen. Seine Box-Anbindung
(`StorageBox`) nutzen auch `scripts/stage-frames.py` und die Verpixelung.

### `web/`

PHP-Weboberfläche ohne Framework und Datenbank: `web/public/` ist der einzige DocumentRoot,
die Logik liegt in `web/src/`. Externe Prozesse nur über `proc_open` mit Argumentliste und die
festen Wrapper. Aufbau und Dateien: [weboberflaeche.md](weboberflaeche.md).

## Projektstruktur

```text
timelapse/
├── config/
│   ├── config.json
│   └── mount.env.example
├── docker/
│   ├── docker-compose.yml
│   ├── entrypoint.sh
│   ├── .env.example
│   ├── pull-videos.sh
│   └── storage-box.env.example
├── docs/
│   ├── plans/   (Umsetzungspläne)
│   ├── superpowers/   (Entwürfe (Specs) neuer Funktionen)
│   ├── architektur.md
│   ├── betrieb.md
│   ├── cli.md
│   ├── docker.md
│   ├── flagger.md
│   ├── handbuch.md
│   ├── highlights-seite.md
│   ├── nas.md
│   ├── raspberry-pi.md
│   ├── verpixelung-box.md
│   ├── verpixelung.md
│   ├── weboberflaeche.md
│   ├── werkzeuge.md
│   ├── wordpress.md
│   ├── youtube-description-prompt.md
│   └── youtube-texts.md
├── frontend/
│   └── zeitraffer/
│       ├── assets/   (CSS und JavaScript des Plugins)
│       └── plugin-timelapse.php
├── .github/
│   └── workflows/
│       └── test.yml
├── nas/
│   ├── helpers/   (Zähl- und Prüfwerkzeuge)
│   ├── nas-extract.py
│   └── README.md
├── scripts/
│   ├── cameras-sshfs-preflight
│   ├── pi-crash-logging-setup
│   ├── stage-frames.py
│   ├── storage-filter-all
│   ├── timelapse-nightly-staged
│   ├── timelapse-web-delete
│   ├── timelapse-web-delete-highlight
│   ├── timelapse-web-status.sh
│   ├── timelapse-web-trigger
│   ├── timelapse-web-worker
│   └── yearly-backfill.py
├── src/
│   ├── flagger/
│   │   ├── __init__.py
│   │   ├── groups.py
│   │   ├── report.py
│   │   ├── run.py
│   │   ├── settings.py
│   │   └── yolox.py
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── daily.py
│   │   ├── monthly.py
│   │   ├── weekly.py
│   │   └── yearly.py
│   ├── privacy/
│   │   ├── __init__.py
│   │   ├── anonymize.py
│   │   ├── blur_box.py
│   │   ├── box_writer.py
│   │   └── detect.py
│   ├── config.py
│   ├── date_coverage.py
│   ├── diagnostics.py
│   ├── image_worker.py
│   ├── images.py
│   ├── interval_window.py
│   ├── logger.py
│   ├── main.py
│   ├── run_state.py
│   ├── solar.py
│   ├── storage_filter.py
│   ├── video.py
│   └── yearly_selection.py
├── systemd/
│   └── cameras-sshfs.service
├── tests/   (pytest, eine *_test.py-Datei pro Modul)
├── web/
│   ├── public/
│   │   ├── camera.php
│   │   ├── highlights.php
│   │   ├── index.php
│   │   ├── job-status.php
│   │   └── style.css
│   └── src/
│       ├── components/
│       │   ├── confirm-delete.php
│       │   ├── header.php
│       │   └── job-watcher.php
│       ├── highlight-delete.php
│       ├── highlights-library.php
│       ├── job-runner.php
│       ├── process-runner.php
│       ├── video-delete.php
│       └── video-library.php
├── logs/         (Laufzeitdaten, nicht im Repository)
├── models/       (Erkennungsmodelle, nicht im Repository)
├── reports/      (Laufzeitdaten, nicht im Repository)
├── state/        (Laufzeitdaten, nicht im Repository)
├── temp/         (Laufzeitdaten, nicht im Repository)
├── videos/       (Laufzeitdaten, nicht im Repository)
├── backup.env.example
├── backup.sh
├── compose.yaml
├── Dockerfile
├── .dockerignore
├── .gitignore
├── migrate.sh
├── pyproject.toml
├── README.md
└── requirements.txt
```

Runtime-Daten unter `logs/`, `reports/`, `state/`, `temp/` und `videos/` werden nicht als Quelldaten
behandelt. `models/` enthält die Erkennungsmodelle für Verpixelung und Highlights-Flagger; sie
werden separat heruntergeladen bzw. aus der Sicherung zurückgespielt und sind nicht im Repository.

Was in welcher Datei unter `docs/` steht, listet das README unter
[Dokumentation](../README.md#dokumentation).

`backup.sh` und `migrate.sh` sichern bzw. stellen einen Raspberry Pi bei einer Neuinstallation
wieder her; siehe [Neuinstallation des Raspberry Pi](raspberry-pi.md#neuinstallation-des-raspberry-pi).
`scripts/stage-frames.py` und `scripts/timelapse-nightly-staged` sind der Weg für einen Host ohne
SSHFS-Mount; siehe [werkzeuge.md](werkzeuge.md#staging-für-hosts-ohne-mount).

## Sicherheit und Datenintegrität

Grundregeln des Projekts:

- Originalbilder unter `/mnt/cameras` niemals verändern.
- Frames nur lokal unter `temp/` vorbereiten.
- Unbekannte Dateinamensformate niemals erraten.
- Verpixelung schlägt im Zweifel fehl: lieber kein Video als ein ungeprüftes Bild.
- Bestehende Videos erst nach erfolgreicher Neuerstellung ersetzen.
- Daily-Retention erst nach erfolgreicher Videoerstellung anwenden.
- Fehler einer Kamera dürfen spätere Kameras nicht unnötig blockieren.
- Blockierende Dateisystemzugriffe möglichst in isolierten Workern ausführen.
- Automatische Jobs verwenden standardmäßig ausschließlich abgeschlossene Kalendertage.
- Historische automatische Läufe verwenden das explizit gewählte `--target-date` als Datumsanker.

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

Drei Tests in `tests/images_test.py` lesen echte Bilder unter `/mnt/cameras`. Ist der Mount nicht
vorhanden (z. B. in GitHub Actions), werden sie mit Begründung übersprungen statt fehlzuschlagen.
Erscheint lokal auf dem Pi „3 skipped“, ist der SSHFS-Mount nicht erreichbar.

Die Web-Tests benötigen `php` auf der Kommandozeile, siehe [Webtests](weboberflaeche.md#webtests).

### GitHub Actions und Pre-Push-Hook

`.github/workflows/test.yml` läuft bei jedem Push und Pull Request auf `ubuntu-latest` mit
Python 3.13 und führt nacheinander aus:

```text
ruff check .
→ ruff format --check .
→ python -m pytest
```

Schlägt ein Schritt fehl, laufen die folgenden nicht mehr; ein roter Lauf heißt also nicht
zwingend, dass Tests fehlgeschlagen sind. Ein neuerer Push auf denselben Branch bricht einen noch
laufenden älteren Lauf ab.

Lokal führt `.git/hooks/pre-push` (nicht versioniert) dieselben drei Prüfungen aus und blockiert
den Push bei einem Fehler. Er prüft den Arbeitsstand, also auch nicht committete Änderungen.
Notfalls umgehen mit:

```bash
git push --no-verify
```

## Linting und Formatierung

Das Projekt verwendet Ruff, gepinnt in `requirements.txt`, damit lokal und in GitHub Actions
dieselbe Version prüft.

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
