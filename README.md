# Timelapse

Automatisierte Erstellung von Timelapse-Videos aus den Bildbeständen mehrerer Kameras.

Das Projekt läuft auf einem Raspberry Pi und verarbeitet Bilder aus den unter `/mnt/cameras` eingebundenen Kameraordnern.

Ziel ist zunächst die automatische Erstellung täglicher Timelapse-Videos. Die Architektur soll später zusätzlich wöchentliche, monatliche und jährliche Timelapses ermöglichen.

---

## Projektziele

Das System soll:

- verfügbare Kameras automatisch über ihre Verzeichnisse erkennen,
- Bilder für einen gewünschten Zeitraum auswählen,
- Sonnenaufgang und Sonnenuntergang berücksichtigen,
- unterschiedliche bestehende Dateinamensformate unterstützen,
- Bilder chronologisch für FFmpeg vorbereiten,
- Timelapse-Videos mit einer einheitlichen Framerate erzeugen,
- temporäre Dateien nach erfolgreicher Verarbeitung entfernen,
- Fehler einzelner Kameras behandeln, ohne den gesamten Job unnötig zu gefährden,
- langfristig nachvollziehbare Logs für den automatisierten Betrieb erzeugen.

---

## Aktueller Workflow

Der derzeitige Daily-Workflow basiert auf einem Zieldatum.

Ohne explizite Angabe soll standardmäßig der vorherige Tag verarbeitet werden.

Beispiel:

```bash
python src/main.py --date 2026-09-14
```

Der grundsätzliche Ablauf ist:

```text
Kameras ermitteln
        ↓
Sonnenaufgang / Sonnenuntergang berechnen
        ↓
Bilder des Zieldatums suchen
        ↓
Zeitstempel aus Dateinamen ermitteln
        ↓
Bilder außerhalb der Tageslichtzeit entfernen
        ↓
ausgewählte Bilder in temp/ kopieren
        ↓
einheitlich als Frames benennen
        ↓
FFmpeg ausführen
        ↓
Video speichern
        ↓
temporäre Dateien entfernen
```

---

# Projektstruktur

Die zentralen Verzeichnisse sind derzeit:

```text
timelapse/
├── config/
│   └── cameras.json
├── src/
│   ├── config.py
│   ├── images.py
│   ├── main.py
│   ├── solar.py
│   └── video.py
├── tests/
├── temp/
├── videos/
└── README.md
```

Runtime-Daten werden nicht in Git gespeichert.

Entsprechende `.gitignore`-Einträge:

```gitignore
# Runtime data
temp/*
logs/*
videos/*
```

---

# Kameraerkennung

Die verfügbaren Kameras werden derzeit automatisch anhand ihrer Verzeichnisse unter

```text
/mnt/cameras
```

ermittelt.

Beispiel:

```text
/mnt/cameras/
├── Alter-Winkel-Promenade/
├── BSV-Steinhude/
├── Nordufer_tele/
├── Nordufer_wide/
├── Reolink/
├── Scheunenviertel/
└── ...
```

Versteckte Verzeichnisse werden ignoriert.

Dadurch muss eine neue Kamera nicht manuell in der Programmlogik hinterlegt werden, sofern ihr Verzeichnis korrekt eingebunden ist.

---

# Dateinamenskonzept

## Zukünftiger Standard

Für zukünftige Kamerabilder wurde ein einheitliches Dateinamensschema festgelegt.

Die Kamera selbst liefert den Kameranamen. Dieser Name ist nicht frei änderbar und kann daher gleichzeitig als eindeutiger Prefix verwendet werden.

Das vorgesehene Format lautet:

```text
<Kameraname>_YY-MM-DD_HH-MM-SS-MS.jpg
```

Dabei gilt:

```text
YY = Jahr
MM = Monat
DD = Tag

HH = Stunde
MM = Minute
SS = Sekunde
MS = Millisekunden
```

Beispiel:

```text
Scheunenviertel_26-09-16_14-35-42-39.jpg
```

Der ausgeschriebene reale Kameraname bleibt Bestandteil des Dateinamens.

Eine zusätzliche technische Kamera-ID ist nicht notwendig, da die Kameranamen durch die Kamerasysteme vorgegeben und nicht änderbar sind.

---

## Legacy-Dateinamen

