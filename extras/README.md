# Extras

Optionale Zusätze. Sie liegen im Repository und werden getestet, sind aber an nichts angeschlossen:
Sie laufen nur, wenn jemand sie selbst in die Crontab einträgt. Nichts im übrigen Code hängt von
ihnen ab.

## `mark_newest.py`: neuestes Bild der übrigen Kameras markieren

Der Abholjob der Website lädt Bilder hoch, die die Markierung `blur:checked=true` tragen
([verpixelung-box.md](../docs/verpixelung-box.md#markierung-für-die-webseite)). Die Blur-Kameras
markiert die laufende Verpixelung selbst. Dieses Extra markiert bei **allen anderen Kameras** das
**neueste Bild**, ohne es anzusehen: Diese Kameras sind für die Website ohnehin freigegeben. Damit
braucht der Abholjob keine eigene Liste der Blur-Kameras mehr; er nimmt einfach nur markierte Bilder.

Pro Lauf und Kamera (alle Kameras der Storage Box außer `privacy.blur_cameras` und
`ignored_cameras`):

1. Bilder von heute und gestern auflisten und das neueste **nicht leere** nehmen (dieselbe Wahl wie
   der Abholjob, der leere Dateien überspringt).
2. Überspringen, wenn es schon markiert ist (`state/privacy/newest-marked.json` merkt sich das
   zuletzt markierte Bild je Kamera) oder noch hochgeladen wird (jünger als 15 Sekunden).
3. Herunterladen; abgeschnittene Bilder werden nicht markiert, der nächste Lauf versucht es erneut.
4. Markierung einfügen und auf der Box tauschen, **ohne Sicherung und ohne Verpixelung**: Der
   Schreibcode prüft, dass sich nur die 21 Bytes der Markierung unterscheiden und das Bild auf der
   Box unverändert ist.

Ältere Bilder werden nie angefasst. Log: eine Zeile pro Lauf in `logs/privacy/<Datum>.log`, z. B.
`Newest marked: 15 cameras | marked=2 unchanged=12 settling=1 incomplete=0 none=0 failed=0`.
Exit-Code 1, wenn eine Kamera fehlschlug (die übrigen laufen weiter).

### Anschließen

An die Cron-Zeile der laufenden Verpixelung anhängen, damit es direkt nach jeder Runde läuft (auch
wenn die Runde fehlschlug):

```cron
*/5 * * * * cd <projektpfad> && export TIMELAPSE_STORAGE_BOX=<ssh-alias> && timeout -k 10 240 .venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras; timeout 60 .venv/bin/python3 -m extras.mark_newest
```

Danach kann der Abholjob die Liste der Blur-Kameras (`blur_cameras.conf`) weglassen und bei **jeder**
Kamera nur markierte Bilder hochladen.

### Abschalten

`; timeout 60 .venv/bin/python3 -m extras.mark_newest` wieder aus der Cron-Zeile entfernen. Der
Abholjob muss dann wieder mit der Liste arbeiten, sonst bekommt keine andere Kamera mehr ein neues Bild.

### Folgen

- Sobald der Abholjob bei allen Kameras die Markierung verlangt, hängen **alle** Kameras am VPS: Ist
  er oder die Verbindung zur Box weg, zeigt die Website überall das letzte markierte Bild.
- Lädt eine Kamera zweimal innerhalb von 5 Minuten hoch, wird das ältere Bild nie markiert und nie
  veröffentlicht (die Website zeigt ohnehin nur das neueste).
- Die neuesten Bilder aller Kameras ändern sich auf der Box um die 21 Bytes der Markierung (kein Pixel).

Tests: `extras/mark_newest_test.py` (laufen mit `pytest` wie alle anderen).
