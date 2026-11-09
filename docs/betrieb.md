# Betrieb: Zeitplanung, Timelapse-Typen, Ablage und Protokolle

Wie die nächtlichen Läufe geplant sind, welche Videos entstehen, wo sie liegen, wann alte Videos gelöscht werden und wo die Protokolle stehen.


## Zeitplanung mit Cron

Die Zeitplanung erfolgt über Linux-Cron. Es gibt keinen internen Python-Scheduler.

### Nächtlicher Produktionslauf

Die installierte Crontab verpixelt täglich um 02:00 Uhr zuerst die noch offenen Bilder der
letzten 48 Stunden ([Verpixelung auf der Storage Box](verpixelung-box.md)) und startet dann den
Nachtlauf. Danach lädt ein Skript die neuen Videos auf die Website hoch
([Upload auf die Website](#upload-auf-die-website)), und zuletzt folgt in derselben Zeile der
[Highlights-Flagger](#highlights-flagger):

```cron
0 2 * * * cd <projektpfad> && export TIMELAPSE_STORAGE_BOX=<ssh-alias> && flock -n <projektpfad>/state/zeitraffer-run.lock -c '<projektpfad>/.venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras --catch-up'; TIMELAPSE_X264_PRESET=medium <projektpfad>/scripts/timelapse-nightly-staged; /bin/bash <projektpfad>/scripts/copy_zeitraffer_videos_vps2siteground.sh --run >> <projektpfad>/logs/siteground-delivery.log 2>&1; TIMELAPSE_FRAME_SOURCE=ssh <projektpfad>/.venv/bin/python3 -m src.flagger.run
```

`./install.sh cron_hint` druckt diese Zeile. Der Upload-Schritt braucht die Zugangsdaten in
`config/siteground.env` (siehe [Upload auf die Website](#upload-auf-die-website)); `./install.sh
verify` warnt, wenn sie fehlen.

Der Wrapper `scripts/timelapse-nightly-staged` nimmt die Sperre selbst. (Der Name stammt aus der Zeit,
als er die Bilder vorher herüberkopierte; das tut er nicht mehr.) Er schreibt die Kameraliste der
Weboberfläche (`state/web-jobs/cameras.json`), startet `src.main` einmal für alle Kameras, das die Bilder
per ssh von der Storage Box liest, und prüft danach das Ergebnis: die Zusammenfassungszeilen der
Jobs, fehlgeschlagene Kameras aus dem Protokoll und jedes neue Video. Der Bericht steht in
`logs/nightly/<Lauf>/report.txt`. Ohne `TIMELAPSE_X264_PRESET` nimmt der Wrapper `ultrafast`; die
Cron-Zeile setzt `medium` (FFmpeg-Standard).

Schlägt das Nachholen der Verpixelung fehl, startet der Zeitraffer-Lauf trotzdem (`;`, nicht `&&`);
die Fehler stehen in `logs/privacy/`. Seit dem 23.10.2026 entstehen die Dailys der Kameras aus
`privacy.blur_cameras` damit aus verpixelten Bildern. Außerdem baut der Lauf die automatischen
Videos dieser Kameras nur aus Bildern, die der Box-Job bestätigt hat
([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)); im Code gilt das für das Daily seit
dem 05.11.2026, für Monthly und Yearly seit dem 09.11.2026.

`flock -n` verwendet einen nicht blockierenden Lock. Läuft bereits ein Prozess mit demselben Lock,
wird kein zweiter Produktionslauf gestartet; der Wrapper meldet das und endet mit Status 75.

### Wiederanlauf nach Neustart

Auf dem Server gibt es keine automatische Wiederholung nach einem Neustart: `install.sh` richtet
keine `@reboot`-Zeile ein. Der Marker `state/run-in-progress` (siehe
[Run-State und Wiederanlauf](#run-state-und-wiederanlauf)) bleibt bei einem Abbruch bestehen und
zeigt, dass ein Lauf unterbrochen wurde. Den Lauf startet man dann von Hand wie in der Cron-Zeile,
nachdem man mit `pgrep -af src.main` geprüft hat, dass nicht schon einer läuft.

Nachtlauf, Flagger, Weboberfläche und Speicherfilter verwenden dieselbe Sperre:

```text
<projektpfad>/state/zeitraffer-run.lock
```

Dadurch können sie nicht überlappen. Es ist keine zusätzliche Cron-Logdatei konfiguriert; die
Anwendung schreibt ihre eigenen Job-Logs.

### Upload auf die Website

Nach dem Nachtlauf lädt `scripts/copy_zeitraffer_videos_vps2siteground.sh` die fertigen Videos
per FTP in den Ordner der Website, den das WordPress-Plugin liest
([wordpress.md](wordpress.md#videos-auf-die-live-seite-bringen-welche-dateien-dürfen-raus)).
Welche Dateien dabei überhaupt in Frage kommen, bestimmt `scripts/list-deliverable-videos.py`.

```bash
scripts/copy_zeitraffer_videos_vps2siteground.sh [<Kamera>] [--run]
```

- Ohne `--run` ist es ein Trockenlauf: Es gibt keine Verbindung, nichts wird gesendet oder gelöscht.
- Ohne `<Kamera>` ruft sich das Skript einmal je Kamera der Liste selbst auf, jeweils mit eigener
  Sperre (nur im echten Lauf: `state/siteground-delivery-<Kamera>.lock`), eigener Ausgabe und
  eigenem Ergebnis. Eine fehlgeschlagene Kamera hält die anderen nicht auf.
- Eine Datei, die schon mit gleicher Größe auf der Website liegt, wird übersprungen. Alle anderen
  gehen zuerst unter einem versteckten Namen (`.<Name>.part`) hoch und werden erst danach auf den
  echten Namen umbenannt; fehlende Ordner legt das Skript an.
- Aufgeräumt wird je Kamera und Videotyp: Es bleiben die zwei neuesten Videos, das neueste und das
  vorherige. Das passiert nur, wenn in diesem Ordner weder eine Datei fehlt noch ein Upload oder
  Umbenennen fehlgeschlagen ist und wenn die Dateiliste der Website lesbar ist und die gerade
  gesendete Datei enthält. Nur fertige `.mp4`-Namen zählen.
- Eine leere Liste bricht ab: Es wird nichts gesendet und nichts gelöscht.
- Rückgabewerte bei einem Aufruf mit `<Kamera>`: `0` alles gut, `1` ein Upload ist fehlgeschlagen
  oder die Liste ist leer bzw. nicht erstellbar (auch fehlendes `curl` oder `flock`), `2` Aufruf oder
  Zugangsdaten falsch, `3` für diese Kamera läuft schon ein Lauf. Ohne `<Kamera>` (so ruft Cron es
  auf) endet das Skript mit `1`, sobald eine Kamera fehlgeschlagen ist, gleich mit welchem dieser
  Codes; die Ursache steht im Protokoll.
- Die Zugangsdaten stehen in `config/siteground.env` (nicht versioniert, je Zeile `NAME=Wert` für
  `SITEGROUND_HOST`, `SITEGROUND_USER`, `SITEGROUND_PASS`). Eine gleichnamige Umgebungsvariable hat
  Vorrang; `SITEGROUND_CONFIG` nennt eine andere Datei.
- Die Verbindung ist einfaches FTP (`ftp://`), also nicht verschlüsselt.
- Das Ergebnis steht je Kamera im Protokoll `logs/siteground-delivery.log` in der Zeile
  `Ergebnis: hochgeladen=… übersprungen=… fehlgeschlagen=… gelöscht=…`.

### Highlights-Flagger

Der [Highlights-Flagger](flagger.md) steht am Ende der 02:00-Zeile (siehe oben) und startet damit
erst, wenn der Nachtlauf mit allen Videos fertig ist, egal wie lange der dauert; eine feste
Uhrzeit gibt es nicht. Die Schritte sind mit `;` verbunden: Ein Fehler im einen Schritt hält den
nächsten nicht auf. Der Flagger nimmt die Sperre selbst, gehört also nicht in `flock -c`;
Arbeitsverzeichnis und `TIMELAPSE_STORAGE_BOX` stammen vom Anfang der Zeile (`cd`, `export`). Er
prüft den Vortag und braucht für fünf Kameras ca. 40 Minuten (gemessen auf dem früheren Host).

- Hält ein anderer Job die Sperre, wenn der Flagger startet (zum Beispiel ein Web-Auftrag),
  überspringt er die Nacht und schreibt nur `Skipped:` in `logs/flagger/`.
- Hängt der Nachtlauf, startet der Flagger gar nicht; das fällt am fehlenden Protokoll in
  `logs/flagger/` auf.
- Fehlende Tage lassen sich mit `--target-date` nachholen.

Installierte Einträge prüfen:

```bash
crontab -l
```

## Timelapse-Typen

### Daily

- Zieldatum: standardmäßig gestern
- optional: explizites Zieldatum über `--target-date`
- Quelle: Originalbilder
- Auswahl: Sunrise-/Sunset-Fenster inklusive Buffer für den Zieltag (automatisch nach Monat aus `automatic_daylight_buffer_minutes`, historisch fest aus `daylight_buffer_minutes`); der vollständige Vortag dient als Duplicate-Referenz
- Zieltag und Vortag werden in einem gemeinsamen Verzeichnis-Scan gefunden
- der Vortag dient ausschließlich als Duplicate-Referenz und wird nicht ins Daily übernommen
- Zieltag-Frames mit byte-identischem Inhalt vom Vortag werden ausgeschlossen
- spätere byte-identische Bilder innerhalb des Zieltags werden ebenfalls ausgeschlossen
- bleibt danach kein Zieltag-Frame übrig, wird die Kamera übersprungen und ein vorhandenes Video bleibt erhalten
- Kameras aus `privacy.blur_cameras` (automatischer Lauf): nur Bilder, die der Box-Job bestätigt hat
  ([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)); ist keines bestätigt, wird die
  Kamera übersprungen
- Framerate: `daily_framerate`
- Retention: exaktes rollierendes 7-Tage-Fenster relativ zum Zieldatum

### Weekly

- Fenster: exakt 7 Kalendertage inklusive Enddatum
- automatischer Lauf: vorhandene Daily-Videos, Enddatum standardmäßig gestern
- fehlende automatische Dailys werden protokolliert
- der automatische Lauf benötigt mindestens ein Daily und verwendet kein älteres Backfill
- historischer Lauf: Originalbilder für genau eine Kamera und explizites `--target-date`
- historische Auswahl: Sunrise bis Sunset inklusive Buffer für jeden einzelnen Tag
- byte-identische Bilder werden aus der historischen Frame-Sequenz gefiltert
- ein historisches Weekly erfordert vollständige Bildabdeckung an allen 7 Tagen
- keine automatische Retention für historische Weeklys

### Monthly

- Fenster: rollierende 30 Tage inklusive Enddatum
- Enddatum: standardmäßig gestern oder explizites `--target-date`
- Quelle: Originalbilder
- täglich 10:30 bis 13:30 Uhr (`interval_window`, historisch per `--window-time` /
  `--window-tolerance-minutes` verschiebbar)
- verwendet alle ausgewählten Intervallbilder
- filtert byte-identische Bilder innerhalb jedes einzelnen Tages
- Kameras aus `privacy.blur_cameras` (automatischer Lauf): nur bestätigte Bilder
  ([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)), und zwar vor der Mindestabdeckung:
  ein unbestätigtes Bild zählt nicht als Tag
- Mindestabdeckung: `min_coverage_days.monthly` (25 von 30 Tagen), automatisch und historisch;
  darunter wird die Kamera übersprungen. Ein Tag gilt als fehlend, wenn im gewählten Zeitfenster
  kein brauchbares Bild liegt. Fehlende Tage fehlen im Video und werden als Bereiche geloggt.
- Framerate: `monthly_framerate`

### Yearly

- Fenster: exaktes Kalenderjahr bis einschließlich Enddatum — 365 oder 366 Tage, je nachdem ob ein Schalttag (29. Februar) im Zeitraum liegt; kein fest codiertes 365-Tage-Fenster mehr
- Enddatum: standardmäßig gestern oder explizites `--target-date`
- Quelle: Originalbilder
- tägliche Kandidaten aus 10:30 bis 13:30 Uhr (`interval_window`, historisch verschiebbar)
- Zielzeit: 12:00 Uhr bzw. die Mitte des gewählten Fensters
- bis zu 5 eindeutige Frames pro Tag
- bei Duplikaten werden weitere Kandidaten nachgezogen
- Kameras aus `privacy.blur_cameras` (automatischer Lauf): nur bestätigte Bilder
  ([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)), und zwar vor der Mindestabdeckung
  und vor der Frame-Auswahl: ein unbestätigtes Bild zählt nicht als Tag und wird nie gewählt
- Mindestabdeckung: `min_coverage_days.yearly` (300 Tage, auch im Schaltjahr), automatisch und
  historisch; darunter wird die Kamera übersprungen, bevor die Frame-Auswahl läuft. Fehlende
  Tage fehlen im Video und werden als Bereiche geloggt.
- Framerate: `yearly_framerate`
- Wechselnde Bildgrößen: Wurde eine Kamera getauscht (Uferstrasse: 640×480, ab August 2026
  1920×1080), liegen Bilder zweier Größen in einem Video. Dann werden alle Bilder in die größte
  vorkommende Größe eingepasst, mit schwarzen Balken und ohne Verzerrung; das gilt für alle
  Videos aus Einzelbildern (Daily, Monthly, Yearly). Haben alle Bilder dieselbe Größe, ändert sich
  nichts. Weekly fügt fertige Tagesvideos zusammen und passt nichts an.

## Kameraerkennung

### Dynamische Kameraerkennung

Kameras werden dynamisch anhand der Ordner auf der Storage Box erkannt (bei einem Basisordner in
`TIMELAPSE_STORAGE_BOX` darunter).

Beispiel:

```text
<Storage Box>/
├── Alter-Winkel-Promenade/
├── BSV-Steinhude/
├── Nordufer_tele/
├── Nordufer_wide/
├── Scheunenviertel/
└── ...
```

Versteckte Verzeichnisse werden ignoriert.

Ist der globale Kamera-Storage nicht erreichbar, wird der Lauf abgebrochen. Operative Fehler einer einzelnen Kamera werden dagegen pro Kamera behandelt, sodass spätere Kameras weiterverarbeitet werden können.

### Alternative Bildquelle (NAS-Archiv)

Die Umgebungsvariable `TIMELAPSE_CAMERA_ROOT` ersetzt die Storage Box als Bildquelle: Ist sie
gesetzt, liest das Programm die Kameraordner von dort. Cron und Weboberfläche setzen sie nicht; ohne
sie und ohne `TIMELAPSE_STORAGE_BOX` bricht ein Lauf mit einer Fehlermeldung ab.

Damit lassen sich Kalenderjahr-Videos aus dem alten Webcam-Archiv auf dem NAS erstellen. Die
Werkzeuge dafür liegen im Ordner `nas/` und gehören nicht zum Produktionslauf. Anleitung:
[docs/nas.md](nas.md).

Der frühere Container-Test mit Docker liegt im Archiv ([archive/README.md](../archive/README.md)).

## Bildvalidierung und Duplikate

0-Byte-Dateien werden vor der weiteren Verarbeitung ausgeschlossen und geloggt. Die Quelldateien bleiben unverändert.

Abgeschnittene Bilder (Upload der Kamera mittendrin abgebrochen, JPEG-Endmarke `FF D9` fehlt) werden ebenfalls ausgelassen und als Warnung geloggt. Ohne diese Prüfung würde FFmpeg den fehlenden unteren Teil mit dem vorherigen Bild füllen. Yearly prüft das schon bei der Auswahl und nimmt stattdessen das nächstgelegene vollständige Bild desselben Tages, damit der Tag seine fünf Bilder behält. Alle Jobs prüfen außerdem jede Kopie in `temp/` vor dem Encodieren; dort fällt ein abgeschnittenes Bild ersatzlos weg. Gelesen wird dafür nichts zusätzlich von der Storage Box.

Die Duplicate-Behandlung hängt vom Job ab:

- Daily scannt Zieltag und Vortag gemeinsam. Byte-identische Zieltag-Frames, deren Inhalt an irgendeinem Zeitpunkt des Vortags vorhanden war, werden entfernt. Danach werden spätere Duplikate innerhalb des Zieltags entfernt.
- Historische Weeklys filtern byte-identische Frames einmal über die vollständige Sieben-Tage-Sequenz.
- Monthly filtert byte-identische Frames unabhängig innerhalb jedes Kalendertages. Gleicher Inhalt an unterschiedlichen Tagen bleibt erhalten.
- Yearly wählt pro Tag bis zu fünf inhaltlich eindeutige Frames aus.

Yearly behandelt Duplikate anders:

```text
Kandidat nahe 12:00
→ Hash prüfen
→ bereits gleicher Inhalt an diesem Tag?
   → ja: nächsten Kandidaten prüfen
   → nein: Frame übernehmen
→ bis zu 5 eindeutige Frames
```

Dadurch muss Yearly nicht mehr sämtliche Bilder eines ganzen Jahres vollständig hashen, bevor die eigentliche Auswahl stattfindet.

## Ausgabe- und Arbeitsverzeichnisse

### Automatische Videos

Automatische Ausgaben liegen unter:

```text
videos/<camera>/<job>/<camera>_<zieldatum>.mp4
```

Beispiele:

```text
videos/Scheunenviertel/daily/Scheunenviertel_2026-09-21.mp4
videos/Scheunenviertel/weekly/Scheunenviertel_2026-09-21.mp4
videos/Scheunenviertel/monthly/Scheunenviertel_2026-09-21.mp4
videos/Scheunenviertel/yearly/Scheunenviertel_2026-09-21.mp4
```

### Historische Ausgaben

Historische `--target-date`-Läufe und der `--date`-Alias werden getrennt von automatischen Ausgaben gespeichert:

```text
videos/<camera>/manual-runs/<job>/<camera>_<zieldatum>.mp4
```

Beispiele:

```text
videos/Scheunenviertel/manual-runs/daily/Scheunenviertel_2026-08-15_90min.mp4
videos/Scheunenviertel/manual-runs/weekly/Scheunenviertel_2026-08-15_90min.mp4
videos/Scheunenviertel/manual-runs/monthly/Scheunenviertel_2026-08-15.mp4
videos/Scheunenviertel/manual-runs/yearly/Scheunenviertel_2026-08-15.mp4
videos/Scheunenviertel/manual-runs/yearly/Scheunenviertel_2026-08-15_sunset-60min.mp4
```

Historische Daily- und Weekly-Videos tragen immer den Zeitpuffer als Suffix `_<N>min`
(30, 60 oder 90), damit Läufe mit verschiedenem Puffer sich nicht überschreiben. Monthly und
Yearly haben kein Suffix, außer bei einem abweichenden Zeitfenster (`--window-time` /
`--window-tolerance-minutes`): dann `_<HHMM|sunset>-<toleranz>min`. Mit `--blur-people` kommt
`_blur` dazu.

Historische Ausgaben werden von automatischer Retention nicht verändert.

### Temporäre Frames

Bildbasierte Jobs kopieren ausgewählte Quellen nach:

```text
temp/<camera>/<zieldatum>/frame_000001.jpg
temp/<camera>/<zieldatum>/frame_000002.jpg
...
```

Automatische Weeklys verwenden für die Concat-Datei:

```text
temp/<camera>/weekly/<enddatum>/concat.txt
```

Temporäre Arbeitsverzeichnisse werden erst nach erfolgreicher Videoerstellung entfernt. Bei einem Fehler bleiben sie für die Diagnose erhalten.

### Atomarer Austausch

FFmpeg schreibt im Zielverzeichnis zunächst nach:

```text
.<dateiname>.tmp.mp4
```

Nur ein erfolgreicher FFmpeg-Lauf ersetzt die endgültige MP4-Datei. Eine fehlgeschlagene Neuerstellung lässt das vorherige Video unverändert.

## Automatische Retention

| Job | Aufbewahrung |
|---|---|
| Daily | Exaktes rollierendes Fenster der letzten 7 Kalendertage relativ zum Zieldatum |
| Weekly | Nur das neueste erfolgreich erstellte automatische Weekly pro Kamera |
| Monthly | Nur das neueste erfolgreich erstellte automatische Monthly pro Kamera |
| Yearly | Nur das neueste erfolgreich erstellte automatische Yearly pro Kamera |

Retention läuft ausschließlich nach erfolgreicher Videoerstellung. Fehlende Daily-Tage werden nicht durch ältere Videos aufgefüllt. Historische Ausgaben unter `manual-runs/` sind ausgeschlossen.

## Run-State und Wiederanlauf

Nur der vollständige Produktionslauf ohne Argumente

```bash
python3 -m src.main
```

verwendet den persistenten Marker:

```text
state/run-in-progress
```

Ablauf nach erfolgreicher Konfigurations-, Logging- und Kamera-Storage-Prüfung:

```text
vollständiger Produktionslauf startet
→ state/run-in-progress wird angelegt

Daily → Weekly → Monthly → Yearly laufen durch
→ Marker wird nach Abschluss entfernt

Prozessabbruch, Stromausfall oder Neustart vor Abschluss
→ Marker bleibt bestehen
```

Explizite `--jobs`-, `--target-date`- und `--date`-Aufrufe erzeugen keinen Marker und gelten nicht als wiederaufzunehmender Produktionslauf.

Der Status ist absichtlich einfach: Es gibt keinen Resume-Punkt pro Kamera oder Job. Wird der Lauf von Hand wiederholt, startet der komplette automatische Workflow erneut. Bereits vorhandene Videos werden durch atomaren Austausch geschützt, und Retention erfolgt erst nach erfolgreicher Neuerstellung.

Der Marker liegt unter `state/` und nicht unter `/tmp`, damit er einen Neustart überlebt.

Kameralokale operative Fehler werden innerhalb des jeweiligen Jobs behandelt und lassen spätere Kameras weiterlaufen. Ein nicht behandelter Prozessabbruch oder globaler Fehler nach dem Anlegen des Markers lässt ihn bestehen, ein unterbrochener Lauf bleibt so erkennbar.

## Logging

Logs werden nach Job-Typ getrennt:

```text
logs/
├── daily/YYYY-MM-DD.log
├── weekly/YYYY-MM-DD.log
├── monthly/YYYY-MM-DD.log
├── yearly/YYYY-MM-DD.log
├── filter/YYYY-MM-DD.log
├── privacy/YYYY-MM-DD.log
├── flagger/YYYY-MM-DD.log
├── nightly/<Lauf>/report.txt
└── siteground-delivery.log
```

`filter` schreibt der [Speicherfilter](werkzeuge.md), `privacy` die
[Box-Verpixelung](verpixelung-box.md) und `flagger` der [Highlights-Flagger](flagger.md).
`nightly` enthält je Nachtlauf den Bericht des Wrappers (neben `report.txt` auch `main.out`), und
`siteground-delivery.log` das Protokoll des [Uploads auf die Website](#upload-auf-die-website).

Bei einer gezielten Job-Auswahl wird vor dem ersten ausgeführten Job direkt dessen Log aktiviert. Bei mehreren Jobs wird vor jedem weiteren Job auf das passende Log gewechselt.

Die Konsole erhält Meldungen ab INFO. Die Dateien enthalten zusätzlich DEBUG-Meldungen wie ausgewählte Bildgrenzen, temporäre Pfade, FFmpeg-Befehle, fehlende Datumsbereiche und Retention-Cleanup.

Jeder Prozess erhält eine Run-ID. Startmeldungen enthalten Run-ID, Ausführungsmodus und Kameraauswahl. Die Abschlussmeldung jedes Jobs enthält die Anzahl erstellter, übersprungener und fehlgeschlagener Kameras.

Fehlende Monthly- und Yearly-Tage werden als kompakte Datumsbereiche protokolliert. Duplicate-Filter melden die Anzahl ausgeschlossener Frames. Bei einem FFmpeg-Fehler werden die letzten 40 Zeilen der FFmpeg-Fehlerausgabe in das Anwendungslog übernommen.

Während FFmpeg läuft, werden Spitzenwerte für folgende Ressourcen erfasst:

```text
FFmpeg CPU
FFmpeg RAM
System CPU
System RAM
```

Auf Mehrkernsystemen kann die FFmpeg-CPU-Auslastung von `psutil` über 100 Prozent liegen. Hohe CPU-Auslastung allein bedeutet daher keinen fehlgeschlagenen Lauf.

Die Aufbewahrungsdauer wird über `log_retention_days` konfiguriert.

Operative Fehler wie

```text
OSError
TimeoutError
subprocess.CalledProcessError
```

werden pro Kamera behandelt.

Programmierfehler wie `TypeError` oder `AttributeError` werden nicht pauschal verschluckt.