Im bestehenden Bildbestand befinden sich verschiedene historisch gewachsene Dateinamensformate.

Beispiele:

```text
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

Diese bestehenden Formate werden weiterhin durch explizite Regex-Patterns unterstützt.

Die Legacy-Parser bleiben bewusst bestehen, damit historische Bilder auch nach Einführung des neuen Standards weiterhin verarbeitet werden können.

### Designentscheidung

Die Parser sollen unbekannte Formate **nicht erraten**.

Kann ein Dateiname keinem unterstützten Format sicher zugeordnet werden, wird kein Datum bzw. keine Uhrzeit angenommen.

Das bedeutet:

```text
bekanntes Format
→ Datum/Zeit extrahieren

unbekanntes Format
→ nicht raten
→ Datei als nicht erkannt behandeln
```

Diese Entscheidung verhindert, dass ein zufällig passender Zahlenblock als plausibles, aber falsches Datum interpretiert wird.

Neue Dateinamensformate sollen deshalb bei Bedarf ausdrücklich als neues unterstütztes Pattern ergänzt und mit Tests abgesichert werden.

---

# Datum und Uhrzeit aus Bildern

`images.py` enthält die Logik zur Interpretation der verschiedenen Dateinamen.

Dabei werden Datum und Uhrzeit getrennt extrahiert.

`extract_date()` wird unter anderem für die Diagnose des vorhandenen Bildbestands verwendet.

`extract_time()` wird verwendet, um Bilder eines Tages anhand ihrer Aufnahmezeit einzuordnen.

Ungültige oder nicht unterstützte Dateinamen werden bewusst nicht interpretiert.

---

# Auswahl der Bilder

Für einen Daily-Timelapse werden zunächst alle Bilder gesucht, deren Dateiname zum gewünschten Datum gehört.

Anschließend wird die Uhrzeit aus dem jeweiligen Dateinamen extrahiert.

Aus Datum und Uhrzeit wird ein Timestamp gebildet.

Nur Bilder innerhalb dieses Bereichs werden verwendet:

```text
sunrise <= timestamp <= sunset
```

Dadurch werden Nachtaufnahmen nicht in den täglichen Timelapse aufgenommen.

---

# Sonnenaufgang und Sonnenuntergang

Die Berechnung erfolgt in `solar.py` mithilfe von `astral`.

Die geografischen Daten werden aus der Konfiguration gelesen.

Beispielsweise:

```json
{
  "location": {
    "latitude": 52.45,
    "longitude": 9.38,
    "timezone": "Europe/Berlin"
  }
}
```

Dadurch wird nicht mit fest hinterlegten Uhrzeiten gearbeitet.

Die tatsächlichen Sonnenzeiten des jeweiligen Tages bestimmen den verwendeten Bildbereich.

---

# Temporäre Frames

Die ausgewählten Originalbilder werden nicht direkt durch FFmpeg verarbeitet.

Stattdessen werden sie in ein temporäres Verzeichnis kopiert:

```text
temp/
└── <camera>/
    └── <date>/
```

Beispiel:

```text
temp/
└── Scheunenviertel/
    └── 2026-09-14/
        ├── frame_000001.jpg
        ├── frame_000002.jpg
        ├── frame_000003.jpg
        └── ...
```

Die Bilder werden dabei bewusst einheitlich und fortlaufend umbenannt.

Damit erhält FFmpeg unabhängig von den unterschiedlichen ursprünglichen Kamera-Dateinamen eine konsistente Eingabesequenz:

```text
frame_%06d.jpg
```

Die Originalbilder unter `/mnt/cameras` werden dabei nicht verändert.

Vor Verwendung eines Temp-Verzeichnisses werden eventuell vorhandene alte Inhalte entfernt.

---

# Videoerstellung

Die Videoerstellung erfolgt mit FFmpeg.

Als Codec wird derzeit H.264 über `libx264` verwendet.

Das Ausgabeformat ist MP4.

Die Pixel-Darstellung wird auf

```text
yuv420p
```

gesetzt, um eine breite Kompatibilität mit Videoplayern sicherzustellen.

---

## Einheitliche Framerate

Die Länge eines Timelapse-Videos ist bewusst **nicht fest vorgegeben**.

Stattdessen verwenden alle Videos eine globale Framerate.

Aktuell:

```python
VIDEO_FRAMERATE = 10
```

Das bedeutet:

```text
10 Bilder = 1 Sekunde Video
100 Bilder = 10 Sekunden Video
1000 Bilder = 100 Sekunden Video
```

Dadurch werden Tage mit vielen Bildern automatisch länger dargestellt als Tage mit wenigen Bildern.

Die Geschwindigkeit der Bildfolge bleibt dagegen zwischen allen Timelapses konsistent.

---

# Videoverzeichnis

Daily-Videos werden kamerabezogen gespeichert:

```text
videos/
└── <camera>/
    └── daily/
        └── YYYY-MM-DD.mp4
