# Konfiguration

Die Einstellungen des Programms (`config/config.json`) und die Umgebungsvariablen. Wie man einen
Server einrichtet, steht in [installation.md](installation.md) und [vps.md](vps.md).

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
historisches Monthly und Yearly"). Ein Fenster darf nicht über Mitternacht reichen.

`min_coverage_days` legt fest, wie viele Tage mit mindestens einem Bild im Zeitfenster ein
Monthly bzw. Yearly braucht (automatisch und historisch gleich). Erlaubt sind ganze Zahlen von 1
bis zur Fensterlänge (30 bzw. 365, mit 29. Februar im Zeitraum 366).

`image_scan_stall_timeout_seconds` (Sekunden): Meldet der Bildscan einer Kamera so lange keinen
Fortschritt, wird er abgebrochen und die Kamera übersprungen. Gemessen wird Stillstand, nicht
die Gesamtdauer. `log_retention_days` (Tage): ältere Logdateien werden beim Start gelöscht.
`timelapse.*_framerate` (Bilder pro Sekunde im Video; Weekly nutzt den Daily-Wert),
`timelapse.ffmpeg_threads` (Threads pro FFmpeg-Aufruf) und `timelapse.crf` (x264-Qualität,
ganze Zahl von 0 bis 51; niedriger ist besser und größer, höher ist kleiner; Standard 28)
steuern die Videoerstellung.

`privacy` steuert die Verpixelung von Personen und Kennzeichen: `detector_command` ist die
Befehlszeile der Erkennung (als Liste, Pfade relativ zum Projektordner), `blur` das Aussehen
(Blockgröße, Rand, weicher Übergang), `ignore_boxes` und `ignore_top_share` verwerfen bekannte
Fehlerkennungen, `skip_labels` schaltet pro Kamera die Fahrzeug- und Kennzeichenverpixelung ab
(z. B. Boote auf Trailern), `min_person_score` verwirft pro Kamera unsichere Personen-Boxen
(z. B. Bootsplanen; kann entfernte Personen unverpixelt lassen). Ungültige Werte brechen einen Lauf mit Verpixelung ab, bevor ein Bild bearbeitet
wird. Alle Werte und Grenzen:
[docs/verpixelung.md](verpixelung.md#konfiguration).

`flagger` steuert den Highlights-Flagger: `cameras` sind die Kameras, die jede Nacht geprüft
werden (leer = keine), `retention_days` ist die Aufbewahrung der Berichte in Tagen (mindestens
7). Details: [docs/flagger.md](flagger.md#konfiguration).

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
