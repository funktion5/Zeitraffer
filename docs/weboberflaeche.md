# Lokale Weboberfläche

Was die Weboberfläche kann, welche Dateien dazugehören und wie ein Video-Auftrag aus dem Browser abläuft. Die Einrichtung (Apache, Anmeldung, Wrapper, Dateirechte) steht in [installation.md](installation.md#weboberfläche-einrichten).


## Aktueller Funktionsumfang

Die Startseite listet die Kameras aus der Kameraliste `state/web-jobs/cameras.json` auf, die der
Nachtlauf schreibt. Die gesamte Oberfläche ist auf Deutsch; interne Bezeichner (`daily`/`weekly`/`monthly`/`yearly` in Formularwerten, URLs und der CLI) bleiben davon unberührt. Die Kameraseite bietet:

- Anzeige von gesamtem, verwendetem und freiem Speicherplatz des Dateisystems von `videos/`
- Liste **Automatische Videos** aus `videos/<camera>/<job>/`: Täglich die letzten 7,
  Wöchentlich/Monatlich/Jährlich jeweils das neueste. Nur ansehen und herunterladen, kein
  Löschen (die Aufräumregel entfernt sie); die Auswahl trägt `source=auto` in der URL, weil
  derselbe Dateiname auch unter den manuellen Videos vorkommen kann
- Bibliothek der historischen Videos unter `videos/<camera>/manual-runs/`, mit kurzem deutschem Datum statt Dateiname (plus Zeitpuffer in Minuten, sofern der Dateiname einen trägt, z. B. „24.09.2026 (60 Min.)“, bzw. das Zeitfenster bei Monthly/Yearly, z. B. „30.06.2025 (Sonnenuntergang ±60 Min.)“); die Liste bleibt für den Job-Typ des gerade ausgewählten Videos aufgeklappt
- Das gerade abgespielte Video ist in seiner Liste hervorgehoben (`aria-current`, auch für Screenreader)
- Wiedergabe des ausgewählten MP4 direkt im Browser, mit Download- und Löschen-Button (Icon + Beschriftung); nur Löschen fragt vorher in einem Bestätigungsdialog nach
- Formular für genau eine Kamera, einen Job-Typ und ein Zieldatum; bei Daily/Weekly zusätzlich ein Zeitpuffer (30/60/90 Minuten) als Radiogruppe, die nur für diese beiden Job-Typen eingeblendet wird — Monthly/Yearly nutzen keinen Zeitpuffer und erhalten ihn serverseitig auch dann nicht, wenn einer übermittelt würde. Das Zieldatum steht anfangs auf gestern, Tage nach heute sind gesperrt (beides nach der Uhr des Browsers). Nach dem Absenden ist der Button gesperrt, bis der in diesem Browser-Tab gestartete Auftrag fertig ist (Abschlussdialog); die Seite leitet nach dem Start einmal weiter (Post/Redirect/Get), Neuladen oder ein Doppelklick startet den Auftrag also nicht ein zweites Mal. Aufträge aus anderen Tabs oder von anderen Geräten sperren den Button nicht (ein Start meldet dann „Es läuft bereits ein anderer Zeitraffer-Auftrag.“), aber jede Seite (Kameraübersicht, Kameraseite und Highlights) fragt alle fünf Sekunden `running-job.php` und zeigt im Hinweisstreifen ganz oben, mit einem Drehsymbol, „Gerade läuft ein Auftrag. Ein neues Video kann erst danach gestartet werden.“, solange irgendein Web-Auftrag läuft (ohne Kamera, Job-Typ und Datum: die kennt nur der Tab, der ihn gestartet hat). Der nächtliche Lauf, der Flagger und die Werkzeuge belegen dieselbe Laufsperre, stehen aber in keiner Statusdatei und erscheinen darin nicht
- bei Monthly/Yearly eine Radiogruppe „Zeitfenster“: „Mittag (Standard)“ übergibt nichts (es gilt `interval_window` aus der Config), „Sonnenuntergang“ übergibt `sunset` plus eine Fensterbreite von ±30/60/90 Minuten (eigene Radiogruppe, nur bei Sonnenuntergang sichtbar); serverseitig sind nur diese Werte erlaubt
- kurzer Hinweistext über dem Formular: Zieldatum ist immer der letzte Tag des Zeitraums; Monthly braucht mindestens 25 der 30 Tage, Yearly mindestens 300 Tage mit Bildern im gewählten Zeitfenster (`min_coverage_days`), fehlende Tage werden im Video übersprungen
- historische Daily-, Weekly-, Monthly- und Yearly-Läufe
- bei Kameras aus `privacy.blur_cameras` ein Hinweis unter dem Formular: Die Bilder werden vorher
  automatisch verpixelt, die Erstellung dauert deshalb deutlich länger. Er gilt für jeden Job-Typ und
  nennt deshalb keinen; Kameras ohne Verpixelung zeigen ihn nicht. Was dahinter passiert:
  [verpixelung-box.md](verpixelung-box.md#verpixelung-bei-von-hand-gestarteten-videos)
- Live-Status per Polling im Abstand von fünf Sekunden, als Hinweisstreifen mit Drehsymbol ganz oben auf jeder Seite (er liegt im gemeinsamen Header, `header.php`, und ist ohne laufenden Auftrag unsichtbar; bei einer anderen Kamera steht deren Name dabei) samt Hinweis, dass ein neues Video erst danach starten kann; der Abschlussdialog übersteht auch einen Seitenwechsel weg von der auslösenden Seite (Fortsetzung des Pollings über `sessionStorage`) und bietet einen direkten Link zum fertigen Video an
- Löschen eines historischen Videos über denselben eingeschränkten Wrapper-Mechanismus wie die Job-Erstellung. Das Löschen läuft im Hintergrund: der Eintrag verschwindet, die Liste bleibt offen und die Seite lädt nicht neu; wird das gerade laufende Video gelöscht, lädt die Seite ohne es neu (gleiche Liste offen). Ein erfolgreiches Löschen zeigt die grüne Meldung „Video erfolgreich gelöscht.“ unter der Überschrift, über dem Videoplayer; sie bleibt, bis die Seite neu geladen oder verlassen wird oder ein anderes Video geöffnet wird (ein Zeitgeber ist nicht nötig). Zusätzlich meldet ein unsichtbarer Statusbereich es an Screenreader. Schlägt das Löschen fehl, steht der Grund im Bestätigungsdialog. Ohne JavaScript läuft es wie bisher als Formular mit Weiterleitung
- **Automatische Videos neu erstellen und hochladen**: eine aufklappbare Leiste (zu, solange man sie nicht öffnet) mit zwei nummerierten Abschnitten, Schritt 1 „Neu erstellen wie der Nachtlauf“ und Schritt 2 „Auf die Website übertragen“. Aufbau und Ablauf stehen weiter unten: [Neu erstellen wie der Nachtlauf](#neu-erstellen-wie-der-nachtlauf) und [Auf die Website übertragen](#auf-die-website-übertragen)

Die Seite **Highlights** (`/highlights.php`, Link im Header) zeigt die vom [Highlights-Flagger](flagger.md) markierten Bilder pro Kamera und Tag, mit Zeitraum- und Kamerafilter, Großansicht per Klick (Blättern mit den Pfeiltasten), Download und Löschen (Bestätigungsdialog, eigener Lösch-Wrapper). Details: [docs/highlights-seite.md](highlights-seite.md).

Beide Listen lesen nur die vier Job-Ordner (`daily`, `weekly`, `monthly`, `yearly`); `highlights/` und `manual-runs/` erscheinen also nie als Job. Versteckte Dateien werden nicht gelistet, darunter `.<name>.tmp.mp4` eines laufenden Renderings, das so weder abgespielt noch gelöscht werden kann. Gelöscht werden können nur manuelle Videos: das Löschen prüft gegen die Liste der manuellen Videos, der Lösch-Wrapper lehnt automatische ab. Eine Status-Datei-Bereinigung ist nicht implementiert.

Die Kameraerkennung der Weboberfläche ignoriert versteckte Verzeichnisse und blendet zusätzlich alle Kameras aus `ignored_cameras` in `config/config.json` aus (`getIgnoredCameras()` in `web/src/video-library.php`). Die Weboberfläche benötigt deshalb Lesezugriff auf `config/config.json`; dieselbe Datei liefert über `getBlurCameras()` die Kameras aus `privacy.blur_cameras` für den Verpixelungs-Hinweis.

## Webdateien

```text
web/public/index.php               Kameraübersicht
web/public/camera.php              Player, Bibliothek, Formulare (historisches Video, Neu erstellen, Upload) und Status-Polling
web/public/highlights.php          Highlights-Seite (Bilder des Flaggers, Löschen)
web/public/job-status.php          read-only JSON-Status-Endpunkt (inkl. Tote-Prozess-Erkennung und Ergebniszeilen)
web/public/running-job.php         read-only JSON: läuft gerade irgendein Web-Auftrag? (Hinweisstreifen auf jeder Seite)
web/public/style.css               Darstellung und responsives Layout
web/src/components/header.php      gemeinsamer Header, Speicheranzeige und Hinweisstreifen „Auftrag läuft“
web/src/components/job-watcher.php gemeinsamer Abschlussdialog (mit Ergebniszeilen), seitenübergreifendes Polling
web/src/components/confirm-delete.php gemeinsamer Bestätigungsdialog, löscht im Hintergrund
web/src/video-library.php          Kamera-, Video- und Speicherermittlung, Vorschau der Dateien für den Upload
web/src/job-runner.php             Aufruf des fest installierten Triggers
web/src/rebuild-runner.php         Aufruf des Triggers zum Neuerstellen der automatischen Videos
web/src/publish-runner.php         Aufruf des Triggers für den Upload einer Kamera
web/src/job-state.php              Auftragsstatus aus den Statusdateien (Tote-Prozess-Erkennung, läuft ein Auftrag?, Ergebniszeilen)
web/src/video-delete.php           Aufruf des fest installierten Lösch-Wrappers
web/src/highlights-library.php     Lesen und Prüfen der Flagger-Berichte
web/src/highlight-delete.php       Aufruf des Lösch-Wrappers für Highlight-Bilder
web/src/process-runner.php         gemeinsame proc_open-Hilfsfunktion (Trigger und Löschen)
web/src/json-response.php          gemeinsame JSON-Antwort (Status-Endpunkt und Löschen im Hintergrund)
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
meldet `job-status.php` `failed`, damit der Browser nicht endlos wartet. Dasselbe gilt, wenn nach
über einer Minute noch gar keine `.pid` da ist (der Worker schreibt sie in der ersten Sekunde; fehlt
sie, ist er nie richtig gestartet). Die Statusdatei selbst bleibt dabei unverändert. Ein Neuerstellen und ein Upload schreiben zusätzlich `<job-id>.result` mit je einer deutschen Ergebniszeile (Aufbau in den Abschnitten unten).

Endet ein Auftrag ohne Video, schreibt der Worker vor `failed` die Ursache nach
`<job-id>.reason`: die letzte Warnung von `src.main` mit „- skipping“ (die Konsolenausgabe hebt
er dafür während des Laufs in einer temporären Datei auf). Spätere Hinweise wie der Bildzeitraum
nach einem übersprungenen Daily zählen nicht als Ursache. `job-status.php` übersetzt bekannte
Ursachen ins Deutsche und gibt sie als `reason` mit (zu wenige Tage mit Bildern im Zeitfenster,
Woche nicht vollständig, keine Bilder am Tag, keine verwendbaren Bilder, Verpixelung nicht fertig oder von einer anderen Verpixelung belegt); unbekannter Text wird nie an den
Browser weitergegeben, der Dialog zeigt dann den allgemeinen Hinweis. Die Änderung am Worker
wirkt erst nach dem erneuten `sudo install` ([Installation – Wrapper installieren](installation.md#wrapper-installieren)).

Erlaubte Inhalte sind ausschließlich `running`, `completed` und `failed`. `job-status.php` akzeptiert nur eine 32-stellige, kleingeschriebene hexadezimale Job-ID und liefert den Zustand als JSON. Nach dem Start reicht `camera.php` die Auftragsdaten über die PHP-Session (`started_job`, einmalig gelesen) an die nächste Seite weiter; der Browser legt den laufenden Job dann in `sessionStorage` ab (`job-watcher.php`); nach einem Neuladen oder Seitenwechsel setzt er das Polling dort fort. Sobald `completed` oder `failed` vorliegt, wird der Eintrag entfernt und ein nativer `<dialog>` mit dem Ergebnis (bei `failed` mit der Ursache, falls bekannt) geöffnet. Holt der Browser eine Seite mit „Zurück“ aus seinem Zwischenspeicher, nimmt er das Warten dort wieder auf; ist der Auftrag inzwischen auf einer anderen Seite fertig gemeldet worden, hört die alte Abfrage auf, statt das Ergebnis ein zweites Mal zu zeigen. Eine fehlgeschlagene Abfrage (Netz weg, Pi beschäftigt) beendet das Warten nicht: der Browser fragt fünf Sekunden später erneut. Meldet der Endpunkt den Auftrag als unbekannt (404, Statusdatei entfernt), wird der Eintrag verworfen und der Button wieder freigegeben.

Eine automatische Bereinigung alter Web-Statusdateien ist noch nicht implementiert.

Der Trigger verwendet denselben Lock wie Cron:

```text
<projektpfad>/state/zeitraffer-run.lock
```

Dadurch können ein Web-Job, der nächtliche Produktionslauf und der Wiederanlauf nach einem Neustart nicht gleichzeitig arbeiten. Ist der Lock bereits belegt, meldet die Oberfläche, dass ein anderer Timelapse-Job läuft. Ein Auftrag einer Blur-Kamera dauert wegen der Verpixelung lange (gemessen: ein Monatsvideo mit 360 Bildern 55 Minuten) und hält den Lock die ganze Zeit; läuft er über 02:00 hinaus, fällt der Nachtlauf aus.

## Neu erstellen wie der Nachtlauf

Für den Fall, dass eine Kamera in der Nacht kein Video bekommen hat. Die Kameraseite hat dafür die aufklappbare Leiste „Automatische Videos neu erstellen und hochladen“; sie ist zu, solange man sie nicht öffnet. Schritt 1 darin:

- Ein Kästchen je Videoart (Täglich, Wöchentlich, Monatlich, Jährlich), anfangs alle leer; der Button bleibt gesperrt, bis eines angekreuzt ist. Die Videos entstehen wie im Nachtlauf: ohne Zieldatum (Täglich für den letzten abgeschlossenen Tag), mit den Einstellungen der Config, in `videos/<Kamera>/<Videoart>/` und nicht unter `manual-runs/`. Ein neu erstelltes Video ersetzt das vorhandene; die Aufräumregeln gelten wie nachts.
- Die Reihenfolge ist immer Täglich, Wöchentlich, Monatlich, Jährlich, jede Videoart einmal, gleich was der Browser sendet (das erledigt `src.main`). Wöchentlich wird aus den vorhandenen Täglich-Videos gebaut: Fehlt ein Tagesvideo, Täglich mit ankreuzen.
- Kameras aus `privacy.blur_cameras` verwenden wie nachts nur bestätigt verpixelte Bilder und verpixeln hier nichts selbst; ohne bestätigtes Bild wird die Kamera übersprungen ([Sperre in automatischen Videos](verpixelung-box.md#sperre-in-automatischen-videos)).

Ablauf:

```text
camera.php  (Aktion rebuild-jobs: CSRF-Token, Kamera, Videoarten)
  → rebuild-runner.php:
    sudo -n -u <benutzer> /usr/local/sbin/timelapse-web-rebuild <job-id> <kamera> <job> [<job> ...]

timelapse-web-rebuild
  → validiert Job-ID, Kamera (einfacher Name, in der Kameraliste) und 1 bis 4 Videoarten
  → belegt state/zeitraffer-run.lock ohne Warten (belegt: Exit 75)
  → schreibt running
  → startet timelapse-web-worker-rebuild im Hintergrund

timelapse-web-worker-rebuild
  → startet python3 -m src.main --jobs ... --cameras <kamera>   (ohne --target-date)
  → schreibt <job-id>.result, danach completed oder failed
```

Ein Lauf mit `--jobs`, aber ohne `--target-date`, ist kein Produktionslauf: der Marker `state/run-in-progress` wird nicht angelegt ([cli.md](cli.md#einzelne-automatische-jobs)).

Das Ergebnis: Der Worker liest aus der Ausgabe von `src.main` die Zusammenfassungszeile jedes Jobs (`… timelapse job finished … | created=1 | skipped=0 | failed=0`) und schreibt je Job eine Zeile nach `state/web-jobs/<job-id>.result`, zum Beispiel `Täglich: 1 erstellt, 0 übersprungen, 0 fehlgeschlagen`. `job-status.php` gibt sie als `results` mit (höchstens 8 Zeilen); der Abschlussdialog („Neu erstellen abgeschlossen“) listet sie unter der Meldung. Der Status ist `completed`, wenn `src.main` ohne Fehler endete. Ein übersprungenes Video (zu wenige Tage, kein bestätigtes Bild) und eine Kamera, die in einem Job fehlgeschlagen ist, stehen nur in der Zeile, nicht im Status. Ein Absturz von `src.main` ergibt `failed`, mit `.reason` wie bei den anderen Aufträgen.

Gut zu wissen:

- Die Laufsperre ist die ganze Zeit belegt: Kein anderer Auftrag und kein Nachtlauf kann starten. Gemessen: Ein Daily einer Kamera ohne Verpixelung brauchte unter einer halben Minute; Monthly und Yearly dauern länger.
- Ein neu erstelltes Video ist das neueste seiner Videoart. Der Upload der nächsten Nacht sendet es also auch, ohne dass jemand etwas tut; der Abschnitt darunter macht es nur früher.
- Nach einer abgelehnten Anfrage (nichts angekreuzt, unbekannter Wert, ungültiger Token, Sperre belegt) bleibt die Leiste offen, und die Meldung steht im Abschnitt.

## Auf die Website übertragen

Schritt 2 in derselben Leiste, nur sichtbar, wenn die Kamera automatische Videos hat. Er sendet dieselben Dateien wie der nächtliche Upload ([betrieb.md](betrieb.md#upload-auf-die-website)), aber nur für diese eine Kamera:

- Der Abschnitt zeigt vorher die Dateien: je Videoart das neueste automatische Video (`newestAutomaticVideos()` in `web/src/video-library.php`). Das ist eine Vorschau mit denselben Regeln wie `scripts/list-deliverable-videos.py`: nur die vier Videoordner direkt unter der Kamera, keine Symlinks, nur reguläre, nicht leere, nicht versteckte Dateien mit der Endung `.mp4` in Kleinschreibung, das neueste nach Dateiname. Maßgeblich bleibt das Skript: Ändert sich ein neuestes Video zwischen Anzeige und Klick, geht das neuere.
- Der Text sagt, was der Upload tut: Dateien, die schon mit gleicher Größe auf der Website liegen, werden übersprungen, und ältere Videos dort werden gelöscht, von jeder Videoart bleiben die zwei neuesten.
- Bestätigt wird mit dem Kästchen „Ja, diese Videos jetzt auf die Website übertragen“. Der Server nimmt nur `confirm` mit genau dem Wert `yes` an (zusätzlich zu Token und Kamera); jeder andere Wert, auch ein leerer oder ein Array, wird abgelehnt. Der gesperrte Button im Browser ersetzt diese Prüfung nicht.
- Vom Browser kommt nur der Kameraname. Host, Zugangsdaten, Ordner und Dateinamen kommen nie aus dem Browser.

Ablauf:

```text
camera.php  (Aktion publish-camera: CSRF-Token, Kamera, confirm=yes)
  → publish-runner.php:
    sudo -n -u <benutzer> /usr/local/sbin/timelapse-web-publish <job-id> <kamera>

timelapse-web-publish
  → validiert Job-ID und Kamera (einfacher Name, in der Kameraliste), genau 2 Argumente
  → belegt state/zeitraffer-run.lock ohne Warten (belegt: Exit 75)
  → schreibt running
  → startet timelapse-web-worker-publish im Hintergrund

timelapse-web-worker-publish
  → startet scripts/copy_zeitraffer_videos_vps2siteground.sh <kamera> --run
  → hängt die Ausgabe an logs/siteground-delivery.log an
  → schreibt <job-id>.result, danach completed oder failed
```

Die Ausgabe des Skripts bleibt in einer privaten temporären Datei und im Protokoll `logs/siteground-delivery.log` (dasselbe wie beim Nachtlauf; der Worker legt es nur für den Projektbenutzer lesbar an, weil die ausführliche Ausgabe von `curl` den FTP-Zugang enthält). Zum Browser gelangen nur die Zahlen der Ergebniszeile, als eine deutsche Zeile in `<job-id>.result`: `Hochgeladen: 1, übersprungen: 2, fehlgeschlagen: 0, gelöscht: 1`. Der Status ist `completed`, wenn das Skript mit `0` endet, die Ergebniszeile da ist und `fehlgeschlagen` 0 ist. Sonst ist er `failed`: Eine leere Liste, fehlende Zugangsdaten (Exit 2) und ein anderer Upload derselben Kamera, etwa der nächtliche (Exit 3, eigene Sperre `state/siteground-delivery-<Kamera>.lock`), enden ohne Ergebniszeile. Der Dialog sagt dann „Bitte das Anwendungsprotokoll prüfen“; die Ursache steht im Protokoll ([Handbuch](handbuch.md#hochladen-schlägt-fehl)).

Der Trigger nimmt dieselbe Laufsperre wie alle anderen Aufträge: Während eines Uploads läuft kein Video-Auftrag und umgekehrt. Beide Wrapper-Paare (Neuerstellen und Upload) installiert `./install.sh` im Schritt `web_bridge` samt sudoers-Regeln; von Hand: [Installation – Wrapper installieren](installation.md#wrapper-installieren).

## Webtests

Wrapper, PHP-Helfer und Status-Endpunkt werden mit pytest geprüft (benötigt `php` auf der Kommandozeile):

```bash
python3 -m pytest tests/web
```

- `web_status_test.py`: atomare Statuswechsel, ungültige Job-IDs, gemeinsamer Lock, Trigger-Validierung, erfolgreiche Videoveröffentlichung, fehlgeschlagene Jobs und die Fehlergrund-Datei `.reason` des Workers
- `web_status_endpoint_test.py`: JSON-Antworten von `job-status.php`, inklusive Übersetzung bekannter Fehlergründe und `failed` für einen Auftrag ohne `.pid` nach einer Minute, sowie `running-job.php` (läuft irgendein Web-Auftrag: lebender Worker, tote Prozesse, frischer Start ohne PID, fremde Dateien im Ordner), sowie die Ergebniszeilen (`results`), wenn eine `.result`-Datei da ist
- `web_delete_test.py`: Lösch-Wrapper, u. a. Pfad-Traversal, Dateityp, Symlinks und dass automatische Videos unangetastet bleiben
- `web_php_test.py`: `video-library.php`, `process-runner.php`, `job-runner.php`, `rebuild-runner.php`, `publish-runner.php`, `job-state.php` (Ergebniszeilen) und `video-delete.php`; in `video-library.php` auch `newestAutomaticVideos()` (Vorschau des Uploads, mit Randfällen wie leeren, versteckten und verlinkten Dateien); die Tests kopieren `web/src` nach `tmp_path`, ersetzen dort die festen Pfade und verwenden ein Fake-`sudo`, sodass weder echte Videos noch installierte Wrapper berührt werden
- `web_camera_page_test.py`: `camera.php` als Ganzes (Kopie in `tmp_path`, Kamerapfad und `sudo` ersetzt): beide Listen, Auswahl über `source=auto`, Lese-Schutz der automatischen Videos, ungültige Parameter, Markierung des laufenden Videos, Löschen per `response=json`, Weiterleitung nach dem Start (Post/Redirect/Get), Verpixelungs-Hinweis nur bei Blur-Kameras. die Leiste (zu, nach einer abgelehnten Anfrage offen), das Neuerstellen-Formular, der Upload-Abschnitt mit der strengen Bestätigung (`yes` und nichts sonst) und der Hinweisstreifen im Header. Die gemeinsame Hilfsfunktion `render_page()` dafür liegt in `web_php_test.py`
- `web_rebuild_test.py`: Trigger und Worker des Neuerstellens (Argumente, Kameraliste, Laufsperre, Aufruf von `src.main` ohne `--target-date`, Ergebniszeilen)
- `web_publish_test.py`: Trigger und Worker des Uploads (genau zwei Argumente, `--run`, Ergebniszeile, `failed` ohne Ergebniszeile, privates Protokoll, und dass der FTP-Zugang nie in die Statusdateien gelangt)

Die Tests der Highlights-Seite stehen in [highlights-seite.md](highlights-seite.md#dateien-und-tests).

Nicht automatisiert getestet sind die Speicheranzeige (`getStorageUsage`) und das JavaScript der Seiten.
