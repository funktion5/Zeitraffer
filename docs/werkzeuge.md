# Werkzeuge: Speicherfilter und Yearly-Backfill

Eigenständige Hilfsprogramme neben dem nächtlichen Lauf.


## Speicherfilter

Die Jobs filtern leere und doppelte Bilder nur für das jeweilige Video; auf dem Kamera-Storage bleiben sie liegen. Der Speicherfilter geht deshalb einmal durch den kompletten Ordner einer Kamera und schreibt einen Bericht darüber, welche Dateien gelöscht werden können.

Der Speicherfilter **löscht nichts**. `/mnt/cameras` ist ohnehin read-only eingehängt. Das eigentliche Löschen erfolgt später separat anhand des Berichts.

### Aufruf

```bash
.venv/bin/python3 -m src.storage_filter --cameras Uferstrasse
.venv/bin/python3 -m src.storage_filter --cameras Uferstrasse Nordufer_wide
.venv/bin/python3 -m src.storage_filter --all-cameras
```

- `--cameras` prüft genau die genannten Kameras, auch solche aus `ignored_cameras`.
- `--all-cameras` prüft alle Kameras außer denen aus `ignored_cameras`.
- Eine der beiden Optionen ist Pflicht.

Für einen langen Lauf, der auch nach dem Schließen von VS Code oder der SSH-Verbindung weiterläuft:

```bash
scripts/storage-filter-all                                 # alle Kameras außer ignored_cameras
scripts/storage-filter-all --cameras Uferstrasse SVG       # beliebige Argumente wie oben
```

Das Skript startet den Speicherfilter per `nohup` im Hintergrund und gibt die PID sowie den Pfad der Konsolenausgabe aus (`logs/filter/run_YYYY-MM-DD_HHMMSS.out`). Fortschritt verfolgen mit `tail -f` auf diese Datei, abbrechen mit `kill -TERM -- -<PID>` (beendet auch laufende SSH-Aufrufe; `kill -INT` wirkt bei Hintergrundprozessen nicht). Der Bericht der gerade laufenden Kamera wird dann nicht geschrieben; fertige Kameras behalten ihren. Die `.out`-Dateien fallen nicht unter die Log-Retention und müssen bei Bedarf von Hand gelöscht werden.

Der Speicherfilter nimmt denselben Lock wie Cron und die Weboberfläche (`state/zeitraffer-run.lock`). Läuft bereits ein Timelapse-Lauf, bricht er sofort ab. Er schreibt kein `state/run-in-progress` und wird nach einem Neustart nicht automatisch fortgesetzt.

Fehler einer Kamera (`OSError`, `TimeoutError`) werden protokolliert; die übrigen Kameras laufen weiter. Der Exit-Code ist dann `1`.

### Ablauf

1. **Liste per SSH:** Ein einziges `ls -l` auf der Storage Box liefert alle Dateinamen mit Größe (Uferstrasse, ca. 189.000 Dateien: rund 3,5 Sekunden). Benutzer und Host kommen aus dem laufenden SSHFS-Mount (`/proc/mounts`), Port und Schlüssel aus `~/.ssh/config` (siehe unten). Ohne aktiven Mount bricht der Speicherfilter ab.
2. **Leere Dateien:** Alle JPGs mit 0 Byte laut Liste.
3. **Duplikate pro Tag:** Nur Dateien, die am selben Aufnahmetag (laut Dateiname) dieselbe Größe haben, werden verglichen. Die SHA-256-Hashes berechnet die Storage Box selbst (`sha256sum`, 1.000 Dateien pro Aufruf, 4 Aufrufe parallel); über das Netz kommen nur die Hashes, nicht die Bilder. Behalten wird die erste Datei des Tages in Dateinamen-Reihenfolge; gemeldet werden alle späteren Kopien.

Der Speicherfilter liest keine Bilddateien über `/mnt/cameras`; der Mount wird nur benötigt, um Benutzer und Host der Storage Box zu ermitteln.

Port und Schlüssel stehen bewusst nicht im Code, sondern in `~/.ssh/config` des Kontos `<benutzer>` (gleiche Werte wie `REMOTE_PORT` und `REMOTE_SSH_KEY` in `/etc/timelapse/mount.env`). Einmalig anlegen:

```text
Host <storage-host>
	Port <port>
	IdentityFile <schlüsselpfad>
	IdentitiesOnly yes
```

Danach `chmod 600 ~/.ssh/config`. Fehlt der Eintrag, bricht der Speicherfilter mit einem SSH-Fehler ab. Die Datei ist Teil des Backups und wird bei einer Neuinstallation wiederhergestellt. Fehlt beim Hashen eine Datei oder ist sie nicht lesbar, schlägt die Kamera fehl, statt die Datei als eindeutig zu behandeln.

Nicht geprüft werden:

- Bilder vom heutigen Tag – sie können noch im Upload sein und kurzzeitig 0 Byte haben.
- Dateien, deren Name keinem bekannten Format entspricht (Formate werden nie geraten).
- Dateien ohne `.jpg`-Endung, Unterordner und Symlinks.
- Identische Bilder an verschiedenen Tagen: Ein kameraweiter Vergleich müsste bei Uferstrasse rund 92 % aller Dateien über SSHFS lesen und dauert pro Kamera Stunden.

