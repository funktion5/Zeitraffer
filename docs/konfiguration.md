# Konfiguration

Die Einstellungen des Programms (`config/config.json`), die Werte, die die Weboberfläche darüber legt
([Einstellungen der Weboberfläche](#einstellungen-der-weboberfläche)), und die Umgebungsvariablen.
Wie man einen Server einrichtet, steht in [installation.md](installation.md) und [vps.md](vps.md).

*Für die technische Einrichtung.*

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
  "automatic_daylight_buffer_minutes": {
    "1": 30, "2": 60, "3": 60, "4": 60, "5": 90, "6": 90,
    "7": 90, "8": 60, "9": 60, "10": 60, "11": 30, "12": 30
  },
  "interval_window": {
    "target_time": "12:00",
    "tolerance_minutes": 90
  },
  "min_coverage_days": {
    "monthly": 25,
    "yearly": 300
  },
  "image_scan_stall_timeout_seconds": 60,
  "log_retention_days": 30,
  "ignored_cameras": [
    "Reolink",
    "Wunstorf-Marktplatz",
    "SVG"
  ],
  "timelapse": {
    "daily_framerate": 10,
    "monthly_framerate": 20,
    "yearly_framerate": 20,
    "ffmpeg_threads": 2,
    "crf": 28
  },
  "privacy": {
    "blur_cameras": ["…"],
    "ignore_boxes": {"…": [[703, 557, 742, 643]]},
    "ignore_top_share": 0.333,
    "skip_labels": {"…": ["vehicle", "plate"]},
    "min_person_score": {"…": 0.35},
    "detector_command": [
      ".venv/bin/python3", "-I", "src/privacy/detect.py",
      "--model", "models/object_detection_yolox_2022nov.onnx",
      "--tiles", "2",
      "--threshold", "0.25",
      "--vehicle-plate-share", "0.55",
      "--vehicle-threshold", "0.15",
      "--plate-search",
      "--vehicle-block-ratio", "0.0133"
    ],
    "blur": {
      "strength": 0.08,
      "padding_ratio": 0.05,
      "feather": 0.5
    }
  },
  "flagger": {
    "cameras": ["Strandallee", "SLSV", "BSV-Steinhude", "SKM-Mardorf", "Kitestrand"],
    "retention_days": 30
  }
}
```

`automatic_daylight_buffer_minutes` ist der Zeitpuffer vor Sonnenaufgang und nach
Sonnenuntergang für das automatische Daily, abhängig vom Monat des Zieltags (Schlüssel `"1"` bis
`"12"`, alle zwölf müssen vorhanden sein): Mai bis Juli 90, März, April, August und September 60, sonst 30 Minuten.
Das automatische Weekly wird aus den Dailys zusammengesetzt und übernimmt den Puffer damit pro Tag.
Historische Daily- und Weekly-Läufe nutzen dagegen immer den festen Wert `daylight_buffer_minutes`
(oder den per CLI/Weboberfläche gewählten), weil dieser im Dateinamen steht.
`--daylight-buffer-minutes` überschreibt für einen Lauf beide Werte, auch bei automatischen Jobs.

`interval_window` ist das tägliche Bildfenster für Monthly und Yearly: Zielzeit
`target_time` (`HH:MM` oder `sunset`) ± `tolerance_minutes`. Automatische Läufe verwenden immer
diesen Wert; historische Läufe können ihn per CLI überschreiben (siehe „Zeitfenster für
historisches Monthly und Yearly"). Ein Fenster darf nicht über Mitternacht reichen, und die
Toleranz muss mindestens 1 Minute betragen. Auf der Weboberfläche sind nur eine Zielzeit von 10:00
bis 14:00 und eine Toleranz von 1 bis 120 Minuten wählbar (Tageslicht, Fenster im selben Tag);
`sunset` und andere Zeiten gelten nur in dieser Datei und per CLI.

`min_coverage_days` legt fest, wie viele Tage mit mindestens einem Bild im Zeitfenster ein
Monthly bzw. Yearly braucht (automatisch und historisch gleich). Erlaubt sind ganze Zahlen von 1
bis zur Fensterlänge (30 bzw. 365, mit 29. Februar im Zeitraum 366); mehr lässt den Auftrag abbrechen.
Die Weboberfläche bietet höchstens 30 und 365 an, damit der Wert in jedem Jahr passt.

`image_scan_stall_timeout_seconds` (Sekunden): Meldet der Bildscan einer Kamera so lange keinen
Fortschritt, wird er abgebrochen und die Kamera übersprungen. Gemessen wird Stillstand, nicht
die Gesamtdauer. `log_retention_days` (Tage): ältere Logdateien werden beim Start gelöscht.
`timelapse.*_framerate` (Bilder pro Sekunde im Video; Weekly nutzt den Daily-Wert),
`timelapse.ffmpeg_threads` (Threads pro FFmpeg-Aufruf) und `timelapse.crf` (x264-Qualität,
ganze Zahl von 0 bis 51; niedriger ist besser und größer, höher ist kleiner; Standard 28)
steuern die Videoerstellung.

`privacy` steuert die Verpixelung von Personen und Kennzeichen: `detector_command` ist die
Befehlszeile der Erkennung (als Liste, Pfade relativ zum Projektordner), `blur` das Aussehen
(Blockgröße, Rand, weicher Übergang), `ignore_boxes` und `ignore_top_share` (mit dem Wert je Kamera
`ignore_top_share_per_camera`) verwerfen bekannte
Fehlerkennungen, `skip_labels` schaltet pro Kamera die Fahrzeug- und Kennzeichenverpixelung ab
(z. B. Boote auf Trailern), `min_person_score` verwirft pro Kamera unsichere Personen-Boxen
(z. B. Bootsplanen; kann entfernte Personen unverpixelt lassen). Ungültige Werte brechen einen Lauf mit Verpixelung ab, bevor ein Bild bearbeitet
wird. Alle Werte und Grenzen:
[docs/verpixelung.md](verpixelung.md#konfiguration).

`flagger` steuert den Highlights-Flagger: `cameras` sind die Kameras, die jede Nacht geprüft
werden (leer = keine), `retention_days` ist die Aufbewahrung der Berichte in Tagen (mindestens
7). Details: [docs/flagger.md](flagger.md#konfiguration).

## Einstellungen der Weboberfläche

`config/config.json` ist die Datei der IT. Eine festgelegte Auswahl ihrer Werte können die
Kolleginnen und Kollegen auf der Seite **Einstellungen** der Weboberfläche ändern
([weboberflaeche.md](weboberflaeche.md#einstellungen)). Diese Änderungen landen nicht in
`config.json`, sondern in zwei eigenen Dateien, je Reiter eine, und gelten **über** `config.json`:

| Datei | Reiter | Bereich |
|---|---|---|
| `config/settings.json` | Allgemein | `general` |
| `config/settings-privacy.json` | Verpixelung | `privacy` |

Beide sind in Git ignoriert und gibt es je Host einmal; die Datei auf dem VPS ist maßgeblich.
`config/settings.example.json` zeigt die Form. Fehlt eine Datei, gelten ihre Werte nicht.

- **Rangfolge:** `config.json`, darüber `settings.json`, darüber `settings-privacy.json`
  (`load_config()` in `src/config.py`). Objekte werden Schlüssel für Schlüssel gemischt (ein Monat des
  Tageslicht-Puffers ändert nur diesen Monat), Zahlen und Listen ersetzen den Wert.
- **Nur Abweichungen:** Die Dateien enthalten nur, was von `config.json` abweicht. Wird ein Wert auf
  der Seite auf den Standard zurückgestellt, verschwindet er aus der Datei, und eine spätere
  Änderung an `config.json` erreicht den Schlüssel wieder. Steht ein Schlüssel in einer
  Einstellungsdatei, ist eine Änderung in `config.json` für ihn wirkungslos: Bei einem Wert auf der Seite
  zurücksetzen („Alles auf Standard“, dann Speichern) oder den Schlüssel aus der Datei löschen. Die
  Kameralisten und die Rahmen haben keinen Standard-Knopf; stellt man sie von Hand wieder so ein wie in
  `config.json`, verschwindet ihr Schlüssel ebenfalls aus der Datei.
- **Nur freigegebene Schlüssel:** `src/settings.py` ist die einzige Liste mit Regeln und Grenzen.
  Alles andere in einer Einstellungsdatei, ein Wert außerhalb der Grenzen, eine kaputte oder
  unlesbare Datei wird mit einer Warnung im Protokoll ignoriert und kann den Nachtlauf nicht stoppen.
  Die PHP-Seiten kennen nur die Schlüsselnamen; ein Test vergleicht sie mit der Python-Liste.
- **Erster Schlüssel `_note`** in `config.json` weist darauf hin; er wird nicht ausgewertet.

Bereich `general` (Reiter Allgemein):

| Schlüssel | Erlaubt |
|---|---|
| `timelapse.crf` | ganze Zahl 18–35 (die Umgebungsvariable `TIMELAPSE_X264_CRF` erlaubt 0–51) |
| `timelapse.daily_framerate`, `monthly_framerate`, `yearly_framerate` | je 1–60 |
| `ignored_cameras` | Liste einfacher Kameranamen |
| `flagger.cameras` | Liste einfacher Kameranamen, ohne eine in `ignored_cameras` stehende (der Flagger startet sonst für keine Kamera) |
| `flagger.retention_days` | 7–365 (mindestens die Woche, die der Flagger verlangt) |
| `daylight_buffer_minutes` | 0–240 |
| `automatic_daylight_buffer_minutes.1` bis `.12` | je 0–240 |
| `interval_window.target_time` | `HH:MM` von 10:00 bis 14:00 |
| `interval_window.tolerance_minutes` | 1–120 |
| `min_coverage_days.monthly`, `.yearly` | 1–30; 1–365 |
| `log_retention_days` | 1–365 |

Bereich `privacy` (Reiter Verpixelung); die Grenzen sind die des Verpixelungs-Codes selbst
(`src/privacy/anonymize.py`):

| Schlüssel | Erlaubt |
|---|---|
| `privacy.blur_cameras` | Liste einfacher Kameranamen |
| `privacy.blur.strength` | 0,05–0,5 |
| `privacy.blur.padding_ratio` | 0,05–1 |
| `privacy.blur.feather` | 0–1 |
| `privacy.ignore_top_share_per_camera.<Kamera>` | 0 bis unter 0,5 (0 = aus) |
| `privacy.min_person_score.<Kamera>` | 0–0,5 |
| `privacy.ignore_boxes.<Kamera>` | höchstens 50 Rahmen `[x0, y0, x1, y1]`, ganze Zahlen von 0 bis 20 000, `x1 > x0`, `y1 > y0` |

`privacy.ignore_top_share_per_camera.<Kamera>` **ersetzt** für diese Kamera den globalen
`privacy.ignore_top_share` ([verpixelung.md](verpixelung.md#ignore_boxes-ignore_top_share-skip_labels-und-min_person_score)).
Der globale Wert bleibt in `config.json` der Standard der IT und steht nicht auf der Seite; ein Wert
je Kamera, der ihm gleicht, wird nicht gespeichert.

Absichtlich **nicht** auf der Seite: `location`, `timelapse.ffmpeg_threads`,
`image_scan_stall_timeout_seconds` (ein falscher Wert kann den VPS überlasten oder Aufträge hängen
lassen) und aus `privacy` der Detektor (`detector_command`), `skip_labels` und der globale
`ignore_top_share`.

Jede Speicherung schreibt eine Zeile nach `logs/settings.log` (Zeit, Bereich, Schlüssel alt → neu;
keine IP-Adresse). Auf einen neuen Host kommen die beiden Dateien einmal mit der Sicherung
(`backup.sh`, Schritt `restore`) oder mit `rsync --no-perms --ignore-existing`; danach nie wieder
von einem anderen Rechner kopieren, sonst gehen die Änderungen der Kolleginnen und Kollegen verloren.

## Tests der Konfiguration

Die Tests prüfen unter anderem:

- erwarteten Config-Pfad
- Existenz der Datei
- gültige JSON-Syntax
- erwartete Schlüssel
- grundlegende Datentypen

## Umgebungsvariablen

Pfade und Einstellungen lassen sich über Umgebungsvariablen setzen. Für den normalen Betrieb
braucht es nur `TIMELAPSE_STORAGE_BOX`; die Cron-Zeilen setzen sie.

| Variable | Standard | Wirkung |
|---|---|---|
| `TIMELAPSE_CAMERA_ROOT` | keiner | Ordner mit den Kamerabildern statt der Storage Box, z. B. ein entpacktes NAS-Archiv ([docs/nas.md](nas.md)). Ist er gesetzt, liest das Programm von dort; ein leerer Wert zählt als nicht gesetzt (dann gilt die Storage Box, falls `TIMELAPSE_STORAGE_BOX` gesetzt ist) |
| `TIMELAPSE_STORAGE_BOX` | keiner | Name des Eintrags der Storage Box in `~/.ssh/config`, optional mit Basisordner: `<ssh-alias>[:<basisordner>]`. Benutzer, Port und Schlüssel stehen unter dem Alias, nie im Repository. Ohne ihn und ohne `TIMELAPSE_CAMERA_ROOT` bricht ein Lauf mit einer Fehlermeldung ab |
| `TIMELAPSE_FRAME_SOURCE` | automatisch | Woher die Jobs die Kamerabilder lesen: `local` (Ordner aus `TIMELAPSE_CAMERA_ROOT`) oder `ssh` (Dateiliste per ssh von der Storage Box, Bilder per rsync in einen Zwischenspeicher unter `temp/frame-cache/`). Ohne Angabe gilt `local`, wenn `TIMELAPSE_CAMERA_ROOT` gesetzt ist, sonst `ssh`, wenn `TIMELAPSE_STORAGE_BOX` gesetzt ist |
| `TIMELAPSE_X264_PRESET` | x264-Standard (`medium`) | Encoder-Preset (`ultrafast` … `placebo`): schneller, aber größere Dateien; `ultrafast` braucht deutlich weniger Arbeitsspeicher |
| `TIMELAPSE_X264_CRF` | `timelapse.crf` aus `config/config.json` (28) | x264-Qualität für einen Lauf (ganze Zahl 0 bis 51; niedriger = besser und größer). Ein ungültiger Wert bricht das Encodieren mit einer Fehlermeldung ab |
| `TIMELAPSE_PROJECT_ROOT` | `~/timelapse` des ausführenden Benutzers | Projektordner für die Web-Wrapper und `timelapse-nightly-staged` |
| `TIMELAPSE_NIGHTLY_PYTHON` | `.venv/bin/python3` im Projekt | Python für `timelapse-nightly-staged` |

Nur für Tests gedacht sind `TIMELAPSE_DISABLE_FILE_LOGGING` (setzt `tests/conftest.py`) und
`TIMELAPSE_WEB_*` (`PYTHON`, `LOCK_FILE`, `STATUS_HELPER`, `STATUS_ROOT`, `WORKER`), mit denen die
Tests die Web-Wrapper umleiten; `sudo` setzt die Umgebung im Betrieb ohnehin zurück.
