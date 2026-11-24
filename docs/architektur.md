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

Die Businesslogik der vier Videoarten, je eine Datei: `daily.py`, `weekly.py`, `monthly.py`,
`yearly.py`. Was jede Art auswählt, welche Fenster gelten und was aufbewahrt wird, steht in
[betrieb.md](betrieb.md#timelapse-typen). Für den Code wichtig:

- `weekly.py` setzt das automatische Weekly per FFmpeg-Concat ohne neues Encodieren aus den
  Daily-Videos zusammen; ein historisches Weekly baut es aus den Bildern einer Kamera.
- `yearly.py` gibt die Bildauswahl an `yearly_selection.py` ab (siehe unten).
- `diagnostics.py` liest bei einer Kamera ohne passende Bilder den vorhandenen Bildbereich für das
  Log, über den Worker-Supervisor.
- Blur-Kameras: Ein manueller Lauf verpixelt seine Bilder zuerst auf der Box
  (`privacy/blur_job.py`), ein automatischer nimmt nur bestätigte Bilder (`privacy/blur_gate.py`),
  bei Monthly und Yearly vor der Abdeckungsprüfung, bei Yearly auch vor der Auswahl. Das
  automatische Weekly erbt die Sperre von den Dailys.

### `src/images.py`

Allgemeine Bildlogik:

- Kameraerkennung
- `os.scandir()`-basierte Bildsuche für einzelne oder mehrere angeforderte Tage
- Datum und Uhrzeit aus dem Dateinamen (siehe unten)
- daylight-basierte Auswahl
- Interval-Suche
- 0-Byte-Filterung
- SHA-256-Hashing
- job-spezifische Duplicate-Filterung

**Datum und Uhrzeit aus dem Dateinamen** (`extract_date`, `extract_time`): Der Leser kennt keine
Kameranamen, nur Schreibweisen. Jede Datums-Schreibweise wird mit jedem Trenner und jeder
Uhrzeit-Schreibweise kombiniert; was davor oder dahinter steht (Präfix, Hundertstel, Zähler), ist egal.

| Datum | Trenner | Uhrzeit |
|---|---|---|
| `YYYYMMDD`, `YYMMDD` | keiner, `T`, `_`, `-` | `HHMMSS`, `HHMM` |
| `YYYY-MM-DD`, `YY-MM-DD` | | `HH-MM-SS` |
| `YYYY_MMDD` (Cafe am Meer, alt) | | `HHMMSScc` (P/T-Kameras, alt) |

Eine Kombination zählt nur als Ganzes (keine Ziffer direkt davor oder dahinter), Jahre 2000 bis 2099.
Ergeben zwei Kombinationen verschiedene gültige Lesarten, gilt der Name als unlesbar: Er wird nie
geraten. Eine wirklich neue Schreibweise (etwa `2026.11.17`) braucht einen neuen Baustein in der
Tabelle in `src/images.py`; bis dahin meldet der Nachtlauf die Kamera (siehe
[handbuch.md](handbuch.md#eine-kamera-hat-keine-bilder)).

### `src/storage/frame_source.py`

Die Bildquelle (`FrameSource`): Alle Jobs, die Kommandozeile, die Weboberfläche und die Werkzeuge
listen und holen Kamerabilder über dieselbe Schnittstelle. `LocalFrameSource` liest einen Ordner
(`TIMELAPSE_CAMERA_ROOT`, zum Beispiel das NAS-Archiv). `SshFrameSource` listet die Storage Box mit
einem `ls -l` über ssh und holt die nötigen Bilder per rsync in einen Zwischenspeicher unter
`temp/frame-cache/`; nach jeder Kamera werden sie wieder entfernt. Welche Quelle gilt, entscheidet
`TIMELAPSE_FRAME_SOURCE`, sonst der gesetzte Ordner, sonst die Storage Box
([Konfiguration](konfiguration.md#umgebungsvariablen)).

### `src/camera_list.py`

Schreibt die Kameraliste der Weboberfläche nach `state/web-jobs/cameras.json`, weil der
Webserver-Benutzer weder einen ssh-Schlüssel hat noch die Box selbst abfragt. Der Nachtlauf und
`python3 -m src.camera_list` aktualisieren sie.

### `src/night_warnings.py` und `src/web_state.py`

`night_warnings.py` sammelt als letzter Schritt der 02:00-Zeile, was jemand erledigen muss, und
schreibt es nach `state/web-jobs/warnings.json` für den
[Meldungsbalken](weboberflaeche.md#meldungsbalken). `web_state.py` (`write_web_json`) ersetzt die
Dateien unter `state/web-jobs/`, die die Seiten lesen, in einem Schritt, sodass eine Seite nie eine
halbe Datei liest.

### `src/config.py`, `src/settings.py` und `src/settings_save.py`

`load_config()` liest `config/config.json` und legt darüber die gültigen Werte der beiden
Einstellungsdateien der Weboberfläche, `config/settings.json` und `config/settings-privacy.json`
([konfiguration.md](konfiguration.md#einstellungen-der-weboberfläche)). Eine kaputte Einstellungsdatei
stoppt nichts, sie wird mit einer Warnung ignoriert; eine kaputte `config.json` stoppt den Lauf.

- `settings.py`: die einzige Liste dessen, was auf der Seite „Einstellungen“ änderbar ist, mit Regel
  und Grenzen je Schlüssel (Zahlen, Kameralisten, Uhrzeit, Dezimalzahlen, Rahmenlisten, ein Wert je
  Kamera über `<Präfix>.*`). Die Grenzen der Verpixelung kommen aus `privacy/anonymize.py`, damit
  nichts gespeichert werden kann, was den Nachtlauf abbrechen ließe. Sie prüft und mischt, schreibt aber nichts.
- `settings_save.py`: der Schreiber hinter dem Wrapper `timelapse-web-settings`. Er prüft zuerst,
  vergleicht dann die Änderungszeit der Datei (veraltete Seite), speichert nur Abweichungen von
  `config.json` atomar und hängt eine Zeile an `logs/settings.log` an.

Die Seiten lesen dieselbe zusammengeführte Config über `web/src/project-config.php`; ein Test
vergleicht ihre Schlüsselnamen mit der Python-Liste.

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

Eine Worker-Funktion ist eine normale Funktion mit `progress_callback`-Parameter, die ihr Ergebnis zurückgibt. `run_isolated_worker(camera, target, kwargs, ...)` startet sie im eigenen Prozess. Auch die Bildbereich-Diagnose (`src/jobs/diagnostics.py`) läuft darüber, mit 10 Sekunden Stall-Timeout.

### `src/date_coverage.py`

Gemeinsame Datumslogik für exakte rollierende Fenster:

- Weekly: 7 Kalendertage inklusive Enddatum
- Monthly: 30 Kalendertage inklusive Enddatum
- Yearly: ein Kalenderjahr inklusive Enddatum, 365 oder 366 Tage
- Ermittlung fehlender Kalendertage
- Lesen und Prüfen der Mindestabdeckung (`get_min_coverage_days`)
- kompakte Darstellung aufeinanderfolgender fehlender Tage für Logs

### `src/jobs/yearly_selection.py`

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

Verpixelung von Personen und Kennzeichen direkt auf der Storage Box
([verpixelung-box.md](verpixelung-box.md)); Detektor und `blur`-Werte:
[verpixelung.md](verpixelung.md):

- `anonymize.py`: die Bausteine: ruft den Detektor auf und prüft seine Antwort, verwirft bekannte
  Fehlerkennungen (`ignore_boxes`, oberer Rand, `skip_labels`, `min_person_score`), liest die
  `blur`-Werte und verpixelt ein Bild mit FFmpeg; jeder Zweifel bricht ab (`PrivacyCheckError`)
- `detect.py`: Erkennung von Personen und Fahrzeugen (YOLOX), läuft als eigener Prozess
- `blur_box.py`: Runde über neue Bilder auf der Storage Box; liest und schreibt nur per SSH
- `box_writer.py`: einzige Stelle, die auf die Box schreibt (Sicherung des Originals, Upload,
  geprüfter Tausch)
- `checked_mark.py`: die Markierung `blur:checked=true` (lesen, setzen); sie ändert kein Pixel
- `blur_watch.py`: der Wächter; meldet Bilder, die länger als 10 Minuten ungeprüft auf der Box
  liegen, nur lesend, ohne Sperre und ohne Detektor
- `blur_job.py`: Verpixelung der Bilder eines von Hand gestarteten Videos vor dem Videobau
  (`blur_job_frames`); nutzt `blur_box` und `box_writer` und passt deren Altersgrenze und Anzahl der
  Sicherungen an die Bilder des Videos an
- `preview.py`: das Vorschaubild der Seite „Verpixelung“: wählt ein Bild, das der Box-Job geprüft hat
  (verpixelt oder sauber, nie ein Nachtbild), holt es mit der Bildquelle, prüft die Prüfsumme und legt es unter `state/web-jobs/previews/` ab; läuft
  als `python3 -m src.privacy.preview` hinter dem Wrapper `timelapse-web-preview`
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

### `src/storage/storage_box.py`

Die Storage Box: ihr Name aus der Umgebung (`TIMELAPSE_STORAGE_BOX`), ein lesender Befehl über ssh
(`StorageBox.run`) und das Lesen einer `ls -l`-Ausgabe. Das Modul importiert nichts aus dem Projekt,
damit Bildquelle, Speicherfilter, Bilder und Verpixelung es ohne Importschleife nutzen können.

### `src/storage/storage_filter.py`

Speicherfilter ([werkzeuge.md](werkzeuge.md)): listet leere und doppelte Bilder per `ls` und
`sha256sum` direkt auf der Storage Box, ohne Bilder über das Netz zu lesen. Die Box-Anbindung
(`StorageBox`, siehe oben) nutzen auch die Bildquelle (`src/storage/frame_source.py`) und die Verpixelung.

### `web/`

PHP-Weboberfläche ohne Framework und Datenbank: `web/public/` ist der einzige DocumentRoot,
die Logik liegt in `web/src/`. Externe Prozesse nur über `proc_open` mit Argumentliste und die
festen Wrapper. Aufbau und Dateien: [weboberflaeche.md](weboberflaeche.md).

## Projektstruktur

```text
timelapse/
├── config/
│   ├── config.json
│   ├── settings.json, settings-privacy.json   (entstehen auf dem Host, nicht in git)
│   └── siteground.env.example   (Vorlage für die Zugangsdaten des Uploads)
├── docker/
│   ├── zeitraffer-web/   (Webteil des VPS zum Testen auf dem eigenen Rechner, siehe docs/docker-web.md)
│   ├── docker-compose.yml   (WordPress zum Entwickeln)
│   └── .env.example
├── docs/
│   ├── plans/   (offene und zurückgestellte Pläne; fertige Pläne und Entwürfe in plans/done/)
│   ├── youtube/   (Regeln und Texte für YouTube-Beschreibungen)
│   ├── architektur.md
│   ├── betrieb.md
│   ├── cli.md
│   ├── docker-web.md
│   ├── flagger.md
│   ├── handbuch.md
│   ├── highlights-seite.md
│   ├── installation.md
│   ├── konfiguration.md
│   ├── nas.md
│   ├── verpixelung-box.md
│   ├── verpixelung.md
│   ├── vps.md
│   ├── weboberflaeche.md
│   ├── werkzeuge.md
│   └── wordpress.md
├── extras/   (vorhanden, nicht eingeschaltet)
│   ├── README.md
│   └── mark_newest.py   (markiert bei Kameras ohne Verpixelung das neueste Bild)
├── frontend/
│   └── f5-webcams/   (WordPress-Plugin: Player, Shortcode, Kameraeinträge; eigenes Repository)
├── .github/
│   └── workflows/
│       └── test.yml
├── nas/
│   ├── helpers/   (Zähl- und Prüfwerkzeuge)
│   ├── nas-extract.py
│   ├── README.md
│   └── yearly-backfill.py   (Kalenderjahr-Videos ohne Mindestabdeckung)
├── scripts/
│   ├── web/   (Wrapper der Weboberfläche, installiert unter /usr/local/)
│   │   ├── timelapse-web-delete
│   │   ├── timelapse-web-delete-highlight
│   │   ├── timelapse-web-preview
│   │   ├── timelapse-web-publish
│   │   ├── timelapse-web-rebuild
│   │   ├── timelapse-web-settings
│   │   ├── timelapse-web-status.sh
│   │   ├── timelapse-web-trigger
│   │   ├── timelapse-web-worker
│   │   ├── timelapse-web-worker-publish
│   │   └── timelapse-web-worker-rebuild
│   ├── copy_zeitraffer_videos_vps2siteground.sh   (Upload der Videos auf die Website)
│   ├── list-deliverable-videos.py   (Liste der Videos, die hochgeladen werden dürfen)
│   ├── storage-filter-all
│   └── timelapse-nightly-staged   (Nachtlauf-Wrapper)
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
│   │   ├── diagnostics.py
│   │   ├── monthly.py
│   │   ├── weekly.py
│   │   ├── yearly.py
│   │   └── yearly_selection.py
│   ├── privacy/
│   │   ├── __init__.py
│   │   ├── anonymize.py
│   │   ├── blur_box.py
│   │   ├── blur_gate.py
│   │   ├── blur_job.py
│   │   ├── blur_watch.py
│   │   ├── box_writer.py
│   │   ├── checked_mark.py
│   │   ├── detect.py
│   │   └── preview.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── frame_source.py
│   │   ├── storage_box.py
│   │   └── storage_filter.py
│   ├── camera_list.py
│   ├── config.py
│   ├── date_coverage.py
│   ├── image_worker.py
│   ├── images.py
│   ├── interval_window.py
│   ├── logger.py
│   ├── main.py
│   ├── night_warnings.py
│   ├── run_state.py
│   ├── settings.py
│   ├── settings_save.py
│   ├── solar.py
│   ├── video.py
│   └── web_state.py
├── tests/   (pytest, eine *_test.py-Datei pro Modul)
│   ├── extras/   (Tests von extras/)
│   ├── flagger/   (Tests des Highlights-Flaggers und seine Fakes)
│   ├── jobs/   (Tests von Daily, Weekly, Monthly, Yearly)
│   ├── nas/   (Tests der NAS-Werkzeuge in nas/)
│   ├── privacy/   (Tests der Verpixelung)
│   ├── scripts/   (Tests von install.sh, backup.sh und scripts/)
│   ├── storage/   (Tests von src/storage/)
│   ├── web/   (Tests der Weboberfläche und ihrer Wrapper)
│   └── conftest.py, frame_source_fakes.py, privacy_fakes.py, *_test.py   (übrige Module)
├── web/
│   ├── public/
│   │   ├── camera.php
│   │   ├── highlights.php
│   │   ├── index.php
│   │   ├── job-status.php
│   │   ├── preview-refresh.php
│   │   ├── preview.php
│   │   ├── running-job.php
│   │   ├── settings-common.js   (Skript, das beide Einstellungs-Reiter teilen)
│   │   ├── settings.php
│   │   ├── storage-ring.js   (Textfeld über den Bögen der Speicherringe)
│   │   ├── style.css
│   │   ├── verpixelung.js   (Skript des Reiters „Verpixelung“, mit dem Zeichen-Editor)
│   │   └── verpixelung.php
│   └── src/
│       ├── components/
│       │   ├── confirm-delete.php
│       │   ├── header.php
│       │   ├── job-watcher.php
│       │   ├── settings-tabs.php
│       │   ├── storage-panel.php
│       │   └── warning-banner.php
│       ├── highlight-delete.php
│       ├── highlights-library.php
│       ├── job-runner.php
│       ├── job-state.php
│       ├── json-response.php
│       ├── preview-runner.php
│       ├── privacy-form.php
│       ├── process-runner.php
│       ├── project-config.php
│       ├── publish-runner.php
│       ├── rebuild-runner.php
│       ├── settings-form.php
│       ├── settings-runner.php
│       ├── video-delete.php
│       ├── video-library.php
│       └── warnings.php
├── logs/         (Laufzeitdaten, nicht im Repository)
├── models/       (Erkennungsmodelle, nicht im Repository)
├── reports/      (Laufzeitdaten, nicht im Repository)
├── state/        (Laufzeitdaten, nicht im Repository)
├── temp/         (Laufzeitdaten, nicht im Repository)
├── videos/       (Laufzeitdaten, nicht im Repository)
├── backup.env.example
├── backup.sh
├── .gitignore
├── install.sh
├── pyproject.toml
├── README.md
└── requirements.txt
```

Runtime-Daten unter `logs/`, `reports/`, `state/`, `temp/` und `videos/` werden nicht als Quelldaten
behandelt. `models/` enthält die Erkennungsmodelle für Verpixelung und Highlights-Flagger; sie
werden separat heruntergeladen bzw. aus der Sicherung zurückgespielt und sind nicht im Repository.

Was in welcher Datei unter `docs/` steht, listet das README unter
[Wo steht was?](../README.md#wo-steht-was).

`install.sh` richtet einen frischen Debian- oder Ubuntu-Host ein (host-neutral, ohne eingebundenen
Ordner); `backup.sh` sichert von einem Host, was ein neuer Host braucht und nicht im Git liegt (Modell,
Status, die Einstellungsdateien der Weboberfläche, auf Wunsch Videos, keine Geheimnisse), und `install.sh` spielt es im Schritt `restore` zurück. Ablauf:
[vps.md](vps.md).
`scripts/timelapse-nightly-staged` ist der Nachtlauf-Wrapper ([werkzeuge.md](werkzeuge.md#nachtlauf-wrapper)).
Der Upload der fertigen Videos auf die Website steht in [betrieb.md](betrieb.md#upload-auf-die-website).
Stillgelegtes (Raspberry Pi, Container-Test, Staging) ist nicht mehr im Repository; es steht in der
Git-Historie bis Commit `55c7219`.

## Sicherheit und Datenintegrität

Grundregeln des Projekts:

- Originalbilder auf der Storage Box niemals verändern (Ausnahme: Die Verpixelung auf der Box sichert
  vorher das Original).
- Frames nur lokal unter `temp/` vorbereiten.
- Unbekannte oder mehrdeutige Dateinamen niemals erraten.
- Verpixelung schlägt im Zweifel fehl: lieber kein Video als ein ungeprüftes Bild. Automatische
  Videos von Blur-Kameras entstehen nur aus Bildern, die der Box-Job bestätigt hat.
- Bestehende Videos erst nach erfolgreicher Neuerstellung ersetzen.
- Daily-Retention erst nach erfolgreicher Videoerstellung anwenden.
- Fehler einer Kamera dürfen spätere Kameras nicht unnötig blockieren.
- Blockierende Dateisystemzugriffe möglichst in isolierten Workern ausführen.
- Automatische Jobs verwenden standardmäßig ausschließlich abgeschlossene Kalendertage.
- Historische automatische Läufe verwenden das explizit gewählte `--target-date` als Datumsanker.

## Tests

```bash
python3 -m pytest                          # alle Tests
python3 -m pytest tests/main_test.py -v    # eine Datei, ausführlich
```

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

Ein lokaler Hook `.git/hooks/pre-push` (nicht versioniert) kann dieselben drei Prüfungen ausführen und den Push bei einem Fehler
blockieren. Er prüft den Arbeitsstand, also auch nicht committete Änderungen.
Notfalls umgehen mit:

```bash
git push --no-verify
```

## Linting und Formatierung

Ruff, gepinnt in `requirements.txt`, damit lokal und in GitHub Actions dieselbe Version prüft. Die
Einstellungen stehen in `pyproject.toml`: Einrückung mit Tabs (`indent-style = "tab"`), deshalb ist
`W191` bewusst aus.

```bash
ruff format .            # formatieren
ruff check .             # Linting
ruff format --check .    # nur prüfen, nichts ändern (so prüft CI)
```

Vor jedem Push: `ruff format .`, `ruff check .`, `python3 -m pytest`.
