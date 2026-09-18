# Timelapse

Automatisierte Erstellung von Timelapse-Videos aus den Bildbeständen mehrerer Kameras auf einem Raspberry Pi.

Das System liest Originalbilder aus den unter `/mnt/cameras` eingebundenen Kameraordnern, wählt passende Bilder aus, bereitet sie lokal auf und erzeugt daraus MP4-Timelapses mit FFmpeg.

Die Originalbilder unter `/mnt/cameras` werden niemals verändert.

---

## Aktueller Produktionsstand

Der aktuelle automatische Ablauf besteht aus:

```text
main.py
   ↓
Daily für gestern
   ↓
Daily-Retention
   ↓
Weekly für das rollierende 7-Tage-Fenster
```

Zusätzlich können Manual-Timelapses für ein explizit angegebenes Datum erzeugt werden.

Aktuell implementiert:

- Daily-Timelapses
- Manual-Timelapses
- Weekly-Timelapses
- globale Kamera-Ausschlussliste über die Konfiguration
- daylight-basierte Bildauswahl
- Unterstützung mehrerer historischer Dateinamensformate
- sichere temporäre Videoerstellung vor dem Ersetzen bestehender Dateien
- getrennte Logs für Daily, Manual und Weekly
- FFmpeg- und System-Performance-Logging
- isolierte Image-Range-Diagnose mit Timeout für nicht erreichbare Kameraquellen
- 7-Tage-Retention für Daily-Videos

Geplant:

- Yearly-Timelapse über ein rollierendes 365-Tage-Fenster

Monthly ist derzeit nicht festgelegt.

---

## Projektstruktur

```text
timelapse/
├── config/
│   └── cameras.json
├── src/
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── daily.py
│   │   ├── manual.py
│   │   └── weekly.py
│   ├── config.py
│   ├── diagnostics.py
│   ├── images.py
│   ├── logger.py
│   ├── main.py
│   ├── solar.py
│   └── video.py
├── tests/
│   ├── camera_test.py
│   ├── daily_test.py
│   ├── diagnostics_test.py
│   ├── main_test.py
│   ├── manual_test.py
│   ├── video_test.py
│   ├── weekly_test.py
│   └── conftest.py
├── temp/
├── videos/
├── logs/
└── README.md
```

Runtime-Daten werden nicht in Git gespeichert.

Beispiel:

```gitignore
# Runtime data
temp/*
logs/*
videos/*
```

---

## Architektur

Die Verantwortlichkeiten sind bewusst getrennt.

### `src/main.py`

`main.py` ist der zentrale Koordinator.

Aufgaben:

- CLI-Argumente verarbeiten
- Konfiguration laden
- Kamera-Mount prüfen
- global ignorierte Kameras filtern
- File-Logging konfigurieren
- Manual oder automatischen Workflow starten

Der automatische Workflow läuft in dieser Reihenfolge:

```text
Daily
→ Weekly
```

Ein Manual-Lauf bleibt davon getrennt.

### `src/jobs/daily.py`

Enthält ausschließlich Daily-Businesslogik.

Aufgaben:

- Zieldatum = gestern in der konfigurierten Zeitzone
- Sonnenaufgang und Sonnenuntergang bestimmen
- passende Bilder auswählen
- Daily-Video erzeugen
- Fehler pro Kamera behandeln
- Daily-Retention anwenden

### `src/jobs/manual.py`

Enthält Manual-Businesslogik.

Aufgaben:

- explizites Datum verarbeiten
- optional bestimmte Kameras auswählen
- Reihenfolge beibehalten
- doppelte Kameranamen entfernen
- unbekannte Kameras loggen
- bereits vorhandene Manual-Videos überspringen
- historische Manual-Videos behalten

### `src/jobs/weekly.py`

Enthält Weekly-Businesslogik.

Aufgaben:

- exaktes rollierendes 7-Tage-Fenster bestimmen
- passende Daily-Videos suchen
- fehlende Dailys protokollieren
- vorhandene Dailys chronologisch zusammenfügen
- bei 0 vorhandenen Dailys die Kamera überspringen
- bestehendes Weekly erst nach erfolgreicher Neuerstellung ersetzen

