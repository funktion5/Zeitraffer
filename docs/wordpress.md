# WordPress-Frontend

Zusätzlich zur PHP-Weboberfläche gibt es das WordPress-Plugin „Zeitraffer“
(`frontend/zeitraffer/`), das die fertigen Videos auf einer WordPress-Seite zeigt. Dieses Dokument
beschreibt, wie es funktioniert und wie es lokal entwickelt und getestet wird. Es ist **nur lesend**: Es startet keine Jobs, schreibt keine Dateien und hat keine Formulare, AJAX- oder REST-Endpunkte. Entwickelt wird es lokal auf dem Mac in einer Docker-Umgebung; die Pi-Weboberfläche bleibt davon unberührt.

```text
Pi: videos/<Kamera>/<Zeitraum>/*.mp4
  → docker/pull-videos.sh (rsync, nur Lesen auf dem Pi)
  → Mac: videos/
  → Docker-Container "wordpress": wp-content/uploads/zeitraffer/ (schreibgeschützt)
  → Plugin frontend/zeitraffer/plugin-timelapse.php
  → Shortcode [zeitraffer] und Player auf der Webcam-Seite
```

## Voraussetzungen für das Frontend

- Docker Desktop (mit `docker compose`) auf dem Mac
- SSH-Zugang zum Pi per Schlüssel; Benutzer und Adresse stehen in `docker/.env` (Variable `PI`, siehe Schritt 1); der Pi muss im Netz erreichbar sein
- `rsync` auf dem Mac (bei macOS vorhanden)
- Port `8080` auf dem Mac ist frei

## Ablauf in Kurzform

```bash
cd docker
cp .env.example .env         # danach die Werte eintragen, siehe unten
docker compose up -d
cd ..
docker/pull-videos.sh        # Videos vom Pi holen
```

Danach WordPress einmalig installieren, das Plugin aktivieren und den Shortcode in eine Seite einbauen (Details unten).

## Schritt 1: Umgebung konfigurieren

`docker/.env.example` ist die Vorlage; `docker/.env` ist per `.gitignore` ausgeschlossen und darf nie committet werden.

```bash
cd docker
cp .env.example .env
```

Alle Werte in `docker/.env` ausfüllen. Die Datenbankwerte sind frei wählbar, es ist nur eine lokale Entwicklungsdatenbank:

| Variable | Bedeutung |
|---|---|
| `DB_NAME` | Name der Datenbank, z. B. `wordpress` |
| `DB_USER` | Datenbankbenutzer für WordPress |
| `DB_PASSWORD` | Passwort dieses Benutzers |
| `DB_ROOT_PASSWORD` | Root-Passwort der MariaDB |
| `PI` | Benutzer und Adresse des Pi für `pull-videos.sh`, Format `benutzer@adresse` |

Bleibt ein Wert leer, startet die Datenbank nicht oder WordPress kann sich nicht verbinden. Compose liest die `.env` aus dem Ordner `docker/` und löst alle Pfade relativ zu diesem Ordner auf.

Die Konfiguration lässt sich vorab prüfen:

```bash
docker compose config
```

## Schritt 2: Videos vom Pi holen

Hinweis (Stand 30.10.2026): Die Videos entstehen seit dem Umzug auf dem VPS, der Pi ist stillgelegt.
Skript und Variable heißen noch `pull-videos.sh` und `PI`, nehmen aber jeden ssh-Login, auch einen
Alias aus `~/.ssh/config`: `PI=<ssh-alias-des-VPS> docker/pull-videos.sh`. Das ist noch nicht
ausprobiert; der Pfad `timelapse/videos/` gilt auf dem VPS ebenfalls.

Der Container erwartet die Videos unter `videos/` im Projektordner, in derselben Struktur wie auf dem Pi:

```text
videos/<Kamera>/<daily|weekly|monthly|yearly>/<Kamera>_<Datum>.mp4
```

Ohne Videos zeigt das Plugin keine Kameras an.

```bash
cd /pfad/zum/projekt
docker/pull-videos.sh -n     # Probelauf: zeigt nur, was passieren würde
docker/pull-videos.sh        # Probelauf anzeigen, nach Bestätigung (y) wirklich spiegeln
```

Das Skript **spiegelt** den Ordner `~/timelapse/videos/` des Pi-Logins nach `videos/`:

- Neue und geänderte Dateien werden kopiert.
- Dateien, die auf dem Pi nicht mehr existieren, werden lokal **gelöscht**, damit keine veralteten Videos übrig bleiben. Deshalb zeigt das Skript immer zuerst einen Probelauf und fragt nach, bevor es etwas ändert.
- `manual-runs/` und versteckte Dateien (z. B. unfertige Renderings) werden weder kopiert noch gelöscht.
- Auf dem Pi wird nichts verändert.

