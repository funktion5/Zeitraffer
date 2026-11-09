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
- `--cameras` mit `--jobs` (ohne `--target-date`): automatische Jobs nur für die gewählten Kameras;
  das ist kein Produktionslauf und legt den Statusmarker nicht an
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
- Blur-Kameras: ein manueller Lauf verpixelt seine Bilder zuerst auf der Box
  (`privacy/blur_job.py`), ein automatischer baut nur aus bestätigten Bildern (`privacy/blur_gate.py`)

`weekly.py`
- erstellt automatische Weeklys aus vorhandenen Daily-Videos
- erstellt historische Weeklys direkt aus Originalbildern für genau eine Kamera
- verarbeitet ein exaktes rollierendes 7-Tage-Fenster
- füllt fehlende automatische Dailys nicht mit älteren Videos auf
- verlangt für historische Weeklys vollständige Bildabdeckung
- verwendet für automatische Weeklys FFmpeg-Concat ohne Re-Encoding
- hat keine eigene Sperre für Blur-Kameras: ein automatisches Weekly erbt sie von den Dailys, ein
  manuelles verpixelt seine Bilder zuerst auf der Box

`monthly.py`
- verarbeitet ein rollierendes 30-Tage-Fenster
- Fenster endet standardmäßig gestern oder am expliziten `target_date`
- verwendet Originalbilder
- berücksichtigt alle ausgewählten Bilder im täglichen Zielzeitfenster aus `interval_window`
  (Standard 12:00 Uhr ±90 Minuten; historisch per CLI überschreibbar, auch `sunset`)
- Blur-Kameras: manuell zuerst verpixeln (vor der Abdeckungsprüfung), automatisch nur bestätigte
  Bilder (`privacy/blur_gate.py`, ebenfalls vor der Abdeckungsprüfung)

`yearly.py`
- verarbeitet ein Kalenderjahr bis zum Enddatum (365 oder 366 Tage, je nachdem ob ein
  29. Februar im Zeitraum liegt)
- Fenster endet standardmäßig gestern oder am expliziten `target_date`
- verwendet Originalbilder
- delegiert die Yearly-spezifische Frame-Auswahl an `yearly_selection.py` (bis zu fünf eindeutige,
  vollständige Bilder pro Tag, am nächsten an der Zielzeit)
- Blur-Kameras: automatisch nur bestätigte Bilder (`privacy/blur_gate.py`), vor Abdeckungsprüfung und
  Auswahl; manuell werden die Bilder verpixelt, die die Auswahl liefert

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

### `src/frame_source.py`