### `src/diagnostics.py`

Enthält gemeinsame Diagnosefunktionen.

Die Image-Range-Diagnose läuft in einem isolierten Prozess.

Grund:

Dateisystemzugriffe wie `stat()` können bei einer nicht erreichbaren oder abgeschalteten Kameraquelle blockieren.

Die Diagnose besitzt deshalb einen Timeout und darf niemals den vollständigen Daily- oder Manual-Job dauerhaft blockieren.

### `src/images.py`

Verantwortlich für:

- Kameraerkennung
- Bildsuche
- Dateinamens-Parsing
- Datums- und Uhrzeitextraktion
- daylight-basierte Bildauswahl
- Image-Range-Diagnosedaten

### `src/video.py`

Technische Video- und FFmpeg-Schicht.

Enthält keine Daily-, Manual- oder Weekly-Businessregeln.

Verantwortlich für:

- lokale Temp-Verzeichnisse
- Kopieren und Normalisieren von Frames
- Bild-Timelapses
- Concat-Dateien
- Video-Concat
- sichere temporäre Ausgabedateien
- FFmpeg-Prozessüberwachung
- CPU- und RAM-Messungen

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

Wenn der globale Kamera-Mount nicht erreichbar ist und `get_cameras()` einen `OSError` auslöst, wird der komplette Lauf abgebrochen.

---

## Ignorierte Kameras

Bestimmte Kameras können zentral in der Konfiguration ausgeschlossen werden.

Beispiel:

```json
{
  "ignored_cameras": [
    "Reolink"
  ]
}
```

Diese Kameras werden global herausgefiltert, bevor Daily, Manual oder Weekly gestartet werden.

Die Entscheidung in der Konfiguration hat Vorrang. Eine explizite Manual-Auswahl hebt die Ignore-Liste nicht auf.

---

## Unterstützte Dateinamensformate

Die Kameraarchive enthalten mehrere historisch gewachsene Formate.

Neue bzw. bekannte Formate werden explizit unterstützt.

Beispiele:

```text
<Kameraname>_YY-MM-DD_HH-MM-SS-MS.jpg
20260915T145103.jpg
scheunenviertel-26-09-15_14-29-56-39.jpg
aw10_26-08-27_15-52-07-75.jpg
see-26-09-15_14-44-58-48.jpg
bsv_steinhude_2510091630.jpg
bsv_steinhude_202410020900.jpg
image_241030_010043.jpg
P23091411034310.jpg
T23091315270800.jpg
Nordufer_tele_20250419T094017.jpg
Nordufer_wide_20250419T100009.jpg
sam-Reolink_00_20251024145546.jpg
```

### Designentscheidung

Unbekannte Formate werden nicht geraten.

```text
bekanntes Format
→ Datum/Zeit extrahieren

unbekanntes Format
→ nicht raten
→ als nicht erkannt behandeln
```

Neue Formate sollen nur über ein explizites Parser-Pattern mit passenden Tests ergänzt werden.

---

## Daylight-Auswahl

Daily- und Manual-Timelapses orientieren sich an Sonnenaufgang und Sonnenuntergang.

Die geografischen Daten und die Zeitzone kommen aus der Konfiguration.

Beispiel:

```json
{
  "location": {
    "latitude": 52.45,
    "longitude": 9.38,
    "timezone": "Europe/Berlin"
  },
  "daylight_buffer_minutes": 90
}
```

Der verwendete Zeitraum ist:

```text
sunrise - daylight_buffer
bis
sunset + daylight_buffer
```

Der Buffer bleibt damit konfigurierbar, ohne die Bildauswahl in `images.py` zu verändern.

---

## Temporäre Frames

Ausgewählte Originalbilder werden lokal kopiert und fortlaufend umbenannt.

Beispiel:

```text
temp/
└── Scheunenviertel/
    └── 2026-09-17/
        ├── frame_000001.jpg
        ├── frame_000002.jpg
        ├── frame_000003.jpg
        └── ...
```

