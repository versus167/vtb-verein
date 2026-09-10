"""Ist ein Sidecar-Lauf fällig? — Merker im Protokoll statt Uhr im Container.

Die Erinnerungs-Sidecars liefen bisher sofort beim Start und danach alle H Stunden
(`while true; python …; sleep H*3600`). Jeder Deploy löste damit einen zusätzlichen
Lauf aus, außer der Reihe und mit vollem Mailversand — bei mehreren Deploys am Tag
mehrfach.

Deshalb dasselbe Muster wie beim Zutritts-Sync (siehe `zutritt_takt`): Der Container
tickt in einem kurzen festen Takt und fragt hier nach, ob wirklich etwas ansteht.
Anders als dort steht der Takt nicht in der App, sondern bleibt betriebliche
Env-Sache — wie oft an Termine erinnert wird, entscheidet der Verein über die
Vorlauf-Stufen, nicht über die Frequenz des Containers.

Der Merker steht im `access_log`: Das Protokoll trägt diese Information ohnehin
(dort merken sich die Läufe schon, welche Stufe an welchen Termin ging), eine
eigene Tabelle bräuchte Schema, Migration und einen PRUNE_REGISTRY-Eintrag für
genau eine Zeitangabe. Die zeitbasierte Bereinigung des Protokolls gilt für ihn
mit; fällt der Merker dabei weg, ist die Folge ein Lauf zu viel, nicht einer zu
wenig.

Die Entscheidung selbst ist frei von DB und Uhr, damit sie sich testen lässt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Ein Merker je Lauf-Art, deshalb ein fester `detail`-Wert: Die Lauf-Arten trennt
# schon der `event_type` (`termin_erinnerung_lauf`, `ticket_erinnerung_lauf`).
DETAIL = 'lauf'
KATEGORIE = 'system'


def _als_zeitpunkt(wert: Any) -> Optional[datetime]:
    """Merker aus dem Protokoll → aufgeweckter Zeitpunkt; Unlesbares gilt als „nie".

    psycopg liefert `TIMESTAMPTZ` bereits als `datetime`; ältere oder von Hand
    geschriebene Zeilen können ISO-Strings sein. Ein nicht lesbarer Merker führt
    zu einem Lauf, nicht zu einer Pause — die für Erinnerungen sichere Richtung.
    """
    if isinstance(wert, datetime):
        zeitpunkt = wert
    elif isinstance(wert, str) and wert:
        try:
            zeitpunkt = datetime.fromisoformat(wert)
        except ValueError:
            return None
    else:
        return None
    return zeitpunkt if zeitpunkt.tzinfo else zeitpunkt.replace(tzinfo=timezone.utc)


def ist_faellig(letzter: Any, jetzt: datetime, abstand: timedelta) -> bool:
    """Fällig, wenn seit `letzter` mindestens `abstand` vergangen ist.

    Kein Merker heißt fällig (erster Lauf nach dem Update). Ein Merker aus der
    Zukunft ebenfalls: Das ist eine zurückgestellte Uhr, und ohne diese Regel
    stünden die Erinnerungen still, bis die Zukunft eingeholt ist.

    Der Abstand wird knapp bemessen verglichen (`>=` minus einer Toleranz von einer
    Minute): Der Sidecar tickt in festen Abständen, und ohne Toleranz verschöbe
    sich ein 24-Stunden-Lauf mit jedem Tag um eine Tick-Länge nach hinten, bis er
    irgendwann mitten in der Nacht läge.
    """
    zeitpunkt = _als_zeitpunkt(letzter)
    if zeitpunkt is None or zeitpunkt > jetzt:
        return True
    return (jetzt - zeitpunkt) >= (abstand - timedelta(minutes=1))


def letzter_lauf(db, event: str) -> Any:
    """Zeitpunkt des letzten vermerkten Laufs dieser Art (None = noch keiner)."""
    return db.access_log_repository.letzte_je_detail(event).get(DETAIL)


def vermerken(db, event: str) -> None:
    """Diesen Lauf als geschehen vermerken — am Ende, nicht am Anfang.

    Ein Lauf, der auf halber Strecke abstürzt, gilt damit als nicht gelaufen und
    wird beim nächsten Tick wiederholt. Was er bis dahin verschickt hatte, ist
    ohnehin je Termin bzw. Ticket vermerkt und geht nicht doppelt raus.
    """
    db.access_log_repository.log(event, category=KATEGORIE, detail=DETAIL)