```

Beispiel:

```text
videos/
└── Scheunenviertel/
    └── daily/
        └── 2026-09-14.mp4
```

Fehlt ein benötigtes Verzeichnis, wird es automatisch erstellt.

Dadurch können neu hinzukommende Kameras ohne manuelles Erstellen der Videoverzeichnisse verarbeitet werden.

Die Struktur ist bereits auf zukünftige Timelapse-Typen vorbereitet:

```text
videos/
└── <camera>/
    ├── daily/
    ├── weekly/
    ├── monthly/
    └── yearly/
```

Die konkrete Logik für Weekly-, Monthly- und Yearly-Timelapses wird erst implementiert, wenn deren Anforderungen festgelegt werden.

Die allgemeine Videoerzeugung soll dabei möglichst unabhängig vom Zeitraum bleiben.

---

# Cleanup

Nach erfolgreicher Verarbeitung werden die temporären Frames wieder entfernt.

Das fertige Video bleibt ausschließlich im entsprechenden Unterverzeichnis von `videos/` erhalten.

Die Originalbilder werden nicht gelöscht oder verändert.

Fehlerfälle sollen so behandelt werden, dass für die Diagnose relevante temporäre Daten nicht vorschnell verloren gehen.

---

# Diagnose von fehlenden Bildern

Wenn für eine Kamera an einem gewünschten Datum keine geeigneten Bilder gefunden werden, reicht die Information

```text
0 images
```

für den späteren automatisierten Betrieb nicht aus.

Deshalb wurde `get_image_range()` eingeführt.

Die Funktion untersucht den vorhandenen JPG-Bestand einer Kamera und ermittelt:

```text
earliest_date
latest_date
total_files
recognized_files
unrecognized_files
```

Das Ergebnis wird in einer `ImageRange`-Dataclass gespeichert.

Dadurch kann später beispielsweise unterschieden werden zwischen:

```text
Kameraordner ist leer

Bilder existieren, aber nicht am gewünschten Datum

Bilder existieren, aber Dateinamen sind unbekannt

Bilder existieren teilweise in bekannten und teilweise in unbekannten Formaten
```

Ein zukünftiger Logger kann dadurch beispielsweise melden:

```text
WARNING
Camera: BSV-Steinhude
No images found for requested date.
Available range: 2023-02-12 -> 2025-10-09
```

oder:

```text
WARNING
Camera: New-Camera
Files found: 500
Recognized filenames: 0
Unrecognized filenames: 500
```

---

# Performance von `get_image_range()`

`get_image_range()` durchsucht den Bildbestand linear.

Die Laufzeitkomplexität ist damit grundsätzlich:

```text
O(n)
```

wobei `n` der Anzahl untersuchter Dateien entspricht.

Die Funktion sortiert nicht den gesamten Bestand, sondern aktualisiert beim Durchlaufen jeweils das früheste und späteste erkannte Datum.

Dies vermeidet eine unnötige vollständige Sortierung.

---

## Messungen mit realen Daten

Die Funktion wurde mit realen Kameraarchiven getestet.

Beispiele:

```text
Wunstorf-Marktplatz
91.767 Dateien
Laufzeit: ca. 11,4 Sekunden
Recognized: 91.767
Unrecognized: 0
```

```text
Scheunenviertel
5.143 Dateien
Laufzeit: ca. 0,9 Sekunden
Recognized: 5.143
Unrecognized: 0
```

Bei sehr großen Kameraordnern können die Laufzeiten deutlich höher sein.

Beispiel:

```text
SKM-Mardorf
ca. 243.000 JPG-Dateien
```

Dabei wurde festgestellt, dass insbesondere Dateisystem-Metadatenzugriffe wie

```python
Path.is_file()
```

auf dem eingebundenen Kameraspeicher teuer sein können.

Ein Vergleich bei 243.209 Dateien ergab:

```text
iterdir + Dateiendung prüfen:
ca. 12 Sekunden

