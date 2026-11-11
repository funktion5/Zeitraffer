# Lokale Weboberfläche

Was die Weboberfläche kann, welche Dateien dazugehören und wie ein Video-Auftrag aus dem Browser abläuft. Die Einrichtung (Apache, Anmeldung, Wrapper, Dateirechte) steht in [installation.md](installation.md#weboberfläche-einrichten).


## Aktueller Funktionsumfang

Die Startseite listet die Kameras aus der Kameraliste `state/web-jobs/cameras.json` auf, die der
Nachtlauf schreibt, jede mit der Größe ihrer Videos ([Speicheranzeige](#speicheranzeige)). Die gesamte Oberfläche ist auf Deutsch; interne Bezeichner (`daily`/`weekly`/`monthly`/`yearly` in Formularwerten, URLs und der CLI) bleiben davon unberührt. Die Kameraseite bietet:

- Speicheranzeige im Header (auf jeder Seite): ein Ring mit der Aufteilung des Platzes, gesamter, belegter und freier Speicher des Dateisystems von `videos/`, die Größe der Videos und eine Warnung, wenn es eng wird. Aufbau: [Speicheranzeige](#speicheranzeige)
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

Die Seite **Einstellungen** (Link mit Zahnrad ganz rechts im Header) hat zwei Reiter, **Allgemein** und **Verpixelung**. Dort ändern die Kolleginnen und Kollegen eine festgelegte Auswahl der Werte aus `config/config.json`, ohne die Datei anzufassen. Aufbau, Grenzen und Ablauf: [Einstellungen](#einstellungen). Über den Reitern steht auf beiden Seiten das Feld **Speicher** mit zwei Ringen und einer Liste: [Speicheranzeige](#speicheranzeige).

Beide Listen lesen nur die vier Job-Ordner (`daily`, `weekly`, `monthly`, `yearly`); `highlights/` und `manual-runs/` erscheinen also nie als Job. Versteckte Dateien werden nicht gelistet, darunter `.<name>.tmp.mp4` eines laufenden Renderings, das so weder abgespielt noch gelöscht werden kann. Gelöscht werden können nur manuelle Videos: das Löschen prüft gegen die Liste der manuellen Videos, der Lösch-Wrapper lehnt automatische ab. Eine Status-Datei-Bereinigung ist nicht implementiert.

Die Kameraerkennung der Weboberfläche ignoriert versteckte Verzeichnisse und blendet zusätzlich alle Kameras aus `ignored_cameras` in `config/config.json` aus (`getIgnoredCameras()` in `web/src/video-library.php`). Die Weboberfläche benötigt deshalb Lesezugriff auf `config/config.json`; dieselbe Datei liefert über `getBlurCameras()` die Kameras aus `privacy.blur_cameras` für den Verpixelungs-Hinweis.

## Webdateien

```text
web/public/index.php               Kameraübersicht, je Kamera die Größe ihrer Videos
web/public/camera.php              Player, Bibliothek, Formulare (historisches Video, Neu erstellen, Upload) und Status-Polling
web/public/highlights.php          Highlights-Seite (Bilder des Flaggers, Löschen)
web/public/settings.php            Einstellungen, Reiter „Allgemein“
web/public/verpixelung.php         Einstellungen, Reiter „Verpixelung“ (Vorschaubild, Zeichen-Editor, Bestätigungsdialog)
web/public/settings-common.js      Skript, das beide Einstellungs-Reiter teilen: Regler, „Auf Standard zurücksetzen“, „Änderungen verwerfen“
web/public/verpixelung.js          Skript des Reiters „Verpixelung“: Rahmenzeilen, Zeichen-Editor, „Vorschau aktualisieren“, Bestätigungsdialog
web/public/storage-ring.js         Skript des Feldes „Speicher“: das sofortige Textfeld über einem Bogen der Ringe
web/public/preview.php             liefert das zwischengespeicherte Vorschaubild einer Blur-Kamera (nur JPEG)
web/public/preview-refresh.php     „Vorschau aktualisieren“: holt ein neues Bild, antwortet mit JSON
web/public/job-status.php          read-only JSON-Status-Endpunkt (inkl. Tote-Prozess-Erkennung und Ergebniszeilen)
web/public/running-job.php         read-only JSON: läuft gerade irgendein Web-Auftrag? (Hinweisstreifen auf jeder Seite)
web/public/style.css               Darstellung und responsives Layout
web/src/components/header.php      gemeinsamer Header, Speicherring mit Warnstufe und Hinweisstreifen „Auftrag läuft“
web/src/components/storage-panel.php  das Feld „Speicher“ über den Einstellungs-Reitern: zwei Ringe und die Liste
web/src/components/job-watcher.php gemeinsamer Abschlussdialog (mit Ergebniszeilen), seitenübergreifendes Polling
web/src/components/confirm-delete.php gemeinsamer Bestätigungsdialog, löscht im Hintergrund
web/src/components/settings-tabs.php  Reiterleiste „Allgemein | Verpixelung“
web/src/video-library.php          Kamera-, Video- und Speicherermittlung (Größen, Aufteilung, Warnstufe, Teile der Ringe), Vorschau der Dateien für den Upload
web/src/job-runner.php             Aufruf des fest installierten Triggers
web/src/rebuild-runner.php         Aufruf des Triggers zum Neuerstellen der automatischen Videos
web/src/publish-runner.php         Aufruf des Triggers für den Upload einer Kamera
web/src/job-state.php              Auftragsstatus aus den Statusdateien (Tote-Prozess-Erkennung, läuft ein Auftrag?, Ergebniszeilen)
web/src/video-delete.php           Aufruf des fest installierten Lösch-Wrappers
web/src/highlights-library.php     Lesen und Prüfen der Flagger-Berichte
web/src/highlight-delete.php       Aufruf des Lösch-Wrappers für Highlight-Bilder
web/src/process-runner.php         gemeinsame proc_open-Hilfsfunktion (Trigger, Löschen, Einstellungen, Vorschau) und das Lesen der einen JSON-Zeile eines Wrappers
web/src/project-config.php         liest config.json mit den beiden Einstellungsdateien darüber (dieselben Werte wie die Aufträge)
web/src/settings-form.php          Felder des Reiters „Allgemein“, die Umrechnung zwischen Formular und Werten und `assetUrl()` (Adresse eines Skripts mit der Änderungszeit der Datei als Version)
web/src/privacy-form.php           dasselbe für „Verpixelung“, mit den Erklärtexten
web/src/settings-runner.php        Aufruf des Speicher-Wrappers
web/src/preview-runner.php         Aufruf des Vorschau-Wrappers, Lesen und Prüfen des Zwischenspeichers
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

## Speicheranzeige

Der Speicher wird an drei Stellen gezeigt. Gemessen werden nur Dateigrößen; alle Zahlen kommen aus
`web/src/video-library.php`.

**Was gemessen wird.** `getVideoStorage()` zählt die Dateien unter `videos/<Kamera>/` und teilt sie je Kamera
in vier Gruppen: **automatische Videos** (`daily`, `weekly`, `monthly`, `yearly`), **manuelle Videos**
(`manual-runs/`), **Highlight-Bilder** (`highlights/`) und **Übriges** (alles andere im Kameraordner). Jeder
Kameraordner zählt, auch die Kameras aus `ignored_cameras`: Sie füllen die Platte trotzdem. Nicht gezählt
werden Symlinks, lose Dateien neben den Kameraordnern, versteckte Ordner und nicht lesbare Unterordner. Die
Bilder der Kameras auf der Storage Box gehören nicht dazu. „Gesamt“, „Belegt“ und „Verfügbar“ sind das
Dateisystem, auf dem `videos/` liegt: Auf dem VPS ist das die ganze Platte, nicht nur die Videos (Stand der
Messung: rund 2,8 GB Videos auf einer 38-GB-Platte). Ein Durchlauf kostet nichts Merkliches: ein `du` über
589 Dateien dauerte auf dem VPS wenige Millisekunden, deshalb gibt es keinen Zwischenspeicher.

**Header (jede Seite).** Ein Ring und vier Felder: **Gesamt**, **Belegt**, **Verfügbar** und **Davon Videos**
(nur echte Videos: automatische plus manuelle; die Highlight-Bilder haben einen eigenen Teil im Ring). Der Ring
besteht aus fünf Bögen in dieser Reihenfolge: automatische Videos, manuelle Videos, Highlight-Bilder,
Übriges (System, Modelle, Protokolle) und Frei. Ein Teil ohne Inhalt bekommt keinen Bogen. Fährt man mit der
Maus über einen Bogen, erscheint **sofort** ein Textfeld mit dem Namen, der Größe und dem Anteil. Das ist
reines CSS (`:has()`), weil das eingebaute Titel-Tooltip des Browsers erst nach einer Verzögerung kommt. Für
Screenreader trägt der Ring ein `aria-label` mit allen Teilen. Die **Warnstufe** (`storageLevel()`): ab 80 %
Belegt färbt sich die Zahl im Ring amber und daneben steht „Speicher wird knapp“, ab 90 % rot mit „Speicher
fast voll“. Die Farbe allein genügt nie, der Text steht immer dabei.

**Kameraliste (Startseite).** Jede Kamera trägt eine Kapsel, zum Beispiel „519.0 MB Videos“, oder „keine
Videos“. Bewusst kein Balken und kein Prozentwert: Neben dem Ring läse man ihn als Anteil an der Platte.

**Feld „Speicher“ (beide Einstellungs-Reiter).** Es steht unter der Überschrift „Einstellungen“ und über den
Reitern (`web/src/components/storage-panel.php`). Links zwei Ringe nebeneinander, rechts die Liste:

- **„Der ganze Speicher“:** die Kameras, Übriges und Frei, zusammen die ganze Platte. Auf dem VPS sind die
  Kameras darin nur dünne Linien, weil die Videos nur einen kleinen Teil der Platte belegen.
- **„Nur die Videos“:** nur die Kameras, jede ein eigenes Stück. Dieser Ring ist der bunte; die Mitte nennt
  die Gesamtgröße der Kameraordner, also auch mit den Highlight-Bildern (anders als „Davon Videos“ im Header,
  das nur echte Videos zählt).
- **Die Liste** nennt jeden Teil mit Farbpunkt und Größe, ohne Prozentspalte: Die beiden Ringe haben
  verschiedene Grundlagen, die in einer Spalte nicht nebeneinander stehen sollen.
- **Die Prozentwerte** stehen nur im Textfeld über einem Bogen und nennen ihre Grundlage: „% des Speichers“
  beim ganzen Ring, „% der Videos“ beim Videoring. Das Textfeld kommt von `web/public/storage-ring.js`
  (ein Skript und ein Feld für alle Bögen, gelesen aus `data-tip`).
- **Farben:** Die sechs größten Kameras haben je eine feste Farbe (`--chart-1` bis `--chart-6`, in
  `style.css`), in beiden Ringen dieselbe. Alle weiteren werden zu „Weitere Kameras (n)“ (`--chart-7`); bleibt
  nur eine übrig, steht sie mit Namen da.
- **Schmale Fenster:** Unter etwa 56 rem Breite rutscht die Liste unter die Ringe.

Die Teile berechnen `storageCameraParts()` (Kameras, Übriges, Frei; Summe immer die ganze Platte),
`storageVideoParts()` (nur die Kameras, je als Anteil der Videos) und `storageArcs()` (die Bögen: ein Kreis
mit `pathLength="100"`, eine Strichlänge ist also ein Prozent).

**Grenzen.** Das Textfeld erscheint nur mit der Maus, nicht per Tastatur; Screenreader bekommen das Label des
Rings und die Liste. Im Docker-Testsystem zeigt die Anzeige die virtuelle Platte von Docker Desktop, nicht den
freien Platz des Rechners ([docker-web.md](docker-web.md)).

## Einstellungen

Zwei Reiter, jeder eine eigene Seite mit eigenem Formular, eigenem Speichern-Knopf und eigener Datei. Eine Speicherung im einen Reiter kann den anderen deshalb weder überschreiben noch veraltet machen. Die IT ändert weiter `config/config.json`; was auf der Seite einstellbar ist und was nicht, legt `src/settings.py` fest ([konfiguration.md](konfiguration.md#einstellungen-der-weboberfläche)).

Für beide Reiter gilt:

- **Anzeige:** Die Seite zeigt die Werte, die gerade gelten (`config.json` mit den gespeicherten Änderungen darüber). Hinter jedem Feld steht „Standard: …“, das ist der Wert aus `config.json`, auch bei den Kameralisten („alle außer X“, die Namen, „keine“) und den Rahmen („2 Rahmen“).
- **Zurücksetzen:** „Auf Standard zurücksetzen“ je Abschnitt und „Alles auf Standard“ in der unteren Leiste tragen den Standard ein und speichern nichts; „Änderungen verwerfen“ geht zu den geladenen Werten zurück. Die Standard-Knöpfe erscheinen erst mit JavaScript und wirken nur im eigenen Reiter.
- **Speichern:** Wie auf den anderen Seiten prüft der Server das Sitzungs-Token (`hash_equals`) und nimmt nur die Bestätigung mit genau dem Wert `yes` an; gelesen werden nur die festen Felder des Formulars. Ein ungültiger Wert speichert nichts: Die Seite listet jeden Fehler, steht er an einem Feld, auch dort, und behält die Eingaben.
- **Veraltete Seite:** Das Formular trägt die Änderungszeit der Einstellungsdatei (ganze Sekunden). Hat sich die Datei seit dem Laden geändert, wird nichts gespeichert und die Seite sagt „Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden.“ Zwei Speicherungen in derselben Sekunde können an dieser Prüfung vorbeirutschen. Ohne Datei zählt die Zeit 0.
- **Wirkung:** Ab dem nächsten Auftrag; ein laufender ist nicht betroffen. Eine neue Qualität (CRF) gilt nur für Videos, die danach entstehen, bestehende bleiben.
- **Protokoll:** `logs/settings.log` bekommt je Speicherung eine Zeile mit Zeit, Bereich und den geänderten Schlüsseln (`[general] timelapse.crf: 28 -> 30`). Keine IP-Adresse, kein User-Agent; die Datei ist nur für den Projektbenutzer lesbar.

### Reiter „Allgemein“ (`/settings.php`)

25 Werte in Gruppen. Die Grenzen prüft der Server; die Felder im Browser zeigen sie nur an.

| Gruppe | Wert | Erlaubt |
|---|---|---|
| Videoqualität | `timelapse.crf` | ganze Zahl 18–35 |
| | `timelapse.daily_framerate`, `monthly_framerate`, `yearly_framerate` | je 1–60 |
| Kameras | `ignored_cameras` (je Kamera ein Haken; abgewählt = nicht verarbeitet) | Kameranamen, mindestens eine angehakt |
| Highlights | `flagger.cameras` (je Kamera ein Haken), `flagger.retention_days` | Kameranamen, keine unter „Kameras“ abgewählte; 7–365 (der Flagger startet mit weniger als einer Woche nicht) |
| Zeitfenster und Abdeckung | `daylight_buffer_minutes` | 0–240 |
| | `interval_window.target_time` (Mittagsbild: Zielzeit) | `10:00` bis `14:00`, Regler in 15-Minuten-Schritten |
| | `interval_window.tolerance_minutes` (± Minuten) | 1–120 |
| | `min_coverage_days.monthly`, `yearly` | 1–30; 1–365 (mehr Tage, als das Fenster hat, lässt den Auftrag abbrechen; das 366. Tag eines Schaltjahrs ist deshalb nicht wählbar) |
| Tageslicht-Puffer je Monat | `automatic_daylight_buffer_minutes` (zwölf Felder) | je 0–240 |
| Protokolle | `log_retention_days` | 1–365 |

- **Zielzeit und Abweichung:** Das Mittagsbild ist ein Tageslichtbild. Mit einer Zielzeit zwischen 10:00 und 14:00 und höchstens 120 Minuten Abweichung bleibt das Fenster in jedem Monat bei Tageslicht und innerhalb eines Kalendertags (die Fensterlogik lehnt ein Fenster über Mitternacht und eine Abweichung unter 1 ab). Neben dem Zeitfeld steht ein Regler, der erst mit JavaScript erscheint; das Zeitfeld bleibt die eigentliche Eingabe. `sunset` und andere Zeiten gibt es nur in `config.json` und per CLI.
- **Regler:** Neben der Zielzeit und den beiden Abdeckungs-Feldern (Monat 1–30, Jahr 1–365) steht ein Regler, der erst mit JavaScript erscheint; das Feld bleibt die eigentliche Eingabe, und gesendet wird nur sie. Die Abdeckung beginnt bei 1, nicht bei 0: Die Aufträge verlangen mindestens einen Tag.
- **Kameras:** Eine abgewählte Kamera verschwindet sofort aus der Kameraliste der Weboberfläche (die Seiten lesen die zusammengeführte Config) und wird nachts nicht mehr gebaut. Sie muss dann auch unter „Highlights“ abgewählt werden: Der Flagger sucht seine Kameras unter den nicht ignorierten, und steht dort eine ignorierte, startet er für alle Kameras nicht (`Requested cameras not found`). Deshalb speichert die Seite diese Kombination nicht und meldet „Unter „Kameras“ abgewählt, unter „Highlights“ aber noch angehakt: <Kamera>. Bitte auch dort abwählen.“ Wieder angehakt erscheint sie in der Kameraliste und hier nach dem nächsten Nachtlauf, denn die Liste schreibt der Nachtlauf (`state/web-jobs/cameras.json`) und die Weboberfläche hat keinen Zugriff auf die Box. Die Liste der Seite besteht aus dieser Kameraliste plus den bereits ignorierten Namen.
- **Nicht einstellbar,** mit Absicht: `location`, `timelapse.ffmpeg_threads` und `image_scan_stall_timeout_seconds` (falsche Werte können den VPS überlasten oder Aufträge hängen lassen). Die Verpixelung hat ihren eigenen Reiter.

### Reiter „Verpixelung“ (`/verpixelung.php`)

Die Seite ist eine Datenschutz-Einstellung und fragt deshalb vor jedem Speichern nach. Die Reihenfolge von oben nach unten:

1. **Welche Kameras werden verpixelt?** (`privacy.blur_cameras`) Je Kamera ein Haken. Kameras, die schon in `config.json` stehen, tragen die Markierung „läuft schon“; ein Hinweis „Wichtig!“ sagt, dass bei ihnen der Haken nicht weg darf, weil Menschen auf den Videos sonst sofort wieder zu erkennen sind. Eine neu angehakte Kamera wird ab der nächsten Nacht verpixelt, auch die Bilder von heute und den zwei Tagen davor ([verpixelung-box.md](verpixelung-box.md#konfiguration)).
2. **Wie wird verpixelt?** Drei Werte für alle Kameras: `privacy.blur.strength` (0,05–0,5, Größe der Kästchen), `padding_ratio` (0,05–1, wie weit der Schutz um einen Menschen reicht), `feather` (0–1, wie weich der Rand ist). Die Grenzen sind die, die der Verpixelungs-Code selbst erzwingt ([verpixelung.md](verpixelung.md#blur)). Sie wirken nur auf Bilder, die danach verpixelt werden.
3. **Ein Block je Verpixelungs-Kamera:**
   - *Mindest-Sicherheit* (`privacy.min_person_score.<Kamera>`, 0–0,5): Funde darunter werden nicht verpixelt.
   - *Oberer Bildrand* (`privacy.ignore_top_share_per_camera.<Kamera>`, 0 bis unter 0,5, 0 = aus): Funde, die überwiegend in diesem oberen Streifen liegen, gelten als Irrtum (Himmel, Dächer, Kamerahalterung) und werden nicht verpixelt. Der Wert **ersetzt** für diese Kamera den globalen `privacy.ignore_top_share` aus `config.json`; der globale Wert bleibt der Standard der IT und steht nicht auf der Seite. Ein Wert gleich dem Standard der Kamera wird nicht gespeichert, die Kamera folgt dann weiter dem globalen Wert.
   - *Vorschaubild* mit Zeichen-Editor (unten).
   - *Rahmen* (`privacy.ignore_boxes.<Kamera>`): Zeilen mit vier Zahlen `links, oben, rechts, unten` in Bildpunkten. Ein Fund, der einen Rahmen zu mindestens 50 % überlappt, wird verworfen. Höchstens 50 Rahmen je Kamera, Koordinaten bis 20 000.

Jedes Feld hat unter sich eine kurze Erklärung in einfachem Deutsch. Das Zahlenfeld ist die eigentliche Eingabe (Tastatur, Screenreader); der Regler daneben hilft nur der Maus und erscheint erst mit JavaScript. Ein Streifen oben und Rahmen sind zwei verschiedene Regeln: Der Streifen verwirft jeden Fund, der überwiegend in ihm liegt, ein Rahmen nur einen, der ihn zu mindestens 50 % überdeckt. Ein Rahmen kann den Streifen also nicht ersetzen.

**Vorschaubild und Editor.** Unter dem Wert für den Rand zeigt jeder Block ein echtes Bild der Kamera. Es ist immer ein Bild, das der Box-Job schon geprüft hat (verpixelt oder sauber), nie ein Rohbild: Nachtbilder notiert der Box-Job ohne Erkennung, sie kommen deshalb nie in Frage. „Vorschau aktualisieren“ (nur mit JavaScript) holt ein neues; die Seite lädt dabei nicht neu, ungespeicherte Änderungen bleiben. Der Schalter „Rahmen bearbeiten“ macht das Bild zur Zeichenfläche:

- ein Rechteck aufziehen legt einen Rahmen an (die Zahlen der Zeile füllen sich),
- ein Rahmen lässt sich verschieben (Größe bleibt, er bleibt im Bild),
- die untere Kante des roten Streifens oben lässt sich ziehen und ändert den Rand dieser Kamera,
- „Rahmen hinzufügen“ und „Entfernen“ in den Zeilen gehen auch ohne Maus; es stehen keine leeren Reserve-Zeilen da. Nach dem Hinzufügen steht der Fokus im ersten Feld der neuen Zeile, nach dem Entfernen in der nächsten Zeile (oder auf „Rahmen hinzufügen“), und die Änderung wird für Screenreader angesagt. Die Knöpfe nennen ihre Zeile und ihre Kamera („Rahmen 2 entfernen“).
- Ein Tippen auf einen Rahmen verschiebt ihn nicht: Erst ab einigen Bildschirmpunkten Weg gilt es als Ziehen (auf dem Handy sind das mehrere Bildpunkte). Ein zweiter Finger übernimmt keine laufende Geste.
- Entfernt man alle Rahmen einer Kamera, speichert die Seite „keine Rahmen“, auch wenn `config.json` welche hat; sie kommen nicht zurück. „Änderungen verwerfen“ bringt die Rahmenzeilen zurück, die die Seite geladen hat, auch nach „Auf Standard zurücksetzen“.

Ausgeschaltet lässt die Ebene jede Berührung durch, das Bild blockiert das Scrollen also nicht. Die Zeilen mit den Zahlen bleiben der Weg ohne Maus. Hat eine Kamera noch kein geprüftes Bild (neue Kamera: erst nach der ersten verpixelten Nacht; auch ein Tag, an dem nur Nachtbilder vorliegen, zählt nicht), steht dort nur ein Hinweis, die Zahlenzeilen funktionieren trotzdem.

**Bestätigung.** „Speichern“ öffnet einen Dialog, der in Worten aufzählt, was sich ändert; ändert sich die Kameraliste, steht sie zusätzlich in einem „Wichtig!“-Block. Erst „Ja, speichern“ sendet das Formular mit `confirm_privacy=yes`. Ohne JavaScript ersetzt ein Kästchen den Dialog. Der Server nimmt nur genau `yes` an, jeder andere Wert, auch ein Array, wird abgelehnt. Jedes Absenden öffnet den Dialog, und nur „Ja, speichern“ sendet das Formular. Es gibt kein „bestätigt“-Merkmal, das nach „Zurück“ oder einer abgebrochenen Seitennavigation bestehen bleiben und den Dialog umgehen könnte. Das Formular bittet den Browser außerdem, getippte Werte nicht wiederherzustellen (`autocomplete="off"`), weil der Dialog gegen die geladenen Werte vergleicht.

Grenze: PHP nimmt je Formular höchstens `max_input_vars` Werte an (Standard 1000). Jeder Rahmen belegt vier, bei rund 240 Zeilen über alle Kameras reicht das nicht mehr, die Speicherung scheitert dann mit „Bitte die Änderungen bestätigen.“, weil die Bestätigung als letztes Feld abgeschnitten wird. Abhilfe: `max_input_vars` in der PHP-Konfiguration von Apache erhöhen.

Ablauf des Speicherns (beide Reiter):

```text
settings.php / verpixelung.php  (Sitzungs-Token, Bestätigung, Werte aus dem festen Feldsatz)
  → settings-runner.php:
    sudo -n -u <benutzer> /usr/local/sbin/timelapse-web-settings <bereich> <änderungszeit> <werte-json>

timelapse-web-settings
  → prüft Bereich (general oder privacy), Änderungszeit (nur Ziffern) und Größe (8 KB, privacy 64 KB)
  → startet python3 -m src.settings_save --scope <bereich>   (die Werte kommen über stdin)
  → Exit 0 gespeichert, 65 ungültige Werte (Meldungen als JSON), 73 inzwischen geändert
```

Der Wrapper arbeitet synchron und nimmt keine Laufsperre: Der Schreiber ersetzt die Datei in einem Schritt (temporäre Datei im selben Ordner, dann Umbenennen, Rechte 0644 damit der Webserver-Benutzer sie liest), und ein laufender Auftrag hat seine Config schon gelesen. Die Werte laufen als EIN JSON-Argument, weil der Prozessaufruf von PHP keine Standardeingabe hat. `src/settings.py` ist der einzige Prüfer: Jeder Schlüssel muss in der Liste des Bereichs stehen und seine Regel erfüllen, alles andere wird abgelehnt, wie auch immer die Anfrage gebaut ist. Gespeichert wird nur, was von `config.json` abweicht; ein Wert, der auf den Standard zurückgesetzt wird, verschwindet aus der Datei, und eine spätere Änderung an `config.json` erreicht den Schlüssel wieder.

Ablauf der Vorschau:

```text
preview-refresh.php  (POST: Sitzungs-Token, Kamera aus der Blur-Liste)
  → preview-runner.php:
    sudo -n -u <benutzer> /usr/local/sbin/timelapse-web-preview <kamera>

timelapse-web-preview
  → prüft den Kameranamen (einfacher Name), Zeitlimit 90 Sekunden, setzt TIMELAPSE_STORAGE_BOX
  → startet python3 -m src.privacy.preview <kamera>
  → Exit 0 Bild zwischengespeichert, 66 keine Blur-Kamera, 67 noch kein geprüftes Bild, 124 Zeitlimit
```

Der Webserver-Benutzer erreicht die Storage Box nicht, deshalb holt das Skript das Bild als Projektbenutzer mit der Bildquelle (`src/frame_source.py`) und legt es in `state/web-jobs/previews/<Kamera>.jpg` ab, dazu `<Kamera>.json` mit Bildname, Art und Aufnahmezeit. Gewählt wird unter den Bildern der letzten Tage, die der Box-Job bestätigt hat: zuerst „verpixelt“, dann „sauber“ (nie ein Nachtbild: der Box-Job notiert es ohne Erkennung), der neueste Tag, dort das Bild nächst der Mittagszeit. Das Bild muss genau die Bytes sein, die der Job festgehalten hat (Prüfsumme); stimmt es nicht, kommt der nächste Kandidat, höchstens drei. Die Bildgröße steht nicht in der JSON-Datei: PHP liest sie aus dem Bild selbst (`getimagesize()`, nur JPEG, Seiten von 1 bis 20 000 Punkten). Ein beschädigtes Bild gilt als „kein Bild“.

`preview.php?camera=<Name>` liefert das Bild: einfacher Name, Kamera aus der Blur-Liste, kein Symlink, Größe 4 Byte bis 32 MiB, JPEG-Typ, und nur, wenn die Seite es auch zeigen würde (gültige Beschreibung, Art „verpixelt“ oder „sauber“); sonst 404. Ein Nachtbild, das vor dem Ausschluss der Nachtbilder zwischengespeichert wurde und liegen blieb, ist deshalb auch über die Adresse nicht abrufbar. Die Antwort trägt `Cache-Control: private, no-cache`, die Adresse eine Version, damit ein altes Bild nie aus dem Zwischenspeicher des Browsers erscheint. Der Wrapper endet nach höchstens 90 Sekunden, damit eine Box, die nicht antwortet, keine Webanfrage minutenlang festhält.

**Wo die Dateien liegen.** `config/settings.json` (Allgemein) und `config/settings-privacy.json` (Verpixelung) sind in Git ignoriert, je Host eine Datei; die auf dem VPS ist maßgeblich. Fehlt eine, gelten keine Änderungen. Eine Starthilfe liegt als `config/settings.example.json` bei. Wer eine Datei vom Mac auf den VPS bringt, tut das **einmal** mit `rsync --no-perms --ignore-existing`: Ein zweites Kopieren würde die Änderungen der Kolleginnen und Kollegen löschen. Eine kaputte oder unlesbare Datei, ein unbekannter Schlüssel oder ein Wert außerhalb der Grenzen wird mit einer Warnung im Protokoll ignoriert und kann den Nachtlauf nicht stoppen. `./install.sh permissions` lässt `www-data` genau diese beiden Dateien lesen, `backup.sh` und der Schritt `restore` nehmen sie mit.

## Webtests

Wrapper, PHP-Helfer und Status-Endpunkt werden mit pytest geprüft (benötigt `php` auf der Kommandozeile):

```bash
python3 -m pytest tests/web
```

Die ganze Suite läuft auch im Docker-Testsystem, das den Webteil des VPS nachbaut (Debian 13, Apache, PHP 8.4,
Python 3.13): [docker-web.md](docker-web.md#die-tests-im-container-laufen-lassen).

- `web_status_test.py`: atomare Statuswechsel, ungültige Job-IDs, gemeinsamer Lock, Trigger-Validierung, erfolgreiche Videoveröffentlichung, fehlgeschlagene Jobs und die Fehlergrund-Datei `.reason` des Workers
- `web_status_endpoint_test.py`: JSON-Antworten von `job-status.php`, inklusive Übersetzung bekannter Fehlergründe und `failed` für einen Auftrag ohne `.pid` nach einer Minute, sowie `running-job.php` (läuft irgendein Web-Auftrag: lebender Worker, tote Prozesse, frischer Start ohne PID, fremde Dateien im Ordner), sowie die Ergebniszeilen (`results`), wenn eine `.result`-Datei da ist
- `web_delete_test.py`: Lösch-Wrapper, u. a. Pfad-Traversal, Dateityp, Symlinks und dass automatische Videos unangetastet bleiben
- `web_php_test.py`: `video-library.php`, `process-runner.php`, `job-runner.php`, `rebuild-runner.php`, `publish-runner.php`, `job-state.php` (Ergebniszeilen) und `video-delete.php`; in `video-library.php` auch `newestAutomaticVideos()` (Vorschau des Uploads, mit Randfällen wie leeren, versteckten und verlinkten Dateien); die Tests kopieren `web/src` nach `tmp_path`, ersetzen dort die festen Pfade und verwenden ein Fake-`sudo`, sodass weder echte Videos noch installierte Wrapper berührt werden
- `web_camera_page_test.py`: `camera.php` als Ganzes (Kopie in `tmp_path`, Kamerapfad und `sudo` ersetzt): beide Listen, Auswahl über `source=auto`, Lese-Schutz der automatischen Videos, ungültige Parameter, Markierung des laufenden Videos, Löschen per `response=json`, Weiterleitung nach dem Start (Post/Redirect/Get), Verpixelungs-Hinweis nur bei Blur-Kameras. die Leiste (zu, nach einer abgelehnten Anfrage offen), das Neuerstellen-Formular, der Upload-Abschnitt mit der strengen Bestätigung (`yes` und nichts sonst) und der Hinweisstreifen im Header. Die gemeinsame Hilfsfunktion `render_page()` dafür liegt in `web_php_test.py`
- `web_rebuild_test.py`: Trigger und Worker des Neuerstellens (Argumente, Kameraliste, Laufsperre, Aufruf von `src.main` ohne `--target-date`, Ergebniszeilen)
- `web_settings_page_test.py`, `web_privacy_page_test.py`: die beiden Seiten als Ganzes (Felder, Standardwerte aus `config.json`, Zurücksetzen, Fehler am Feld, Token und Bestätigung, was an den Wrapper geht, Regler und Skript als Struktur); die Seite „Verpixelung“ zusätzlich Kamerablöcke, Rahmenzeilen, Vorschaubild und Editor-Bausteine
- `web_settings_reader_test.py`, `web_settings_runner_test.py`, `web_settings_wrapper_test.py`: das gemeinsame Lesen der Config (Schlüssellisten wie in `src/settings.py`), der Aufruf des Wrappers (Antworten und Exit-Codes) und der Wrapper selbst
- `web_preview_endpoint_test.py`, `web_preview_runner_test.py`, `web_preview_wrapper_test.py`: `preview.php` und `preview-refresh.php` (Statuscodes, Token, Antwort), das Lesen des Zwischenspeichers (Größe aus dem Bild, beschädigte Bilder) und der Vorschau-Wrapper
- `web_publish_test.py`: Trigger und Worker des Uploads (genau zwei Argumente, `--run`, Ergebniszeile, `failed` ohne Ergebniszeile, privates Protokoll, und dass der FTP-Zugang nie in die Statusdateien gelangt)
- `web_storage_test.py`: das Messen von `videos/` (vier Gruppen je Kamera, Symlinks, lose Dateien und versteckte Ordner außen vor, ausgeblendete Kameras zählen), die Warnstufen bei 80 % und 90 %, die Teile des Header-Rings und die Teile für das Feld „Speicher“ (Summe immer die ganze Platte, einzelne Restkamera mit Namen, eine Farbe je Teil, der Ring der Videos)
- `web_header_test.py`: der Header als Ganzes: ein Bogen je Teil mit den richtigen Strichlängen, ein Textfeld je Bogen, Warntexte nur ab 80 % und 90 %, das Feld „Davon Videos“
- `web_storage_panel_test.py`: das Feld „Speicher“: beide Ringe, die Liste ohne Prozentspalte, die Textfelder mit ihrer Grundlage („des Speichers“, „der Videos“), gleiche Farbe je Kamera in beiden Ringen, mehr als sechs Kameras, das Skript als Struktur; dazu je ein Test in den beiden Einstellungs-Seitentests, dass es über den Reitern steht
- `web_index_page_test.py`: die Kapsel je Kamera („keine Videos“, kein Prozentwert, kein Balken)

Die Tests der Highlights-Seite stehen in [highlights-seite.md](highlights-seite.md#dateien-und-tests).

Die Python-Seite der Einstellungen prüfen `tests/settings_test.py` (Regeln und Grenzen), `tests/settings_save_test.py` (Schreiber: nur Abweichungen, atomar, veraltete Seite, Protokoll) und `tests/privacy/privacy_preview_test.py` (Auswahl und Prüfung des Vorschaubilds).

Nicht automatisiert getestet ist das JavaScript der Seiten (die Zeichen-Gesten des Editors und das Textfeld über den Bögen von `storage-ring.js` sind in einem echten Browser geprüft; die Tests prüfen, was der Server dafür bereitstellt, und lesen das Skript nur als Struktur). Ebenso nicht automatisiert: wie die Ringe und Farben aussehen; das wurde im Browser angesehen.
