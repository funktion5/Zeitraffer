# Handbuch: Raspberry Pi, Stabilität (Archiv)

Aus `docs/handbuch.md` herausgenommen (2026-10-30), weil der Pi abgelöst ist. Der Text gilt nur für den
Raspberry Pi; die allgemeinen Hinweise zum Arbeitsspeicher stehen weiter im Handbuch.

Gilt nur für den Raspberry Pi als Host.

### Der Pi ist unbemerkt neu gestartet

**Prüfen:**

```bash
uptime                                              # seit wann läuft er?
journalctl --list-boots | tail -3                   # Neustarts
journalctl -b -1 -p warning --no-pager | tail -50   # Warnungen vor dem letzten Neustart
grep "<Uhrzeit vor dem Neustart>" /var/log/pi-health.log   # Speicher und Last
```

**Ursache:** Meist ist der Arbeitsspeicher voll gelaufen: großes Video plus weitere Last (VS Code
Remote, ein zweiter Job). Der Pi friert ein, der Hardware-Watchdog startet ihn neu, ohne Meldung.
Danach wiederholt Cron einen unterbrochenen nächtlichen Lauf.

**Lösung:** Gleichzeitige schwere Arbeiten vermeiden (siehe nächster Fall). Fehlen
`/var/log/pi-health.log` oder ein dauerhaftes Journal, die Absturzprotokollierung einrichten
([raspberry-pi.md](raspberry-pi.md)).
