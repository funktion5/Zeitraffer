# Handbuch

Dieses Handbuch ist für alle, die Zeitraffer betreuen. Es zeigt, wie man das System installiert,
wie man jeden Job startet und was man bei Fehlern tut. Den Überblick gibt das
[README](../README.md). Die Details stehen in den anderen Dateien in diesem Ordner; das Handbuch
verlinkt dorthin, statt alles zu wiederholen.

In den Befehlen steht `~/timelapse` für den Projektordner. `<Kamera>` und `<Datum>` (JJJJ-MM-TT)
ersetzt man durch die echten Werte.

## Inhalt

- [Überblick](#überblick)
- [Installation](#installation)
- [Jobs starten](#jobs-starten)
- [Fehler: nächtlicher Lauf](#fehler-nächtlicher-lauf)
- [Fehler: Weboberfläche](#fehler-weboberfläche)
- [Fehler: Erkennung, Highlights und Verpixelung](#fehler-erkennung-highlights-und-verpixelung)
- [Fehler: Sicherung und Wiederherstellung](#fehler-sicherung-und-wiederherstellung)
- [Fehler: Entwicklung und CI](#fehler-entwicklung-und-ci)
- [Arbeitsspeicher](#arbeitsspeicher)

---

## Überblick

Seit dem 30.10.2026 läuft alles auf einem VPS (Debian 13). Der frühere Raspberry Pi ist
stillgelegt; was von ihm übrig ist, liegt im [Archiv](../archive/README.md).

### Was wann läuft

| Was | Wann | Wer startet es |
|---|---|---|
| Verpixelung neuer Bilder (prüft und markiert jedes Bild) | alle 5 Minuten, rund um die Uhr | Cron |
| Wächter der Verpixelung (meldet liegen gebliebene Bilder, ändert nichts) | alle 5 Minuten | Cron |
| Verpixelung nachholen (was in den letzten 48 Stunden liegen blieb) | 02:00 Uhr | Cron |
| Nächtlicher Lauf: Daily, Weekly, Monthly und Yearly für alle Kameras | direkt danach | Cron |
| Upload der Videos auf die Website ([betrieb.md](betrieb.md#upload-auf-die-website)) | direkt nach dem Nachtlauf | Cron |
| Highlights-Flagger | direkt nach dem Upload, also ohne feste Uhrzeit | Cron |
| Videos für vergangene Zeiträume | bei Bedarf | Weboberfläche oder Befehl |
| Verpixelung für ein von Hand gestartetes Video einer Blur-Kamera | automatisch bei jedem solchen Video; dauert deutlich länger | Weboberfläche oder Befehl |
| Speicherfilter, Yearly-Backfill, NAS-Werkzeuge, Sicherung | bei Bedarf | Befehl |

Die vier 02:00-Schritte stehen in einer einzigen Cron-Zeile und laufen nacheinander.

### Wo was liegt

| Was | Wo |
|---|---|
| Kamerabilder (Originale, **nur lesen**) | Storage Box. Die Jobs kopieren die Bilder, die sie brauchen, per rsync nach `temp/frame-cache/` |
| Einstellungen | `config/config.json` enthält die Standardwerte (in git). Was in der Weboberfläche geändert wird, steht darüber in `config/settings.json` (Reiter „Allgemein“) und `config/settings-privacy.json` (Reiter „Verpixelung“). Beide Dateien sind nicht in git und gelten nur für diesen Host |
| Liste der Blur-Kameras des Abholjobs der Website (**zweite Konfiguration**) | `webcam_list.config` auf dem Server, auf dem das Abholskript der Website läuft (der genaue Pfad steht im Skript). Nicht in diesem Repository. Muss dieselben Kameras enthalten wie unsere Liste, siehe [Blur-Kamera hinzufügen oder entfernen](#blur-kamera-hinzufügen-oder-entfernen) |
| Nächtliche Videos | `videos/<Kamera>/{daily,weekly,monthly,yearly}/` |
| Videos aus Weboberfläche und Befehl | `videos/<Kamera>/manual-runs/<job>/` |
| Highlights | `videos/<Kamera>/highlights/<Datum>/` |
| Protokolle | `logs/<job>/<Datum>.log`, z. B. `logs/daily/` oder `logs/flagger/`. Verpixelung und Wächter: `logs/privacy/<Datum>.log` |
| Bericht des Nachtlaufs | `logs/nightly/<Lauf>/report.txt`, die volle Ausgabe in `logs/nightly/<Lauf>/main.out` |
| Protokoll des Uploads auf die Website | `logs/siteground-delivery.log` (enthält den FTP-Zugang, nicht weitergeben) |
| Protokoll der gespeicherten Einstellungen | `logs/settings.log` |
| Laufsperre | `state/zeitraffer-run.lock` |
| Sperre der Box-Verpixelung | `state/privacy-blur.lock` |
| Status der Box-Verpixelung | `state/privacy/box/<Kamera>/<JJJJ-MM>.jsonl` |
| Marker „nächtlicher Lauf unterbrochen“ | `state/run-in-progress` |
| Status der Web-Aufträge | `state/web-jobs/` |
| Kameraliste der Weboberfläche | `state/web-jobs/cameras.json` |
| Zwischendateien | `temp/` |
| Installierte Web-Wrapper | In `/usr/local/sbin/`: `timelapse-web-trigger` (Video-Auftrag starten), `timelapse-web-rebuild` (automatische Videos einer Kamera neu erstellen), `timelapse-web-publish` (Videos einer Kamera hochladen), `timelapse-web-delete` (Video löschen), `timelapse-web-delete-highlight` (Highlight-Bild löschen), `timelapse-web-settings` (Einstellungen speichern), `timelapse-web-preview` (Vorschaubild einer Blur-Kamera holen). In `/usr/local/libexec/`: `timelapse-web-worker`, `timelapse-web-worker-rebuild`, `timelapse-web-worker-publish`, `timelapse-web-status.sh` |
| Apache-Fehlerprotokoll | `/var/log/apache2/zeitraffer-error.log` |

### Grundregeln

- **Immer nur ein Lauf auf einmal.** Nachtlauf, Web-Aufträge (auch der Upload über die
  Weboberfläche), Flagger, Speicherfilter, Backfill und das nächtliche Nachholen der Verpixelung
  teilen sich eine Sperre: `state/zeitraffer-run.lock`. Wer sie nicht bekommt, bricht ab oder
  überspringt. Die Verpixelung alle 5 Minuten hat ihre eigene Sperre (`state/privacy-blur.lock`)
  und läuft deshalb auch neben einem Zeitraffer-Lauf.
- **Auch die Verpixelungs-Sperre teilen sich drei:** die Runde alle 5 Minuten, das Nachholen um
  02:00 und die Verpixelung eines von Hand gestarteten Videos. Daraus folgt:
  - Läuft gerade eine Runde, scheitert ein von Hand gestartetes Video einer Blur-Kamera mit „Gerade
    läuft eine andere Verpixelung. Bitte später noch einmal versuchen.“ Einfach kurz warten.
  - Solange ein von Hand gestartetes Video verpixelt (bis zu einer Stunde), fallen die Runden aus
    (`Skipped` im Protokoll). Der Wächter warnt dann, und die Website bekommt so lange keine neuen
    Bilder der Blur-Kameras.
  - Um 02:00 starten Runde und Nachholen gleichzeitig. Gewinnt die Runde, fällt das Nachholen in
    dieser Nacht aus (`Skipped`); die Runden arbeiten den Rest danach ab.
- **Von Hand gestartete Videos von Blur-Kameras dauern lange.** Sie verpixeln vorher ihre Bilder
  auf der Storage Box und halten so lange die Laufsperre (gemessen: ein Monatsvideo mit rund 350 Bildern
  brauchte 55 Minuten). Läuft so ein Auftrag über 02:00 hinaus, fällt der Nachtlauf aus.
- **Die Originalbilder nie ändern.** Die Zeitraffer-Jobs lesen sie nur. Die einzige Ausnahme ist
  die Verpixelung: Sie sichert das Original und ersetzt es dann durch die verpixelte Fassung. Außerdem
  schreibt sie die Markierung `blur:checked=true` (21 Bytes, kein Pixel ändert sich): die Runde in
  jedes geprüfte Bild, ein von Hand gestartetes Video nur in Bilder von heute und den zwei Tagen
  davor. Bilder ohne Person bekommen die Markierung ohne Sicherung
  ([verpixelung-box.md](verpixelung-box.md#markierung-für-die-webseite)).
- **Die Blur-Kameras stehen in zwei Listen, und beide müssen gleich sein:** unsere (Reiter
  „Verpixelung“) und `webcam_list.config` beim Abholjob der Website. Wer die eine ändert, ändert die
  andere sofort mit ([Blur-Kamera hinzufügen oder entfernen](#blur-kamera-hinzufügen-oder-entfernen)).
- **„Erfolgreich“ heißt nicht „alle Kameras“.** `src.main` endet auch dann mit Exit-Code 0, wenn
  Kameras gefehlt haben. Der Nachtlauf-Wrapper prüft das und endet dann mit 1. Verlässlich ist nur
  die Zusammenfassung am Ende jedes Jobs (siehe unten).
- **Die Web-Wrapper laufen aus installierten Kopien.** Eine Änderung unter `scripts/` wirkt erst,
  wenn sie neu installiert ist ([Installation](installation.md#wrapper-installieren)).
- **Ein Neustart von Apache bricht einen laufenden Web-Auftrag ab.** Vorher mit
  `pgrep -af timelapse-web-worker` nachsehen, ob einer läuft.

### Läuft gerade etwas?

```bash
cd ~/timelapse
flock -n state/zeitraffer-run.lock -c true && echo "Sperre frei" || echo "Sperre belegt"
pgrep -af "src.main|src.flagger|storage_filter|yearly-backfill|blur_box|blur_watch|timelapse-web-worker"
```

`blur_box --all-blur-cameras` (ohne `--catch-up`) und `blur_watch` tauchen alle 5 Minuten kurz
auf. Das ist die Verpixelung mit ihrem Wächter; sie blockieren keinen Zeitraffer-Lauf.

### Zusammenfassung eines Laufs lesen

Jeder Job endet mit einer Zeile wie dieser:

```text
2026-10-22 02:05:21,134 | INFO | Daily timelapse job finished for 2026-10-21 | created=10 | skipped=4 | failed=0 | run_id=20261022T020002-1278463
```

- `created`: neue Videos.
- `skipped`: Kameras ohne genug Bilder. Meist harmlos (siehe unten).
- `failed`: Kameras mit einem echten Fehler. Hier lohnt sich ein Blick ins Protokoll.

Alle Zusammenfassungen von heute auf einmal:

```bash
grep -h "job finished" ~/timelapse/logs/*/$(date +%F).log
```

---

## Installation

Die Kurzfassung als Checkliste; alle Schritte im Detail stehen in [installation.md](installation.md).

Auf einem frischen Debian- oder Ubuntu-Host erledigt `install.sh` schon einiges: die Schritte 1, 2
und 7, die Dateirechte und die leere Login-Datei für den Upload. Liegt eine Sicherung bereit,
spielt es auch Modell, Status und Videos zurück (Schritt 3). Von Hand bleiben der Zugang zur
Storage Box (Schritt 5) und Cron (Schritt 6), beschrieben in [vps.md](vps.md).

| # | Schritt | Klappt, wenn |
|---|---|---|
| 1 | Systempakete installieren ([Installation](installation.md#systempakete-installieren)) | `ffmpeg -version`, `php -v` und `rsync --version` antworten |
| 2 | Python 3.13 und virtuelle Umgebung ([Installation](installation.md#python-umgebung-einrichten)) | `.venv/bin/python3 --version` zeigt 3.13 |
| 3 | Erkennungsmodelle nach `models/` ([verpixelung.md](verpixelung.md#installation)) | `ls models/` zeigt `object_detection_yolox_2022nov.onnx` |
| 4 | `config/config.json` anpassen ([Konfiguration](konfiguration.md)) | `.venv/bin/python3 -m pytest tests/config_test.py` ist grün |
| 5 | Zugriff auf die Storage Box einrichten ([Installation](installation.md#zugriff-auf-die-storage-box)) | `TIMELAPSE_STORAGE_BOX=storagebox .venv/bin/python3 -m src.camera_list` listet die Kameras |
| 6 | Cron eintragen ([Installation](installation.md#cron-installieren-oder-prüfen)) | `crontab -l` zeigt drei Zeilen: die 02:00-Zeile (Verpixelung nachholen, Nachtlauf, Upload, Flagger) und die beiden 5-Minuten-Zeilen (Verpixelung und Wächter). `./install.sh cron_hint` druckt alle drei ([betrieb.md](betrieb.md#nächtlicher-produktionslauf)) |
| 7 | Apache, Anmeldung, Wrapper, Dateirechte ([Installation](installation.md#weboberfläche-einrichten)) | `curl -s -o /dev/null -w '%{http_code}' http://localhost:<Port>/` ergibt `401`, und `./install.sh verify` zeigt kein `WARNING` (es prüft nur, repariert nichts) |
| 8 | Tests | `.venv/bin/python3 -m pytest` ist grün |
| 9 | Ersten Lauf von Hand starten (siehe unten) | `logs/daily/<Datum>.log` endet mit einer Zusammenfassung mit `created` > 0 |

---

## Jobs starten

Alle Befehle laufen im Projektordner (`cd ~/timelapse`). Vorher kurz prüfen, ob schon etwas läuft
([Läuft gerade etwas?](#läuft-gerade-etwas)).

Ein langer Lauf soll weiterlaufen, auch wenn man das Terminal schließt? Dann abgekoppelt starten:

```bash
setsid nohup <befehl> > logs/manuell-$(date +%F_%H%M).out 2>&1 < /dev/null &
kill -TERM -- -<PID>      # so beendet man ihn wieder (PID aus pgrep)
```

### Nächtlicher Lauf

Jeder Befehl liest die Bilder per ssh von der Storage Box. Dafür muss `TIMELAPSE_STORAGE_BOX`
gesetzt sein. Die Cron-Zeilen tun das selbst; in der Shell einmal
`export TIMELAPSE_STORAGE_BOX=<ssh-alias>` eingeben.

Andere Bildquellen:

- `TIMELAPSE_CAMERA_ROOT` liest die Bilder aus einem lokalen Ordner, zum Beispiel aus dem
  NAS-Archiv ([nas.md](nas.md)).
- `TIMELAPSE_FRAME_SOURCE` (`local` oder `ssh`) erzwingt eine der beiden Quellen.
- Ist weder `TIMELAPSE_STORAGE_BOX` noch `TIMELAPSE_CAMERA_ROOT` gesetzt, bricht jeder Befehl mit
  einer Fehlermeldung ab.

Cron startet den Lauf um 02:00 Uhr (die Zeile steht in
[betrieb.md](betrieb.md#nächtlicher-produktionslauf)). Von Hand startet man ihn über denselben
Wrapper wie Cron. Er nimmt die Sperre selbst, baut alle vier Videoarten für alle Kameras mit
gestern als Zieltag und prüft danach das Ergebnis:

```bash
setsid -f env TIMELAPSE_X264_PRESET=medium scripts/timelapse-nightly-staged > ~/nightly-console.log 2>&1 < /dev/null
cat logs/nightly/$(ls -t logs/nightly | head -1)/report.txt   # die letzten Zeilen nennen Kameras und Fehler
```

Nur `src.main`, ohne die Prüfung durch den Wrapper:

```bash
flock -n state/zeitraffer-run.lock -c '.venv/bin/python3 -m src.main'
```

### Einzelne Jobs und vergangene Zeiträume

```bash
.venv/bin/python3 -m src.main --jobs daily weekly                                # nur diese automatischen Jobs
.venv/bin/python3 -m src.main --jobs daily --target-date <Datum> --cameras <Kamera>
.venv/bin/python3 -m src.main --jobs weekly --target-date <Datum> --cameras <Kamera>   # genau eine Kamera
.venv/bin/python3 -m src.main --jobs monthly --target-date <Datum> --window-time sunset --window-tolerance-minutes 60
```

Videos mit `--target-date` landen in `videos/<Kamera>/manual-runs/` und werden nie automatisch
gelöscht. Alle Optionen und welche Kombinationen nicht erlaubt sind: [cli.md](cli.md).

### Über die Weboberfläche

- **Video bestellen:** Kamera wählen, Videotyp und Zieldatum eintragen (vorbelegt ist gestern),
  dann „Video erstellen“. Der Button bleibt gesperrt, bis der Auftrag fertig ist. Ein Fenster meldet
  das Ergebnis, bei einem Fehlschlag mit dem Grund, wenn er bekannt ist. Der Auftrag schreibt in
  dasselbe Protokoll wie der passende Befehl.
- **Nächtliche Videos:** Sie stehen auf der Kameraseite in der Liste „Automatische Videos“ zum
  Ansehen und Herunterladen. Löschen lassen sie sich dort nicht.
- **Automatische Videos neu erstellen und hochladen:** Die aufklappbare Leiste auf der Kameraseite
  baut die Nachtjobs einer Kamera neu und überträgt sie danach auf die Website, etwa nach einem
  Kameraausfall ([weboberflaeche.md](weboberflaeche.md#neu-erstellen-wie-der-nachtlauf)).
- **Einstellungen:** Die Seite „Einstellungen“ ändert einen Teil der Werte aus `config.json`, ohne
  dass man eine Datei anfassen muss (Reiter „Allgemein“ und „Verpixelung“).

Mehr dazu: [weboberflaeche.md](weboberflaeche.md).

### Highlights-Flagger

```bash
.venv/bin/python3 -m src.flagger.run                                               # Kameras aus der Config, gestern
.venv/bin/python3 -m src.flagger.run --cameras <Kamera> --target-date <Datum>
tail -f logs/flagger/$(date +%F).log                                               # Fortschritt
```

Ein neuer Lauf für denselben Tag ersetzt dessen Ordner. Vorher gelöschte Bilder sind danach wieder
da. Details: [flagger.md](flagger.md).

### Verpixelung

- **Im Normalbetrieb muss man nichts tun.** Cron startet die Verpixelung und den Wächter alle
  5 Minuten und das Nachholen um 02:00 (`./install.sh cron_hint` druckt die Zeilen). Ob sie läuft,
  zeigt das Protokoll: Alle 5 Minuten kommt pro Kamera eine Zeile `[<Kamera>] blurred=… clean=… …`
  und vom Wächter `Stale check: … nothing stale`.

  ```bash
  tail -n 20 logs/privacy/$(date +%F).log
  ```

- **Von Hand gestartete Videos einer Blur-Kamera** (Weboberfläche oder `--target-date`) verpixeln
  ihre Bilder selbst. Dafür gibt es keinen Schalter
  ([verpixelung-box.md](verpixelung-box.md#verpixelung-bei-von-hand-gestarteten-videos)). Den
  Fortschritt zeigt `tail -f logs/<job>/$(date +%F).log`: Die Zeile `Blur:` nennt die Zahl der
  Bilder, jede Zeile `Replaced` ist ein verpixeltes Bild. Bilder ohne Person erscheinen nicht
  einzeln. Von Hand gestartete Videos markieren nur Bilder von heute und den zwei Tagen davor.
- **Direkt auf der Storage Box** verpixelt
  `.venv/bin/python3 -m src.privacy.blur_box --cameras <Kamera>`. Das schreibt auf die Box, also
  vorher [verpixelung-box.md](verpixelung-box.md) lesen. Mit `--catch-up` (45 Minuten pro Kamera)
  holt es alle offenen Bilder der letzten 48 Stunden in einem Lauf nach, so wie nachts.
- **Ist ein Bild markiert?** Das geht auch mit dem öffentlichen Bild auf der Website:

  ```bash
  head -c 32 <bild>.jpg | grep -a 'blur:checked=true'
  ```

#### Blur-Kamera hinzufügen oder entfernen

Welche Kameras verpixelt werden, steht an **zwei** Stellen. Beide Listen müssen immer dieselben
Kameras enthalten, mit genau denselben Ordnernamen wie auf der Storage Box (Groß- und
Kleinschreibung zählt).

1. **Unsere Liste:** der Reiter „Verpixelung“ der Weboberfläche (`privacy.blur_cameras`,
   gespeichert in `config/settings-privacy.json`, Standard in `config/config.json`). Sie bestimmt,
   wo die Runde verpixelt und markiert.
2. **Die Liste des Abholjobs:** `webcam_list.config` auf dem Server, auf dem das Abholskript der
   Website läuft (der genaue Pfad steht im Skript). Eine Zeile pro Kamera, `#` leitet einen
   Kommentar ein. Sie bestimmt, bei welchen Kameras die Website **nur markierte** Bilder
   veröffentlicht. Die Datei liegt nicht in diesem Repository. So ändert man sie: per ssh auf
   diesem Server anmelden, die Datei im Editor öffnen, die Zeile ergänzen oder löschen, speichern.
   Der nächste Lauf des Abholskripts liest sie neu.

Eine Änderung ist erst fertig, wenn beide Listen geändert sind. Sonst passiert Folgendes:

| Die Kamera steht nur … | Folge |
|---|---|
| in unserer Liste | Die Website prüft die Markierung nicht. Sie kann ein Bild **unverpixelt** veröffentlichen, bevor die Runde es getauscht hat (Datenschutz) |
| in `webcam_list.config` | Kein Bild der Kamera wird mehr markiert. Die Website zeigt dauerhaft das letzte markierte Bild und bekommt kein neues |

Die Reihenfolge verhindert, dass ein unverpixeltes Bild durchrutscht:

- **Hinzufügen:** erst unsere Liste speichern. Warten, bis im Protokoll die erste Zeile
  `[<Kamera>] blurred=… clean=…` steht. Dann die Kamera in `webcam_list.config` eintragen.
  Dazwischen zeigt die Website schlimmstenfalls ein paar Minuten lang ungeprüfte Bilder, wie bisher.
- **Entfernen:** erst aus `webcam_list.config` löschen, dann aus unserer Liste.

### Werkzeuge

```bash
.venv/bin/python3 -m src.storage.storage_filter --cameras <Kamera>          # listet leere und doppelte Bilder, löscht nichts
```

Ein Jahresvideo für ein Kalenderjahr einer Kamera auf der Storage Box: in den Einstellungen
„Jahresvideo: mindestens so viele Tage mit Bildern“ auf 1 setzen, einen manuellen Yearly mit
Zieldatum 31.12. starten und den Wert danach mit „Standard“ zurücksetzen (er gilt auch für den
Nachtlauf). Für das NAS-Archiv gibt es `nas/yearly-backfill.py`.

Details: [werkzeuge.md](werkzeuge.md); NAS-Archiv: [nas.md](nas.md).

### Sicherung

Die Sicherung läuft auf dem eigenen Rechner (macOS oder Linux), im Repository-Ordner. `BACKUP_HOST`
ist der ssh-Alias des Hosts, den man sichert:

```bash
BACKUP_HOST=<ssh-alias> ./backup.sh              # models/, state/, Einstellungsdateien, crontab.txt
BACKUP_HOST=<ssh-alias> VIDEOS=1 ./backup.sh     # zusätzlich videos/
```

Die Sicherung landet in `~/timelapse-backup`. Drin sind das Erkennungsmodell, der Status (auch der
der Verpixelung), die beiden Einstellungsdateien `config/settings.json` und
`config/settings-privacy.json`, die Crontab (nur zum Nachlesen) und mit `VIDEOS=1` die Videos. Geheimnisse sind
nicht drin: Die Anmeldung der Weboberfläche legt `install.sh` neu an, das Passwort für den Upload
trägt man von Hand ein. Wie man die Sicherung auf einem neuen Host einspielt
(`./install.sh restore`): [vps.md](vps.md).

---

## Fehler: nächtlicher Lauf

### Heute Nacht lief nichts, es gibt kein Protokoll

**Symptom:** `logs/daily/<heute>.log` fehlt, und in `videos/<Kamera>/daily/` gibt es kein Video
von gestern.

**Prüfen:**

```bash
crontab -l                                   # ist die 02:00-Zeile da?
uptime                                       # lief der Rechner um 02:00?
flock -n ~/timelapse/state/zeitraffer-run.lock -c true && echo frei || echo belegt
pgrep -af "src.main|src.flagger|storage_filter|yearly-backfill|blur_box|blur_watch|timelapse-web-worker"
```

**Ursache:** Die Sperre war um 02:00 belegt, von einem Web-Auftrag, dem Flagger, dem
Speicherfilter oder einem hängenden Lauf. Dann fällt das Nachholen der Verpixelung ohne Meldung
aus, und der Nachtlauf-Wrapper endet sofort mit Exit-Code 75. Seine Meldung
(`Another timelapse run holds state/zeitraffer-run.lock.`) geht nur an Cron; einen Ordner unter
`logs/nightly/` legt er dann nicht an. Ob der Flagger danach lief, zeigt
`grep Skipped logs/flagger/<heute>.log`. Seltener fehlt die Crontab, oder der Rechner war aus.

**Lösung:** Den blockierenden Prozess abwarten oder beenden, dann den
[Lauf von Hand starten](#nächtlicher-lauf). Fehlt die Crontab, sie wie in der
[Installation](installation.md#cron-installieren-oder-prüfen) beschrieben wieder eintragen.

### Kamera-Speicher nicht erreichbar

**Symptom:** Gleich am Anfang des Protokolls steht `Failed to access camera storage.`, und es
entsteht kein einziges Video. Dazu kommt einer dieser Fehler:

- ein `OSError`, zum Beispiel `Storage box listing failed ...` oder `TIMELAPSE_STORAGE_BOX is not set`
- ein `ValueError`: `No frame source configured: set TIMELAPSE_CAMERA_ROOT ... or TIMELAPSE_STORAGE_BOX ...`

**Prüfen:**

```bash
ssh <ssh-alias> ls | head -3                                                      # antwortet die Box?
TIMELAPSE_STORAGE_BOX=<ssh-alias> .venv/bin/python3 -m src.camera_list           # listet die Kameras
```

**Ursache:** Eine dieser Ursachen:

- Netzwerk oder Storage Box sind nicht erreichbar.
- Schlüssel oder Host-Key passen nicht mehr (`Permission denied`, `Host key verification failed`).
- Der Eintrag in `~/.ssh/config` fehlt.
- `TIMELAPSE_STORAGE_BOX` ist nicht gesetzt, in der Cron-Zeile oder in der Shell.

**Lösung:** Die ssh-Verbindung von Hand testen und den Eintrag samt Schlüssel in `~/.ssh/config`
richten ([Installation](installation.md#zugriff-auf-die-storage-box), [vps.md](vps.md)). Meldet ssh
einen geänderten Host-Key (`REMOTE HOST IDENTIFICATION HAS CHANGED`), erst den Fingerabdruck mit
der Hetzner-Oberfläche vergleichen. Dann den alten Eintrag löschen und beim nächsten `ssh` den neuen
bestätigen. Die Storage Box nutzt einen eigenen Port, deshalb mit Klammern:
`ssh-keygen -R '[<box-host>]:<box-port>'` (Host und Port zeigt `ssh -G <ssh-alias>`). Danach den
Lauf von Hand starten.

### Bildsuche bricht ab („stalled“)

**Symptom:** Im Protokoll steht `TimeoutError: ... stalled for camera: <Kamera>`. Diese Kamera
fehlt, die anderen laufen weiter.

**Prüfen:** wie bei [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar), dazu:

```bash
time ssh <ssh-alias> ls <Kamera> | wc -l     # ein Ordner mit rund 190.000 Dateien braucht einige Sekunden
```

**Ursache:** Die Storage Box antwortet für diesen Ordner nicht rechtzeitig: Netzwerk, überlastete
Box oder sehr viele Dateien. Damit der Lauf nicht ewig hängt, bricht er die Suche ab, wenn
`image_scan_stall_timeout_seconds` lang nichts vorangeht. Einen fehlgeschlagenen rsync beim
Holen der Bilder wiederholt das Programm nach 30 und nach 120 Sekunden.

**Lösung:** Verbindung prüfen und die Kamera mit `--target-date` nachholen. Passiert es bei einer
Kamera immer wieder, mit dem [Speicherfilter](werkzeuge.md) nachsehen, ob ihr Ordner ungewöhnlich
voll ist.

### Eine Kamera hat keine Bilder

**Symptom:**

```text
WARNING | Found 0 images - skipping camera.
WARNING | No recognized image files available.
WARNING | Available image range: 2026-09-14 - 2026-10-02
```

**Prüfen:**

```bash
ssh <ssh-alias> ls -t <Kamera> | head -5     # die neuesten Dateien auf der Storage Box
```

**Ursache:** Die Kamera lädt nichts hoch (offline, Strom, Netz, Speicherkarte), oder ihre Dateien
haben ein unbekanntes Namensformat. `Available image range` zeigt, bis wann zuletzt Bilder kamen.

**Lösung:** Das ist kein Programmfehler; die Kamera oder ihren Upload prüfen. Ist die Kamera
dauerhaft außer Betrieb, sie in `ignored_cameras` eintragen. Dateien mit unbekanntem Namen errät
das Programm nie, es lässt sie weg.

**Unlesbare Dateinamen:** Kann der Daily bei einer Kamera Datum oder Uhrzeit aus Dateinamen nicht
lesen, steht im Log `[<Kamera>] <n> of <gesamt> image names cannot be read, e.g. <Datei>` und im
Bericht des Nachtlaufs (`report.txt`) unter der Kamera `WARNING: <n> image names cannot be read`. Die
Nacht gilt trotzdem als erfolgreich, denn Daily und Weekly können noch entstehen; Monthly, Yearly und
der Flagger lassen diese Bilder aber weg. Das Beispiel im Log ansehen: Ist es eine neue Schreibweise
für Datum oder Uhrzeit, braucht sie einen neuen Baustein in `src/images.py`
([architektur.md](architektur.md#srcimagespy)).

### Kamera nicht gefunden oder ungültiger Name

**Symptom:** Einer dieser Fälle:

- `ERROR | Requested cameras not found: <Name>`: Der Befehl bricht ab, bevor ein Video entsteht.
- Eine neue Kamera taucht weder im Nachtlauf noch in der Weboberfläche auf.
- `WARNING | Skipping unsafe name on the storage box (camera listing): '<Name>'` oder
  `(camera <Kamera>): '<Datei>'`.

**Prüfen:**

```bash
TIMELAPSE_STORAGE_BOX=<ssh-alias> .venv/bin/python3 -m src.camera_list   # welche Namen kennt das Programm?
ssh <ssh-alias> ls                                                         # welche Ordner liegen auf der Box?
```

**Ursache:**

- `Requested cameras not found`: Der Name in `--cameras` passt nicht genau zu einem Ordner auf der
  Storage Box. Groß- und Kleinschreibung zählt (`SLSV`, nicht `slsv`), oder die Kamera steht in
  `ignored_cameras`.
- Ein Kameraordner darf nur Buchstaben, Ziffern, `.`, `_` und `-` enthalten und muss mit einem
  Buchstaben oder einer Ziffer beginnen. Ein Ordner mit Leerzeichen oder Umlaut (`Café Ufer`)
  wird übersprungen; das Programm nimmt solche Namen aus Sicherheitsgründen nie in ssh- oder
  rsync-Befehle.
- Eine einzelne Datei mit seltsamem Namen (Steuerzeichen, `/`, beginnt mit `-`) wird ebenfalls
  übersprungen. Der Rest der Kamera läuft normal weiter.

**Lösung:** Den Namen genau so schreiben, wie `src.camera_list` ihn zeigt. Einen Kameraordner mit
ungültigem Namen auf der Storage Box umbenennen lassen (und den Upload der Kamera mit). Einzelne
übersprungene Dateien sind harmlos; häufen sie sich, den Upload der Kamera prüfen.

### Monats- oder Jahresvideo übersprungen

**Symptom:**

```text
WARNING | Monthly coverage too low: 18 of 30 days available (minimum 25) - skipping camera: Strandallee
WARNING | Yearly coverage partial: 331 of 365 days available (minimum 300) | missing: 2026-02-03 to 2026-02-12
WARNING | No valid Monthly images available - skipping camera: <Kamera>
```

**Ursache:** Ein Monatsvideo braucht Bilder an mindestens 25 von 30 Tagen, ein Jahresvideo an
300 Tagen (`min_coverage_days`), jeweils im Mittagsfenster.

- „partial“: Das Video entsteht, die genannten Tage fehlen darin.
- „too low“: Es entsteht kein Video, das alte bleibt stehen.
- „No valid Monthly images“: Im ganzen Monat gab es im Mittagsfenster kein einziges brauchbares
  Bild (Kamera aus, nur leere Dateien oder eine falsche Uhrzeit im Dateinamen). Es entsteht kein
  Video.

Beim [Yearly-Backfill](werkzeuge.md) heißen die Meldungen `No valid Yearly images for <Jahr>` bzw.
`No Yearly images selected for <Jahr>`; sie bedeuten dasselbe für ein ganzes Kalenderjahr.

**Lösung:** Meist nichts tun: Das Video entsteht wieder, sobald genug Tage da sind. Ein
Jahresvideo trotz Lücken baut der [Yearly-Backfill](werkzeuge.md). Kommt „No valid Monthly images“
öfter, die Bilder der Kamera um die Mittagszeit ansehen (Uhrzeit im Dateinamen falsch? nur leere
Dateien?).

### Wochenvideo mit fehlenden Tagen

**Symptom:**

```text
WARNING | Missing Daily video: videos/BSV-Steinhude/daily/BSV-Steinhude_2026-10-18.mp4
WARNING | Weekly will be created with 5 of 7 Daily videos.
WARNING | No Daily videos available - skipping Weekly for camera: Bootshaus
```

Bei einem von Hand gestarteten Weekly (`--target-date`):

```text
WARNING | Missing Weekly image date: 2026-10-18
WARNING | Weekly image coverage incomplete: 6 of 7 days available - skipping camera: <Kamera>
```

**Ursache:**

- Das **nächtliche** Wochenvideo setzt die Tagesvideos der letzten 7 Tage zusammen. Fehlt ein
  Tagesvideo (Kamera ohne Bilder, Lauf ausgefallen), fehlt der Tag auch in der Woche.
- Ein **von Hand gestartetes** Weekly baut aus den Bildern selbst und braucht alle 7 Tage. Fehlt
  einer, entsteht kein Video.

**Lösung:** Das nächtliche Weekly nimmt nur Videos aus `videos/<Kamera>/daily/`. Nachträglich
gebaute Tagesvideos landen in `manual-runs/` und zählen dort nicht mit. Für eine vollständige
Woche ein Weekly von Hand bauen:
`--jobs weekly --target-date <letzter Tag> --cameras <Kamera>`. Meldet das „incomplete“, fehlen
an dem genannten Tag wirklich Bilder; dann eine Woche wählen, in der alle Tage da sind.

### Leere oder abgeschnittene Bilder

**Symptom:**

```text
WARNING | Camera SKM-Mardorf: excluded 6 empty image files
WARNING | Skipping truncated image (no JPEG end marker): temp/frame-cache/<Lauf>/Uferstrasse/uferstrasse_….jpg
```

**Ursache:** Der Upload der Kamera brach ab: Die Datei hat 0 Byte oder kein JPEG-Ende. Das Programm
lässt solche Bilder weg. Sonst landete ein halbes Bild mit dem grauen Rest im Video.

**Lösung:** Nichts tun, solange es vereinzelt bleibt. Häuft es sich bei einer Kamera, ihren Upload
prüfen. Der [Speicherfilter](werkzeuge.md) listet alle betroffenen Dateien.

### FFmpeg: `Permission denied`

**Symptom:**

```text
Error opening output files: Permission denied
ERROR | FFmpeg failed with exit code 243:
ERROR | Failed to process timelapse for camera: SKM-Mardorf
```

**Prüfen:**

```bash
ls -ld ~/timelapse/videos ~/timelapse/videos/<Kamera> ~/timelapse/videos/<Kamera>/*/
```

**Ursache:** Ein Ordner unter `videos/` gehört nicht dem Projektbenutzer, etwa weil jemand Videos
als `root` kopiert oder einen Befehl mit `sudo` gestartet hat.

**Lösung:**

```bash
sudo chown -R "$(id -un):$(id -gn)" ~/timelapse/videos   # Eigentümer zurück auf den Projektbenutzer
~/timelapse/install.sh permissions verify                  # Leserechte für www-data setzen, dann prüfen
```

`permissions` allein reicht nicht: Es ändert nur die Rechte, nicht den Eigentümer. Danach die
Kamera mit `--target-date` nachholen. Und: Läufe nie mit `sudo` starten.

### Video wirkt gestaucht oder hat schwarze Balken

**Symptom:** Ein Video ist gestaucht, oder die Bilder haben ab einem bestimmten Datum schwarze
Balken. Im Protokoll steht `Frames of 2 different sizes (640x480, 1920x1080): fitting every frame
into 1920x1080`.

**Prüfen:**

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 <Video>.mp4
```

**Ursache:** Die Kamera wurde getauscht, und die neuen Bilder haben eine andere Größe (Uferstrasse:
640×480 bis August 2026, danach 1920×1080). FFmpeg nimmt die Größe des ersten Bildes und streckt
alle anderen darauf. So wirkte ein Jahresvideo über den Wechsel hinweg gestaucht.

Seit dem 30.10.2026 passt das Programm bei Daily, Monthly und Yearly alle Bilder in die größte
vorkommende Größe ein. Das Seitenverhältnis bleibt, schwarze Balken füllen den Rest. Die alten
4:3-Bilder bekommen also Balken links und rechts und sind etwas weicher, weil sie vergrößert
werden. Haben alle Bilder dieselbe Größe, ändert sich nichts.

**Lösung:** Meist nichts tun. Die Balken sind gewollt und verschwinden von selbst, sobald die alten
Bilder aus dem Zeitraum fallen (beim Yearly nach 365 Tagen). Ein Video, das vor dem 30.10.2026
entstanden ist, bleibt gestaucht, bis es neu gebaut wird; das nächtliche Yearly ersetzt sich
selbst.

**Bekannte Lücke:** Das Weekly setzt fertige Tagesvideos zusammen und passt nichts an. Liegt ein
Kamerawechsel in den 7 Tagen, kann es gestaucht sein.

### Videodateien zu groß oder Qualität nicht gut genug

**Hintergrund:** Die Qualität steuert der CRF-Wert von x264: niedriger heißt besser und größer,
höher heißt kleiner. Seit dem 30.10.2026 ist der Standard **28** (`timelapse.crf` in
`config/config.json`). An einem Jahresvideo (Uferstrasse) gemessen ist die Datei damit rund 53 %
kleiner als mit CRF 23 (9,9 statt 21,2 MiB), ohne sichtbaren Mangel.

**Lösung:** Für dauerhaft `timelapse.crf` ändern (ganze Zahl von 0 bis 51). Für einen einzelnen
Lauf den Wert vor den Befehl setzen:

```bash
TIMELAPSE_X264_CRF=23 .venv/bin/python3 -m src.main --jobs yearly --target-date <Datum> --cameras <Kamera>
```

Ein ungültiger Wert bricht das Encodieren ab, und es entsteht kein Video. Die Meldung lautet
`TIMELAPSE_X264_CRF must be a whole number from 0 to 51` (bzw. `timelapse.crf must be ...`). Die
Änderung gilt nur für neue Videos. `TIMELAPSE_X264_PRESET` ändert dagegen Laufzeit,
Speicherbedarf und Größe, nicht den CRF-Wert ([Konfiguration](konfiguration.md#umgebungsvariablen)).

### Festplatte voll

**Symptom:** FFmpeg meldet `No space left on device`, oder Python `OSError: [Errno 28]`.

**Prüfen:**

```bash
df -h ~/timelapse
du -sh ~/timelapse/videos/*/manual-runs ~/timelapse/temp ~/timelapse/logs | sort -h | tail
```

**Ursache:** Meist liegen viele Videos in `manual-runs/` (sie werden nie automatisch gelöscht),
oder ein abgebrochener Lauf hat Reste in `temp/` hinterlassen.

**Lösung:** Alte Videos über die Weboberfläche löschen. Ordner in `temp/` darf man löschen, wenn
kein Lauf aktiv ist. Danach die betroffenen Kameras nachholen.

### Lauf meldet Erfolg, aber Kameras fehlen

**Symptom:** Der Lauf endet ohne Fehler, trotzdem fehlen Videos.

**Prüfen:** die Zusammenfassungen lesen (`grep -h "job finished" logs/*/<Datum>.log`). Steht bei
`failed=` mehr als 0, die Zeilen mit `ERROR` und den Traceback davor lesen.

**Ursache:** Fehler einer einzelnen Kamera (Zugriff auf die Storage Box, FFmpeg, Dateirechte)
fängt das Programm ab, damit die anderen Kameras weiterlaufen. Der Exit-Code von `src.main` bleibt
deshalb 0. Der Nachtlauf-Wrapper meldet es trotzdem: mit Exit-Code 1 und im Bericht.

**Lösung:** Die Ursache aus dem Traceback beheben (siehe die Fälle oben) und die Kamera nachholen.

### Lauf wurde nach einem Neustart nicht wiederholt

**Symptom:** Der Server ist mitten im Lauf neu gestartet. Die Videos dieser Nacht fehlen, und es
startet kein zweiter Lauf.

**Ursache:** Das ist so gewollt: `install.sh` legt keine `@reboot`-Zeile an. Der Marker
`state/run-in-progress` bleibt liegen und zeigt, dass ein Lauf unterbrochen wurde.

**Lösung:** Mit `pgrep -af src.main` prüfen, dass nichts läuft, dann den Lauf von Hand wiederholen
([Nächtlicher Lauf](#nächtlicher-lauf)). Startet der Rechner immer wieder neu, den Arbeitsspeicher
prüfen ([Arbeitsspeicher](#arbeitsspeicher)).

---

## Fehler: Weboberfläche

### Anmeldung klappt nicht

**Symptom:** Der Browser fragt immer wieder nach Benutzername und Passwort.

**Lösung:** Das Passwort neu setzen:

```bash
sudo htpasswd -B /etc/apache2/.htpasswd <login>
```

`-B` speichert es mit bcrypt. **Kein `-c`:** Das legt die Datei neu an und löscht alle anderen
Logins ([Installation](installation.md#basisauthentifizierung-einrichten)).

### `403 Forbidden`

**Prüfen:** `tail /var/log/apache2/zeitraffer-error.log`. Typisch ist
`AH00035: ... search permissions are missing on a component of the path`.

**Ursache:** `www-data` kommt nicht mehr in den Projektordner, etwa nach einer Neuinstallation oder
nachdem jemand Dateien von Hand kopiert hat.

**Lösung:** `~/timelapse/install.sh permissions verify`.

- `permissions` setzt die Leserechte für `www-data` neu (nur die Rechte, nicht den Eigentümer).
- `verify` repariert nichts. Es prüft danach alles, meldet jedes Problem als `WARNING`, führt dabei
  die Tests aus und fragt nach dem `sudo`-Passwort.

### Kameraliste leer

**Prüfen:** `cat state/web-jobs/cameras.json` als Projektbenutzer. Fehlt die Datei oder steht nur
`[]` darin, kennt die Weboberfläche keine Kamera.

**Ursache:** Die Liste schreibt der Nachtlauf, außerdem `.venv/bin/python3 -m src.camera_list`.
Eine leere Liste schreiben beide nie: Klappt das Auflisten nicht, melden sie
`Camera list not updated: …` und lassen die alte Datei stehen. Leer ist die Seite deshalb nur in
zwei Fällen:

- Die Liste wurde noch nie geschrieben.
- Alle Kameras stehen in `ignored_cameras`.

Zeigt die Seite eine alte Liste (eine neue Kamera fehlt), war die Storage Box beim letzten Versuch
nicht erreichbar.

**Lösung:** Die Storage Box prüfen ([Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar))
und die Liste einmal von Hand schreiben:

```bash
TIMELAPSE_STORAGE_BOX=<ssh-alias> .venv/bin/python3 -m src.camera_list
```

Fehlt nur eine bestimmte Kamera, siehe
[Kamera nicht gefunden oder ungültiger Name](#kamera-nicht-gefunden-oder-ungültiger-name).

### „Es läuft bereits ein anderer Zeitraffer-Auftrag.“

**Ursache:** Die gemeinsame Sperre ist belegt: vom Nachtlauf, vom Flagger, vom Speicherfilter, vom
Backfill oder von einem anderen Web-Auftrag.

**Lösung:** [Nachsehen, was läuft](#läuft-gerade-etwas), abwarten und dann erneut starten.

### „Video erstellen“ ist grau

**Ursache:** In diesem Browser-Tab läuft noch ein Auftrag; die Statuszeile über dem Formular nennt
ihn. Der Button wird wieder frei, sobald das Ergebnisfenster erscheint.

**Lösung:** Abwarten. Hängt es, siehe [Auftrag scheint zu hängen](#auftrag-scheint-zu-hängen). Ein
Auftrag, dessen Worker nie gestartet ist, gilt nach einer Minute als fehlgeschlagen.

### „Das Löschen hat nicht geklappt. Bitte die Seite neu laden.“

**Ursache:** Die Löschanfrage kam nicht an, oder die Antwort war unbrauchbar: Netz weg, Sitzung
abgelaufen oder ein Fehler auf dem Server. Andere Gründe, etwa „Die Anfrage ist ungültig
(Sicherheitstoken).“, stehen direkt im Bestätigungsdialog.

**Lösung:** Seite neu laden und noch einmal löschen. Scheitert es wieder:
`tail /var/log/apache2/zeitraffer-error.log`.

### „Der Videoauftrag konnte nicht gestartet werden.“

**Prüfen:**

```bash
sudo -l -U www-data                                    # Regeln für trigger, rebuild, publish, delete und delete-highlight?
cmp scripts/web/timelapse-web-trigger /usr/local/sbin/timelapse-web-trigger
tail /var/log/apache2/zeitraffer-error.log
```

**Ursache:** Eine dieser Ursachen:

- Die sudoers-Regel fehlt.
- Der installierte Wrapper fehlt oder ist veraltet.
- Der Projektordner gehört `root`. Dann verweigert die Seite den Start absichtlich.

**Lösung:** Wrapper und sudoers neu einrichten, wie in der
[Installation](installation.md#wrapper-installieren) beschrieben.

### „Der Videoauftrag wurde abgelehnt oder konnte nicht gestartet werden.“

**Prüfen:**

```bash
grep -E "(Video|Rebuild|Publish) wrapper failed with exit code" /var/log/apache2/zeitraffer-error.log | tail -3
```

`Video` steht für das historische Video, `Rebuild` für das Neuerstellen, `Publish` für den Upload.

**Ursache:** Der Wrapper lief, hat den Auftrag aber abgelehnt. Der Exit-Code sagt warum:

| Code | Bedeutung | Lösung |
|---|---|---|
| 66 | Die Kamera steht nicht in der Kameraliste `state/web-jobs/cameras.json` | [Kameraliste leer](#kameraliste-leer) |
| 64 | Ungültige Eingabe (Datum, Job, Zeitfenster oder Zahl der Argumente) | prüfen, ob installierter Wrapper und Weboberfläche zusammenpassen (`cmp` wie oben) |
| 69 | Worker oder Status-Hilfsskript unter `/usr/local/libexec/` fehlt | die Wrapper neu installieren |

### „Videoerstellung fehlgeschlagen“

**Symptom:** Das Abschlussfenster meldet „… konnte nicht erstellt werden.“ Bekannte Gründe nennt es
selbst, zum Beispiel „Zu wenige Tage mit Bildern im Zeitfenster: 21 von 30 (mindestens 25).“ Sonst
steht dort „Bitte das Anwendungsprotokoll prüfen.“

**Prüfen:**

- `state/web-jobs/<id>.reason`: die Warnung, aus der der Grund stammt.
- `logs/<job>/<heute>.log`, dort die Zeilen zur gewählten Kamera. Das Protokoll trägt das Datum des
  Auftrags, nicht das Zieldatum.

**Ursache:** Fast immer zu wenige Bilder. Die Kamera hatte an dem Tag keine Bilder, Monat oder Jahr
liegen unter der Mindestabdeckung, oder einem historischen Weekly fehlt einer der 7 Tage (alle 7
sind Pflicht). Der Auftrag gilt als fehlgeschlagen, sobald kein neues Video entsteht.

Bei einer Blur-Kamera gibt es zwei weitere Gründe:

- „Gerade läuft eine andere Verpixelung. Bitte später noch einmal versuchen.“: Eine Runde oder ein
  anderer Auftrag verpixelt gerade. Ein paar Minuten warten und neu starten.
- „Von N Bildern sind M noch nicht verpixelt …“: Ein Teil der Bilder ließ sich in diesem Lauf nicht
  verpixeln. Den Auftrag noch einmal starten; er macht dort weiter.

**Lösung:** Ein anderes Datum, Fenster oder einen anderen Videotyp wählen. Sonst den Fehler wie
beim [nächtlichen Lauf](#fehler-nächtlicher-lauf) suchen.

### „Neu erstellen“: Ergebniszeile mit „übersprungen“ oder „fehlgeschlagen“

**Symptom:** Der Abschlussdialog „Neu erstellen abgeschlossen“ zeigt zum Beispiel
`Monatlich: 0 erstellt, 1 übersprungen, 0 fehlgeschlagen`. Der Status ist trotzdem
„abgeschlossen“; er sagt nur, dass `src.main` ohne Fehler endete.

**Prüfen:** `state/web-jobs/<id>.result` (dieselben Zeilen) und `logs/<job>/<heute>.log`, dort die
Zeilen zur Kamera. Das Protokoll trägt das Datum des Auftrags.

**Ursache:**

- **Übersprungen:** zu wenige Tage mit Bildern (Monthly mindestens 25 von 30, Yearly 300), keine
  Bilder an dem Tag, oder bei einer Blur-Kamera kein bestätigt verpixeltes Bild
  ([Sperre](verpixelung-box.md#sperre-in-automatischen-videos)).
- **Fehlgeschlagen:** ein Fehler bei dieser Kamera (Bildabruf, FFmpeg, Zeitüberschreitung). Die
  Stelle steht im Protokoll.

**Lösung:** Bei einer Blur-Kamera warten, bis die Verpixelung die Bilder geprüft hat (neue Bilder
nach wenigen Minuten, Älteres spätestens beim Nachholen um 02:00), dann neu erstellen. Sonst den
Fehler wie beim [nächtlichen Lauf](#fehler-nächtlicher-lauf) suchen. Ein übersprungenes Video lässt
das vorhandene stehen.

### Hochladen schlägt fehl

**Symptom:** Der Dialog meldet „Hochladen fehlgeschlagen“ („Bitte das Anwendungsprotokoll
prüfen.“), oder die Ergebniszeile zeigt bei `fehlgeschlagen` mehr als 0, zum Beispiel
`Hochgeladen: 2, übersprungen: 0, fehlgeschlagen: 1, gelöscht: 0`.

**Prüfen:**

- `tail -n 60 ~/timelapse/logs/siteground-delivery.log`. **Achtung:** Die ausführliche Ausgabe
  enthält den FTP-Zugang; nichts davon weitergeben.
- `./install.sh verify` zeigt, ob die drei `SITEGROUND_*`-Werte gesetzt sind.

**Ursache:**

- **Ohne Ergebniszeile:** Die Zugangsdaten fehlen (Exit 2), die Liste der Videos ist leer, oder für
  diese Kamera läuft schon ein Upload, zum Beispiel der nächtliche (Exit 3).
- **Mit Ergebniszeile:** Eine Datei fehlte oder ließ sich nicht hochladen oder umbenennen
  (FTP-Fehler). In diesem Ordner wird dann auch nicht aufgeräumt.

**Lösung:** Fehlende Zugangsdaten in `config/siteground.env` eintragen. Lief schon ein Upload,
danach erneut starten. Bei FTP-Fehlern später noch einmal versuchen. Mehr zum Skript:
[Upload auf die Website](betrieb.md#upload-auf-die-website).

### Auftrag scheint zu hängen

**Prüfen:**

```bash
ls -l ~/timelapse/state/web-jobs/                       # <id>.pid, <id>.status, <id>.reason
pgrep -af "src.main"
```

**Ursache:** Entweder rendert er noch, oder der Prozess ist gestorben. Einen toten Prozess meldet
die Seite bei der nächsten Abfrage als fehlgeschlagen, ebenso einen Auftrag, der nach einer Minute
noch keine `.pid` hat.

**Lösung:** Läuft `src.main` noch, abwarten. Wurde Apache zwischendurch neu gestartet, ist der
Auftrag abgebrochen; dann neu starten.

### Löschen schlägt fehl

**Symptom:** „Das Video konnte nicht gelöscht werden.“ bzw. „Das Bild konnte nicht gelöscht
werden.“

**Prüfen:** `sudo -l -U www-data` muss `timelapse-web-delete` bzw. `timelapse-web-delete-highlight`
zeigen. Details stehen im Apache-Fehlerprotokoll.

**Lösung:** Den fehlenden Wrapper und die sudoers-Zeile ergänzen
([Installation](installation.md#wrapper-installieren)).

### „Die Anfrage ist ungültig (Sicherheitstoken).“

**Ursache:** Die Sitzung ist abgelaufen (nach 24 Minuten ohne Aktivität).

**Lösung:** Seite neu laden und erneut absenden.

### Einstellungen lassen sich nicht speichern

**Symptom:** Auf der Seite „Einstellungen“ wird nichts gespeichert, und oben steht eine Meldung.

| Meldung | Ursache | Lösung |
|---|---|---|
| „Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden.“ | Jemand anderes hat im selben Reiter gespeichert, seit die Seite geladen wurde | Seite neu laden und die eigene Änderung erneut eintragen |
| Meldung mit dem Namen eines Feldes (Wert „muss …“) | Der Wert liegt außerhalb der Grenzen; gespeichert wurde nichts | Wert korrigieren. Die Grenzen stehen in der Meldung und in [konfiguration.md](konfiguration.md#einstellungen-der-weboberfläche) |
| „Mindestens eine Kamera muss angehakt bleiben.“ | Alle Kameras sind abgewählt | mindestens eine ankreuzen |
| „Unter „Kameras“ abgewählt, unter „Highlights“ aber noch angehakt: …“ | Die Kamera wird nicht mehr verarbeitet, steht aber noch bei den Highlights. Dann würde der Flagger für keine Kamera mehr starten | die Kamera unter „Highlights“ ebenfalls abwählen |
| „Die Einstellungen konnten nicht gespeichert werden.“ | Der Wrapper lief nicht oder ist gescheitert | siehe unten |
| „Bitte die Änderungen bestätigen.“ (Verpixelung) | Der Bestätigungsdialog wurde umgangen, oder ohne JavaScript fehlt das Kästchen | erneut speichern und im Dialog „Ja, speichern“ wählen |

**Prüfen (bei „konnten nicht gespeichert werden“):** `sudo -l -U www-data` muss
`timelapse-web-settings` zeigen. Im Apache-Fehlerprotokoll steht
`Settings wrapper failed with exit code <N>`:

- 64: falsche Eingabe oder zu langer Text.
- 69: Die Python-Umgebung unter `~/timelapse/.venv` fehlt.
- 1: Das Schreiben ist gescheitert.

Die Fälle „Wert ungültig“ und „inzwischen geändert“ aus der Tabelle stehen nicht im Protokoll;
die Seite zeigt sie direkt an.

Scheitert das Schreiben selbst, prüfen, ob der Projektbenutzer in `config/` schreiben darf.

**Lösung:** Wrapper und sudoers-Zeile ergänzen ([Installation](installation.md#wrapper-installieren))
oder mit `./install.sh web_bridge` neu installieren (nur, wenn kein Auftrag läuft).

**Gespeichert, aber ohne Wirkung?**

- Die Werte gelten ab dem **nächsten** Auftrag. Ein laufender Auftrag hat seine Einstellungen
  schon gelesen.
- Bei einer Blur-Kamera wirken Streifen, Schwellen und Rahmen nur auf Bilder, die danach verpixelt
  werden.
- Ein Wert in `config.json` wirkt nicht, solange derselbe Schlüssel in `config/settings.json` oder
  `config/settings-privacy.json` steht: Die Einstellungsdatei gewinnt. Den Wert auf der Seite
  zurücksetzen oder den Schlüssel aus der Datei löschen.
- Was wann gespeichert wurde, zeigt `logs/settings.log`: eine Zeile je Speicherung, mit altem und
  neuem Wert.

### Das Vorschaubild fehlt oder lässt sich nicht aktualisieren

**Symptom:** Im Reiter „Verpixelung“ fehlt bei einer Kamera das Bild, oder „Vorschau
aktualisieren“ meldet einen Fehler.

| Meldung | Ursache | Lösung |
|---|---|---|
| „Für diese Kamera gibt es noch kein geprüftes Bild.“ | Die Verpixelung hat noch kein Bild dieser Kamera geprüft, etwa weil sie gerade erst angehakt wurde | nach der nächsten Runde (5 Minuten) erneut versuchen. Die Zahlenfelder für Rahmen gehen auch ohne Bild |
| „Diese Kamera wird nicht verpixelt.“ | Die Kamera steht nicht in der gespeicherten Liste der Blur-Kameras | erst speichern, dann aktualisieren |
| „Die Speicherbox hat nicht rechtzeitig geantwortet.“ | Der Wrapper hat nach 90 Sekunden abgebrochen | später erneut versuchen; die Verbindung zur Storage Box prüfen ([Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar)) |
| „Das Bild konnte nicht geholt werden.“ | Der Wrapper fehlt oder ist gescheitert, die Box antwortet nicht, oder das Bild ist beschädigt | Apache-Fehlerprotokoll: `Preview wrapper failed with exit code <N>`. `sudo -l -U www-data` muss `timelapse-web-preview` zeigen. Im Anwendungsprotokoll nach `Preview failed` oder `not fit to show` suchen |

Ein Bild, das PHP nicht als JPEG in sinnvoller Größe lesen kann, wird nie angezeigt. Dann steht dort
„noch kein Bild“, bis ein brauchbares Bild kommt. Das Vorschaubild ist immer eins, das die
Verpixelung schon geprüft hat, nie ein Rohbild.

### Änderungen an einem Wrapper wirken nicht

**Ursache:** Apache ruft die installierten Kopien unter `/usr/local/` auf, nicht die Dateien in
`scripts/`.

**Lösung:** Den geänderten Wrapper mit `sudo install` neu installieren
([Installation](installation.md#wrapper-installieren)), oder alle auf einmal mit
`./install.sh web_bridge` (nur, wenn kein Auftrag läuft).

---

## Fehler: Erkennung, Highlights und Verpixelung

Flagger und Verpixelung nutzen dasselbe Erkennungsmodell: YOLOX, abgelegt in `models/` und
ausgeführt mit `onnxruntime`.

### Modelldatei fehlt

**Symptom:** `Flagger not started: model file missing: models/object_detection_yolox_2022nov.onnx`.
Auch die Verpixelung kann ohne Modell nichts prüfen: Die Runde meldet je Bild
`Not processed, retrying next round: …`, der Wächter warnt, und ein von Hand gestartetes Video
einer Blur-Kamera scheitert. Ungeprüfte Bilder gibt sie nie frei.

**Lösung:** `models/` aus der Sicherung zurückspielen (`./install.sh restore`) oder das Modell neu
herunterladen ([verpixelung.md](verpixelung.md#installation)). Die Sicherung ist besser: Mit
derselben Datei bleiben zwischengespeicherte Ergebnisse gültig.

### Modell lässt sich nicht laden

**Prüfen:**

```bash
.venv/bin/python3 -c "import onnxruntime, cv2; print(onnxruntime.__version__, cv2.__version__)"
```

**Ursache:** `onnxruntime` oder OpenCV fehlen in der virtuellen Umgebung oder passen nicht zur
Plattform. Seltener ist die Modelldatei beschädigt.

**Lösung:** `.venv/bin/python3 -m pip install -r requirements.txt`. Die Modelldatei mit der aus der
Sicherung vergleichen: `sha256sum models/*.onnx`.

### Erkennung liegt falsch

**Symptom:** Die Highlights zeigen Unsinn (ein Busch als „Giraffe?“, ein Kondensstreifen als
„Drachen?“) oder übersehen Tiere. Oder die Verpixelung trifft Schilder und übersieht Personen.

**Ursache:** YOLOX kennt Alltagsdinge, aber keine Rehe, Schwäne oder Ballons, und bei kleinen,
fernen Objekten rät es. Einzelne Fehltreffer sind normal.

**Lösung:**

- **Flagger:** Feststehende Objekte filtert er selbst. Die Schwellen und diesen Filter in
  `src/flagger/groups.py` nur mit echten Beispielbildern ändern ([flagger.md](flagger.md)).
- **Verpixelung:** Bekannte Fehlerkennungen ausschließen. Am einfachsten geht das im Reiter
  „Verpixelung“ der Weboberfläche: Rahmen auf das Kamerabild ziehen, oberen Rand und
  Mindest-Sicherheit je Kamera einstellen. Von Hand geht es über `ignore_boxes`,
  `ignore_top_share`, `skip_labels` und `min_person_score`
  ([verpixelung.md](verpixelung.md#ignore_boxes-ignore_top_share-skip_labels-und-min_person_score)).

### Ein feststehendes Objekt wird immer wieder verpixelt

**Symptom:** Auf der Storage Box ist bei einer Kamera in vielen Bildern dasselbe Objekt verpixelt
(Beispiel vom 23.10.2026: die Ankerkette vor dem Gebäude bei Scheunenviertel).

**Ursache:** Der Detektor hält das Objekt für eine Person, meist mit niedriger Sicherheit
(0,25 bis 0,6). Weil es sich nicht bewegt, trifft es jedes Mal dieselbe Stelle.

**Prüfen:** Welche Boxen immer wieder an derselben Stelle auftauchen, steht in der Statusdatei:

```bash
grep -h '"status": "blurred"' state/privacy/box/<Kamera>/*.jsonl | head -3
```

Jede Box ist `[x0, y0, x1, y1, Sicherheit, Label]`, in Pixeln des Originalbilds.

**Lösung:** Die wiederkehrenden Stellen als `ignore_boxes` der Kamera eintragen:

- **Auf der Weboberfläche:** im Reiter „Verpixelung“ mit „Rahmen bearbeiten“ ein Rechteck über die
  Stelle ziehen und speichern ([weboberflaeche.md](weboberflaeche.md#reiter-verpixelung-verpixelungphp)).
  Die Rahmen landen in `config/settings-privacy.json`.
- **Von Hand:** in `config/config.json`.

Beides wirkt ab dem nächsten Lauf, ohne Neustart. Eine Box wird nur verworfen, wenn sie fast
deckungsgleich mit einem Rahmen ist: Schnittfläche geteilt durch Gesamtfläche mindestens 0,5. Den
Rahmen deshalb eng um das Objekt ziehen. Eine kleine Person in einem großen Rahmen bleibt
verpixelt.

**Mit Claude (empfohlen):** In einer Claude-Sitzung im Projekt etwa so beauftragen:

> Bei `<Kamera>` wird `<Objekt>` (`<wo im Bild>`) fälschlich verpixelt. Werte die Boxen in
> `state/privacy/box/<Kamera>/` aus, prüfe an einem Original aus `original/` auf der Box, dass es
> das Objekt ist und keine Person, und schlage `ignore_boxes` vor. Zeig, wie viele der bisherigen
> Treffer sie verwerfen und welche echten Personen bleiben.

Claude wertet die Statusdatei aus, sieht sich einen Bildausschnitt an, prüft die Rahmen gegen alle
bisherigen Boxen und trägt sie nach Freigabe ein. Bei der Ankerkette dauerte das rund 10 Minuten
(geschätzt 15.000 bis 20.000 Tokens). Ergebnis: 28 von 35 Treffern verworfen; die übrigen 7 waren
echte Personen neben der Kette.

**Grenzen:**

- Schon verpixelte Bilder bleiben verpixelt. Sie stehen als `blurred` in der Statusdatei und werden
  nicht neu bearbeitet. Das Original liegt in `<Kamera>/original/`.
- Die Rahmen sind feste Pixel. Verschiebt sich die Kamera um mehr als etwa ein Drittel der
  Boxbreite (bei der Kette ca. 15 Pixel), wird das Objekt wieder verpixelt. Dann die Rahmen neu
  bestimmen, wie oben.
- Steht eine Person genau vor dem Objekt, bleibt sie unverpixelt (wie beim Wegweiser).

### Einstellungsdatei wird ignoriert

**Symptom:** Im Protokoll eines Laufs steht

```text
WARNING | Settings file ignored (settings-privacy.json): …
WARNING | Settings value ignored: …
```

und die Werte von der Seite „Einstellungen“ wirken nicht. Rahmen, oberer Rand oder
Mindest-Sicherheit einer Kamera sind zum Beispiel wieder auf dem Standard.

**Prüfen:**

```bash
python3 -m json.tool config/settings-privacy.json > /dev/null && echo "Datei ist gültig"
python3 -m json.tool config/settings.json > /dev/null && echo "Datei ist gültig"
```

**Ursache:**

- `Settings file ignored`: Die Datei ist kein gültiges JSON oder nicht lesbar, meist weil jemand
  sie von Hand bearbeitet hat. Dann gilt **die ganze Datei nicht**, und alle Werte kommen aus
  `config/config.json`.
- `Settings value ignored`: Ein einzelner Wert ist ungültig, etwa außerhalb der Grenzen. Nur dieser
  Wert fällt weg, der Rest gilt.

Ist `settings-privacy.json` betroffen, fällt auch die Liste der Blur-Kameras auf den Standard aus
`config.json` zurück. Eine Kamera, die nur im Reiter hinzugefügt wurde, wird dann nicht mehr
verpixelt und markiert. Außerdem gehen die Feineinstellungen je Kamera verloren: Fehlen die
Rahmen, verpixelt die Runde wieder bekannte Fehltreffer.

**Lösung:** Die Werte auf der Seite „Einstellungen“ neu eintragen und speichern; die Seite schreibt
immer eine gültige Datei. Weil sie die kaputte Datei ebenfalls nicht lesen kann, zeigt sie die
Standardwerte. Welche Werte vorher eingestellt waren, steht in `logs/settings.log` (alter und neuer
Wert je Speicherung). Wer die Datei doch von Hand ändert, prüft sie danach mit `json.tool` (siehe
oben).

### Flagger startet nicht oder überspringt

| Meldung | Ursache | Lösung |
|---|---|---|
| `Skipped: ...` | Die Sperre ist belegt | später erneut starten |
| `Flagger not started: ...` mit einer unbekannten oder ignorierten Kamera | Eine Kamera in `flagger.cameras` existiert nicht oder steht in `ignored_cameras`. Dann startet der Flagger für **keine** Kamera. Die Seite „Einstellungen“ speichert so etwas nicht; es entsteht nur durch Handarbeit in einer Datei | die Kamera aus `flagger.cameras` oder aus `ignored_cameras` nehmen (in `config.json`, `config/settings.json` oder auf der Seite) |
| `Flagger not started: flagger.retention_days must be at least 7` | Von Hand ein Wert unter einer Woche eingetragen; die Seite lässt das nicht zu | Wert auf mindestens 7 setzen |
| `[<Kamera>] no images for <Datum> - nothing written` | Es gibt keine Bilder von diesem Tag | wie [Eine Kamera hat keine Bilder](#eine-kamera-hat-keine-bilder) |
| `Skipping unreadable or truncated image: <Datei>` | Das Bild ist abgeschnitten oder kaputt (abgebrochener Upload) | nichts; das Bild wird nur nicht geprüft. Häuft es sich, den Upload der Kamera prüfen |
| `Skipping image without a parseable time: <Datei>` | Aus dem Dateinamen lässt sich keine Uhrzeit lesen | nichts, solange es Einzelfälle sind. Bei allen Bildern einer Kamera: neues Namensformat, siehe [Eine Kamera hat keine Bilder](#eine-kamera-hat-keine-bilder) |
| Ein gelöschtes Highlight ist wieder da | Der Tag wurde neu geprüft, und der Ordner wurde ersetzt | erneut löschen |

Fehler auf der Highlights-Seite: [highlights-seite.md](highlights-seite.md#fehlersuche).

### Verpixelung

Die vollständigen Tabellen mit Fehlerbildern stehen in [verpixelung.md](verpixelung.md#fehlersuche)
(Videos) und [verpixelung-box.md](verpixelung-box.md#fehlersuche) (Storage Box). Der Grundsatz: Im
Zweifel bricht die Verpixelung ab und schreibt nichts. Ein Abbruch ist also kein Datenverlust.

| Meldung oder Beobachtung | Ursache | Lösung |
|---|---|---|
| `[<Kamera>] N images unblurred for more than 10 minutes: …` (Wächter) | Die Runde hat diese Bilder nicht geprüft: Sie hängt oder läuft nicht, der Detektor fällt aus, oder die Box ist nicht erreichbar | die Rundenzeilen im selben Protokoll lesen (`logs/privacy/<Datum>.log`), dann [verpixelung-box.md](verpixelung-box.md#fehlersuche) |
| Im Protokoll fehlt die Zeile `Stale check: …` | Der Wächter selbst läuft nicht | die Cron-Zeile mit `crontab -l` prüfen |
| Die Website zeigt bei einer Kamera seit langem dasselbe Bild | Die Kamera steht in `webcam_list.config`, aber nicht (mehr) in unserer Liste, also markiert niemand ihre Bilder. Oder die Runde läuft nicht (siehe Wächter) | beide Listen vergleichen ([Blur-Kamera hinzufügen oder entfernen](#blur-kamera-hinzufügen-oder-entfernen)) und die Markierung des neuesten Bildes prüfen |
| Die Website zeigt bei einer Blur-Kamera ein unverpixeltes Bild | Die Kamera fehlt in `webcam_list.config`, also prüft der Abholjob dort keine Markierung. Oder die Erkennung hat die Person übersehen | die Kamera sofort in `webcam_list.config` eintragen ([Blur-Kamera hinzufügen oder entfernen](#blur-kamera-hinzufügen-oder-entfernen)); steht sie schon drin, siehe [Erkennung liegt falsch](#erkennung-liegt-falsch) |
| `Skipped: …privacy-blur.lock…` in den Rundenzeilen | Ein anderer Verpixelungslauf hält die Sperre: das Nachholen oder ein von Hand gestartetes Video | nichts, solange es vorbeigeht. Die nächste Runde holt die Bilder nach |
| `[<Kamera>] Blur gate: left out N of M unconfirmed images: …` | Ein automatisches Video einer Blur-Kamera nimmt nur bestätigte Bilder. N Bilder waren nicht bestätigt; das Video entsteht aus den übrigen | meist nichts; Details in [verpixelung-box.md](verpixelung-box.md#fehlersuche) |
| `[<Kamera>] Blur gate: no confirmed image - skipping camera.` | Kein einziges Bild war bestätigt. Die Kamera wird übersprungen, ihr bisheriges Video bleibt | prüfen, ob die Verpixelung läuft (Wächter, Protokoll), dann [verpixelung-box.md](verpixelung-box.md#fehlersuche) |
| `Unsafe storage box remote: '<Wert>'` | Der Alias in `TIMELAPSE_STORAGE_BOX` (der Teil vor einem `:`) enthält ein unerlaubtes Zeichen. Erlaubt sind Buchstaben, Ziffern, `.`, `_` und `-`, am Anfang ein Buchstabe oder eine Ziffer (damit ssh den Wert nie als Option liest), optional als `benutzer@host` | den Eintrag in `~/.ssh/config` passend umbenennen oder den Alias in der Cron-Zeile korrigieren |

### Upload auf die Website

Das Protokoll steht in `logs/siteground-delivery.log`. Für jede Kamera endet es mit
`Ergebnis: hochgeladen=… übersprungen=… fehlgeschlagen=… gelöscht=…`
([betrieb.md](betrieb.md#upload-auf-die-website)).

| Meldung | Ursache | Lösung |
|---|---|---|
| `Die Liste der freigegebenen Videos konnte nicht erstellt werden.` | `scripts/list-deliverable-videos.py` ist gescheitert, zum Beispiel weil `videos/` fehlt | das Skript einzeln ausführen und seine Meldung lesen |
| `Die Liste ist leer: Es wird nichts gesendet und nichts gelöscht.` (oder `… Für <Kamera> wird nichts gesendet …`) | Es gibt keine freigegebenen Videos (alle Kameras in `ignored_cameras` oder noch keine Videos), bzw. die genannte Kamera ist nicht freigegeben | die Liste prüfen: `.venv/bin/python3 scripts/list-deliverable-videos.py` |
| `SITEGROUND_HOST, SITEGROUND_USER und SITEGROUND_PASS müssen ausgefüllt sein.` | `config/siteground.env` fehlt oder ist unvollständig | `./install.sh upload_login` legt die Datei aus der Vorlage an (leer); dann die drei Werte eintragen ([betrieb.md](betrieb.md#upload-auf-die-website)) |
| `Es läuft bereits ein anderer Lauf.` (Rückgabewert 3) | Für diese Kamera läuft schon ein Upload | warten und wiederholen |
| `Upload fehlgeschlagen: …` oder `Umbenennen fehlgeschlagen: …` | Die FTP-Verbindung oder die Rechte auf der Website | Verbindung prüfen; die nächste Nacht lädt erneut hoch. In diesem Ordner wird dann nicht aufgeräumt (`Aufräumen von … übersprungen`) |
| `Mindestens eine Kamera ist fehlgeschlagen.` | siehe die Zeilen darüber im Protokoll | jede Kamera einzeln behandeln |

### Speicherfilter

- `TIMELAPSE_STORAGE_BOX is not set`: Die Storage Box ist nicht angegeben. Die Variable setzen
  ([Konfiguration](konfiguration.md#umgebungsvariablen)).
- `Storage box listing failed`, obwohl die Variable gesetzt ist: siehe
  [Kamera-Speicher nicht erreichbar](#kamera-speicher-nicht-erreichbar).

### WordPress

Siehe [wordpress.md](wordpress.md#fehlerbehebung-wordpress-frontend).

---

## Fehler: Sicherung und Wiederherstellung

Die Meldungen kommen von `backup.sh` und vom Schritt `restore` des Installers. Dazu kommt die
ssh-Meldung bei einem geänderten Host-Key, die rsync durchreicht.

| Meldung | Ursache | Lösung |
|---|---|---|
| `BACKUP_HOST is not set: …` | Der ssh-Alias fehlt | `BACKUP_HOST=<alias> ./backup.sh` oder den Alias in `backup.env` eintragen |
| `Invalid BACKUP_HOST: …` | Der Alias beginnt nicht mit Buchstabe oder Ziffer, oder er enthält andere Zeichen als Buchstaben, Ziffern, `.`, `_`, `@` und `-` | den Alias aus `~/.ssh/config` verwenden |
| `Invalid PROJECT_DIR (relative to the host's home, no '..'): …` | Der Pfad ist absolut, enthält `..` oder andere Zeichen als Buchstaben, Ziffern, `.`, `_`, `/` und `-` | den Pfad relativ zum Home-Ordner des Hosts angeben, zum Beispiel `timelapse` |
| `VIDEOS must be 0 or 1.` | `VIDEOS` hat einen anderen Wert | `0` oder `1` setzen |
| `ssh was not found on this computer.` oder `rsync was not found on this computer.` | Das Werkzeug fehlt auf dem eigenen Rechner | installieren |
| `[WARN] models/ could not be saved.` und am Ende `Not saved: …` | rsync konnte den Ordner nicht holen: Er fehlt auf dem Host, `PROJECT_DIR` ist falsch, oder die Verbindung riss ab | die rsync-Meldung davor lesen, Alias und `PROJECT_DIR` prüfen. Alles andere ist gesichert, und den Lauf kann man einfach wiederholen |
| `No crontab on <alias> (or it is not readable).` | Der Host hat keine Crontab | nichts tun: `crontab.txt` bleibt leer, die Sicherung ist trotzdem vollständig |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Der Host wurde neu installiert | erst den Fingerabdruck prüfen, dann `ssh-keygen -R <host>` (bei einem anderen Port als 22: `ssh-keygen -R '[<host>]:<port>'`) und beim nächsten `ssh` neu bestätigen |
| `BACKUP_DIR must be an absolute path: …` (bei `install.sh`) | `BACKUP_DIR` ist ein relativer Pfad | einen absoluten Pfad angeben |
| `No backup folder at …: nothing to restore` | Es liegt keine Sicherung bereit | bei einem Neuaufbau ohne Sicherung normal. Sonst die Sicherung nach `~/timelapse-backup` kopieren und `./install.sh restore` starten |
| `… holds no models/, state/, videos/ or config/settings.json: nothing restored.` | Im Sicherungsordner fehlt alles, was `restore` zurückspielt | den Inhalt prüfen: `ls ~/timelapse-backup` |

Wie man den Server einrichtet: [vps.md](vps.md).

---

## Fehler: Entwicklung und CI

### CI ist rot, lokal ist alles grün

**Prüfen:** den fehlschlagenden Test im Log der GitHub Action.

**Ursache:** Die CI-Umgebung unterscheidet sich vom Server:

- **Kein FFmpeg oder ffprobe.** Ein Test, der ohne FFmpeg nicht läuft, braucht ein
  `pytest.mark.skipif(shutil.which("ffmpeg") is None, …)` (so wie `requires_ffmpeg` in
  `tests/privacy/privacy_test.py`) oder muss den FFmpeg-Aufruf ersetzen.
- **Xdebug ist geladen.** Eine Exception aus einem PHP-Konstruktor (etwa `new DateTimeZone(...)`)
  wird dort zu einem `Error`, und den fängt `catch (Exception)` nicht. Deshalb Eingaben vorher
  prüfen, statt Exceptions zu fangen.
- **Die PHP-Version ist nicht festgelegt.** CI nimmt das PHP von `ubuntu-latest` (mindestens 8.3).
  Im Web-Code nichts verwenden, was es nur in neueren Versionen gibt (etwa `array_any`).

**Lösung:** Lokal ohne FFmpeg testen, indem man `ffmpeg` und `ffprobe` aus dem `PATH` nimmt, und
den Test entsprechend anpassen.

### Push wird blockiert

**Ursache:** Das passiert nur, wenn lokal ein Pre-Push-Hook eingerichtet ist
(`.git/hooks/pre-push`, nicht in git). Er führt `ruff check`, `ruff format --check` und `pytest` aus
und bricht bei einem Fehler ab ([architektur.md](architektur.md#github-actions-und-pre-push-hook)).
Im Klon auf dem Mac gibt es keinen (Stand 30.10.2026); dort prüft erst CI.

**Lösung:** `ruff format .` ausführen und den Fehler beheben. `git push --no-verify` nur im Notfall;
CI prüft ohnehin dasselbe.

### Tests laufen auf dem Mac nicht vollständig durch

**Ursache:** Auf macOS schlagen rund 67 Tests aus Plattformgründen fehl: BSD-`ls` und BSD-`date`
statt der GNU-Versionen, `spawn` statt `fork`. Stand 29.10.2026, ohne `onnxruntime`: 897 bestanden,
67 fehlgeschlagen. Das ist kein Fehler im Code.

**Lösung:** Maßgeblich sind der VPS und CI, beide unter Linux. Änderungen pushen, auf dem VPS mit
`git pull` holen ([vps.md](vps.md#code-auf-den-vps-bringen)) und dort ausführen:

```bash
.venv/bin/python3 -m pytest
.venv/bin/python3 -m ruff check .
.venv/bin/python3 -m ruff format --check .
```

Schlägt dort mehr fehl als die bekannten macOS-Fälle, ist der Fehler echt.

---

## Arbeitsspeicher

### Arbeitsspeicher knapp

**Prüfen:**

```bash
free -m
ps -eo rss,args --sort=-rss | head -10
```

**Ursache:** Neben dem Lauf belegen oft alte VS-Code-Server Speicher. Sie laufen weiter, wenn die
Verbindung abgebrochen ist (Mac im Ruhezustand) oder nach einem VS-Code-Update.

**Lösung:**

- Alte VS-Code-Server beenden, etwa über „Remote-SSH: Kill VS Code Server on Host…“ in VS Code.
- Während eines großen Renders keine weiteren Läufe oder Tests starten.
- `TIMELAPSE_X264_PRESET=ultrafast` senkt den Speicherbedarf des Encoders deutlich, macht die
  Dateien aber größer ([Konfiguration](konfiguration.md#umgebungsvariablen)).