`PI` wird aus der Umgebung oder aus `docker/.env` gelesen; ein einmaliger anderer Wert lässt sich so übergeben:

```bash
PI=benutzer@<Pi-Adresse> docker/pull-videos.sh
```

Achtung bei eigenen Testvideos in `videos/`: Sie stehen im Probelauf unter den Löschungen, sofern sie auf dem Pi nicht existieren.

## Schritt 3: Container starten

```bash
cd docker
docker compose up -d
```

Der Stack besteht aus zwei Containern:

| Container | Image | Aufgabe |
|---|---|---|
| `db` | `mariadb:11` | Datenbank, Daten im benannten Volume `db` |
| `wordpress` | `wordpress:php8.4-apache` | WordPress, erreichbar unter http://localhost:8080 |

Eingebunden werden:

| Host (Mac) | Container | Zweck |
|---|---|---|
| `frontend/zeitraffer/` | `/var/www/html/wp-content/plugins/zeitraffer` | Das Plugin, schreibgeschützt (`:ro`). Änderungen am Code sind sofort sichtbar. |
| `videos/` | `/var/www/html/wp-content/uploads/zeitraffer/` | Die Videos, schreibgeschützt. Nach jedem `pull-videos.sh` ohne Neustart sichtbar. |
| Volume `wordpress` | `/var/www/html` | WordPress-Dateien und Uploads |
| Volume `db` | `/var/lib/mysql` | Datenbank |

Status prüfen:

```bash
docker compose ps
docker compose logs -f wordpress
```

## Schritt 4: WordPress installieren

1. http://localhost:8080 öffnen. Beim ersten Start erscheint der Installationsassistent.
2. Sprache wählen, Seitentitel, Admin-Benutzer, **ein starkes Passwort** und eine E-Mail-Adresse angeben und installieren. Die Daten bleiben nur in der lokalen Umgebung.
3. Unter **Einstellungen → Permalinks** die Struktur **Beitragsname** wählen und speichern. Das Plugin funktioniert auch mit „Einfach“, aber mit Beitragsname entsprechen die URLs der späteren Live-Seite (`/zeitraffer/?camera=...`).

Die Installation überlebt `docker compose down` und einen Neustart des Macs, da sie in den benannten Volumes liegt.

## Schritt 5: Plugin aktivieren

