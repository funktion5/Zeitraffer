# Die Weboberfläche lokal testen (Docker)

Ein Testsystem auf dem eigenen Rechner, das den Webteil des VPS nachbaut: **Debian 13**, **Apache 2.4**
mit **PHP 8.4** und **Python 3.13**, dazu dieselben Hilfsprogramme (Wrapper, `sudo`-Regeln, Basic-Auth-Login)
wie auf dem Server. So lässt sich eine Änderung an der Weboberfläche unter `http://localhost:55222`
ausprobieren, **ohne den VPS anzufassen**. Erst wenn sie gefällt, wird der Zweig in `main` gemerged und der
VPS holt ihn mit `git pull`.

Es ist nur für diesen Zweck gedacht: HTTP, ein einfacher Test-Login, erreichbar nur vom eigenen Rechner
(`127.0.0.1`). Es gehört nie ins Netz.

## Was es kann und was nicht

| Geht | Geht nicht |
|---|---|
| alle Seiten (Kameras, Kamera, Highlights, Einstellungen, Verpixelung) | alles, was die Storage Box braucht: „Vorschau aktualisieren“, die Verpixelung auf der Box, echte Videoläufe |
| Einstellungen speichern (Browser → PHP → `sudo` → Wrapper → Python) | Kamerabilder lesen (keine Box, keine Schlüssel) |
| Videos ansehen und löschen (Testvideos), Speicheranzeige, Login | die Cron-Zeiten des Nachtlaufs |

Die Daten sind **erfundene Testdaten** (kleine Platzhaltervideos). Echte Videos, Schlüssel und Passwörter
sind nicht im Container. Die Größen der Testvideos sind nur „scheinbar“ (sparse Dateien): die Speicheranzeige
zeigt realistische Zahlen, es wird kaum Platz belegt.

Der Container läuft mit der CPU des eigenen Rechners (Intel oder ARM), der VPS ist ARM. Für PHP- und
Python-Code spielt das kaum eine Rolle, identisch ist es aber nicht.

## Einmal einrichten

1. Docker Desktop starten.
2. In den Ordner wechseln: `cd docker/zeitraffer-web`
3. Die Vorlage kopieren: `cp .env.example .env`, dann in `.env` ein Passwort bei `DEV_PASSWORD` eintragen
   (`.env` steht nicht in git). Der Login-Name ist `DEV_LOGIN`.

## Starten, ansehen, beenden

Alles im Ordner `docker/zeitraffer-web`:

| Was | Befehl |
|---|---|
| starten (beim ersten Mal baut es das Image und installiert die Python-Pakete, einige Minuten) | `docker compose up --build -d` |
| Testdaten anlegen (einmal; wiederholen ist harmlos) | `docker compose exec -u zeitraffer web seed-demo-data` |
| ansehen | <http://localhost:55222> (Login aus `.env`) |
| Protokoll von Apache und PHP | `docker compose logs -f web` |
| neu starten | `docker compose restart web` |
| beenden (Daten bleiben) | `docker compose down` |
| beenden und **alle Testdaten löschen** | `docker compose down -v` |

## Einen Zweig testen

Der Container zeigt **immer den Stand, der auf dem Rechner ausgecheckt ist**: Zweig wechseln
(`git switch <zweig>`), Seite neu laden, fertig. Ein Neubau ist dafür nicht nötig.

| Geändert wurde … | Dann … |
|---|---|
| PHP, CSS, JavaScript, Python in `web/` oder `src/` | nur die Seite neu laden |
| ein Wrapper in `scripts/web/` | `docker compose restart web` (er wird beim Start neu installiert, wie `./install.sh web_bridge` auf dem VPS) |
| `requirements.txt` | `docker compose restart web` (die Python-Pakete werden neu eingerichtet, wenn sich die Datei geändert hat) |
| das `Dockerfile` oder `entrypoint.sh` | `docker compose up --build -d` |

Gespeicherte Einstellungen landen in `config/settings.json` und `config/settings-privacy.json` im eigenen
Ordner (wie auf dem VPS, von git ignoriert). Wer sie zurücksetzen will, löscht diese Dateien.

## Die Tests im Container laufen lassen

Der Container hat dieselbe Umgebung wie der VPS (Debian 13, Python 3.13, PHP, FFmpeg, die Pakete aus
`requirements.txt`). Tests, die auf dem Mac nur wegen macOS-Unterschieden scheitern, laufen dort. Im Ordner
`docker/zeitraffer-web`:

```
docker compose exec -u zeitraffer web bash -c "cd ~/timelapse && .venv/bin/python3 -m pytest"
```

Eingebunden sind `tests`, `src`, `web`, `scripts`, `config`, `pyproject.toml`, `requirements.txt`, `install.sh`
und `backup.sh`: das, was die Tests lesen. Nicht dabei sind `docs/`, `models/` und `sandbox/`; der eine Test, der
das Erkennungsmodell und die Beispielbilder braucht (`tests/flagger/flagger_acceptance_test.py`), überspringt sich
selbst. Ruff geht ebenso: `.venv/bin/ruff check .`.

## Warum es so gebaut ist

- **Die Ordner werden einzeln eingebunden** (`web`, `src`, `scripts`, `tests`, `config`, `pyproject.toml`,
  `requirements.txt`, `install.sh`, `backup.sh`), nicht das ganze Repo. Der Grund: Docker Desktop zeigt eingebundene Dateien im Container
  als Eigentum von root, und `projectRunUser()` in `web/src/process-runner.php` startet die Wrapper als
  **Eigentümer des Projektordners** und verweigert root. Deshalb ist `/home/zeitraffer/timelapse` ein echter
  Ordner des Kontos `zeitraffer`.
- **Laufzeitdaten** (`state`, `videos`, `logs`, `temp`, `reports`) und die **Python-Umgebung** liegen in
  Docker-Volumes, getrennt vom Repo: nichts davon landet im Arbeitsordner.
- **Der Start entspricht der Installation:** `entrypoint.sh` macht, was `install.sh` auf dem VPS macht
  (Login, Vhost, Wrapper, `sudo`-Regeln) und startet dann Apache. Ändert sich dort etwas, muss es hier
  mitgezogen werden.
- **Das Passwort kommt aus `.env`**, nicht aus dem Image.

## Wenn etwas nicht klappt

| Symptom | Ursache und Lösung |
|---|---|
| `docker compose` meldet, `DEV_PASSWORD` fehle | `.env` ist nicht angelegt: siehe „Einmal einrichten“ |
| der Browser fragt immer wieder nach dem Login | Name und Passwort aus `.env` verwenden; nach einer Änderung an `.env`: `docker compose up -d` |
| die Seiten sind leer | die Testdaten fehlen: `seed-demo-data` ausführen |
| „Vorschau aktualisieren“ oder ein Lauf meldet einen Fehler | gewollt: ohne Storage Box geht das nicht |
| Port 55222 ist belegt | ein anderes Programm nutzt ihn: beenden, oder in `compose.yaml` den linken Port ändern |
