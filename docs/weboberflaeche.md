# Lokale Weboberfläche

Was die Weboberfläche kann, welche Dateien dazugehören und wie ein Video-Auftrag aus dem Browser abläuft. Die Einrichtung (Apache, Anmeldung, Wrapper, Dateirechte) steht im README unter Installation.


## Aktueller Funktionsumfang

Die Startseite listet die unter `/mnt/cameras` gefundenen Kameraverzeichnisse auf. Die gesamte Oberfläche ist auf Deutsch; interne Bezeichner (`daily`/`weekly`/`monthly`/`yearly` in Formularwerten, URLs und der CLI) bleiben davon unberührt. Die Kameraseite bietet:

- Anzeige von gesamtem, verwendetem und freiem Speicherplatz des Dateisystems von `videos/`
- Bibliothek der historischen Videos unter `videos/<camera>/manual-runs/`, mit kurzem deutschem Datum statt Dateiname (plus Zeitpuffer in Minuten, sofern der Dateiname einen trägt, z. B. „24.09.2026 (60 Min.)“, bzw. das Zeitfenster bei Monthly/Yearly, z. B. „30.06.2025 (Sonnenuntergang ±60 Min.)“); die Liste bleibt für den Job-Typ des gerade ausgewählten Videos aufgeklappt
- Wiedergabe des ausgewählten MP4 direkt im Browser, mit Download- und Löschen-Button (Icon + Beschriftung); nur Löschen fragt vorher in einem Bestätigungsdialog nach
- Formular für genau eine Kamera, einen Job-Typ und ein Zieldatum; bei Daily/Weekly zusätzlich ein Zeitpuffer (30/60/90 Minuten) als Radiogruppe, die nur für diese beiden Job-Typen eingeblendet wird — Monthly/Yearly nutzen keinen Zeitpuffer und erhalten ihn serverseitig auch dann nicht, wenn einer übermittelt würde
- bei Monthly/Yearly eine Radiogruppe „Zeitfenster“: „Mittag (Standard)“ übergibt nichts (es gilt `interval_window` aus der Config), „Sonnenuntergang“ übergibt `sunset` plus eine Fensterbreite von ±30/60/90 Minuten (eigene Radiogruppe, nur bei Sonnenuntergang sichtbar); serverseitig sind nur diese Werte erlaubt
- kurzer Hinweistext über dem Formular: Zieldatum ist immer der letzte Tag des Zeitraums; Monthly braucht mindestens 25 der 30 Tage, Yearly mindestens 300 Tage mit Bildern im gewählten Zeitfenster (`min_coverage_days`), fehlende Tage werden im Video übersprungen
- historische Daily-, Weekly-, Monthly- und Yearly-Läufe
- Live-Status per Polling im Abstand von fünf Sekunden; der Abschlussdialog übersteht auch einen Seitenwechsel weg von der auslösenden Seite (Fortsetzung des Pollings über `sessionStorage`) und bietet einen direkten Link zum fertigen Video an
- Löschen eines historischen Videos über denselben eingeschränkten Wrapper-Mechanismus wie die Job-Erstellung

Die Seite **Highlights** (`/highlights.php`, Link im Header) zeigt die vom [Highlights-Flagger](flagger.md) markierten Bilder pro Kamera und Tag, mit Zeitraum- und Kamerafilter, Großansicht per Klick (Blättern mit den Pfeiltasten), Download und Löschen (Bestätigungsdialog, eigener Lösch-Wrapper). Details: [docs/highlights-seite.md](highlights-seite.md).

Die Bibliothek zeigt derzeit ausschließlich `manual-runs`. Versteckte Dateien werden nicht gelistet, darunter `.<name>.tmp.mp4` eines laufenden Renderings, das so weder abgespielt noch gelöscht werden kann. Automatische Videos werden noch nicht in der Oberfläche aufgelistet, und eine Status-Datei-Bereinigung ist nicht implementiert.

Die Kameraerkennung der Weboberfläche ignoriert versteckte Verzeichnisse und blendet zusätzlich alle Kameras aus `ignored_cameras` in `config/config.json` aus (`getIgnoredCameras()` in `web/src/video-library.php`). Die Weboberfläche benötigt deshalb Lesezugriff auf `config/config.json`.

## Webdateien

```text
web/public/index.php               Kameraübersicht
web/public/camera.php              Player, Bibliothek, Formular und Status-Polling
web/public/highlights.php          Highlights-Seite (Bilder des Flaggers, Löschen)
web/public/job-status.php          read-only JSON-Status-Endpunkt (inkl. Tote-Prozess-Erkennung)
web/public/style.css               Darstellung und responsives Layout
web/src/components/header.php      gemeinsamer Header und Speicheranzeige
web/src/components/job-watcher.php gemeinsamer Abschlussdialog, seitenübergreifendes Polling
web/src/components/confirm-delete.php gemeinsamer Bestätigungsdialog vor dem Löschen
web/src/video-library.php          Kamera-, Video- und Speicherermittlung
web/src/job-runner.php             Aufruf des fest installierten Triggers
web/src/video-delete.php           Aufruf des fest installierten Lösch-Wrappers
web/src/highlights-library.php     Lesen und Prüfen der Flagger-Berichte
web/src/highlight-delete.php       Aufruf des Lösch-Wrappers für Highlight-Bilder
web/src/process-runner.php         gemeinsame proc_open-Hilfsfunktion (Trigger und Löschen)
```

