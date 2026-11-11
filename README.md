# Zeitraffer

Zeitraffer macht aus den Bildern unserer Webcams jede Nacht automatisch Zeitraffer-Videos: ein
Video pro Kamera für gestern, für die letzte Woche, für den letzten Monat und für das letzte Jahr.
Die fertigen Videos erscheinen auf der Website unter dem Webcam-Bild.

Diese Seite erklärt in einfachen Worten, **was** das Programm tut. Wie man es einrichtet und wie es
im Inneren funktioniert, steht in den Dokumenten im Ordner [`docs/`](docs); am Ende dieser Seite
steht, was wo zu finden ist.

## Der Weg eines Bildes – auf einen Blick

```
 Kamera  ──►  Storage Box  ──►  Zeitraffer-Server  ──►  Website  ──►  Besucher
 (macht      (sammelt alle      (baut jede Nacht       (zeigt das     (sehen das Video
  Fotos)      Bilder, Archiv)    die Videos)            Video)         unter dem Bild)
```

1. **Kamera** – Jede Webcam macht den ganzen Tag über regelmäßig ein Foto und lädt es hoch.
2. **Storage Box** – Ein Online-Speicher. Hier landen alle Bilder aller Kameras. Er ist
   das Archiv: Das Programm liest von hier nur, es räumt hier nichts weg.
3. **Zeitraffer-Server** – Ein Server, auf dem das Programm läuft. Jede Nacht holt er
   sich die Bilder, wählt die passenden aus und setzt daraus die Videos zusammen.
4. **Website** – Der Server lädt die fertigen Videos auf die Website hoch. Das WordPress-Plugin
   „F5 Webcams“ zeigt sie unter dem Webcam-Bild an.
5. **Besucher** – Sie sehen den Zeitraffer auf der Seite der jeweiligen Webcam.

## Was jede Nacht passiert

Jede Nacht um 2 Uhr startet der Server von selbst vier Schritte nacheinander. Niemand muss etwas tun.

```
 02:00 Uhr
   │
   ├─ 1. Menschen unkenntlich machen   (nur bei Kameras, auf denen Menschen zu sehen sind)
   │
   ├─ 2. Videos bauen                  (Tag, Woche, Monat, Jahr – für jede Kamera)
   │
   ├─ 3. Videos auf die Website laden
   │
   └─ 4. Nach Tieren und Flugobjekten suchen   (die „Highlights“)
```

Geht bei einem Schritt etwas schief, laufen die nächsten trotzdem weiter. Jeder Lauf schreibt einen
Bericht, in dem sich Fehler nachlesen lassen.

## Die vier Videos

| Video | Was es zeigt | Welche Bilder |
|---|---|---|
| **Tagesvideo** | gestern | alle Bilder bei Tageslicht, vom Sonnenaufgang bis zum Sonnenuntergang |
| **Wochenvideo** | die letzten 7 Tage | die sieben Tagesvideos hintereinander |
| **Monatsvideo** | die letzten 30 Tage | jeden Tag die Bilder um die Mittagszeit |
| **Jahresvideo** | das letzte Jahr | jeden Tag bis zu fünf Bilder um die Mittagszeit |

- Von jedem Video bleibt immer das neueste. Auf dem Server bleiben außerdem die Tagesvideos der
  letzten 7 Tage, auf der Website je Kamera und Videoart die zwei neuesten.
- War eine Kamera so lange ausgefallen, dass für ein Monats- oder Jahresvideo zu viele Tage fehlen
  (beim Monat müssen 25 von 30 Tagen Bilder haben, beim Jahr 300 Tage), wird dieses Video in der
  Nacht ausgelassen. Das alte Video bleibt dann stehen.
- **Die Originalbilder verändert das Zeitraffer-Programm nie.** Die einzige Ausnahme ist das
  Unkenntlichmachen von Menschen (siehe unten): Dort ersetzt eine verpixelte Fassung das Bild auf
  dem Online-Speicher, und das Original wird vorher gesichert.

## Menschen und Kennzeichen – der Datenschutz

Auf manchen Kameras sind Menschen oder Autokennzeichen zu erkennen. Bei diesen Kameras (derzeit
Scheunenviertel und SLSV) macht das Programm sie jede Nacht unkenntlich, **bevor** Videos gebaut werden.

```
 Bild vom Online-Speicher
          │
          ▼
 Erkennung: Ist ein Mensch oder ein Kennzeichen zu sehen?
          │                            │
         ja                          nein
          │                            │
          ▼                            │
 Das Original wird gesichert,          │
 die Stelle wird verpixelt             │
          │                            │
          ▼                            ▼
 Erst jetzt darf das Bild in ein Video
```