iterdir + is_file() + Dateiendung prüfen:
ca. 2 Minuten 37 Sekunden
```

### Entscheidung

Diese Laufzeit wird derzeit bewusst akzeptiert.

`get_image_range()` ist primär eine Diagnosefunktion und soll insbesondere bei ungewöhnlichen bzw. fehlenden Daten eingesetzt werden.

Eine Laufzeit von einigen Minuten bei sehr großen Archiven ist für den vorgesehenen automatisierten Betrieb akzeptabel.

Deshalb wird aktuell keine Performance-Optimierung vorgenommen, die Lesbarkeit oder Sicherheit der Dateiprüfung reduziert.

Sollte die Performance später relevant werden, kann diese Entscheidung anhand realer Messdaten erneut bewertet werden.

---

# Bisherige Validierung mit realen Kameraarchiven

Die Datumsparser wurden nicht ausschließlich mit künstlichen Unit-Tests getestet.

Zusätzlich wurden vollständige reale Kameraarchive durch `get_image_range()` verarbeitet.

Unter anderem:

```text
Alter-Winkel-Promenade
188.622 Dateien
188.622 erkannt
0 unbekannt

BSV-Steinhude
67.572 Dateien
67.572 erkannt
0 unbekannt

Nordufer_tele
78.008 Dateien
78.008 erkannt
0 unbekannt

Nordufer_wide
79.760 Dateien
79.760 erkannt
0 unbekannt

Reolink
866 Dateien
866 erkannt
0 unbekannt
```

Bei BSV-Steinhude wurde durch diese Prüfung ein zusätzliches Legacy-Dateiformat entdeckt:

```text
bsv_steinhude_202410020900.jpg
```

Dieses wurde anschließend explizit in den Parser aufgenommen.

Diese Vorgehensweise ist beabsichtigt:

```text
unbekannte Dateien entdecken
        ↓
reales Namensformat untersuchen
        ↓
Testfall ergänzen
        ↓
explizites Parser-Pattern ergänzen
        ↓