Unter **Plugins** erscheint **Zeitraffer** (Datei `frontend/zeitraffer/plugin-timelapse.php`). Auf **Aktivieren** klicken. Erscheint das Plugin nicht, ist der Mount nicht angekommen; siehe [Fehlerbehebung](#fehlerbehebung-wordpress-frontend).

## Schritt 6: Kameras anlegen und Shortcode einbauen

Namen und Beschreibungen der Kameras werden im WordPress-Admin gepflegt, nicht im Code und nicht in den Seiten. Der Shortcode nennt nur den Kameraordner.

### Kameras anlegen (einmalig, danach bei neuen Ordnern)

1. Im Admin **Zeitraffer → Alle Kameras** öffnen.
2. Auf **Kameras aus Ordnern anlegen** klicken. Für jeden Ordner unter `uploads/zeitraffer/` mit mindestens einem Video entsteht ein Eintrag **als Entwurf**; vorhandene Einträge bleiben unverändert, der Button kann beliebig oft gedrückt werden. Neue Kameraordner werden später genauso übernommen.
3. Einen Eintrag öffnen, ausfüllen und, wenn die Kamera getestet ist, **veröffentlichen**:
   - **Titel:** der Anzeigename auf der Seite, z. B. „Hafenstraße“ (zunächst der Ordnername).
   - **Auszug:** die Beschreibung der Szene als Textalternative zum Video (siehe unten).
   - Rechts zeigt der Kasten **Zeitraffer** den Ordner (nicht änderbar) und den passenden Shortcode.

Die Einträge sind nicht öffentlich: Sie haben keine eigene Adresse und erscheinen nur im Admin. Die Liste zeigt je Kamera den Ordner; fehlt der Ordner (umbenannt oder gelöscht), steht dort „Ordner nicht gefunden“. Neue Einträge lassen sich nicht von Hand anlegen, weil jeder Eintrag zu einem Ordner gehört.

### Shortcode einbauen

Das Plugin wird in eine bestehende Kameraseite eingefügt (z. B. `/webcams/hafenstrasse/`). Die Seite behält ihr Bild, ihre Texte, den Geolink und die Werbung; der Player erscheint dort, wo der Shortcode steht.

```text
[zeitraffer camera="tim-meuter"]
```

Die Seiten-URL und der Kameraordner heißen oft unterschiedlich (die Seite `hafenstrasse` gehört zum Ordner `tim-meuter`). Deshalb wird die Kamera immer ausdrücklich im Shortcode genannt und nicht aus der URL abgeleitet. Anlegen: Seite öffnen, an der gewünschten Stelle einen **Shortcode-Block** einfügen, den Shortcode hineinschreiben, speichern.

| Attribut | Pflicht | Bedeutung |
|---|---|---|
| `camera` | nein | Der Ordner der Kamera, klein geschrieben und bereinigt (nur `a-z`, `0-9`, `_`, `-`). Aus `Nordufer_tele` wird `nordufer_tele`; der Kasten „Zeitraffer“ im Kameraeintrag zeigt den richtigen Wert. Ohne dieses Attribut gilt auf der Seite einer Webcam (siehe „Shortcode auf der Webcam-Seite“) deren Feld „foldername“, sonst `?camera=` aus der URL. |
| `title` | nein | Überschreibt den Titel des Kameraeintrags. Normalerweise nicht nötig. |
| `description` | nein | Überschreibt den Auszug des Kameraeintrags. Normalerweise nicht nötig. |
| `heading` | nein | Ebene der Überschrift des Players, `2` bis `6`, Standard `2`. So lässt sich die Überschrift in die Struktur der Seite einpassen, z. B. `heading="4"` für Seiten, deren Abschnittstitel `h4` sind. Ungültige Werte ergeben `2`. |

Vorrang: Attribut im Shortcode, dann Kameraeintrag, dann Ordnername bzw. nur der Hinweis „Zeitraffer ohne Ton“. Texte aus einem Entwurf werden nur Redakteuren in der Vorschau gezeigt (siehe nächster Abschnitt).

### Sichtbarkeit: Entwurf und veröffentlicht

Ob eine Kamera für Besucher erscheint, entscheidet allein der Status ihres Eintrags:

| Eintrag | Besucher | Redakteure (Recht „Beiträge anderer bearbeiten“) |
|---|---|---|
| veröffentlicht | Player, Tabs, Texte | wie Besucher |
| Entwurf, ausstehend, privat | nichts | Player mit Hinweis „nicht veröffentlicht“ |
| kein Eintrag (Ordner noch nicht angelegt) | nichts | Player mit Hinweis |

So kann eine neue Kamera auf ihrer echten Seite getestet werden, ohne dass sie öffentlich ist: Entwurf anlegen, die Seite als angemeldeter Redakteur prüfen, dann veröffentlichen. Wichtig: Schaltet ein bereits veröffentlichter Eintrag zurück auf Entwurf, verschwindet die Kamera sofort. Texte bearbeitet man deshalb am besten im veröffentlichten Eintrag und speichert mit „Aktualisieren“.

Hinweis zum Caching: Sieht ein Zwischenspeicher (Cache-Plugin, CDN) eine für angemeldete Redakteure erzeugte Seite, könnte er den Entwurf an Besucher ausliefern. Angemeldete Nutzer werden normalerweise nicht gecacht; auf der Testseite prüfen.

Hinweise:

- **Tippfehler:** Stimmt `camera` nicht mit einem Ordner überein, sehen Besucher nichts. Angemeldete Redakteure (Recht „Seiten bearbeiten“) sehen einen Hinweis mit den verfügbaren Kameras.
- **Auszug und Barrierefreiheit:** Ein Zeitraffer ohne Ton braucht eine Textalternative (WCAG 1.2.1). Mit Auszug beschreibt der Text die Szene („Blick über den Hafen auf Boote und Steg“); ohne ihn steht nur der Hinweis „Zeitraffer ohne Ton“. Der Auszug sollte deshalb für jede Kamera gesetzt werden. Er ist reiner Text, HTML erscheint wörtlich.
- **Ein Player pro Seite** ist der vorgesehene Fall. Stehen trotzdem mehrere auf einer Seite (zum Beispiel ein versehentlich doppelter Shortcode), stören sie sich nicht gegenseitig: Jeder hat seine eigene Geschwindigkeit und seinen eigenen Tab, und nur der erste schreibt `?period=` in die Adresse.
- **Überschrift:** Das Plugin gibt eine eigene Überschrift aus („Zeitraffer – Zeitraum“, ohne Kameranamen, weil die Seite die Kamera schon im Titel nennt). Standard ist `<h2>`; die Ebene lässt sich mit `heading` anpassen. Ob sie zur Überschriftenstruktur der Seite passt, sollte auf einer Testseite geprüft werden.

### Shortcode auf der Webcam-Seite

Auf der Seite einer Webcam (`/webcams/<name>/`) steht `[zeitraffer]` ohne Attribute am Anfang des Beitragsinhalts. Das Template von f5-webcams gibt zuerst das Bild aus, danach den Beitragsinhalt, danach die Karte; der Player sitzt also zwischen Bild und weiterem Inhalt. Welche Videos erscheinen, entscheidet das ACF-Feld „foldername“ derselben Webcam, aus dem f5-webcams auch den Bildordner (`uploads/webcams/<foldername>/`) bildet. Der Videoordner (`uploads/zeitraffer/<foldername>/`) muss genauso heißen; Groß- und Kleinschreibung spielt keine Rolle, aber Unterstriche und Bindestriche müssen stimmen. Ein Attribut `camera` überschreibt das. Gibt es keinen passenden Videoordner, sehen Besucher nichts, angemeldete Redakteure einen Hinweis. Der Kameraeintrag (Zeitraffer → Alle Kameras) muss veröffentlicht sein.

Das Zeitraffer-Plugin liest vom Plugin f5-webcams nur das Feld „foldername“. Der Shortcode-Player erscheint nur dort, wo der Shortcode steht; unter dem Bild von `[f5_webcams_last]` (neueste Webcam in Seitenleiste oder Startseite) gibt das Plugin nichts aus.

Die Webcam-Seite kann den Player auch **ohne Shortcode** selbst ausgeben: Das Plugin f5-webcams enthält dafür eine eigene Klasse (`includes/class-timelapse.php`), die dasselbe Markup druckt und nach dem Seitentext und vor der Karte einfügt. Steht `[zeitraffer]` im Text der Seite, gibt f5-webcams keinen zweiten Player aus. Ob der Player erscheint, entscheidet auch hier der Kameraeintrag: Das Zeitraffer-Plugin beantwortet zwei Filter von f5-webcams (`f5_webcams_show_timelapse` blendet eine nicht veröffentlichte Kamera für Besucher aus, `f5_webcams_timelapse_notice` liefert Redakteuren den Hinweis). Ohne das Zeitraffer-Plugin erscheint der Player für jede Webcam mit Videos. Beschrieben ist diese Änderung für den Betreuer des f5-Plugins in `frontend/f5-webcams/TIMELAPSE-PLAYER-CHANGES.md`; in diesem Repository ist sie nicht versioniert, weil das f5-Plugin ein eigenes Repository ist.

Der ältere Aufbau mit einer gemeinsamen Playerseite (`[zeitraffer]` ohne `camera`, Kamera aus `?camera=` in der URL) funktioniert weiter. Die frühere Kameraübersicht `[tl]` und der Filter `zeitraffer_camera_page_slug` sind entfernt.

## So funktioniert das Plugin

- **Kameras** sind die Unterordner von `videos/`. Ein Ordner erscheint nur, wenn er in mindestens einem Zeitraum ein `.mp4` enthält **und** sein Kameraeintrag veröffentlicht ist. Der Slug in der URL ist der Ordnername, durch `sanitize_key()` bereinigt (nur `a-z`, `0-9`, `_`, `-`).
- **Das neueste Video** je Zeitraum ist die Datei, die nach Dateinamen zuletzt kommt. Das setzt voraus, dass das Datum im Dateinamen steht (`<Kamera>_<JJJJ-MM-TT>.mp4`), wie es die Pipeline erzeugt.
- Die Überschrift zeigt „Zeitraffer“ und den Zeitraum, den das Video abdeckt. Das Enddatum steht im Dateinamen (`<Kamera>_<JJJJ-MM-TT>.mp4`; ohne Datum im Namen gilt das Änderungsdatum der Datei), der Anfang ergibt sich aus dem Typ wie in der Pipeline: Tag = dieser Tag, Woche = 7 Kalendertage, Monat = 30 Tage, Jahr = das Kalenderjahr bis zum Enddatum (365 oder 366 Tage), jeweils einschließlich Enddatum. Beispiel Woche: „Zeitraffer – 15.09.2026 bis 21.09.2026“. Das Datumsformat folgt der Einstellung von WordPress (Einstellungen → Allgemein), und der Zeitraum wechselt mit dem Tab.
- Hat der angefragte Zeitraum kein Video, springt der Player auf den ersten Zeitraum, der eines hat.
- Versteckte Dateien und `manual-runs/` werden nicht angezeigt.
- Die Tabs funktionieren auch ohne JavaScript als normale Links. `assets/script.js` schaltet ohne Seitenneuladen um und baut die eigene Bedienleiste; `assets/style.css` gestaltet Tabs, Bild und Leiste. Bedienung, Tastatur und Farben: siehe „Player: Bedienung und Bildrate“. Schrift und Textfarbe kommen vom Theme.
- Das Plugin lädt **nichts von Dritten**: keine externen Schriften, Skripte oder Tracker, keine Cookies und kein Browser-Speicher. Es sind also keine Einwilligung und keine Datenschutzanpassung nötig.
- Farben stammen nur aus der Palette des Avada-Themes, jeweils mit demselben Hex-Wert als Rückfallwert in der lokalen Umgebung (Einzelheiten unter „Player: Bedienung und Bildrate“). Schrift und Textfarbe erbt das Plugin vom Theme.

## Player: Bedienung und Bildrate

Der Player ersetzt die Bedienleiste des Browsers durch eine eigene. Sie liegt ohne eigenen Hintergrund am unteren Bildrand (weiße Bedienelemente mit dunklem Rand, damit sie auf hellen und dunklen Bildern lesbar bleiben); sie bleibt immer auf dem Bild. Der Player kennt drei Größen, gemessen an seiner eigenen Breite (nicht an der des Bildschirms): Desktop (über 48 rem, also 768 px), Tablet (bis 48 rem, Knopfgröße 2,5 rem) und Mobil (bis 30 rem, also 480 px). Mobil werden Knöpfe und Schrift am kleinsten (Knopfgröße 2 rem, mindestens die 24 px, die WCAG 2.2 AA verlangt), die Tabs sind in allen Größen gleich breit (mobil in einer Reihe) und zeigen mobil die Kurzformen 1T, 7T, 30T und 365T statt „Gestern“, „Die letzten 7 Tage“ usw. (der lange Text bleibt für Screenreader im Link, nur unsichtbar, damit der Name zum Sichtbaren passt). Die langen Texte passen ab etwa 55 rem (880 px) auf eine Zeile, darunter brechen sie gleichmäßig um. Das Tages-Tab heißt „Gestern“, weil das Tagesvideo genau den Vortag (Sonnenaufgang bis Sonnenuntergang) zeigt und keine gleitenden 24 Stunden; das Jahres-Tab heißt „Die letzten 365 Tage“ (nicht „Das letzte Jahr“, das nach einem Kalenderjahr klingt). Die Leiste hat mobil zwei Zeilen: Fortschritt und Zeit oben, darunter links Abspielen, genau in der Mitte die Bild-Tasten und rechts Geschwindigkeit und Vollbild (die Bild-Tasten sind in jeder Größe mittig, auch wenn die Geschwindigkeit eine Auswahlliste ist).

| Element | Wirkung |
|---|---|
| Fortschrittsleiste mit Zeit | zeigt die Stelle im Video und lässt sich ziehen. Die Zeit ist die Videozeit (z. B. 0:07 / 0:12), keine Uhrzeit. |
| Abspielen / Pause (großer Knopf links) | startet und pausiert; ein Klick auf das Bild tut dasselbe. |
| Bild zurück, Bild vor (Mitte) | pausiert und springt genau ein Bild (siehe Bildrate unten). |
| 0,5× · 1× · 2× | Wiedergabegeschwindigkeit. Der gewählte Wert ist unterstrichen und bleibt beim Wechsel des Tabs erhalten. Bei einem schmalen Player (Handy) sind es keine drei Knöpfe, sondern eine kleine Auswahlliste („1× ▾“). |
| Vollbild | zeigt den ganzen Player samt Leiste im Vollbild. Auf dem iPhone ist das nicht möglich, dort fehlt der Knopf. |

- **Tastatur:** Der Bildbereich ist mit Tab erreichbar. Hat er den Fokus, startet und pausiert die Leertaste, und die Pfeiltasten links und rechts springen ein Bild. Auf der Fortschrittsleiste behalten die Pfeiltasten ihre normale Wirkung (die Leiste rastet auf ganze Bilder ein, eine Taste ist ein Bild), auf einem Knopf die Leertaste.
- **Ausblenden im Vollbild:** Nur im Vollbild (Handy und Desktop) blendet sich die Leiste samt Mauszeiger aus, wenn das Video läuft und 3 Sekunden lang nichts berührt wurde (Maus, Finger, Tastatur). Mausbewegung oder ein Tippen aufs Bild blendet sie wieder ein; das erste Tippen auf die ausgeblendete Leiste pausiert nicht, erst ein Tippen bei sichtbarer Leiste startet oder pausiert wie gewohnt. Pausiert, am Ende, bei einem Fehler und außerhalb des Vollbilds bleibt die Leiste immer sichtbar, ebenso solange ein Bedienelement den Tastaturfokus hat (ein mit Maus oder Finger angeklickter Knopf zählt nicht, sonst würde sich die Leiste nach dem ersten Klick nie ausblenden). Wer „Bewegung reduzieren“ eingestellt hat, sieht das Ein- und Ausblenden ohne Animation.
- **Beschriftungen:** Jeder Knopf hat eine deutsche Beschriftung für Screenreader und einen Tooltip. Der Tooltip ist der des Browsers; er erscheint nach etwa einer Sekunde Ruhe.
- **Fehler:** Lässt sich ein Video nicht laden, erscheint auf dem Bild die Meldung „Das Video konnte nicht geladen werden …“ auf dunklem Grund; lädt es später, verschwindet sie.
- **Ohne JavaScript oder in alten Browsern:** Es bleiben die Bedienleiste des Browsers und die Tabs als normale Links. Das Stylesheet braucht CSS-Verschachtelung und Container-Abfragen, die Browser ab Ende 2023 kennen.
- **Hoher Kontrast (Windows):** Die Leiste zeichnet sich dann in den Systemfarben des Nutzers, mit Rahmen um Knöpfe und Fortschrittsleiste, ohne den dunklen Rand um die Schrift.
- **Nichts wird gespeichert:** Die gewählte Geschwindigkeit gilt nur, solange die Seite offen ist.

**Farben.** Es werden nur Farben der Live-Seite benutzt, jeweils mit demselben Wert als Rückfall: Akzent des aktiven Tabs und des Knopfs auf der Fortschrittsleiste (mit hellem Ring, damit er auf dunklen Bildern sichtbar bleibt) `--primary_color` (`#202b65`), Hover der Tabs `--awb-color3`, Bedienelemente `--awb-color7`, Rand und Fehlerfläche `--awb-custom_color_5`. Ohne eigene Datei ändern lässt sich der Akzent mit einer Regel im benutzerdefinierten CSS von Avada:

```css
.timelapse { --timelapse-accent: <Farbe>; --timelapse-on-accent: <Textfarbe darauf>; }
```

**Bildrate.** Das Springen um ein Bild muss die Bildrate des Videos kennen. Sie steht je Tab (`data-fps`) und kommt aus einer Konstante: Tag 10, Woche 10, Monat 20, Jahr 20 Bilder pro Sekunde. Die Konstante heißt `TL_TIMELAPSE_FRAME_RATES` in `frontend/zeitraffer/plugin-timelapse.php` und `Timelapse::FRAME_RATES` im Plugin f5-webcams. **Die Werte müssen zur Pipeline passen:** `timelapse.daily_framerate`, `monthly_framerate` und `yearly_framerate` in `config/config.json`; das Wochenvideo wird mit der Tagesrate gebaut (`src/jobs/weekly.py`). Ändert sich dort ein Wert, muss er an beiden Stellen geändert werden. Videos, die vor der aktuellen Einstellung gebaut wurden, können eine andere Rate haben; dann springt die Taste entsprechend ungenau. Fehlt die Rate, werden die Bild-Tasten ausgeblendet.

**Skript und Stylesheet gibt es zweimal.** Das Original liegt im Zeitraffer-Plugin (`frontend/zeitraffer/assets/script.js` und `style.css`). Das Plugin f5-webcams enthält wortgleiche Kopien (`assets/js/timelapse.js` und `assets/css/timelapse.css`). Geändert wird nur das Original, danach wird kopiert. Mit beiden Plugin-Ordnern nebeneinander muss die Prüfung nichts ausgeben:

```bash
diff frontend/zeitraffer/assets/script.js frontend/f5-webcams/assets/js/timelapse.js
diff frontend/zeitraffer/assets/style.css frontend/f5-webcams/assets/css/timelapse.css
```

Beide Plugins drucken dazu dasselbe Markup (`.timelapse`, `.timelapse-tabs`, `.timelapse-viewport` usw.).

### Checkliste zur Abnahme (von Hand im Browser)

- [ ] Shortcode-Player und Webcam-Seiten-Player sehen gleich aus und verhalten sich gleich.
- [ ] Ohne JavaScript (in den Entwicklerwerkzeugen abschalten) bleiben Bedienleiste des Browsers und Tab-Links funktionsfähig.
- [ ] Eine kaputte Videoadresse zeigt die Fehlermeldung statt eines schwarzen Kastens (Konsole: `document.querySelector(".timelapse-video").src = "/nope.mp4"`).
- [ ] Die Bedienelemente sind auf einem echten hellen und einem echten dunklen Bild gut lesbar.
- [ ] Mit der Tastatur allein lässt sich alles bedienen (Tab durch alle Elemente, Fokusrahmen sichtbar, Leertaste und Pfeile im Bildbereich); bei 320 px Breite passt alles ohne seitliches Scrollen.
- [ ] Unter Windows mit Hochkontrast-Design (oder in den Entwicklerwerkzeugen unter „Rendering“ „forced-colors“ einschalten) sind Fortschrittsleiste, Beschriftungen und Knöpfe auf hellem und dunklem Bild lesbar.
- [ ] Im Vollbild (Handy und Desktop): Video starten, 3 Sekunden nichts tun: Leiste blendet aus. Mausbewegung oder ein Tippen blendet sie wieder ein, das Video läuft weiter; ein zweites Tippen pausiert. Nach dem Verlassen des Vollbilds bleibt die Leiste sichtbar.
- [ ] Stehen versehentlich zwei Player auf einer Seite, stören sie sich nicht; nur der erste ändert die Adresse.
- [ ] Springen um ein Bild bewegt das Video bei einem Tages- und bei einem Monats- oder Jahresvideo um genau ein Bild.
- [ ] Bildrate-Konstanten tragen den Kommentar und passen zur Pipeline-Konfiguration.

## Täglicher Betrieb

```bash
cd docker
docker compose up -d       # starten
docker compose down        # stoppen, Daten bleiben erhalten
docker compose down -v     # stoppen UND Volumes löschen: WordPress-Installation und Datenbank sind weg
```

- Neue Videos: `docker/pull-videos.sh` ausführen und die Seite neu laden. Ein Neustart ist nicht nötig.
- Code ändern: Datei in `frontend/zeitraffer/` speichern und neu laden. Die Versionsnummer von CSS und JS ist deren Änderungszeit, daher gibt es keine Cache-Probleme; bei Zweifeln Strg/Cmd+Shift+R.
- Mac ausschalten: nichts zu tun. Die Container starten mit Docker Desktop wieder (`restart: always`) oder per `docker compose up -d`; Installation und Videos bleiben erhalten.
- `down -v` entspricht einem Zurücksetzen auf eine frische WordPress-Installation (Schritt 4 beginnt wieder von vorn). Videos und Plugin-Code sind nicht betroffen, weil sie nur eingebunden sind.

## Syntaxprüfung des Plugins

Ohne lokale PHP-Installation über den Container:

```bash
docker run --rm -v "$PWD/frontend":/w php:8.4-cli php -l /w/zeitraffer/plugin-timelapse.php
```

Für die Berechnungen des Players (Zeitanzeige, Sprung um ein Bild) gibt es Node-Tests ohne zusätzliche Abhängigkeit:

```bash
node --test tests/frontend/*.test.js
```

Sie laufen nicht in der GitHub-Action, die nur die Python-Pipeline und die PHP-Weboberfläche prüft. Das Aussehen und die Bedienung des Players werden von Hand im Browser geprüft (Checkliste siehe nächster Abschnitt).

## Fehlerbehebung (WordPress-Frontend)

| Symptom | Ursache und Lösung |
|---|---|
| Das Plugin „Zeitraffer“ fehlt in der Pluginliste | Der Mount fehlt. `docker compose exec wordpress ls /var/www/html/wp-content/plugins/zeitraffer` muss `plugin-timelapse.php` zeigen. Compose muss aus dem Ordner `docker/` gestartet werden, weil der Pfad `../frontend/zeitraffer` relativ dazu aufgelöst wird. |
| Die Seite zeigt nichts oder „Derzeit sind keine Zeitraffer-Videos verfügbar“ | `videos/` ist leer, oder es gibt keine `.mp4` unter `videos/<Kamera>/<Zeitraum>/`. Mit `docker compose exec wordpress ls /var/www/html/wp-content/uploads/zeitraffer` prüfen und `docker/pull-videos.sh` ausführen. |
| Das Video lädt, lässt sich aber nicht abspielen (z. B. 403 „Forbidden“) | Dateirechte oder Mount prüfen: `docker compose exec wordpress ls -l /var/www/html/wp-content/uploads/zeitraffer/<Kamera>/<Zeitraum>`. Die Dateien müssen für den Webserver lesbar sein. |
| Auf dem Player steht „Das Video konnte nicht geladen werden“ | Die Videodatei fehlt oder ist nicht lesbar. Die Videoadresse im Browser öffnen und Rechte und Mount wie in der Zeile davor prüfen. |
| Kamera ist in der Übersicht, aber der Link zeigt keinen Player | Die Seite mit `[zeitraffer]` fehlt oder hat nicht den Slug `zeitraffer` (siehe Schritt 6). |
| Port 8080 belegt | In `docker/docker-compose.yml` den linken Teil von `"8080:80"` ändern, z. B. `"8081:80"`, und neu starten. |
| Datenbankfehler beim Start | `docker/.env` unvollständig. Alle `DB_*`-Werte setzen. Wurden Werte nach dem ersten Start geändert, bleibt die Datenbank mit den alten Zugangsdaten bestehen; dann `docker compose down -v` und neu installieren. |
| `pull-videos.sh` bricht ab oder hängt | Pi nicht erreichbar oder kein SSH-Schlüssel eingerichtet. Verbindung mit `ssh benutzer@<Pi-Adresse>` prüfen; fehlt `PI`, bricht das Skript mit einem Hinweis ab. |

## Wichtig für den Live-Betrieb

Diese Anleitung beschreibt nur die lokale Entwicklungsumgebung. Auf der Live-Seite werden Plugin und Videos nicht von Docker bereitgestellt. Das Plugin erwartet die Videos unter `wp-content/uploads/zeitraffer/` in genau der Ordnerstruktur oben. Deployment auf die Live-Seite oder den Pi gehört nicht zu diesem Ablauf und passiert nie automatisch.

## Videos auf die Live-Seite bringen: welche Dateien dürfen raus

Der Schritt, der die fertigen Videos vom VPS auf die Live-Seite bringt, ist noch nicht gebaut (README, „Noch offen“). Damit er nicht mehr überträgt als nötig, gibt es auf dem VPS eine Liste der erlaubten Dateien. Sie wird nur gelesen und schreibt nichts:

```bash
.venv/bin/python3 scripts/list-deliverable-videos.py > deliverable.txt
rsync -a --files-from=deliverable.txt videos/ <Ziel>
```

**Was auf der Liste steht**

- Je Kamera und Zeitraum (`daily`, `weekly`, `monthly`, `yearly`) nur das neueste Video, nach Dateinamen wie im Plugin (siehe „So funktioniert das Plugin“).
- Nur reguläre, nicht leere `.mp4`-Dateien direkt in diesen vier Ordnern. Versteckte Dateien (der Encoder schreibt `.<Name>.tmp.mp4`, bis das Video fertig ist) und Symlinks zählen nicht. Eine neuere, leere Datei verdrängt das ältere gültige Video nicht.
- Nichts von Kameras in `ignored_cameras`.
- Alles andere in `videos/` nie: `manual-runs/`, `highlights/`, unbekannte Ordner, lose Dateien. Fehlt `videos/` ganz, endet das Skript mit Fehler (Rückgabewert 1) statt mit einer leeren Liste.

**Neue Kamera.** Den Namen in `ignored_cameras` (`config/config.json`) eintragen, wenn die Kamera eingerichtet wird, vor dem ersten Lauf um 02:00, sonst baut die Nacht schon ein Video. Erst wenn die Kamera live gehen darf, den Namen entfernen. Der Entwurf des Kameraeintrags im WordPress-Plugin ist nur die zweite Sicherung. Wird eine Kamera wegen ihres Inhalts zurückgezogen (Datenschutz, nicht verpixelt), reicht der Entwurf nicht: Die Dateien auf der Live-Seite müssen gelöscht werden.

**Regeln für den Übertragungsjob.** Der Job ist nicht Teil dieses Repositorys, und die Liste schützt nur, wenn er sie benutzt.

1. Eine neue Datei zuerst unter einem versteckten Temporärnamen im selben Ordner hochladen (`rsync` macht das ohne `--inplace` von selbst).
2. Die Größe mit der Quelle vergleichen.
3. Erst dann auf den endgültigen Namen umbenennen.
4. Erst danach, je Kamera und Zeitraum, das neueste und das vorherige Video behalten und ältere löschen. Das vorherige ist die Sicherung und deckt eine zwischengespeicherte Seite ab, die noch den alten Dateinamen enthält.
5. Bei jedem Fehler, bei einer leeren Liste und wenn nichts Neues da ist, wird nichts gelöscht. Nie `rsync --delete` verwenden.
