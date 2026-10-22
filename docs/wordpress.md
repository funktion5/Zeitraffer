# WordPress-Frontend

Das WordPress-Plugin „Zeitraffer“ zeigt die fertigen Videos auf einer WordPress-Seite, und so wird es lokal entwickelt und getestet.


Zusätzlich zur PHP-Weboberfläche gibt es ein WordPress-Plugin (`frontend/`), das die fertigen Videos auf einer WordPress-Seite zeigt. Es ist **nur lesend**: Es startet keine Jobs, schreibt keine Dateien und hat keine Formulare, AJAX- oder REST-Endpunkte. Entwickelt wird es lokal auf dem Mac in einer Docker-Umgebung; die Pi-Weboberfläche bleibt davon unberührt.

```text
Pi: videos/<Kamera>/<Zeitraum>/*.mp4
  → docker/pull-videos.sh (rsync, nur Lesen auf dem Pi)
  → Mac: videos/
  → Docker-Container "wordpress": wp-content/uploads/zeitraffer/ (schreibgeschützt)
  → Plugin frontend/zeitraffer/plugin-timelapse.php
  → Shortcodes [tl] und [zeitraffer]
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
| `frontend/` | `/var/www/html/wp-content/plugins/zeitraffer` | Das Plugin, schreibgeschützt (`:ro`). Änderungen am Code sind sofort sichtbar. |
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
| `camera` | ja | Der Ordner der Kamera, klein geschrieben und bereinigt (nur `a-z`, `0-9`, `_`, `-`). Aus `Nordufer_tele` wird `nordufer_tele`; der Kasten „Zeitraffer“ im Kameraeintrag zeigt den richtigen Wert. Ohne dieses Attribut wird `?camera=` aus der URL verwendet. |
| `title` | nein | Überschreibt den Titel des Kameraeintrags. Normalerweise nicht nötig. |
| `description` | nein | Überschreibt den Auszug des Kameraeintrags. Normalerweise nicht nötig. |
| `heading` | nein | Ebene der Überschrift des Players, `2` bis `6`, Standard `2`. So lässt sich die Überschrift in die Struktur der Seite einpassen, z. B. `heading="4"` für Seiten, deren Abschnittstitel `h4` sind. Ungültige Werte ergeben `2`. |

Vorrang: Attribut im Shortcode, dann Kameraeintrag, dann Ordnername bzw. nur der Hinweis „Zeitraffer ohne Ton“. Texte aus einem Entwurf werden nur Redakteuren in der Vorschau gezeigt (siehe nächster Abschnitt).

### Sichtbarkeit: Entwurf und veröffentlicht

Ob eine Kamera für Besucher erscheint, entscheidet allein der Status ihres Eintrags:

| Eintrag | Besucher | Redakteure (Recht „Beiträge anderer bearbeiten“) |
|---|---|---|
| veröffentlicht | Player, Tabs, Texte | wie Besucher |
| Entwurf, ausstehend, privat | nichts (auch kein Link in `[tl]`) | Player mit Hinweis „nicht veröffentlicht“ |
| kein Eintrag (Ordner noch nicht angelegt) | nichts | Player mit Hinweis |

So kann eine neue Kamera auf ihrer echten Seite getestet werden, ohne dass sie öffentlich ist: Entwurf anlegen, die Seite als angemeldeter Redakteur prüfen, dann veröffentlichen. Wichtig: Schaltet ein bereits veröffentlichter Eintrag zurück auf Entwurf, verschwindet die Kamera sofort. Texte bearbeitet man deshalb am besten im veröffentlichten Eintrag und speichert mit „Aktualisieren“.

Hinweis zum Caching: Sieht ein Zwischenspeicher (Cache-Plugin, CDN) eine für angemeldete Redakteure erzeugte Seite, könnte er den Entwurf an Besucher ausliefern. Angemeldete Nutzer werden normalerweise nicht gecacht; auf der Testseite prüfen.

Hinweise:

- **Tippfehler:** Stimmt `camera` nicht mit einem Ordner überein, sehen Besucher nichts. Angemeldete Redakteure (Recht „Seiten bearbeiten“) sehen einen Hinweis mit den verfügbaren Kameras.
- **Auszug und Barrierefreiheit:** Ein Zeitraffer ohne Ton braucht eine Textalternative (WCAG 1.2.1). Mit Auszug beschreibt der Text die Szene („Blick über den Hafen auf Boote und Steg“); ohne ihn steht nur der Hinweis „Zeitraffer ohne Ton“. Der Auszug sollte deshalb für jede Kamera gesetzt werden. Er ist reiner Text, HTML erscheint wörtlich.
- **Ein Player pro Seite:** Der Player verwendet feste Element-IDs; mehrere `[zeitraffer]` auf derselben Seite funktionieren nicht.
- **Überschrift:** Das Plugin gibt eine eigene Überschrift aus („Zeitraffer – Zeitraum“, ohne Kameranamen, weil die Seite die Kamera schon im Titel nennt). Standard ist `<h2>`; die Ebene lässt sich mit `heading` anpassen. Ob sie zur Überschriftenstruktur der Seite passt, sollte auf einer Testseite geprüft werden.

### Optional: gemeinsame Übersicht und Playerseite

Der ältere Aufbau mit zwei Seiten funktioniert weiter. Er wird für die Kameraseiten nicht gebraucht.

| Seite | Titel / Slug | Inhalt | Funktion |
|---|---|---|---|
| Kameraübersicht | z. B. „Kameras“ | `[tl]` | Liste aller Kameras mit Videos, jede verlinkt auf die Playerseite |
| Player | **„Zeitraffer“, Slug `zeitraffer`** | `[zeitraffer]` | Zeigt das Video der Kamera aus `?camera=` (`http://localhost:8080/zeitraffer/?camera=<slug>`, optional `&period=daily|weekly|monthly|yearly`) |

