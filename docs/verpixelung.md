# Verpixelung von Personen und Kennzeichen

Erkennt Personen und Fahrzeuge in Kamerabildern und macht Personen und Kennzeichen unkenntlich.
Der Code liegt in `src/privacy/`.

Diese Seite beschreibt das, was jede Verpixelung gemeinsam nutzt: Detektor, Installation,
Einstellungen und die Regeln, welche Boxen verworfen werden. Wann und wo verpixelt wird (die
Runde alle 5 Minuten und das Nachholen um 02:00 auf der Storage Box sowie die von Hand gestarteten
Videos von Blur-Kameras),
beschreibt [verpixelung-box.md](verpixelung-box.md).

Alle Pfade sind relativ zum Projektordner.

## Installation

1. Python-Pakete: Der Detektor nutzt `onnxruntime`, `opencv-python-headless` und `numpy`. Sie
   stehen in `requirements.txt` und werden mit der normalen Installation eingerichtet:

   ```bash
   .venv/bin/python3 -m pip install -r requirements.txt
   ```

2. Modell: YOLOX aus dem [OpenCV Model Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox)
   (Apache-2.0). Der Ordner `models/` ist per `.gitignore` vom Repository ausgeschlossen.

   ```bash
   mkdir -p models
   curl -L -o models/object_detection_yolox_2022nov.onnx \
   	https://github.com/opencv/opencv_zoo/raw/main/models/object_detection_yolox/object_detection_yolox_2022nov.onnx
   ```

   Die Datei ist ca. 36 MB groß. Die Lizenz des Modells liegt als `models/LICENSE-yolox` daneben.

3. Prüfen: Eine leere Anfrage muss die Detektor-Kennung liefern.

   ```bash
   echo -n | .venv/bin/python3 -I src/privacy/detect.py \
   	--model models/object_detection_yolox_2022nov.onnx
   ```

   Erwartete Ausgabe: `{"detector": "yolox_2022nov-…", "results": {}}`.