Die Bildquelle (`FrameSource`): Alle Jobs, die Kommandozeile, die Weboberfläche und die Werkzeuge
listen und holen Kamerabilder über dieselbe Schnittstelle. `LocalFrameSource` liest einen Ordner
(`TIMELAPSE_CAMERA_ROOT`, zum Beispiel das NAS-Archiv). `SshFrameSource` listet die Storage Box mit
einem `ls -l` über ssh und holt die nötigen Bilder per rsync in einen Zwischenspeicher unter
`temp/frame-cache/`; nach jeder Kamera werden sie wieder entfernt. Welche Quelle gilt, entscheidet
`TIMELAPSE_FRAME_SOURCE`, sonst der gesetzte Ordner, sonst die Storage Box
([README: Umgebungsvariablen](../README.md#umgebungsvariablen)).

### `src/camera_list.py`

Schreibt die Kameraliste der Weboberfläche nach `state/web-jobs/cameras.json`, weil der
Webserver-Benutzer weder einen ssh-Schlüssel hat noch die Box selbst abfragt. Der Nachtlauf und
`python3 -m src.camera_list` aktualisieren sie.

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
- Yearly: ein Kalenderjahr inklusive Enddatum, 365 oder 366 Tage
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
- `blur_box.py`: Runde über neue Bilder auf der Storage Box; liest und schreibt nur per SSH (einen
  Mount gibt es nicht mehr)
- `box_writer.py`: einzige Stelle, die auf die Box schreibt (Sicherung des Originals, Upload,
  geprüfter Tausch)
- `blur_job.py`: Verpixelung der Bilder eines von Hand gestarteten Videos vor dem Videobau
  (`blur_job_frames`); nutzt `blur_box` und `box_writer` und passt deren Altersgrenze und Anzahl der
  Sicherungen an die Bilder des Videos an
- `blur_gate.py`: die Sperre der automatischen Videos von Blur-Kameras (Daily, Monthly, Yearly): nur
  Bilder, die der Box-Job bestätigt hat (`blurred`, `clean`, `night`), liest den Status auf der
  Seite des Monats jedes Bildes und schreibt nichts
  ([verpixelung-box.md](verpixelung-box.md#sperre-in-automatischen-videos))

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
`sha256sum` direkt auf der Storage Box, ohne Bilder über das Netz zu lesen. Seine Box-Anbindung
(`StorageBox`) nutzen auch die Bildquelle (`src/frame_source.py`) und die Verpixelung.

### `web/`

PHP-Weboberfläche ohne Framework und Datenbank: `web/public/` ist der einzige DocumentRoot,
die Logik liegt in `web/src/`. Externe Prozesse nur über `proc_open` mit Argumentliste und die
festen Wrapper. Aufbau und Dateien: [weboberflaeche.md](weboberflaeche.md).

## Projektstruktur

```text
timelapse/
├── archive/   (stillgelegt: Raspberry Pi, Container-Test, Staging; siehe archive/README.md)
├── config/
│   └── config.json
├── docker/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── pull-videos.sh
├── docs/
│   ├── plans/   (Umsetzungspläne)
│   ├── superpowers/   (Entwürfe (Specs) neuer Funktionen)
│   ├── architektur.md
│   ├── betrieb.md
│   ├── cli.md
│   ├── flagger.md
│   ├── handbuch.md
│   ├── highlights-seite.md
│   ├── nas.md
│   ├── verpixelung-box.md
│   ├── verpixelung.md
│   ├── vps.md
│   ├── weboberflaeche.md
│   ├── werkzeuge.md
│   ├── wordpress.md
│   └── youtube/   (Regeln und Texte für YouTube-Beschreibungen)
├── frontend/
│   └── f5-webcams/   (WordPress-Plugin: Player, Shortcode, Kameraeinträge; eigenes Repository)
├── .github/
│   └── workflows/
│       └── test.yml
├── nas/
│   ├── helpers/   (Zähl- und Prüfwerkzeuge)
│   ├── nas-extract.py
│   └── README.md
├── scripts/
│   ├── web/   (Wrapper der Weboberfläche, installiert unter /usr/local/)
│   │   ├── timelapse-web-delete
│   │   ├── timelapse-web-delete-highlight
│   │   ├── timelapse-web-status.sh
│   │   ├── timelapse-web-trigger
│   │   └── timelapse-web-worker
│   ├── copy_zeitraffer_videos_vps2siteground.sh   (Upload der Videos auf die Website)
│   ├── list-deliverable-videos.py   (Liste der Videos, die hochgeladen werden dürfen)
│   ├── storage-filter-all
│   ├── timelapse-nightly-staged
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
│   │   ├── blur_gate.py
│   │   ├── blur_job.py
│   │   ├── box_writer.py
│   │   └── detect.py
│   ├── camera_list.py
│   ├── config.py
│   ├── date_coverage.py
│   ├── diagnostics.py
│   ├── frame_source.py
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
├── tests/   (pytest, eine *_test.py-Datei pro Modul)
│   ├── flagger/   (Tests des Highlights-Flaggers und seine Fakes)
│   ├── jobs/   (Tests von Daily, Weekly, Monthly, Yearly)
│   ├── privacy/   (Tests der Verpixelung)
│   ├── web/   (Tests der Weboberfläche und ihrer Wrapper)
│   └── conftest.py, frame_source_fakes.py, privacy_fakes.py, *_test.py   (übrige Module)
├── web/
│   ├── public/
│   │   ├── camera.php
│   │   ├── highlights.php
│   │   ├── index.php
│   │   ├── job-status.php
│   │   ├── running-job.php
│   │   └── style.css
│   └── src/
│       ├── components/
│       │   ├── confirm-delete.php
│       │   ├── header.php
│       │   └── job-watcher.php
│       ├── highlight-delete.php
│       ├── highlights-library.php
│       ├── job-runner.php
│       ├── job-state.php
│       ├── json-response.php
│       ├── process-runner.php
│       ├── video-delete.php
│       └── video-library.php
├── logs/         (Laufzeitdaten, nicht im Repository)
├── models/       (Erkennungsmodelle, nicht im Repository)
├── reports/      (Laufzeitdaten, nicht im Repository)
├── state/        (Laufzeitdaten, nicht im Repository)
├── temp/         (Laufzeitdaten, nicht im Repository)
├── videos/       (Laufzeitdaten, nicht im Repository)
├── .gitignore
├── install.sh
├── pyproject.toml
├── README.md
└── requirements.txt
```

Runtime-Daten unter `logs/`, `reports/`, `state/`, `temp/` und `videos/` werden nicht als Quelldaten
behandelt. `models/` enthält die Erkennungsmodelle für Verpixelung und Highlights-Flagger; sie
werden separat heruntergeladen bzw. vom bisherigen Host kopiert und sind nicht im Repository.

Was in welcher Datei unter `docs/` steht, listet das README unter
[Dokumentation](../README.md#dokumentation).

`install.sh` richtet einen frischen Debian- oder Ubuntu-Host ein (host-neutral, ohne eingebundenen
Ordner); Ablauf: [vps.md](vps.md).
`scripts/timelapse-nightly-staged` ist der Nachtlauf-Wrapper ([werkzeuge.md](werkzeuge.md#nachtlauf-wrapper)).
Der Upload der fertigen Videos auf die Website steht in [betrieb.md](betrieb.md#upload-auf-die-website).
Stillgelegtes (Raspberry Pi, Container-Test, Staging) liegt in [`archive/`](../archive/README.md).

## Sicherheit und Datenintegrität

Grundregeln des Projekts:

- Originalbilder auf der Storage Box niemals verändern (Ausnahme: Die Verpixelung auf der Box sichert
  vorher das Original).
- Frames nur lokal unter `temp/` vorbereiten.
- Unbekannte Dateinamensformate niemals erraten.
- Verpixelung schlägt im Zweifel fehl: lieber kein Video als ein ungeprüftes Bild. Automatische
  Videos von Blur-Kameras entstehen nur aus Bildern, die der Box-Job bestätigt hat.
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

Drei Tests in `tests/images_test.py` lesen echte Bilder aus einem eingebundenen Kamera-Ordner. Sie
laufen nur, wenn `TIMELAPSE_CAMERA_ROOT` auf einen echten Mountpunkt zeigt; sonst (z. B. in GitHub
Actions oder auf dem Server) werden sie mit Begründung übersprungen statt fehlzuschlagen, ein
„skipped“ ist dort normal.

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

Ein lokaler Hook `.git/hooks/pre-push` (nicht versioniert; im Klon auf dem Mac steht Stand
30.10.2026 keiner) kann dieselben drei Prüfungen ausführen und den Push bei einem Fehler
blockieren. Er prüft den Arbeitsstand, also auch nicht committete Änderungen.
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
