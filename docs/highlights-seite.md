# Highlights-Seite

Zeigt in der Weboberfläche die Bilder, die der [Highlights-Flagger](flagger.md) jede Nacht
beiseitelegt (Tiere und Flugobjekte), damit sich Bilder für YouTube oder die Website auswählen
lassen. Aufruf über den Link **Highlights** im Header oder direkt `/highlights.php`.

## Was die Seite zeigt

- Pro Kamera ein Abschnitt, darin die Tage (neuester zuerst) und pro Tag die Bilder (sicherster
  Treffer zuerst).
- Pro Bild: Uhrzeit, Vermutung des Modells mit Fragezeichen (z. B. „Flugzeug?“, das Modell
  irrt sich oft) und Sicherheit in Prozent, dazu **Herunterladen** und **Löschen**.
- Ein Klick auf ein Bild zeigt es groß. **← Vorheriges** / **Nächstes →** oder die
  Pfeiltasten blättern durch alle Bilder der Seite; **Schließen**, Esc oder ein Klick
  neben das Bild schließt die Großansicht. Ohne JavaScript öffnet der Klick das Bild direkt.
- **Markierung zeigen** blendet den Rahmen ein, in dem das Modell etwas erkannt hat, auch in
  der Großansicht. Das Bild selbst bleibt unverändert, auch beim Download.
- Kameras ohne Treffer bleiben sichtbar:
  - „geprüft, nichts gefunden (N Bilder geprüft)“: der Flagger ist gelaufen, aber es gab nichts.
  - „Kein Bericht im Zeitraum.“: für diese Kamera liegt kein Bericht vor (Flagger nicht
    gelaufen oder Kamera fehlgeschlagen, siehe `logs/flagger/`).

Filter (stehen in der URL, lassen sich also als Lesezeichen speichern):

| Feld | Werte | Standard |
|---|---|---|
| Zeitraum (`days`) | Letzter Tag (`1`), 7 Tage (`7`), 30 Tage (`30`), Alles (`all`) | 7 Tage |
| Kamera (`camera`) | Alle oder eine Kamera | Alle |

„Letzter Tag“ ist gestern: der Flagger prüft einen Tag in der Nacht danach. Gezählt wird in der
Zeitzone aus `config.json` (`location.timezone`).

Gelistet werden alle Kameras aus `flagger.cameras` und zusätzlich jede Kamera, für die noch
Berichte da sind (etwa nachdem sie aus der Config genommen wurde).

## Woher die Daten kommen

Die Seite liest nur, was der Flagger schreibt:

```text
videos/<Kamera>/highlights/<JJJJ-MM-TT>/manifest.json
videos/<Kamera>/highlights/<JJJJ-MM-TT>/<bild>.jpg
```

Felder der `manifest.json`: [flagger.md](flagger.md#ausgabe). Ein beschädigter Bericht oder
ein Eintrag mit falschen Feldern wird übersprungen, ohne die Seite zu stören. Ein Bild, das in
der `manifest.json` steht, aber nicht mehr als Datei da ist, wird nicht angezeigt.

Berichte älter als 30 Tage (`flagger.retention_days`) räumt der Flagger selbst auf; die Seite
löscht nichts automatisch.

## Löschen

Ein Klick auf **Löschen** öffnet einen Bestätigungsdialog mit dem Dateinamen. Erst nach
**Löschen** im Dialog wird das Bild entfernt, danach erscheint „Bild erfolgreich gelöscht.“.
Die `manifest.json` bleibt unverändert; die Seite zeigt das Bild nicht mehr, weil die Datei fehlt.

Läuft der Flagger für einen Tag erneut (nur von Hand), ersetzt er den ganzen Ordner des Tages:
vorher gelöschte Bilder dieses Tages sind dann wieder da.

Technisch: `videos/` ist für `www-data` nur lesbar. PHP prüft Sicherheitstoken, Kamera, Datum
und Dateiname gegen die aktuelle Liste und ruft dann über `sudo` den festen Wrapper
`/usr/local/sbin/timelapse-web-delete-highlight <Kamera> <Datum> <Datei>` auf. Er löscht
nur eine `.jpg` direkt in `videos/<Kamera>/highlights/<Datum>/`, nie die `manifest.json`, und
lehnt Symlinks ab.

## Einmalige Einrichtung auf dem Pi

Als root, wie bei den anderen Wrappern ([README: Wrapper installieren](../README.md#wrapper-installieren)):

```bash
sudo install -o root -g root -m 755 \
  scripts/timelapse-web-delete-highlight \
  /usr/local/sbin/timelapse-web-delete-highlight
sudo visudo -f /etc/sudoers.d/timelapse-web
```

In `visudo` diese Zeile ergänzen (`<benutzer>` = Besitzer des Projektordners):

```sudoers
www-data ALL=(<benutzer>) NOPASSWD: /usr/local/sbin/timelapse-web-delete-highlight
```

Nach jeder Änderung an `scripts/timelapse-web-delete-highlight` muss der Wrapper erneut mit
`sudo install` installiert werden. Bei einer Neuinstallation erledigt das `migrate.sh`.

## Fehlersuche

| Anzeige | Ursache | Lösung |
|---|---|---|
| „Das Bild konnte nicht gelöscht werden.“ | Wrapper nicht installiert oder sudoers-Zeile fehlt | Einrichtung oben; Details in `/var/log/apache2/zeitraffer-error.log` |
| „Das ausgewählte Bild wurde nicht gefunden.“ | Bild inzwischen gelöscht (anderer Tab, Aufräumen) | Seite neu laden |
| „Die Anfrage ist ungültig (Sicherheitstoken).“ | Sitzung abgelaufen | Seite neu laden, erneut löschen |
| Kamera zeigt „Kein Bericht im Zeitraum.“ | Flagger nicht gelaufen oder für diese Kamera fehlgeschlagen | `logs/flagger/<Datum>.log` prüfen |
| „Noch keine Highlights vorhanden.“ | `flagger.cameras` leer und keine Berichte | Kameras in `config/config.json` eintragen |
| Kamera zeigt „Keine Highlights im Zeitraum.“ | Kamera steht nicht mehr in `flagger.cameras`, hat aber alte Highlights; im gewählten Zeitraum liegt keiner | Zeitraum vergrößern; normal, wenn die Kamera bewusst entfernt wurde |
| „Für diese Kamera gibt es keine Highlights.“ | Die Kamera im Filter (`camera=` in der URL, z. B. aus einem alten Lesezeichen) hat weder einen Eintrag in `flagger.cameras` noch einen Highlights-Ordner | Filter „Kamera“ auf „Alle“ stellen |
| „Die ausgewählte Kamera ist ungültig.“ | Löschen für eine Kamera, die nicht (mehr) in der Liste steht | Seite neu laden |

## Dateien und Tests

| Datei | Aufgabe |
|---|---|
| `web/public/highlights.php` | Seite, Filter, Löschen |
| `web/src/highlights-library.php` | Berichte lesen und prüfen |
| `web/src/highlight-delete.php` | Aufruf des Wrappers |
| `scripts/timelapse-web-delete-highlight` | Löschen als Projektbenutzer |

Tests: `tests/web_highlights_test.py` (Bibliothek, Wrapper-Aufruf),
`tests/web_highlights_page_test.py` (Seite, Filter, Löschen per POST),
`tests/web_delete_highlight_test.py` (Wrapper).
