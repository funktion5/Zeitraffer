# NAS-Archiv

Werkzeuge, um Bilder aus dem alten Webcam-Archiv auf dem Synology-NAS zu holen und daraus
Kalenderjahr-Videos zu erstellen. Nicht Teil des Produktionslaufs; Cron und Weboberfläche
nutzen nichts aus diesem Ordner. Das Lesen aus einem anderen Bildordner übernimmt
`TIMELAPSE_CAMERA_ROOT` in `src/images.py`.

## Inhalt

- `nas-extract.py`: Fensterbilder aus den Tar-Archiven holen (Details unten).
- `helpers/zip_extract.py`: Bilder aus einem Kamera-Zip 2004-2008 (Zip in Zip, Tars) holen.
- `helpers/seqzip_extract.py`: dasselbe für die vier Zips ohne zentrales Verzeichnis.
- `helpers/storagebox_fill.py`: Fensterbilder eines Jahres von der Storage Box ergänzen.
- `helpers/delete_dark.py`: dunkle Bilder in Zeiträumen löschen (falsche Kamerauhr).
- `helpers/render_letterbox.py`: Jahresvideo mit gemischter Auflösung ohne Verzerrung rendern.
- `docs/nas/` im Projektordner (nur lokal, per `.gitignore` nicht im Repository):
  - `docs/nas/nas-archive.md`: Stand und Verlauf des Archiv-Projekts.
  - `docs/nas/nas-inventar.md`: Bestand aller NAS-Ordner.
  - `docs/nas/yearly-videos-zahlen.md`: Zahlen zu den erstellten Yearly-Videos.

Die Helfer unter `helpers/` lesen über den read-only Mount `/mnt/nas` und schreiben nach
`~/nas-cameras/<Kamera>/`. `nas-extract.py` liest direkt über den rclone-Remote `nas`.

## Bilder aus den Tar-Archiven holen

Das Archiv auf dem NAS (Synology, nur per FTP erreichbar, kein Shell- oder Adminzugang) liegt
als Tar-Archive unter `Webcams/storagebox-mirror/tar/backup_<Kamera>_<YYYYMMDD>.tar`. Der
rclone-Remote `nas` nutzt FTPS (`explicit_tls`) ohne Zertifikatsprüfung (das NAS-Zertifikat
enthält keine IP-Adresse) und mit `disable_tls13` (unter TLS 1.3 brachen Uploads sporadisch mit
`426 Data connection` ab).

`nas/nas-extract.py` lädt jedes Tar einmal per `rclone cat` als Stream und schreibt nur die
Bilder im Monthly/Yearly-Zeitfenster flach (nur Dateiname, ohne die Ordnerkette des Archivs)
nach `~/nas-cameras/<Kamera>/`. Auf das NAS wird nichts geschrieben; entpackte Einzelbilder per
FTP hochzuladen hätte pro Datei eine eigene Datenverbindung gekostet (~3 min pro Tar statt ~1 s).

```bash
.venv/bin/python3 nas/nas-extract.py --cameras BSV-Steinhude
.venv/bin/python3 nas/nas-extract.py --all-cameras --exclude Kapellenhoehe
```

- Zeitfenster: Standard aus `config.json` (`interval_window`), überschreibbar mit
  `--window-time HH:MM|sunset` und `--window-tolerance-minutes N`.
- Fortschritt: `state/nas-extract-done_<Fenster>.txt` (ein Tar pro Zeile, je Fenster eigene
  Datei); ein abgebrochener Lauf setzt dort fort. Log: `logs/nas-extract.log`.
- Unbekannte Dateinamenformate werden nicht übernommen, sondern als `unknown_format` gezählt.
- `--source nas:<Ordner>` liest Tars aus einem anderen NAS-Ordner (z. B.
  `storagebox-mirror/webcams-sortiert/<Kamera>` für 2014 bis 2019), `--until-date YYYY-MM-DD`
  übernimmt keine späteren Bilder (Jahre, die die Storage Box bereits abdeckt).
- Cafe-am-Meer-Promenade nutzt das Format `promenade_YYYY_MMDD_HHMMSS_01.jpg`. Die Uhrzeit im
  Namen ist ganzjährig Winterzeit (MEZ): Im Sommer liegt das 12:00-Fenster damit bei 13:00 MESZ.
- Platzbedarf: etwa 1/6 der Tar-Größe (BSV-Steinhude: 4,7 GiB Tars → 818 MB).

Der Ordnername unter `~/nas-cameras/` ist der Kameraname und damit auch der Ordner unter
`videos/`. Kalenderjahr-Videos aus dem Archiv:

```bash
TIMELAPSE_CAMERA_ROOT=/home/zruser/nas-cameras \
	.venv/bin/python3 scripts/yearly-backfill.py --years 2020 2021 --cameras BSV-Steinhude
```

Der read-only Mount `/mnt/nas` (`rclone mount nas:Webcams /mnt/nas --read-only --daemon`) wird
dafür nicht benötigt; aushängen mit `fusermount -u /mnt/nas`.