### Laufzeit und Fortschritt

Warum alles auf der Storage Box läuft (gemessen am 2026-09-28):

| Schritt | über SSHFS | auf der Storage Box |
|---|---|---|
| Liste + Größen, Uferstrasse (ca. 189.000 Dateien) | 2 bis ca. 45 Minuten, je nach Cache | ca. 3,5 Sekunden |
| Hashen pro Datei | ca. 43 ms | ca. 10 ms, mit 4 parallelen Aufrufen ca. 4 ms |

Wie lange ein Lauf dauert, hängt vor allem davon ab, wie viele Dateien am selben Tag gleich groß sind:

- Uferstrasse: ca. 1.800 von 189.000 Dateien (0,9 %).
- Segelsport-Club-Suedenmeer: ca. 180.000 von 244.000 Dateien (74 %). Die Bilder sind sehr klein (meist 13–22 KB), und an manchen Tagen hat die Kamera den ganzen Tag dasselbe eingefrorene Bild geliefert. Erwartete Laufzeit: ca. 12 Minuten.

Damit ein langer Lauf nicht wie hängend aussieht, meldet der Speicherfilter:

```text
Storage filter: camera <camera> | listed=… | empty=… | checking … files for duplicates
Storage filter: camera <camera> | checked …/… files for duplicates      (alle 30 Sekunden)
```

Den Speicherfilter trotzdem nicht kurz vor dem nächtlichen Lauf um 02:00 Uhr starten: Er hält währenddessen den gemeinsamen Lock.

### Bericht

Pro Kamera und Lauf entsteht eine Datei:

```text
reports/storage-filter/<camera>_YYYY-MM-DD_HHMMSS.csv
```

Format: CSV mit `;` als Trennzeichen und UTF-8 mit BOM, damit ein deutsches Excel oder LibreOffice die Datei per Doppelklick korrekt öffnet. Jede Zeile ist ein Löschkandidat:

```text
camera;path;reason
Cam;/mnt/cameras/Cam/cam_250101_120000.jpg;empty
Cam;/mnt/cameras/Cam/cam_250101_121500.jpg;duplicate
```

Der Bericht wird zuerst als temporäre Datei geschrieben und erst danach umbenannt; ein abgebrochener Lauf hinterlässt keine halbe Liste. `reports/` wird mit `770` angelegt und ist für `www-data` nicht lesbar.

Die Anzahl gefundener Dateien pro Kamera steht in `logs/filter/YYYY-MM-DD.log`.

## Yearly-Backfill für Kalenderjahre

`scripts/yearly-backfill.py` erstellt Yearly-Videos für ganze Kalenderjahre (1. Januar bis
31. Dezember, im laufenden Jahr bis gestern). Bildsuche, 0-Byte-Filter, Zeitfenster
(`interval_window`) und die Auswahl von bis zu fünf Bildern pro Tag sind dieselben wie beim
Yearly-Job, aber **ohne** Mindestabdeckung: Jede Kamera wird gerendert, fehlende Tage werden nur
protokolliert.

```bash
.venv/bin/python3 scripts/yearly-backfill.py
.venv/bin/python3 scripts/yearly-backfill.py --years 2024 2025 --cameras BSV-Steinhude
.venv/bin/python3 scripts/yearly-backfill.py --years 2025 --force
```

- `--years`: Kalenderjahre (Standard: 2026)
- `--cameras`: nur diese Kameras (Standard: alle außer `ignored_cameras`)
- `--force`: vorhandene Videos neu erstellen statt überspringen
- `--blur-people`: Personen und Kennzeichen verpixeln wie bei historischen Dailys (Einstellungen
  aus `privacy` in `config.json`, siehe [docs/verpixelung.md](verpixelung.md)). Das Video
  bekommt die Endung `_blur`; das unverpixelte bleibt erhalten. Die Erkennung dauert ca. 8–9
  Sekunden pro Bild, ein ganzes Jahr (rund 1.640–1.830 Bilder) also ca. 4 Stunden. Weil das
  Skript den Lock belegt, so starten, dass es vor 02:00 fertig ist, sonst fällt der nächtliche
  Lauf aus.

Ausgabe wie bei historischen Läufen unter `videos/<camera>/manual-runs/yearly/<camera>_<Enddatum>.mp4`
mit `yearly_framerate`; Enddatum ist der 31. Dezember, im laufenden Jahr der gestrige Tag. Pro Lauf entsteht ein Bericht
`reports/yearly-coverage/backfill_YYYY-MM-DD_HHMMSS.csv` (`;`-getrennt, Spalten `camera`, `year`,
`covered`, `total`, `missing_ranges`, `status`, `video`), der nach jeder Zeile geschrieben wird.
Das Skript belegt denselben Lock wie Cron und Weboberfläche und wird nicht von pytest abgedeckt.
