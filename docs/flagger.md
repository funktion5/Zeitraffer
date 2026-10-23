# Highlights-Flagger

Sieht sich jede Nacht die Daily-Bilder ausgewählter Kameras an und legt die wenigen Bilder
beiseite, auf denen etwas Besonderes zu sehen ist: Tiere und Flugobjekte (Vögel, Flugzeuge,
Drachen). Die Highlights-Seite der Weboberfläche zeigt sie dann direkt als Bilder an.
Der Code liegt in `src/flagger/`.

**Stand:** fertig gebaut und getestet. Geprüft werden Strandallee, SLSV, BSV-Steinhude,
SKM-Mardorf und Kitestrand; automatisch läuft er erst mit dem Cron-Eintrag (unten).

Der Flagger ist ein eigenes Programm. Er hängt nicht von der Verpixelung ab und teilt keinen
Code mit ihr. **Die beiseitegelegten Bilder sind nicht verpixelt.** Vor einer Veröffentlichung
müssen sie verpixelt werden.

Alle Pfade sind relativ zum Projektordner.

## Ablauf

1. Für jede Kamera aus `flagger.cameras` dieselben Bilder auswählen wie das automatische Daily
   (Sonnenauf- bis Sonnenuntergang mit dem Monatspuffer aus
   `automatic_daylight_buffer_minutes`).
2. Jedes Bild durch das YOLOX-Modell schicken: einmal das ganze Bild und zusätzlich vier
   überlappende Ausschnitte (je 60 % Breite und Höhe), damit auch kleine, weit entfernte Tiere
   gefunden werden.
3. Ein Bild wird markiert, wenn eine Erkennung aus einer der beiden Gruppen ihre Schwelle
   erreicht. Pro Bild zählt die sicherste Erkennung.
4. Markierte Bilder werden unverändert in den Berichtsordner kopiert, dazu eine
   `manifest.json`.
5. Am Ende eines nächtlichen Laufs werden Berichte gelöscht, die älter als
   `flagger.retention_days` sind, ebenso alte Arbeitsordner (`.JJJJ-MM-TT.tmp`) nach einem
   Absturz. Ein Lauf mit `--target-date` räumt nicht auf, damit ein
   älterer Tag nicht gleich wieder gelöscht wird.

Der Flagger liest nur. Er schreibt nie nach `/mnt/cameras` oder auf die Storage Box.

## Gruppen und Schwellen

| Gruppe | Klassen des Modells | Schwelle |
|---|---|---|
| `flying` | bird, airplane, kite | 0,30 |
| `animal` | cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe | 0,30 |

- Ein Vogel im Flug wird vom Modell meist zuerst als Flugzeug erkannt (Testbild Strandallee
  20.10.2026: airplane 0,86). Deshalb gehören bird, airplane und kite in eine Gruppe, und echte
  Flugzeuge werden mit markiert.
- Jede Klasse gehört zu genau einer Gruppe. Ein Schwan auf dem Wasser landet deshalb in
  `flying`; das spielt keine Rolle, weil die Seite die Klasse des Modells anzeigt.
- Das Modell kennt keine Rehe, Wildschweine, Robben oder Schwäne. Solche Tiere kommen als
  horse, cow, sheep, dog oder bear zurück, oder gar nicht. Die Bezeichnung ist eine Vermutung;
  ein Mensch sieht sich das Bild an.
- Ballons haben keine eigene Klasse. Ob sie als kite erkannt werden, ist nicht getestet.
- Personen werden nie markiert.

Die Schwellen stehen in `src/flagger/groups.py` und werden anhand echter Bilder nachjustiert.

### Feststehende Objekte

Ein Boot am Ufer oder eine Boje steht den ganzen Tag an derselben Stelle und würde sonst in fast
jedem Bild markiert (SKM-Mardorf 21.10.2026: ein Katamaran als „airplane“ in 69 von 71 Bildern;
SLSV: ein Schwimmkörper als „sheep“). Deshalb entscheidet der Flagger erst nach allen Bildern
eines Tages:

- Ein Treffer gilt als feststehend, wenn an seiner Stelle in mindestens **15 %** der Bilder des
  Tages, und in mindestens **3** Bildern, ebenfalls etwas erkannt wurde. „Dieselbe Stelle“
  heißt: die Rahmen überlappen sich zu mindestens 30 % (IoU). Ein leicht schaukelndes Objekt
  bleibt so dieselbe Stelle; ein kleiner Vogel vor dem großen Rahmen eines Boots nicht.
- Dabei zählen auch schwache Erkennungen ab **0,10**, die selbst nie markiert würden: Die Boje,
  die nur ab und zu über 0,30 kommt, wird in den übrigen Bildern meist schwach erkannt.
- Die Klasse spielt keine Rolle („airplane“ in einem Bild, „kite“ im nächsten).
- Pro Bild gewinnt der beste Treffer, der nicht feststehend ist. Ein echter Vogel neben dem Boot
  wird also weiter markiert.

Grenze: Ein Tier, das stundenlang an genau derselben Stelle sitzt, fällt ebenfalls heraus.
Werte (`STATIONARY_SHARE`, `STATIONARY_MIN_IMAGES`, `STATIONARY_IOU`, `PRESENCE_FLOOR`) in
`src/flagger/groups.py`.

## Konfiguration

In `config/config.json`:

```json
"flagger": {
  "cameras": ["Strandallee", "SLSV", "BSV-Steinhude", "SKM-Mardorf", "Kitestrand"],
  "retention_days": 30
}
```

- `cameras`: die Kameras, die jede Nacht geprüft werden. Leer bedeutet: es wird nichts geprüft
  (nur alte Berichte werden aufgeräumt). Jede Kamera muss unter `/mnt/cameras` existieren und
  darf nicht in `ignored_cameras` stehen, sonst bricht der Lauf ab, bevor ein Bild gelesen wird.
- `retention_days`: wie lange Berichte bleiben, mindestens 7 Tage.

## Aufruf

Nächtlicher Modus (Kameras aus der Config, Zieltag gestern):

```bash
.venv/bin/python3 -m src.flagger.run
```

Einzelne Kameras oder ein bestimmter Tag:

```bash
.venv/bin/python3 -m src.flagger.run --cameras Strandallee --target-date 2026-10-20
```

Testmodus für einen beliebigen Bildordner (ohne Config-Kameras, ohne Sperre, ohne Aufräumen):

```bash
.venv/bin/python3 -m src.flagger.run --images sandbox/flagger-samples --out /tmp/flagger-out --target-date 2026-10-20
```

Der Bericht landet dann in `/tmp/flagger-out/adhoc/highlights/2026-10-20/`. `--images` braucht
`--out` und lässt sich nicht mit `--cameras` kombinieren. Ohne `--target-date` trägt der
Testmodus das heutige Datum ein (der normale Lauf nimmt gestern).

Weitere Optionen: `--model <Datei>` (Standard:
`models/object_detection_yolox_2022nov.onnx`). Übersicht: `--help`.

Exit-Codes: `0` alles gelaufen (oder übersprungen, weil die Sperre belegt war), `1` mindestens
eine Kamera fehlgeschlagen, unbekannte oder ignorierte Kamera, Modelldatei fehlt, ungültiger
`flagger`-Abschnitt.

## Sperre und Cron

Der Flagger nimmt dieselbe Sperre wie der nächtliche Lauf, die Web-Jobs und der Speicherfilter
(`state/zeitraffer-run.lock`). Ist sie belegt, schreibt er „Skipped" ins Log und beendet sich.
So läuft er nie gleichzeitig mit einem Encoding.

Geplant, nicht eingerichtet: der Flagger direkt nach dem nächtlichen Lauf in derselben
Cron-Zeile, aber außerhalb von `flock -c`, damit seine eigene Sperre nicht an der von Cron
scheitert:

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && .venv/bin/python3 -m src.main'; cd <projektpfad> && .venv/bin/python3 -m src.flagger.run
```

## Ausgabe

```text
videos/<Kamera>/highlights/<JJJJ-MM-TT>/
  <Originalname>.jpg   unveränderte Kopie, Endung immer klein ".jpg"
  manifest.json