Die Übersicht sucht die Playerseite über den Slug `zeitraffer`. Ist sie nicht vorhanden, verlinkt die Übersicht auf die aktuelle Seite. Der Slug lässt sich per Filter ändern, ohne das Plugin zu bearbeiten:

```php
add_filter( 'zeitraffer_camera_page_slug', fn() => 'mein-slug' );
```

## So funktioniert das Plugin

- **Kameras** sind die Unterordner von `videos/`. Ein Ordner erscheint nur, wenn er in mindestens einem Zeitraum ein `.mp4` enthält **und** sein Kameraeintrag veröffentlicht ist. Der Slug in der URL ist der Ordnername, durch `sanitize_key()` bereinigt (nur `a-z`, `0-9`, `_`, `-`).
- **Das neueste Video** je Zeitraum ist die Datei, die nach Dateinamen zuletzt kommt. Das setzt voraus, dass das Datum im Dateinamen steht (`<Kamera>_<JJJJ-MM-TT>.mp4`), wie es die Pipeline erzeugt.
- Die Überschrift zeigt „Zeitraffer“ und den Zeitraum, den das Video abdeckt. Das Enddatum steht im Dateinamen (`<Kamera>_<JJJJ-MM-TT>.mp4`; ohne Datum im Namen gilt das Änderungsdatum der Datei), der Anfang ergibt sich aus dem Typ wie in der Pipeline: Tag = dieser Tag, Woche = 7 Kalendertage, Monat = 30 Tage, Jahr = das Kalenderjahr bis zum Enddatum (365 oder 366 Tage), jeweils einschließlich Enddatum. Beispiel Woche: „Zeitraffer – 15.09.2026 bis 21.09.2026“. Das Datumsformat folgt der Einstellung von WordPress (Einstellungen → Allgemein), und der Zeitraum wechselt mit dem Tab.
- Hat der angefragte Zeitraum kein Video, springt der Player auf den ersten Zeitraum, der eines hat.
- Versteckte Dateien und `manual-runs/` werden nicht angezeigt.
- Die Tabs funktionieren auch ohne JavaScript als normale Links; `assets/script.js` schaltet nur ohne Seitenneuladen um und zeigt dabei ein Lade-Skelett (`assets/style.css`).
- Das Plugin lädt **nichts von Dritten**: keine externen Schriften, Skripte oder Tracker, keine Cookies und kein Browser-Speicher. Es sind also keine Einwilligung und keine Datenschutzanpassung nötig.
- Farben folgen der Palette des Avada-Themes (`--awb-color*`), mit denselben Hex-Werten als Rückfallwert in der lokalen Umgebung. Schrift und Textfarbe erbt das Plugin vom Theme.