FFmpeg erhält dadurch unabhängig vom ursprünglichen Kameranamen eine konsistente Eingabe:

```text
frame_%06d.jpg
```

Originalbilder unter `/mnt/cameras` werden nicht verändert.

Nach erfolgreicher Verarbeitung wird das Temp-Verzeichnis entfernt.

Bei einem Fehler während der Videoerstellung bleiben relevante temporäre Daten zur Diagnose erhalten.

---

## Videoerstellung

Bildbasierte Timelapses werden mit FFmpeg und H.264 erzeugt.

Konzeptionell:

```bash
ffmpeg -y   -framerate 10   -i frame_%06d.jpg   -c:v libx264   -pix_fmt yuv420p   output.mp4
```

Aktuelle Framerate:

```text
10 fps
```

Damit gilt:

```text
10 Bilder   = 1 Sekunde
100 Bilder  = 10 Sekunden
1000 Bilder = 100 Sekunden
```

Die Länge eines Timelapses hängt damit von der Anzahl der vorhandenen Bilder ab.

---

## Sichere Videoersetzung

Bestehende Videos werden nicht direkt überschrieben.

FFmpeg schreibt zunächst in eine temporäre MP4-Datei im Zielverzeichnis.

Beispiel:

```text
.Scheunenviertel_2026-09-17.tmp.mp4
```

bzw. für Weekly:

```text
.Scheunenviertel_weekly.tmp.mp4
```

Nur wenn FFmpeg erfolgreich beendet wurde, ersetzt die temporäre Datei das endgültige Video.

Dadurch bleibt ein vorheriges funktionierendes Video erhalten, wenn die Neuerstellung fehlschlägt.

---

## Daily

Der automatische Daily verarbeitet immer den vorherigen Kalendertag in der konfigurierten Zeitzone.

Ausgabe:

```text
videos/<camera>/daily/<camera>_YYYY-MM-DD.mp4
```

Beispiel:

```text
videos/Scheunenviertel/daily/Scheunenviertel_2026-09-17.mp4
```

### Daily-Retention

Pro Kamera wird ein exaktes rollierendes 7-Tage-Fenster gehalten.

Wenn das Zieldatum beispielsweise `2026-09-17` ist, gehören ausschließlich diese Tage zum Fenster:

```text
2026-09-11
2026-09-12
2026-09-13
2026-09-14
2026-09-15
2026-09-16
2026-09-17
```

Fehlende Tage werden nicht mit älteren Videos aufgefüllt.

Die Retention wird erst angewendet, nachdem das neue Daily erfolgreich erstellt wurde.

---

## Manual

Manual-Timelapses verarbeiten ein explizit angegebenes Datum.

Ausgabe:

```text
videos/<camera>/manual/<camera>_YYYY-MM-DD.mp4
```

Beispiel:

```text
videos/Scheunenviertel/manual/Scheunenviertel_2026-08-15.mp4
```

Manual-Videos sind historische Ergebnisse und werden nicht automatisch gelöscht.

Existiert das exakte Manual-Video bereits, wird die Kamera bereits vor Bildsuche, Kopieren und FFmpeg übersprungen.

### Bestimmte Kameras auswählen

Mehrere Kameras können angegeben werden:

```bash
python3 -m src.main   --date 2026-08-15   --cameras Scheunenviertel SVG
```

`--cameras` ist nur zusammen mit `--date` gültig.

---

## Weekly

Weekly ist ein rollierendes 7-Tage-Timelapse.

Quelle sind ausschließlich die Daily-Videos der exakten letzten sieben Kalendertage.

Ausgabe:

```text
videos/<camera>/weekly/<camera>_weekly.mp4
```

Beispiel:

```text
videos/Scheunenviertel/weekly/Scheunenviertel_weekly.mp4
```

Regeln:

