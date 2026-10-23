# Betrieb: Zeitplanung, Timelapse-Typen, Ablage und Protokolle

Wie die nächtlichen Läufe geplant sind, welche Videos entstehen, wo sie liegen, wann alte Videos gelöscht werden und wo die Protokolle stehen.


## Zeitplanung mit Cron

Die Zeitplanung erfolgt über Linux-Cron. Es gibt keinen internen Python-Scheduler.

### Nächtlicher Produktionslauf

Die installierte Crontab startet den vollständigen Workflow täglich um 02:00 Uhr:

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'
```

`flock -n` verwendet einen nicht blockierenden Lock. Läuft bereits ein Prozess mit demselben Lock, wird kein zweiter Produktionslauf gestartet.

### Wiederanlauf nach Neustart

Beim Booten wird der Workflow nur gestartet, wenn `state/run-in-progress` existiert. Da der Kamera-Storage eventuell noch nicht bereit ist, wartet Cron zunächst auf einen echten Mount unter `/mnt/cameras`:

```cron
@reboot if [ -f <projektpfad>/state/run-in-progress ]; then until mountpoint -q /mnt/cameras; do sleep 5; done; flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'; fi
```

Der nächtliche Lauf und die Reboot-Wiederherstellung verwenden beide:

```text
<projektpfad>/state/zeitraffer-run.lock
```

Dadurch können sie nicht überlappen. Es ist keine zusätzliche Cron-Logdatei konfiguriert; die Anwendung schreibt ihre eigenen Job-Logs.

### Highlights-Flagger (geplant)

Noch nicht eingerichtet. Der [Highlights-Flagger](flagger.md) soll direkt nach dem
nächtlichen Lauf starten, in derselben Zeile, aber außerhalb von `flock -c`: Er nimmt die Sperre
selbst und würde sonst an der von Cron scheitern.

```cron
0 2 * * * flock -n <projektpfad>/state/zeitraffer-run.lock -c 'cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.main'; cd <projektpfad> && <projektpfad>/.venv/bin/python3 -m src.flagger.run
```

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
- Mindestabdeckung: `min_coverage_days.yearly` (300 Tage, auch im Schaltjahr), automatisch und
  historisch; darunter wird die Kamera übersprungen, bevor die Frame-Auswahl läuft. Fehlende
  Tage fehlen im Video und werden als Bereiche geloggt.
- Framerate: `yearly_framerate`

## Kameraerkennung

### Dynamische Kameraerkennung

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

Ist der globale Kamera-Storage nicht erreichbar, wird der Lauf abgebrochen. Operative Fehler einer einzelnen Kamera werden dagegen pro Kamera behandelt, sodass spätere Kameras weiterverarbeitet werden können.

### Alternative Bildquelle (NAS-Archiv)

Die Umgebungsvariable `TIMELAPSE_CAMERA_ROOT` ersetzt `/mnt/cameras` als Kamera-Wurzel. Ohne
die Variable (oder mit leerem Wert) gilt weiterhin `/mnt/cameras`; Cron und Weboberfläche
setzen sie nicht.

Damit lassen sich Kalenderjahr-Videos aus dem alten Webcam-Archiv auf dem NAS erstellen. Die
Werkzeuge dafür liegen im Ordner `nas/` und gehören nicht zum Produktionslauf. Anleitung:
[docs/nas.md](nas.md).

Das Programm lässt sich auch in einem Docker-Container ausführen (auf einem Mac getestet; der
geplante Betrieb auf dem Synology-NAS ist eingestellt). Der Pi bleibt produktiv. Anleitung:
[docs/docker.md](docker.md).

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

Der Status ist absichtlich einfach: Es gibt keinen Resume-Punkt pro Kamera oder Job. Bei einer Wiederherstellung startet der komplette automatische Workflow erneut. Bereits vorhandene Videos werden durch atomaren Austausch geschützt, und Retention erfolgt erst nach erfolgreicher Neuerstellung.

Der Marker liegt unter `state/` und nicht unter `/tmp`, damit er einen Neustart überlebt.

Kameralokale operative Fehler werden innerhalb des jeweiligen Jobs behandelt und lassen spätere Kameras weiterlaufen. Ein nicht behandelter Prozessabbruch oder globaler Fehler nach dem Anlegen des Markers lässt ihn für die Reboot-Wiederherstellung bestehen.

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
└── flagger/YYYY-MM-DD.log
```

`filter` schreibt der [Speicherfilter](werkzeuge.md), `privacy` die
[Box-Verpixelung](verpixelung-box.md) und `flagger` der [Highlights-Flagger](flagger.md).

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