gesamten Bestand erneut validieren
```

Es sollen keine allgemeinen Regex-Patterns ergänzt werden, die unbekannte Formate lediglich zu erraten versuchen.

---

# Tests

Das Projekt verwendet `pytest`.

Tests werden beispielsweise ausgeführt mit:

```bash
PYTHONPATH=. pytest
```

oder ausführlicher:

```bash
PYTHONPATH=. pytest -v
```

Einzelne Tests können gezielt ausgeführt werden:

```bash
PYTHONPATH=. pytest tests/camera_test.py::test_get_image_range -v
```

Die Tests decken unter anderem ab:

- Erkennung bekannter Kamera-Dateinamen,
- Extraktion von Datum und Uhrzeit,
- Ablehnung ungültiger Dateinamen,
- Verhalten bei vollständig unbekannten Dateinamensformaten,
- Auswahl von Tageslichtbildern,
- Ermittlung des vorhandenen Bildzeitraums,
- Erstellung und Bereinigung temporärer Verzeichnisse,
- Kopieren und fortlaufendes Benennen von Frames,
- Video-/Timelapse-Workflow und Fehlerfälle.

Eine wichtige Testregel lautet:

```text
Unbekanntes Dateiformat -> nicht raten
```

Dafür existiert ausdrücklich ein Test mit einer simulierten neuen Kamera, deren Dateinamen keinem bekannten Format entsprechen.

---

# Fehlerbehandlung

Das System soll langfristig unbeaufsichtigt laufen können.

Daher gilt grundsätzlich:

```text
Ein Fehler bei einer Kamera soll nachvollziehbar sein
und möglichst nicht unnötig die Verarbeitung aller anderen Kameras verhindern.
```

Für kritische Operationen, insbesondere die Videoerstellung, ist eine kontrollierte Fehlerbehandlung vorgesehen.

Retry-Verhalten wird gezielt dort eingesetzt, wo ein erneuter Versuch sinnvoll ist.

Die endgültige Retry- und Logging-Strategie wird im weiteren Projektverlauf vervollständigt.

---

# Daylight-Buffer

Die Auswahl der Bilder orientiert sich dynamisch an Sonnenaufgang und Sonnenuntergang.

Zusätzlich wird der verwendete Zeitraum um einen konfigurierbaren Daylight-Buffer vor Sonnenaufgang und nach Sonnenuntergang erweitert. Dadurch können auch die Übergangsphasen vor Sonnenaufgang und nach Sonnenuntergang im Timelapse enthalten sein.

Der Buffer wird zentral in der Konfiguration festgelegt:

```json
"daylight_buffer_minutes": 90
```

`main.py` liest diesen Wert aus der Konfiguration und übergibt ihn an `find_images()`.

Die eigentliche Bildauswahl enthält dadurch keinen fest vorgegebenen Buffer. Der gewünschte Zeitraum kann über die Konfiguration geändert werden, ohne die Logik in `images.py` anzupassen.

Aktuell sind 90 Minuten konfiguriert. Der endgültige fachliche Wert ist noch abzustimmen.

---

# Logging

Das Projekt verwendet Pythons `logging`-Modul mit einer zentralen Logger-Konfiguration in `src/logger.py`.

Der Logger dient dazu, den automatisierten Ablauf nachvollziehbar zu machen und insbesondere Probleme bei einzelnen Kameras diagnostizieren zu können.

Der aktuelle Daily-Workflow protokolliert unter anderem:

- Start und Ende eines Daily-Jobs,
- das verarbeitete Zieldatum,
- den konfigurierten Daylight-Buffer,
- Sonnenaufgang und Sonnenuntergang,
- Beginn der Verarbeitung einer Kamera,
- Anzahl der ausgewählten Bilder,
- erstes und letztes ausgewähltes Bild als Debug-Information,
- fehlende Bilder,
- verfügbaren Bildzeitraum bei fehlenden Bildern,
- unbekannte Dateinamensformate,
- Schritte der Videoerstellung,
- erfolgreiche Videoerstellung und Ausgabepfad,
- Erstellung und Bereinigung temporärer Verzeichnisse.

Die Log-Level werden nach Bedeutung getrennt:

```text
DEBUG    technische Detailinformationen
INFO     normaler Programmablauf
WARNING  ungewöhnliche, aber behandelbare Zustände
ERROR    fehlgeschlagene Verarbeitung
```

Die gezielte Fehlerbehandlung und Retry-Strategie für den späteren automatisierten Betrieb wird im weiteren Projektverlauf ergänzt.

---

# Tests

Das Projekt verwendet `pytest`.

Tests werden beispielsweise ausgeführt mit:

```bash
PYTHONPATH=. pytest
```

oder ausführlicher:

```bash
PYTHONPATH=. pytest -v
```

Einzelne Tests können gezielt ausgeführt werden:

```bash
PYTHONPATH=. pytest tests/camera_test.py::test_get_image_range -v
```

Die Tests decken unter anderem ab:

- Erkennung bekannter Kamera-Dateinamen,
- Extraktion von Datum und Uhrzeit,
- Ablehnung ungültiger Dateinamen,
- Verhalten bei vollständig unbekannten Dateinamensformaten,
- Auswahl von Bildern innerhalb des Tageslichtfensters,
- konfigurierbaren Daylight-Buffer,
- Ermittlung des vorhandenen Bildzeitraums,
- Diagnose bei fehlenden Bildern,
- Erstellung und Bereinigung temporärer Verzeichnisse,
- Kopieren und fortlaufendes Benennen von Frames,
- Video-/Timelapse-Workflow,
- Verhalten bei Fehlern während der Videoerstellung.

Der Daylight-Buffer wird in den entsprechenden Tests explizit an `find_images()` übergeben. Die Tests bleiben dadurch unabhängig vom aktuell in der Konfiguration gesetzten Betriebswert.

Eine wichtige Testregel lautet:

```text
Unbekanntes Dateiformat -> nicht raten
```

Dafür existiert ausdrücklich ein Test mit einer simulierten neuen Kamera, deren Dateinamen keinem bekannten Format entsprechen.

Aktueller Teststand:

```text
18 passed
```

---

# Zentrale Architekturentscheidungen

Folgende Entscheidungen gelten derzeit für das Projekt:

1. Kameras werden anhand der gemounteten Kameraordner erkannt.
2. Der reale, nicht änderbare Kameraname kann zukünftig als Dateiprefix verwendet werden.
3. Das zukünftige Standardformat lautet `<Kameraname>_YY-MM-DD_HH-MM-SS-MS.jpg`.
4. Historische Dateinamensformate bleiben als Legacy-Parser erhalten.
5. Unbekannte Dateinamensformate werden niemals geraten.
6. Tageslicht wird dynamisch anhand von Sonnenaufgang und Sonnenuntergang bestimmt.
7. Der Zeitraum kann über einen konfigurierbaren Daylight-Buffer vor Sonnenaufgang und nach Sonnenuntergang erweitert werden.
8. Originalbilder werden für die Videoerstellung nicht verändert.
9. FFmpeg erhält eine normalisierte `frame_XXXXXX.jpg`-Sequenz.
10. Timelapses haben eine einheitliche Framerate statt einer einheitlichen Videolänge.
11. Videos werden nach Kamera und Timelapse-Typ strukturiert gespeichert.
12. Daily-, Weekly-, Monthly- und Yearly-Bildauswahl sollen von der allgemeinen Videoerstellung getrennt bleiben.
13. Diagnose- und Ablaufmeldungen werden zentral über Pythons `logging`-Modul protokolliert.
14. Konfigurierbare Betriebsparameter wie der Daylight-Buffer werden von der Verarbeitungslogik getrennt gehalten.

---

# Sicherheit und Datenintegrität

Die Originalbilder unter `/mnt/cameras` sind die Quelldaten.

Die Videoverarbeitung arbeitet deshalb grundsätzlich mit Kopien im `temp/`-Verzeichnis.

Originalbilder sollen durch die Timelapse-Erstellung nicht verändert werden.

Unbekannte Dateinamensformate werden nicht automatisch interpretiert.

Neue Verzeichnisse und Kameras können erkannt werden, ohne dass dadurch automatisch Annahmen über unbekannte Bildformate getroffen werden.

---

# Geplante Weiterentwicklung

Der aktuelle Fokus liegt auf Daily-Timelapses.

Später sind zusätzlich vorgesehen:

```text
daily
weekly
monthly
yearly
```

Die Auswahl der Bilder für diese Zeiträume soll von der eigentlichen Videoerstellung getrennt bleiben.

Die Videoerstellung soll grundsätzlich nur eine vorbereitete, chronologisch sortierte Frame-Sequenz erhalten.

Dadurch kann dieselbe FFmpeg-/Video-Logik für unterschiedliche Zeiträume wiederverwendet werden.

Die konkrete Architektur für Weekly-, Monthly- und Yearly-Auswahl wird erst implementiert, wenn die fachlichen Anforderungen dafür festgelegt sind.

---

# Zentrale Architekturentscheidungen

Folgende Entscheidungen gelten derzeit für das Projekt:

1. Kameras werden anhand der gemounteten Kameraordner erkannt.
2. Der reale, nicht änderbare Kameraname kann zukünftig als Dateiprefix verwendet werden.
3. Das zukünftige Standardformat lautet `<Kameraname>_YY-MM-DD_HH-MM-SS-MS.jpg`.
4. Historische Dateinamensformate bleiben als Legacy-Parser erhalten.
5. Unbekannte Dateinamensformate werden niemals geraten.
6. Tageslicht wird dynamisch anhand von Sonnenaufgang und Sonnenuntergang bestimmt.
7. Originalbilder werden für die Videoerstellung nicht verändert.
8. FFmpeg erhält eine normalisierte `frame_XXXXXX.jpg`-Sequenz.
9. Timelapses haben eine einheitliche Framerate statt einer einheitlichen Videolänge.
10. Videos werden nach Kamera und Timelapse-Typ strukturiert gespeichert.
11. Daily-, Weekly-, Monthly- und Yearly-Bildauswahl sollen von der allgemeinen Videoerstellung getrennt bleiben.
12. Diagnoseinformationen werden strukturiert vorbereitet und später über einen Logger ausgegeben.
13. Performanceoptimierungen werden anhand realer Messungen vorgenommen und nicht auf Kosten von Sicherheit oder Nachvollziehbarkeit erzwungen.