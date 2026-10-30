# Werkzeuge: Staging für Hosts ohne Mount (Archiv)

Aus `docs/werkzeuge.md` herausgenommen (2026-10-30). Der Nachtlauf liest die Bilder seit der
Umstellung per ssh selbst; `stage-frames.py` liegt mit seinen Tests in diesem Archivordner.
`timelapse-nightly-staged` besteht weiter (siehe `docs/werkzeuge.md`), aber ohne Kopierschritt.

**Stand:** vorhanden und getestet, derzeit nicht im Einsatz. Gebaut für einen Webserver ohne
Root-Rechte, auf dem kein SSHFS-Mount möglich ist; der nächtliche Job ließ sich dort nicht
dauerhaft betreiben. Die Videos entstehen weiterhin auf dem Raspberry Pi. Der Code bleibt für einen
späteren Host ohne Mount erhalten.

Ablauf pro Kamera:

1. Die für den nächtlichen Lauf nötigen Bilder per `rsync` **nur lesend** von der Storage Box nach
   `temp/camera-staging/` kopieren (`scripts/stage-frames.py`).
2. `src.main` mit `TIMELAPSE_CAMERA_ROOT` auf diesen Ordner laufen lassen.
3. Die erzeugten Videos prüfen; der Exit-Code von `src.main` allein verdeckt Fehler einzelner Kameras.
4. Die kopierten Bilder wieder löschen, auch bei einem Abbruch. Gelöscht wird nur innerhalb von
   `temp/`.

Eine fehlerhafte Kamera hält die übrigen nicht auf.

### Voraussetzungen

- SSH-Zugang zur Storage Box über einen Alias in `~/.ssh/config` (Benutzer, Port, Schlüssel stehen
  nur dort, nie im Repository)
- `TIMELAPSE_STORAGE_BOX="<ssh-alias>[:<basisordner>]"` (siehe
  [README: Umgebungsvariablen](../../../README.md#umgebungsvariablen)); `timelapse-nightly-staged` setzt
  ohne Angabe den Alias `box`
- `rsync`, `ffmpeg` und `ffprobe` im `PATH`

### Aufruf

```bash
scripts/timelapse-nightly-staged                          # kompletter nächtlicher Lauf mit Staging
python3 scripts/stage-frames.py --list-cameras            # nur anzeigen, welche Kameras ein Lauf abdeckt
python3 scripts/stage-frames.py --cameras <Kamera> --target-date <Datum>   # nur kopieren
python3 scripts/stage-frames.py --clean-only              # nur die kopierten Bilder entfernen
```

| Option von `stage-frames.py` | Bedeutung |
|---|---|
| `--target-date <Datum>` | Zieltag des Laufs (Standard: gestern) |
| `--cameras A B` | nur diese Kameras |
| `--destination <Pfad>` | Zielordner statt `temp/camera-staging/`; muss unter `temp/` liegen |
| `--clean-only` | nichts kopieren, nur den Zielordner leeren |
| `--no-lock` | keine eigene Sperre nehmen, weil der Aufrufer sie schon hält (so ruft `timelapse-nightly-staged` es auf) |
| `--list-cameras` | die Kameras eines nächtlichen Laufs ausgeben, sonst nichts |

`timelapse-nightly-staged` hält die gemeinsame Sperre `state/zeitraffer-run.lock` für den ganzen
Lauf und schreibt einen Bericht nach `logs/nightly/<run-id>/report.txt`. Es setzt
`TIMELAPSE_X264_PRESET=ultrafast` als Standard, weil der Webserver große Encoder-Prozesse beendet;
`TIMELAPSE_NIGHTLY_PYTHON` wählt den Python-Interpreter.

Für Cron die eigene Zeile **anhängen**, bestehende Einträge auf einem fremden Server nie ändern:

```cron
0 2 * * * <projektpfad>/scripts/timelapse-nightly-staged
```

### Exit-Codes

| Code | `stage-frames.py` | `timelapse-nightly-staged` |
|---|---|---|
| `0` | alle Kameras kopiert | alle Kameras kopiert, gelaufen und geprüft |
| `1` | einzelne Kameras fehlgeschlagen | einzelne Kameras fehlgeschlagen |
| `2` | Abbruch: Box nicht erreichbar, falsche Argumente, unsicherer Zielordner, Sperre belegt | Abbruch: Box nicht erreichbar, keine Kameras, Staging abgebrochen |
| `64` | – | ungültige Einstellung |
| `70` | – | Projektordner unbrauchbar |
| `75` | – | Sperre durch einen anderen Lauf belegt |
