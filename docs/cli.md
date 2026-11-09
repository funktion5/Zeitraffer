# Kommandozeile und Job-Auswahl

Alle Aufrufe von `src.main`: automatische und historische Läufe, Job-Kombinationen und Zeitfenster.


Alle Befehle werden im Projektverzeichnis und innerhalb der virtuellen Umgebung ausgeführt:

```bash
cd ~/timelapse
source .venv/bin/activate
```

## Vollständiger automatischer Lauf

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

## Einzelne automatische Jobs

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

Mit `--cameras` lässt sich ein solcher Lauf auf bestimmte Kameras beschränken, zum Beispiel um die
automatischen Videos einer Kamera neu zu bauen:

```bash
python3 -m src.main --jobs monthly yearly --cameras SLSV
```

Das Ergebnis ersetzt das automatische Video dieser Kameras (Ausgabe unter `videos/<camera>/<job>/`,
Retention wie beim Nachtlauf). Es ist aber kein Produktionslauf: Der Marker `state/run-in-progress`
wird nicht angelegt. Kameras aus `privacy.blur_cameras` bauen ihre Videos wie in der Nacht nur aus
bestätigten Bildern ([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)).

Dasselbe bietet die Weboberfläche auf der Kameraseite, samt Upload auf die Website:
[Neu erstellen wie der Nachtlauf](weboberflaeche.md#neu-erstellen-wie-der-nachtlauf).

## Beliebige Job-Kombination

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

## Historische Job-Läufe

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

## Zeitpuffer für Daily und Weekly überschreiben

```bash
python3 -m src.main \
	--jobs daily \
	--target-date 2026-09-15 \
	--cameras Scheunenviertel \
	--daylight-buffer-minutes 60
```

- `--daylight-buffer-minutes 30|60|90` setzt den Zeitpuffer vor Sonnenaufgang und nach
  Sonnenuntergang für diesen einen Lauf; `config/config.json` bleibt unverändert.
- Der Wert ersetzt sowohl `daylight_buffer_minutes` als auch die Monatstabelle
  `automatic_daylight_buffer_minutes`, gilt also auch für automatische Jobs und den
  vollständigen Lauf.
- Historische Daily- und Weekly-Videos tragen den Puffer immer im Dateinamen, z. B.
  `Scheunenviertel_2026-09-15_60min.mp4`.
- Mit `monthly` oder `yearly` in `--jobs` wird der Aufruf abgelehnt: Beide nutzen keinen
  Zeitpuffer, sondern `interval_window`.

## Zeitfenster für historisches Monthly und Yearly

Standardmäßig wählen Monthly und Yearly Bilder aus `interval_window` in `config/config.json`
(12:00 ± 90 Minuten). Für historische Läufe lässt sich das Fenster verschieben:

```bash
python3 -m src.main \
	--jobs yearly \
	--target-date 2025-12-31 \
	--cameras Scheunenviertel \
	--window-time 18:30 \
	--window-tolerance-minutes 60
```

- `--window-time HH:MM` setzt die Mitte des täglichen Fensters.
- `--window-time sunset` verwendet den Sonnenuntergang des jeweiligen Tages (berechnet aus
  `location` mit `astral`). Das Fenster wandert damit mit der Jahreszeit.
- `--window-tolerance-minutes N` setzt die Minuten vor und nach der Mitte (mindestens 1).
- Fehlt eines der beiden Flags, gilt der Wert aus `interval_window`.
- Yearly wählt die fünf Frames pro Tag nach Abstand zu derselben Fenstermitte aus.
- Ein Fenster, das über Mitternacht reichen würde, wird vor dem Start abgelehnt.
- Die Ausgabe erhält das Fenster im Dateinamen, damit sie das 12:00-Video nicht überschreibt:
  `<camera>_<zieldatum>_1830-60min.mp4` bzw. `<camera>_<zieldatum>_sunset-60min.mp4`.

Die Flags gelten nur für historische Läufe (`--target-date`) mit `monthly` und/oder `yearly`.

## Kurzform für historisches Daily

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

`--cameras` ist gemeinsam mit `--date` oder `--jobs` gültig (mit `--jobs` ohne `--target-date`
betrifft es einen automatischen Lauf, siehe oben). Historische Daily-,
Monthly- und Yearly-Läufe können eine oder mehrere Kameras verarbeiten. Ohne `--cameras`
verarbeiten sie alle erkannten und nicht global ignorierten Kameras. Ein historisches Weekly
benötigt genau eine Kamera.

Angeforderte Kameras müssen auf der Storage Box (oder im Ordner aus `TIMELAPSE_CAMERA_ROOT`)
vorhanden sein und dürfen nicht über
`ignored_cameras` ausgeschlossen sein. Ist mindestens eine angeforderte Kamera nicht verfügbar,
wird der vollständige Aufruf vor dem ersten Job abgebrochen.

Nicht gültig sind unter anderem:

```text
--date + --jobs
--date + --target-date
--target-date ohne --jobs
historisches Weekly ohne genau eine Kamera
historisches Weekly gemeinsam mit einem weiteren Job
--cameras ohne --date oder --jobs
--daylight-buffer-minutes mit monthly oder yearly
--window-time / --window-tolerance-minutes ohne --target-date
--window-time / --window-tolerance-minutes mit daily oder weekly
--blur-people außerhalb eines historischen Daily
```

## Verpixelung bei historischen Läufen (Standard)

Ein historischer Lauf (`--date` oder `--jobs daily|weekly|monthly|yearly --target-date`) einer
Kamera aus `privacy.blur_cameras` verpixelt die Bilder seines Videos zuerst **auf der Storage Box**
und baut das Video danach aus den verpixelten Bildern. Es gibt keinen Schalter und keine Ausnahme;
jedes Zeitfenster ist erfasst. Automatische Läufe verpixeln nie; sie bauen ihre Videos nur aus
Bildern, die der Box-Job bestätigt hat
([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)).

```bash
python3 -m src.main --jobs monthly --target-date 2026-10-05 --cameras SLSV
```

- Ohne Verpixelung in der Kamera-Liste ändert sich nichts.
- Die Bilder werden auf der Box ersetzt, die Originale liegen vorher gesichert in `<Kamera>/original/`.
  Bereits verpixelte Bilder bleiben unberührt; ein abgebrochener Lauf macht beim nächsten Mal dort weiter.
- Es entsteht nur dann ein Video, wenn alle Bilder bestätigt sind. Sonst steht im Log
  `Blur not finished: … - skipping camera: <Kamera>` und die Kamera zählt als `failed`.
- Der Lauf dauert deutlich länger und hält die ganze Zeit die Laufsperre: er muss vor 02:00 fertig
  sein, sonst fällt der Nachtlauf aus.

Ablauf, Schutz vor doppelten Sicherungen, Grenzen und Fehlersuche:
[docs/verpixelung-box.md](verpixelung-box.md#verpixelung-bei-von-hand-gestarteten-videos).

## Personen verpixeln (Test)

`--blur-people` erkennt Personen in den Bildern eines historischen Daily und verpixelt sie vor
dem Encoding. Die Funktion ist ein Test und nur mit `--date` oder `--jobs daily --target-date`
erlaubt:

```bash
python3 -m src.main \
	--date 2026-06-28 \
	--cameras SLSV \
	--blur-people
```

- Das Video heißt dann zum Beispiel
  `videos/SLSV/manual-runs/daily/SLSV_2026-06-28_90min_blur.mp4`, damit es nie mit einem
  unbearbeiteten Video verwechselt wird.
- Bearbeitet werden nur die Kopien unter `temp/`, die Originale bleiben unverändert.
- **Fail closed:** Bei jedem Zweifel der Erkennung bricht der Lauf ab und es entsteht kein
  Video. Ein ungeprüftes Bild wird nie verwendet.
- Ergebnisse der Erkennung werden in `state/privacy/<Kamera>.jsonl` zwischengespeichert; ein
  erneuter Lauf prüft nur neue oder geänderte Bilder.
- Die Erkennung dauerte auf dem früheren Raspberry Pi 4 ca. 7,5–10 Sekunden pro Bild (der VPS ist unvermessen).

Von `--blur-people` noch nicht abgedeckt: automatische Läufe, Weekly, Monthly, Yearly und die
Weboberfläche. Die Verpixelung auf der Box (siehe oben) gilt dagegen für alle historischen Läufe.

Installation des Modells, alle Einstellungen, Cache, Detektor-Protokoll und Fehlersuche:
[docs/verpixelung.md](verpixelung.md).
