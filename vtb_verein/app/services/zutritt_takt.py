"""Welcher Sync-Lauf ist gerade fällig? (#61)

Der Sync-Sidecar tickt in einem festen kurzen Takt und fragt bei jedem Tick hier
nach, was zu tun ist. Der eigentliche Takt steht nicht mehr in der Env, sondern in
`schliessanlage_einstellungen` — damit ist er in der App einstellbar, ohne dass
jemand an die `.env` und an einen Container-Neustart muss.

Zwei Läufe mit verschiedenen Kosten:

* **voll** — Inventar, IC-Karten, Credential-Mirror, Soll-Ist-Abgleich, Akku-Tickets
  und Logs. Viele Cloud-Abfragen, deshalb im Stundentakt.
* **logs** — nur die Zutrittslogs. Sie tragen die Alarme (Sabotage, mehrfach falscher
  Passcode), sind aber billig, deshalb im Minutentakt dazwischen.

Der volle Lauf hat Vorrang: Ist er fällig, holt er die Logs ohnehin mit, ein
zusätzlicher Log-Lauf wäre verschenkt. Die Funktion ist bewusst frei von DB und Uhr
— beides kommt von außen, damit sie sich testen lässt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

VOLL = "voll"
LOGS = "logs"


def _als_zeitpunkt(iso: Optional[str]) -> Optional[datetime]:
    """ISO-String aus der DB → aufgeweckter Zeitpunkt; alles Unlesbare gilt als „nie".

    Ein nicht lesbarer Merker führt damit zu einem Lauf, nicht zu einer Pause — die
    für die Alarme sichere Richtung.
    """
    if not iso:
        return None
    try:
        zeitpunkt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    # Ältere Zeilen können ohne Zone geschrieben worden sein; die Läufe stempeln UTC.
    return zeitpunkt if zeitpunkt.tzinfo else zeitpunkt.replace(tzinfo=timezone.utc)


def _ist_faellig(letzter: Optional[str], jetzt: datetime, abstand: timedelta) -> bool:
    """Fällig, wenn seit `letzter` mindestens `abstand` vergangen ist.

    Kein Merker heißt fällig (erster Lauf nach dem Update). Ein Merker aus der
    Zukunft ebenfalls: Das ist eine zurückgestellte Uhr, und ohne diese Regel
    stünde der Sync still, bis die Zukunft eingeholt ist.
    """
    zeitpunkt = _als_zeitpunkt(letzter)
    if zeitpunkt is None or zeitpunkt > jetzt:
        return True
    return (jetzt - zeitpunkt) >= abstand


def faelliger_lauf(jetzt: datetime, *, letzter_voll_sync_at: Optional[str],
                   letzter_log_sync_at: Optional[str],
                   sync_intervall_stunden: int,
                   logs_intervall_minuten: int) -> Optional[str]:
    """`VOLL`, `LOGS` oder None (nichts zu tun) für diesen Tick."""
    if _ist_faellig(letzter_voll_sync_at, jetzt, timedelta(hours=sync_intervall_stunden)):
        return VOLL
    if _ist_faellig(letzter_log_sync_at, jetzt, timedelta(minutes=logs_intervall_minuten)):
        return LOGS
    return None