Fehlt das Modell, endet jeder Detektor-Aufruf mit einem Fehler und kein Bild gilt als verpixelt
(siehe [Fehlersuche](#fehlersuche)).

## Konfiguration

Abschnitt `privacy` in `config/config.json`:

```json
"privacy": {
  "blur_cameras": ["Scheunenviertel", "SLSV"],
  "ignore_boxes": {"Scheunenviertel": [[703, 557, 742, 643]]},
  "ignore_top_share": 0.333,
  "skip_labels": {"SLSV": ["vehicle", "plate"]},
  "min_person_score": {"SLSV": 0.35},
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
}
```

`blur_cameras` nennt die Kameras, die verpixelt werden
([verpixelung-box.md](verpixelung-box.md#konfiguration)): Die Box-Verpixelung schreibt
ausschließlich in diese Kameras und bricht ohne Eintrag ab.

Ein Teil dieser Werte lässt sich auch auf der Weboberfläche ändern, im Reiter **Verpixelung**
([weboberflaeche.md](weboberflaeche.md#reiter-verpixelung-verpixelungphp)): `blur_cameras`, die
drei `blur`-Werte, je Kamera `min_person_score`, `ignore_boxes` und `ignore_top_share_per_camera`.
Diese Änderungen stehen nicht in `config.json`, sondern in `config/settings-privacy.json` und
gelten darüber ([konfiguration.md](konfiguration.md#einstellungen-der-weboberfläche)). Nur die IT
ändert `detector_command`, `skip_labels` und den globalen `ignore_top_share`.

### `detector_command`

Die Befehlszeile des Detektors als Liste, nie als Shell-Text. Steht hier `null`, verpixelt
nichts: Die Box-Verpixelung bricht mit `privacy.detector_command is not set.` ab.

| Option des Detektors | Bedeutung | Standard |
|---|---|---|
| `--model` | Pfad zur ONNX-Datei | Pflicht |
| `--tiles` | `1` = nur ganzes Bild, `2` = ganzes Bild plus vier überlappende Ausschnitte | `2` |
| `--threshold` | Mindestsicherheit einer Erkennung, 0–1 | `0.25` |
| `--nms` | Schwelle zum Zusammenfassen überlappender Boxen | `0.45` |
| `--threads` | Prozessor-Threads | `4` |
| `--vehicle-plate-share` | Anteil eines Fahrzeugs von unten, der verpixelt wird (Kennzeichen); `0` = nur Personen | `0` (Konfiguration: `0.55`) |
| `--vehicle-threshold` | Eigene Mindestsicherheit für Fahrzeuge, 0–1; niedriger als bei Personen, weil ein übersehenes Auto ein lesbares Kennzeichen hinterlässt, ein falsch erkanntes nur etwas Pflaster verpixelt | wie `--threshold` (Konfiguration: `0.15`) |
| `--plate-search` | Sucht in jedem Fahrzeug zusätzlich nach einem kennzeichenartigen Rechteck (hell, 3- bis 6-mal so breit wie hoch, mehrere dunkle Zeichen) und verpixelt es **zusätzlich** zum unteren Teil, nie stattdessen | aus (Konfiguration: an) |
| `--vehicle-block-ratio` | Blockgröße der Fahrzeug- und Kennzeichenbereiche als Anteil der Fahrzeugbreite, mindestens 4 px; `0` = Regel aus `blur.strength` | `0` (Konfiguration: `0.0133`) |

`--tiles 2` findet auch kleine Personen im Hintergrund, ist aber etwa fünfmal langsamer als
`--tiles 1`. Für den Datenschutz ist `2` die richtige Wahl.

### `ignore_boxes`, `ignore_top_share`, `skip_labels` und `min_person_score`

`ignore_boxes`: bekannte Fehlerkennungen pro Kamera als `[x0, y0, x1, y1]` in Pixeln. Eine Box,
die eine davon zu mindestens 50 % überlappt (Schnitt durch Vereinigung), wird verworfen.
Verschiebt sich die Kamera, sinkt die Überlappung und das Objekt wird wieder verpixelt. Beispiele
bei Scheunenviertel: der Wegweiser am Café-Eingang und die Ankerkette rechts. Wie man die
Koordinaten findet (von Hand oder mit Claude):
[Handbuch](handbuch.md#ein-feststehendes-objekt-wird-immer-wieder-verpixelt).

`ignore_top_share`: Regel für alle Kameras, der Standard der IT. Eine Box, die zu mehr als der Hälfte ihrer
Höhe im oberen Teil des Bildes liegt (hier oberes Drittel), wird verworfen. `ignore_top_share_per_camera`
gibt einer Kamera einen eigenen Wert (`{"Scheunenviertel": 0.2}`), der für sie den globalen
**ersetzt**; `0` schaltet den Streifen dort ab. Die Weboberfläche schreibt nur diesen Wert je Kamera.
Ein Rahmen aus `ignore_boxes` kann den Streifen nicht ersetzen: Er verwirft nur Boxen, deren Schnitt durch
Vereinigung mit ihm mindestens 0,5 ist (also fast deckungsgleiche), der Streifen jede, die überwiegend in ihm liegt. Dort sind Himmel, Dächer, Wasser oder die
Kamerahalterung, keine Person, die man erkennen könnte. Anlass: Bei Scheunenviertel hielt der
Detektor zweimal die Halterung oben rechts für eine Person, einmal mit einer 373 × 460 px großen
Box in der Dämmerung. Am 2026-08-16 betraf die Regel nur diese 2 von 1965 Boxen.

Die Regel greift beim Verpixeln, nicht im Detektor. `0` schaltet die Regel ab.

`skip_labels`: pro Kamera die Erkennungsarten, die dort nie verpixelt werden. Erlaubt sind nur
`vehicle` und `plate`, **nie `person`**. Anlass: Bei SLSV stehen Boote auf Trailern mit Rädern,
der Detektor hält sie für Fahrzeuge und sucht darin Kennzeichen; Autos gibt es dort nicht
(2026-10-19). Fährt doch einmal ein Auto ins Bild, bleibt sein Kennzeichen lesbar, deshalb nur
für Kameras ohne Straße oder Parkplatz eintragen. Boxen ohne Label (ältere Detektoren) werden
nie übersprungen.

`min_person_score`: pro Kamera die Mindestsicherheit für Personen-Boxen (0 bis 0,5; ohne Eintrag
gilt die Detektor-Schwelle 0,25). Anlass: Bei SLSV erkannte der Detektor Bootsplanen,
Segelsäcke, Winschen und Trailerteile als Personen. In einer Stichprobe von 40 Boxen (Yearly
2025) war etwa die Hälfte keine Person, mit Werten bis 0,78; echte Personen lagen teils bei
0,25. Eine saubere Grenze gibt es also nicht. Mit `0.35` (Entscheidung Julius, 2026-10-19)
bleiben bei SLSV 506 statt 781 Boxen; dafür können **einzelne entfernte Personen unverpixelt
bleiben**. Nur für Kameras setzen, bei denen das vertretbar ist.

Alle vier Regeln greifen in einer gemeinsamen Funktion (`filter_boxes`). Verworfene Boxen stehen
in der Statusdatei des Box-Jobs unter `ignored_boxes`. Alle Werte werden bei jedem Start geprüft: Ein Tippfehler wie
`ignore_top_share: 3.33` würde sonst stillschweigend jede Box verwerfen, deshalb bricht der Lauf
mit einer Fehlermeldung ab (erlaubt: 0 bis unter 0,5, auch für jeden Wert in `ignore_top_share_per_camera`; Boxen mit vier ganzen Zahlen ab 0,
`x1 > x0`, `y1 > y0`; bei `skip_labels` eine nicht leere Liste aus `vehicle`/`plate`; bei `min_person_score` eine Zahl
von 0 bis 0,5). Kamerabezogene Regeln nur, wo sie nötig sind; eine Kamera mit Personen im oberen Drittel
(Hang, Balkon) bräuchte eine Ausnahme.

### Kennzeichenbereich (55 %, global)

Wie hoch das Kennzeichen im Kasten eines Autos sitzt, hängt vom Blickwinkel ab: Scheunenviertel
sieht viele Autos schräg von hinten oben, dort sitzt das Kennzeichen bei 41–53 % der Höhe
(gemessen 2026-10-16) und lag damit knapp über den früheren 40 %. Seitdem gilt
`--vehicle-plate-share 0.55` für alle Kameras: Auf anderen Kameras wird dadurch etwas mehr
verpixelt, die sichere Richtung. Eine kameraeigene Einstellung gibt es bewusst nicht mehr
(globale Regeln, solange keine Kamera eine eigene braucht).

Den Anteil nur nach oben erweitern, nie den Bereich nach oben verschieben: Frontkennzeichen und
Autos, die in einer Reihe hinter einem anderen stehen, haben ihr Kennzeichen ganz unten im
Kasten.

### Blockgröße für Kennzeichen (Entscheidung 2026-10-16)

Fahrzeuge werden feiner verpixelt als Personen, damit das Auto erkennbar bleibt. Der Detektor
schreibt die Blockgröße in jede Fahrzeug- und Kennzeichenbox (`block`), das Verpixeln übernimmt
sie; Personen behalten die Regel aus `blur.strength`. Die Blöcke wachsen mit der Breite des Autos
(`--vehicle-block-ratio 0.0133`, nie unter 4 px):

| Breite des Autos im Bild | Block | Beispiel Scheunenviertel |
|---|---|---|
| bis ca. 340 px | 4 px | fast alle Autos auf dem Platz |
| ca. 475 px | 6 px | vorderste Reihe |
| ca. 600 px | 8 px | sehr nah an der Kamera |

Warum mitwachsend statt fest 4 px: Je näher ein Auto, desto größer sein Kennzeichen im Bild. Ein
Kennzeichen von 75 px Breite hat bei 4 px etwa 2 Blöcke pro Zeichen und ist unlesbar; eines von
120 px Breite hätte bei festen 4 px 3–4 Blöcke pro Zeichen und könnte wieder lesbar werden. So
bekommt jedes Kennzeichen ungefähr gleich viele Blöcke. Eine Änderung von
`--vehicle-block-ratio` ändert die Detektor-Kennung.

Bei 4 px ist kein Zeichen mehr lesbar. Bekannt und bewusst in Kauf genommen: Bei sehr feiner
Verpixelung lässt sich ein Kennzeichen mit bekannter Schrift (FE-Schrift) unter Aufwand per
Computer zurückrechnen; 5–6 px würden das erschweren. Abgewogen gegen das Aussehen wurde 4 px
gewählt, weil ein solcher Angriff gezielten Aufwand braucht und ein Kennzeichen allein ohne
Halterauskunft niemanden identifiziert. Das größere Risiko sind Kennzeichen, die gar nicht
verpixelt werden.

### `blur`

Alle Werte sind Pflicht. Ein ungültiger Wert bricht den Lauf ab, bevor ein Bild bearbeitet
wird; der Konfigurationstest prüft die Werte zusätzlich.

| Wert | Bedeutung | Erlaubt |
|---|---|---|
| `strength` | Blockgröße als Anteil der kürzeren Seite des Bereichs (Personen; Fahrzeuge siehe Blockgröße oben) | 0,05–0,5 |
| `padding_ratio` | Rand, um den der Bereich je Seite über die erkannte Box hinaus wächst | 0,05–1,0 |
| `feather` | Anteil des Rands, der weich ausläuft (0 = harte Kante) | 0–1 |

- Jede Box bekommt mindestens 2 Pixel Rand, damit eine knapp erkannte Person nicht am Rand
  sichtbar bleibt.
- Weich ausgeblendet wird nur der zusätzliche Rand. **Die erkannte Box selbst ist immer
  vollständig unkenntlich.**
- Verpixelt wird immer ein Rechteck in Blöcken.

## Sicherheitsregeln (fail closed)

Im Zweifel gilt ein Bild **nicht** als verpixelt. Ein Fehler `PrivacyCheckError` entsteht, wenn:

- `detector_command` fehlt oder der Detektor nicht startet,
- der Detektor mit Fehler endet oder länger braucht als erlaubt (Box-Verpixelung: 120 Sekunden),
- die Ausgabe kein gültiges JSON ist oder eine Detektor-Kennung fehlt,
- ein angefragtes Bild im Ergebnis fehlt oder eine Box ungültig ist,
- das Verpixeln eines Bildes fehlschlägt (FFmpeg-Fehler oder mehr als 120 Sekunden),
- eine Box vollständig außerhalb des Bildes liegt.

Die Box-Verpixelung lässt das Bild dann unverändert und versucht es in der nächsten Runde erneut.
Ein automatisches Video lässt solche unbestätigten Bilder weg, ein von Hand gestartetes Video
einer Blur-Kamera entsteht dann nicht ([verpixelung-box.md](verpixelung-box.md)).

## Detektor-Kennung

Jede Erkennung wird mit der Kennung des Detektors gespeichert (in der Statusdatei des Box-Jobs,
Feld `detector`). Gespeichert werden nur Koordinaten, keine Bildausschnitte. Die Kennung enthält
Modellname, Prüfsumme des Modells, Laufzeit, Kachelung, Schwelle und die Fahrzeug-Einstellungen,
z. B. `yolox_2022nov-c5c2d13e-ort-t2-c0.25-u2-v0.55-vc0.15-ps-b0.0133` (`u2` = Zusammenfassen
als Vereinigung, bei Personen auch für Boxen, die fast ganz in einer anderen liegen; `v` =
Kennzeichenbereich, `vc` = Fahrzeug-Schwelle, `ps` = Kennzeichensuche, `b` = Blockgröße).
`ignore_boxes`, `ignore_top_share` (auch je Kamera), `skip_labels` und `min_person_score` gehören
nicht dazu, weil sie erst beim Verpixeln greifen.

Der Detektor liest die Bilder ohne EXIF-Drehung (`IMREAD_IGNORE_ORIENTATION`), also genau so,
wie FFmpeg sie verpixelt. Sonst lägen die Boxen bei einer Kamera mit Drehungs-Angabe daneben.

## Detektor-Protokoll

`src/privacy/detect.py` kann durch ein anderes Programm ersetzt werden, solange es dieses
Protokoll einhält:

- **Eingabe:** Bildpfade auf stdin, ein Pfad pro Zeile.
- **Ausgabe:** ein JSON-Objekt auf stdout:

  ```json
  {"detector": "<kennung>", "results": {"<pfad>": [{"x0": 0, "y0": 0, "x1": 10, "y1": 20, "score": 0.9, "label": "vehicle", "block": 4}]}}
  ```

- Jeder angefragte Pfad muss enthalten sein; eine leere Liste heißt „geprüft, nichts zu
  verpixeln".
- Jede Box ist ein zu verpixelnder Bereich. `label` (`person`, `vehicle` oder `plate`, optional)
  dient nur der Nachvollziehbarkeit: Es wird in der Statusdatei des Box-Jobs gespeichert,
  ändert aber nicht, wie verpixelt wird.
- `block` (optional, mindestens 1) ist die Blockgröße in Pixeln für `pixelate`; fehlt es, gilt
  `blur.strength`.
- Personen und Fahrzeuge werden getrennt zusammengefasst (NMS), damit eine Person vor einem Auto
  nie in der Fahrzeugbox aufgeht.
- Eine leere Anfrage liefert nur die Kennung (`"results": {}`).
- Ein nicht lesbares Bild führt zu einem Exit-Code ungleich 0.

## Leistung

Auf dem VPS braucht die Erkennung ca. 5 Sekunden pro Bild, ein Bild mit Personen samt Verpixeln
ca. 9 Sekunden ([Messung](verpixelung-box.md#leistung)). Der Detektor braucht ca. 210–220 MB
Arbeitsspeicher.

## Grenzen

- Keine Erkennung findet 100 % aller Personen. Sehr kleine, verdeckte oder unscharfe Personen
  können übersehen werden.
- Erkannt werden ganze Personen. Kennzeichen werden nicht einzeln erkannt: Der Detektor findet
  Fahrzeuge (Auto, Motorrad, Bus, Lkw) und meldet davon den unteren Teil
  (`--vehicle-plate-share`, 55 %), wo das Kennzeichen sitzt. Die
  Kennzeichensuche (`--plate-search`) findet nur gut sichtbare Kennzeichen (im Test etwa jedes
  fünfte Auto) und ergänzt deshalb nur. Ein Kennzeichen an anderer Stelle (z. B. am Dach eines
  Wohnmobils) wird nur erfasst, wenn die Suche es findet.
- Ein Auto, das in einem Bild nicht erkannt wird, wird in diesem Bild nicht verpixelt. Die
  niedrigere Schwelle für Fahrzeuge (`--vehicle-threshold`) verringert das, schließt es aber nicht
  aus.

## Fehlersuche

| Meldung im Log | Ursache | Lösung |
|---|---|---|
| `privacy.detector_command is not set.` | `detector_command` ist `null` | Befehl in `config.json` eintragen |
| `Detector could not be started: …` | Python oder Skript nicht gefunden | Lauf aus dem Projektordner starten, `.venv` prüfen |
| `Detector failed with exit code …` | Modell fehlt, Paket fehlt oder Bild nicht lesbar | Installation prüfen (siehe oben), Meldung des Detektors im Log lesen |
| `Detector timed out after 120 s …` | Rechner überlastet | andere Läufe abwarten, Arbeitsspeicher prüfen |
| `privacy.blur.<Wert> must be …` | ungültiger Wert in `blur` | Wert laut Tabelle korrigieren |
| `No blurrable region left for …` | Detektor meldet eine Box außerhalb des Bildes | Detektor bzw. Modell prüfen |
| `Detector box for … has an invalid 'block'` bzw. `'label'` | Detektor liefert eine Blockgröße unter 1 oder ein Label, das kein Text ist | Detektor prüfen; mit dem mitgelieferten `detect.py` tritt das nicht auf |
| `privacy.ignore_top_share must be …`, `privacy.ignore_top_share_per_camera for … must be …` bzw. `privacy.ignore_boxes … invalid box` | Tippfehler in der Regel; sie hätte zu viel verworfen | Wert korrigieren (0 bis unter 0,5; Boxen `[x0, y0, x1, y1]` als ganze Zahlen). Der Reiter „Verpixelung“ lässt solche Werte nicht speichern; ein Fehler kommt hier nur aus einer von Hand bearbeiteten Datei |
| `privacy.min_person_score for … must be a number from 0 to 0.5` | Tippfehler; ein höherer Wert würde deutlich sichtbare Personen verwerfen | Wert korrigieren |
| `privacy.skip_labels for … may only list vehicle, plate` | leere Liste, Tippfehler oder `person` eingetragen | nur `vehicle` und/oder `plate` eintragen; Personen werden immer verpixelt |
| `Cannot read the size of …` | FFprobe liefert keine oder eine unerwartete Bildgröße (Bild beschädigt) | Bild prüfen; im Box-Job betrifft das nur dieses Bild, es wird jede Runde erneut versucht |

Ohne Logmeldung, beim Ansehen des Videos:

| Beobachtung | Ursache | Lösung |
|---|---|---|
| Kennzeichen knapp über dem verpixelten Bereich | Blickwinkel der Kamera: Kennzeichen sitzt höher im Fahrzeugkasten | `--vehicle-plate-share` erhöhen (heute `0.55`), nie den Bereich verschieben; Bildnummer notieren |
| Auto in einem Bild verpixelt, im nächsten nicht | Erkennungssicherheit schwankt von Bild zu Bild | `--vehicle-threshold` prüfen (`0.15`); Bildnummer notieren, Eintrag in der Statusdatei ansehen |
| Nur ein halbes Auto bzw. eine halbe Person verpixelt | früher: Kachelgrenze bei x = 768 (seit 2026-10-16 behoben, Kennung `-u2`) | betrifft nur Bilder, die vorher verpixelt wurden; ein neues Video ändert daran nichts (siehe unten) |
| Große Pixelfläche oben im Bild ohne Person | Fehlerkennung, z. B. Kamerahalterung | liegt sie überwiegend im oberen Drittel, verwirft `ignore_top_share` (bzw. der Wert der Kamera) sie; sonst als `ignore_boxes` eintragen, am bequemsten auf der Weboberfläche (Reiter Verpixelung, Rahmen auf dem Bild ziehen) |
| Boote, Anhänger oder Stege verpixelt, obwohl es dort keine Autos gibt | Detektor hält Boote auf Trailern für Fahrzeuge | Kamera in `skip_labels` mit `["vehicle", "plate"]` eintragen; gilt für Bilder, die danach verpixelt werden |
| Bootsplanen, Segelsäcke oder Winschen verpixelt | Detektor hält sie für Personen (meist geringe Sicherheit) | `min_person_score` für die Kamera setzen (SLSV: `0.35`); gilt für Bilder, die danach verpixelt werden; nimmt in Kauf, dass entfernte Personen unverpixelt bleiben |
| Auto zu grob verpixelt | `--vehicle-block-ratio` fehlt oder ist `0` | Wert `0.0133` setzen |

Eine geänderte Regel oder ein neuer Detektor wirkt nur auf Bilder, die danach verpixelt werden.
Schon verpixelte Bilder auf der Box bleiben so, auch bei einem neuen Video: Ein von Hand gestarteter
Lauf überspringt bestätigte Bilder. Das unverpixelte Original liegt in `<Kamera>/original/` auf der
Box; ein Werkzeug, das es zurücklegt und neu verpixelt, gibt es nicht.