```

Der Ordner liegt neben `manual-runs/`; die Video-Retention fasst ihn nicht an, und Apache
liefert die Bilder über den vorhandenen `/videos/`-Alias aus. Ein erneuter Lauf für denselben
Tag ersetzt den ganzen Tagesordner (vorher von Hand gelöschte Bilder kommen dann zurück). Der
Ordner wird erst fertig aufgebaut und dann ausgetauscht; die Seite sieht nie einen halben
Bericht, und bei einem Fehler bleibt der alte Bericht stehen.

`manifest.json` (Schema 1):

| Feld | Inhalt |
|---|---|
| `schema` | `1` |
| `camera`, `date` | Kamera und Tag (`JJJJ-MM-TT`) |
| `created` | Zeitpunkt des Laufs, ISO 8601 mit Zeitzone |
| `detector` | Modell, Prüfsumme und Einstellungen, z. B. `yolox_2022nov-<hash>-ort-t2-animal0.3-flying0.3` |
| `checked` | Zahl der geprüften Bilder |
| `items` | markierte Bilder, sicherste zuerst |

Jeder Eintrag in `items`: `file` (Dateiname im Ordner), `taken_at` (Aufnahmezeit aus dem
Dateinamen, ISO 8601), `group`, `label` (Klasse des Modells), `score` (0 bis 1), `box`
(`[x1, y1, x2, y2]` in Bildpixeln), `image_size` (`[Breite, Höhe]`).

Auch ein Tag ohne Treffer bekommt ein Manifest mit `items: []` und der echten `checked`-Zahl,
damit die Seite „geprüft, nichts gefunden" anzeigen kann. Eine Kamera ohne Bilder an dem Tag
bekommt keinen Ordner.

## Fehlerverhalten

- Eine fehlgeschlagene Kamera (Mount weg, Zeitüberschreitung beim Scannen) hält die anderen
  nicht auf; der Exit-Code ist dann `1`.
- Ein unlesbares oder abgeschnittenes Bild (ohne JPEG-Endmarke `FF D9`) oder ein Dateiname ohne
  erkennbare Uhrzeit wird übersprungen, geloggt
  und mitgezählt (`failed=` im Log). Anders als bei der Verpixelung ist das kein Abbruch: ein
  verpasster Treffer kostet nichts.
- Konnte von einer Kamera kein einziges Bild gelesen werden (z. B. Mount-Aussetzer), gilt das
  als Fehler: es wird nichts geschrieben, ein älterer Bericht für den Tag bleibt stehen.
- Ein ungültiger `flagger`-Abschnitt in der Config wird geloggt und beendet den Lauf mit `1`.
- Fehler beim Aufräumen werden geloggt und ändern den Exit-Code nicht.

## Log

`logs/flagger/<Datum>.log` (Datum des Laufs, nicht des geprüften Tages). Pro Kamera zuerst die
Anzahl der Bilder, dann alle 10 Bilder ein Fortschritt (Bilder mit Treffer, vor dem Filter für
feststehende Objekte), gegebenenfalls die Zahl der nur feststehenden Treffer und am Ende eine
Zusammenfassung:

```text
[Strandallee] 143 images to check
[Strandallee] 10/143 images, 1 with hits so far
...
[Strandallee] 3 images had only stationary hits (e.g. a boat or buoy) and are not flagged
[Strandallee] checked=143 flagged=2 failed=0 seconds=1060
```

Fortschritt live verfolgen: `tail -f logs/flagger/$(date +%F).log`

Messwert Pi (21.10.2026): Modell laden 1,1 s, 7,4 s pro Bild (ganzes Bild plus vier
Ausschnitte, 4 Threads), Spitzenspeicher etwa 210 MB. Bei rund 140 Daily-Bildern sind das etwa
17 Minuten pro Kamera.

## Tests

```bash
.venv/bin/python3 -m pytest tests/flagger_*_test.py
```

Alle Tests außer `tests/flagger_acceptance_test.py` laufen mit einem künstlichen Modell und
brauchen weder `models/` noch Kamerabilder (so auch in CI). Der Abnahmetest braucht das Modell
in `models/` und das Testbild `sandbox/flagger-samples/strandallee-26-10-20_08-14-58-20.jpg`
(beides nicht im Repository); fehlt eines, wird er übersprungen.