## Täglicher Betrieb

```bash
cd docker
docker compose up -d       # starten
docker compose down        # stoppen, Daten bleiben erhalten
docker compose down -v     # stoppen UND Volumes löschen: WordPress-Installation und Datenbank sind weg
```

- Neue Videos: `docker/pull-videos.sh` ausführen und die Seite neu laden. Ein Neustart ist nicht nötig.
- Code ändern: Datei in `frontend/` speichern und neu laden. Die Versionsnummer von CSS und JS ist deren Änderungszeit, daher gibt es keine Cache-Probleme; bei Zweifeln Strg/Cmd+Shift+R.
- Mac ausschalten: nichts zu tun. Die Container starten mit Docker Desktop wieder (`restart: always`) oder per `docker compose up -d`; Installation und Videos bleiben erhalten.
- `down -v` entspricht einem Zurücksetzen auf eine frische WordPress-Installation (Schritt 4 beginnt wieder von vorn). Videos und Plugin-Code sind nicht betroffen, weil sie nur eingebunden sind.

## Syntaxprüfung des Plugins

Ohne lokale PHP-Installation über den Container:

```bash
docker run --rm -v "$PWD/frontend":/w php:8.4-cli php -l /w/zeitraffer/plugin-timelapse.php
```

Für das Plugin gibt es keine automatisierten Tests; die GitHub-Action prüft nur die Python-Pipeline und die PHP-Weboberfläche.

## Fehlerbehebung (WordPress-Frontend)

| Symptom | Ursache und Lösung |
|---|---|
| Das Plugin „Zeitraffer“ fehlt in der Pluginliste | Der Mount fehlt. `docker compose exec wordpress ls /var/www/html/wp-content/plugins/zeitraffer` muss `plugin-timelapse.php` zeigen. Compose muss aus dem Ordner `docker/` gestartet werden, weil der Pfad `../frontend/zeitraffer` relativ dazu aufgelöst wird. |
| Die Seite zeigt nichts oder „Derzeit sind keine Zeitraffer-Videos verfügbar“ | `videos/` ist leer, oder es gibt keine `.mp4` unter `videos/<Kamera>/<Zeitraum>/`. Mit `docker compose exec wordpress ls /var/www/html/wp-content/uploads/zeitraffer` prüfen und `docker/pull-videos.sh` ausführen. |
| Das Video lädt, lässt sich aber nicht abspielen (z. B. 403 „Forbidden“) | Dateirechte oder Mount prüfen: `docker compose exec wordpress ls -l /var/www/html/wp-content/uploads/zeitraffer/<Kamera>/<Zeitraum>`. Die Dateien müssen für den Webserver lesbar sein. |
| Kamera ist in der Übersicht, aber der Link zeigt keinen Player | Die Seite mit `[zeitraffer]` fehlt oder hat nicht den Slug `zeitraffer` (siehe Schritt 6). |
| Port 8080 belegt | In `docker/docker-compose.yml` den linken Teil von `"8080:80"` ändern, z. B. `"8081:80"`, und neu starten. |
| Datenbankfehler beim Start | `docker/.env` unvollständig. Alle `DB_*`-Werte setzen. Wurden Werte nach dem ersten Start geändert, bleibt die Datenbank mit den alten Zugangsdaten bestehen; dann `docker compose down -v` und neu installieren. |
| `pull-videos.sh` bricht ab oder hängt | Pi nicht erreichbar oder kein SSH-Schlüssel eingerichtet. Verbindung mit `ssh benutzer@<Pi-Adresse>` prüfen; fehlt `PI`, bricht das Skript mit einem Hinweis ab. |

## Wichtig für den Live-Betrieb

Diese Anleitung beschreibt nur die lokale Entwicklungsumgebung. Auf der Live-Seite werden Plugin und Videos nicht von Docker bereitgestellt. Das Plugin erwartet die Videos unter `wp-content/uploads/zeitraffer/` in genau der Ordnerstruktur oben. Deployment auf die Live-Seite oder den Pi gehört nicht zu diesem Ablauf und passiert nie automatisch.