- Daily-Videos werden chronologisch verarbeitet.
- Daily-Videos außerhalb des 7-Tage-Fensters werden ignoriert.
- Fehlende Tage werden protokolliert.
- Fehlende Tage werden nicht durch ältere Dailys ersetzt.
- Wenn mindestens ein Daily vorhanden ist, wird daraus ein Weekly gebaut.
- Wenn kein Daily vorhanden ist, wird Weekly für diese Kamera übersprungen.
- Das bestehende Weekly bleibt erhalten, bis das neue Concat erfolgreich abgeschlossen wurde.

Weekly verwendet FFmpeg-Stream-Copy und re-encodiert die Daily-Videos nicht:

```bash
ffmpeg -y   -f concat   -safe 0   -i concat.txt   -c copy   output.mp4
```

---

## Diagnose bei fehlenden Bildern

Wenn für ein Datum keine passenden Bilder gefunden werden, kann zusätzlich der vorhandene Bildbestand untersucht werden.

`get_image_range()` liefert:

```text
earliest_date
latest_date
total_files
recognized_files
unrecognized_files
```

Damit kann beispielsweise unterschieden werden zwischen:

```text
keine erkannten Bilder vorhanden
Bilder nur außerhalb des gewünschten Datums
unbekannte Dateinamensformate
gemischte bekannte und unbekannte Formate
```

### Timeout und Isolation

Der Image-Range-Scan kann bei großen oder nicht erreichbaren Kameraquellen teuer oder blockierend sein.

Deshalb läuft die Diagnose in `src/diagnostics.py` in einem separaten Prozess.

Aktuelles Verhalten:

```text
Diagnose starten
→ maximal 10 Sekunden warten
→ bei Timeout Prozess beenden
→ Warnung loggen
→ nächste Kamera verarbeiten
```

Die Diagnose ist optional und darf den vollständigen Job nicht dauerhaft blockieren.

---

## Logging

Logs werden nach Job-Typ und Ausführungstag getrennt gespeichert.

```text
logs/
├── daily/YYYY-MM-DD.log
├── manual/YYYY-MM-DD.log
├── weekly/YYYY-MM-DD.log
└── yearly/YYYY-MM-DD.log
```

Die Datumsangabe im Log-Dateinamen beschreibt den Ausführungstag, nicht zwingend den verarbeiteten Tag.

Beispielhafte Log-Level:

```text
DEBUG    technische Detailinformationen
INFO     normaler Programmablauf
WARNING  ungewöhnliche, aber behandelbare Zustände
ERROR    fehlgeschlagene Verarbeitung
```

Global ignorierte Kameras werden ebenfalls geloggt.

---

## Performance-Monitoring

Während FFmpeg läuft, werden Peak-Werte protokolliert für:

```text
FFmpeg CPU
FFmpeg RAM
System CPU
System RAM
```

Beispiel:

```text
Peak hardware usage | FFmpeg CPU: 404.2% | FFmpeg RAM: 496.2 MB | System CPU: 100.0% | System RAM: 91.9%
```

Bei `psutil.Process.cpu_percent()` können auf einem Mehrkernsystem Werte über 100 % auftreten.

---

# Programm starten

Alle Befehle werden aus dem Projektverzeichnis ausgeführt.

```bash
cd ~/timelapse
source .venv/bin/activate
```

## Automatischer Produktionslauf

Der normale Produktionslauf startet zuerst Daily und anschließend Weekly:

```bash
python3 -m src.main
```

Ablauf:

```text
Daily für gestern
→ Weekly für das rollierende 7-Tage-Fenster bis gestern
```

---

## Manual-Timelapse starten

Alle verfügbaren, nicht ignorierten Kameras für ein bestimmtes Datum:

```bash
python3 -m src.main --date 2026-08-15
```

Nur bestimmte Kameras:

```bash
python3 -m src.main   --date 2026-08-15   --cameras Scheunenviertel SVG
```

Mehrfach angegebene Kameras werden dedupliziert, ihre Reihenfolge bleibt erhalten.

Unbekannte Kameranamen werden geloggt und übersprungen.

---

# Jobs einzeln ausführen

Für Entwicklung und Fehleranalyse können Daily und Weekly unabhängig vom kompletten `main.py`-Workflow gestartet werden.

## Nur Daily