Der Grundsatz heißt: **Im Zweifel lieber kein Video als ein ungeprüftes Bild.**

- Bei diesen Kameras entstehen die nächtlichen Videos nur aus Bildern, die geprüft wurden. Ist
  gar kein geprüftes Bild da, wird die Kamera in dieser Nacht ausgelassen.
- Ein von Hand bestelltes Video einer solchen Kamera prüft und verpixelt seine Bilder zuerst. Das
  dauert deutlich länger (ein Monatsvideo mit rund 350 Bildern brauchte 55 Minuten).
- Keine Erkennung findet jeden Menschen. Das Programm ist eine Hilfe, kein Freibrief.

## Was man selbst tun kann – die Weboberfläche

Zusätzlich gibt es eine kleine Webseite für das Team. Sie ist mit Benutzername und Passwort
geschützt und nicht für das offene Internet gedacht. Dort kann man:

- für eine Kamera ein **Video für einen beliebigen vergangenen Zeitraum** bestellen: einen Tag,
  eine Woche, einen Monat oder ein Jahr, jeweils bis zu einem gewählten Datum. Monats- und
  Jahresvideos gibt es auch mit den Bildern um den **Sonnenuntergang**. Das Video entsteht im
  Hintergrund; ein Fenster meldet, wenn es fertig ist, und nennt bei einem Fehlschlag den Grund.
  Solange eines entsteht, lässt sich kein weiteres bestellen.
- Videos **ansehen und herunterladen**, auch die nächtlichen. **Löschen** lassen sich nur die
  selbst bestellten.
- auf der Seite **Highlights** Bilder ansehen, groß anzeigen, herunterladen und löschen, auf denen
  das Programm Tiere oder Flugobjekte gefunden hat (Vögel, Flugzeuge, Drachen). Das Programm irrt
  sich manchmal, darum zeigt die Seite nur die Markierung, und **ein Mensch entscheidet**. Treffer
  bleiben 30 Tage erhalten. Gedacht ist das für die Auswahl guter Motive, zum Beispiel für YouTube.

- die **automatischen Videos einer Kamera neu erstellen lassen**, zum Beispiel wenn die Kamera in der
  Nacht ausgefallen war, und sie danach **auf die Website übertragen**. Beides steckt auf der Seite
  der Kamera in einer Leiste, die erst aufklappt, wenn man sie öffnet. Vor dem Übertragen muss man
  ausdrücklich bestätigen; die Seite sagt vorher, welche Videos gesendet werden.
- auf der Seite **Einstellungen** (Zahnrad oben rechts) Werte ändern, für die man sonst die IT
  braucht: zum Beispiel in welcher Qualität die Videos entstehen, welche Kameras verarbeitet werden
  oder wie die Verpixelung arbeitet. Bei der Verpixelung kann man auf einem echten Kamerabild
  einzeichnen, wo etwas fälschlich verpixelt wird (ein Poller, ein Boot, die Kamerahalterung).
  Das Bild ist immer eins, das die Verpixelung schon geprüft hat, nie ein Rohbild. Weil
  die Verpixelung eine Datenschutz-Einstellung ist, fragt die Seite vor dem Speichern noch einmal
  nach. Eine Änderung gilt ab dem nächsten Auftrag, laufende Aufträge bleiben unberührt.

Wie diese Seite aufgebaut ist: [docs/weboberflaeche.md](docs/weboberflaeche.md).

## Wenn ein Video fehlt oder zu alt ist

1. **Welches Video, welche Kamera?** Fehlt nur ein Video einer Kamera, oder sind alle alt?
2. **Nur das Monats- oder Jahresvideo einer Kamera fehlt:** Wahrscheinlich war die Kamera so lange
   ausgefallen, dass zu viele Tage ohne Bilder sind (siehe „Die vier Videos“). Kamera und ihren
   Upload zur Storage Box prüfen. Das Video kommt von selbst wieder, sobald genug Tage da sind.