`web/public/` ist der einzige Apache-DocumentRoot. PHP-Quellcode außerhalb dieses Verzeichnisses, Python-Code, Konfiguration, Logs, temporäre Dateien und Statusdateien werden nicht direkt durch Apache veröffentlicht.

## Job-Ausführung und Status

Ein gültiger Formular-POST wird durch einen Session-basierten CSRF-Token geschützt. PHP prüft Kamera, Job-Typ und ISO-Datum und ruft anschließend ohne Shell-Auswertung diesen festen Befehl auf:

```text
sudo -n -u <benutzer> /usr/local/sbin/timelapse-web-trigger \
  <job-id> <job> <zieldatum> <kamera> [<zeitpuffer> | <fenster-zeit> <fenster-toleranz>]
```

Daily/Weekly verlangen genau einen Zeitpuffer (30/60/90). Monthly/Yearly erhalten entweder
nichts oder Fensterzeit (`HH:MM` oder `sunset`) plus Toleranz in Minuten (1–999); Trigger und
Worker prüfen das Format, `src.main` lehnt Fenster über Mitternacht ab. Der Worker übergibt
`--window-time` / `--window-tolerance-minutes` und erwartet die Datei
`<kamera>_<zieldatum>_<HHMM|sunset>-<toleranz>min.mp4`.

Die weitere Kette lautet:

```text
timelapse-web-trigger
  → validiert Job-ID, Job, Datum und Kamera
  → belegt state/zeitraffer-run.lock ohne Warten
  → schreibt running
  → startet timelapse-web-worker im Hintergrund

timelapse-web-worker
  → startet python3 -m src.main --jobs ... --target-date ... --cameras ...
  → prüft, ob die erwartete MP4 neu veröffentlicht oder atomar ersetzt wurde
  → schreibt completed oder failed
```

Statusdateien liegen unter:

```text
state/web-jobs/<32-stellige-job-id>.status
```

Daneben schreibt der Worker `<job-id>.pid` mit seiner Prozess-ID. Steht in der Statusdatei noch
`running`, der Prozess lebt aber nicht mehr (z. B. nach einem Neustart oder einem Apache-Neustart),
meldet `job-status.php` `failed`, damit der Browser nicht endlos wartet. Die Statusdatei selbst
bleibt dabei unverändert.

Erlaubte Inhalte sind ausschließlich `running`, `completed` und `failed`. `job-status.php` akzeptiert nur eine 32-stellige, kleingeschriebene hexadezimale Job-ID und liefert den Zustand als JSON. Der Browser legt den laufenden Job in `sessionStorage` ab (`job-watcher.php`); nach einem Neuladen oder Seitenwechsel setzt er das Polling dort fort. Sobald `completed` oder `failed` vorliegt, wird der Eintrag entfernt und ein nativer `<dialog>` mit dem Ergebnis geöffnet.

Eine automatische Bereinigung alter Web-Statusdateien ist noch nicht implementiert.

Der Trigger verwendet denselben Lock wie Cron:

```text
<projektpfad>/state/zeitraffer-run.lock
```

Dadurch können ein Web-Job, der nächtliche Produktionslauf und der Wiederanlauf nach einem Neustart nicht gleichzeitig arbeiten. Ist der Lock bereits belegt, meldet die Oberfläche, dass ein anderer Timelapse-Job läuft.

## Webtests

Wrapper, PHP-Helfer und Status-Endpunkt werden mit pytest geprüft (benötigt `php` auf der Kommandozeile):

```bash
python3 -m pytest tests/web_status_test.py tests/web_status_endpoint_test.py \
  tests/web_delete_test.py tests/web_php_test.py
```

- `web_status_test.py`: atomare Statuswechsel, ungültige Job-IDs, gemeinsamer Lock, Trigger-Validierung, erfolgreiche Videoveröffentlichung und fehlgeschlagene Jobs
- `web_status_endpoint_test.py`: JSON-Antworten von `job-status.php`
- `web_delete_test.py`: Lösch-Wrapper, u. a. Pfad-Traversal, Dateityp, Symlinks und dass automatische Videos unangetastet bleiben
- `web_php_test.py`: `video-library.php`, `process-runner.php`, `job-runner.php` und `video-delete.php`; die Tests kopieren `web/src` nach `tmp_path`, ersetzen dort die festen Pfade und verwenden ein Fake-`sudo`, sodass weder echte Videos noch installierte Wrapper berührt werden

Nicht automatisiert getestet sind `camera.php` und die Speicheranzeige (`getStorageUsage`), weil beide feste Pfade ohne Umleitungsmöglichkeit verwenden.