```bash
python3 - <<'PY'
from src.config import load_config
from src.images import get_cameras
from src.jobs.daily import run_daily_job
from src.logger import configure_file_logging

config = load_config()

ignored_cameras = set(
    config.get(
        "ignored_cameras",
        [],
    )
)

cameras = [
    camera
    for camera in get_cameras()
    if camera not in ignored_cameras
]

configure_file_logging("daily")

run_daily_job(
    config=config,
    cameras=cameras,
)
PY
```

## Nur Weekly

```bash
python3 - <<'PY'
from src.config import load_config
from src.images import get_cameras
from src.jobs.weekly import run_weekly_job
from src.logger import configure_file_logging

config = load_config()

ignored_cameras = set(
    config.get(
        "ignored_cameras",
        [],
    )
)

cameras = [
    camera
    for camera in get_cameras()
    if camera not in ignored_cameras
]

configure_file_logging("weekly")

run_weekly_job(
    config=config,
    cameras=cameras,
)
PY
```

---

# Tests

Das Projekt verwendet `pytest`.

Komplette Testsuite:

```bash
python3 -m pytest
```

Ausführliche Ausgabe:

```bash
python3 -m pytest -v
```

Einzelne Testdatei:

```bash
python3 -m pytest tests/daily_test.py
```

Einzelner Test:

```bash
python3 -m pytest tests/camera_test.py::test_get_image_range -v
```

Aktuell verifizierter Stand:

```text
52 passed
```

Die Tests sind nach Modulverantwortung getrennt:

```text
camera_test.py
→ Kameraerkennung, Dateinamen, Bildauswahl

daily_test.py
→ Daily-Businesslogik und Retention

diagnostics_test.py
→ gemeinsame Diagnose-Logik

main_test.py
→ Orchestrierung, Routing und globale Fehler

manual_test.py
→ Manual-Businesslogik

video_test.py
→ technische Video-/FFmpeg-Funktionen

weekly_test.py
→ Weekly-Businesslogik
```

Tests deaktivieren das produktive File-Logging über:

```text
TIMELAPSE_DISABLE_FILE_LOGGING=1
```

---

## Fehlerbehandlung

Globale und kamerabezogene Fehler werden bewusst unterschiedlich behandelt.

### Globaler Fehler

Wenn der Kamera-Root `/mnt/cameras` nicht erreichbar ist, wird der komplette Job abgebrochen.

### Fehler einer einzelnen Kamera

Operative Fehler wie:

```python
OSError
subprocess.CalledProcessError
```

werden pro Kamera geloggt.

Danach wird mit der nächsten Kamera weitergearbeitet.

Programmierfehler wie `TypeError` oder `AttributeError` sollen nicht pauschal verschluckt werden.

---

## Sicherheit und Datenintegrität

Grundregeln:

- Originalbilder unter `/mnt/cameras` niemals verändern.
- Frames immer lokal unter `temp/` vorbereiten.
- Unbekannte Dateiformate niemals erraten.
- Bestehende Videos erst nach erfolgreicher Neuerstellung ersetzen.
- Daily-Retention erst nach erfolgreicher Videoerstellung anwenden.
- Eine fehlerhafte Kamera darf andere Kameras möglichst nicht blockieren.
- Diagnosefunktionen dürfen den Produktionslauf nicht dauerhaft blockieren.

---

## Geplante Weiterentwicklung

Als nächster größerer Timelapse-Typ ist Yearly vorgesehen.

Aktuelles Konzept:

```text
rollierende letzte 365 Kalendertage
→ Originalbilder untersuchen
→ pro Tag ein Bild auswählen
→ Bild möglichst nahe an einer einheitlichen lokalen Zielzeit
→ daraus ein image-basiertes Timelapse erstellen
```

Yearly soll nicht aus Daily- oder Weekly-Videos zusammengesetzt werden.

Die genaue Zielzeit und Toleranz sind noch festzulegen.

Die automatische zeitgesteuerte Ausführung soll später über das Betriebssystem erfolgen, vorzugsweise mit `systemd`-Timern statt mit einem internen Python-Scheduler.