3. **Bei einer Kamera mit Menschen im Bild fehlen Videos:** Möglicherweise sind Bilder noch nicht
   geprüft (siehe „Menschen und Kennzeichen“). Meist gleicht sich das in der nächsten Nacht aus; was
   dahintersteckt, steht in [docs/verpixelung-box.md](docs/verpixelung-box.md#sperre-in-automatischen-videos).
4. **Alle Videos sind alt:** Vermutlich ist der nächtliche Lauf nicht gelaufen. Das sieht man im
   Bericht des Laufs; wie man ihn liest, steht im [Handbuch](docs/handbuch.md#nächtlicher-lauf).
5. **Das Video ist auf dem Server, aber nicht auf der Website:** Dann ist der Upload hängengeblieben.
   Was in den Protokollen steht und was zu tun ist:
   [Handbuch – Upload auf die Website](docs/handbuch.md#upload-auf-die-website).
6. **Ein Video fehlt, weil die Kamera in der Nacht ausgefallen war, und sie läuft wieder:** Auf der
   Seite der Kamera in der Weboberfläche die Leiste „Automatische Videos neu erstellen und
   hochladen“ öffnen, die fehlenden Videos neu erstellen, ansehen und danach auf die Website
   übertragen ([so geht es](docs/weboberflaeche.md#neu-erstellen-wie-der-nachtlauf)).

Das Handbuch beschreibt alle Fehlerfälle Schritt für Schritt: [docs/handbuch.md](docs/handbuch.md).

## Kleines Wörterbuch

| Begriff | Bedeutung |
|---|---|
| **Storage Box** | Der Online-Speicher, auf dem alle Kamerabilder liegen |
| **Server** | Der Rechner, auf dem das Programm läuft (auch „VPS“ genannt) |
| **Nachtlauf** | Die Arbeit, die der Server jede Nacht um 2 Uhr erledigt |
| **Cronjob** | Ein regelmäßig automatisch gestarteter Auftrag; der Nachtlauf ist einer |
| **Verpixeln** | Menschen und Kennzeichen auf einem Bild unkenntlich machen |
| **Highlights** | Bilder, auf denen das Programm Tiere oder Flugobjekte gefunden hat |
| **Weboberfläche** | Die kleine Webseite für das Team, um Videos zu bestellen und anzusehen |
| **FFmpeg** | Das Programm, das aus vielen Bildern ein Video macht |
| **WordPress-Plugin** | Der Teil auf der Website, der die Videos anzeigt („F5 Webcams“) |

## Wo steht was?

| Ich möchte … | Hier steht es |
|---|---|
| wissen, was zu tun ist, wenn etwas nicht klappt | [Handbuch](docs/handbuch.md) |
| verstehen, wie der Nachtlauf, die Videoarten und die Aufbewahrung genau funktionieren | [docs/betrieb.md](docs/betrieb.md) |
| einen Server umziehen oder die Sicherung zurückspielen | [docs/vps.md](docs/vps.md) |
| wissen, wie die Verpixelung arbeitet | [docs/verpixelung.md](docs/verpixelung.md) und [docs/verpixelung-box.md](docs/verpixelung-box.md) |
| etwas über die Highlights wissen | [docs/flagger.md](docs/flagger.md) und [docs/highlights-seite.md](docs/highlights-seite.md) |
| das WordPress-Plugin verstehen | [docs/wordpress.md](docs/wordpress.md) |
| einen Lauf von Hand starten | [docs/cli.md](docs/cli.md) |
| Hilfsprogramme nutzen (Speicherfilter, Jahresvideos nachholen, NAS-Archiv) | [docs/werkzeuge.md](docs/werkzeuge.md) und [docs/nas.md](docs/nas.md) |
| nachlesen, was früher war (Raspberry Pi, Docker-Test) | [archive/README.md](archive/README.md) |
| YouTube-Beschreibungen schreiben | [youtube/description-prompt](docs/youtube/youtube-description-prompt.md) und [youtube/texts](docs/youtube/youtube-texts.md) |
| Pläne für neue Funktionen ansehen | `docs/plans/` (offen oder zurückgestellt) und `docs/plans/done/` (umgesetzt) |
| den Code und die Ordner verstehen | [docs/architektur.md](docs/architektur.md) |
| Einstellungen ändern (die Seite „Einstellungen“, `config/config.json`, Umgebungsvariablen) | [docs/konfiguration.md](docs/konfiguration.md) und [docs/weboberflaeche.md](docs/weboberflaeche.md#einstellungen) |
| einen Server von Grund auf installieren | [docs/installation.md](docs/installation.md) und [docs/vps.md](docs/vps.md) |
| die Weboberfläche auf dem eigenen Rechner ausprobieren, ohne den Server anzufassen | [docs/docker-web.md](docs/docker-web.md) |

## Was noch fehlt

Nachtlauf, Upload und Highlights laufen jede Nacht von selbst. Offen ist noch eine Sache: Neue
Bilder werden bisher nur einmal pro Nacht verpixelt, nicht laufend am Tag. Dafür gibt es nur einen
Entwurf, entschieden ist nichts.

## Für Entwickler

Das Programm ist in Python geschrieben, die Videos erzeugt FFmpeg, die Weboberfläche ist in PHP.
Aufbau, Tests und Sicherheitsregeln: [docs/architektur.md](docs/architektur.md).
