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

Seit v122 kommt die Uhrzeit dazu (#95-/#179-Nachgang): Der Abstand allein sagt nur,
WIE OFT gelaufen wird, nicht WANN — der Takt hing am ersten Lauf nach dem Update
und blieb auf dessen zufälliger Uhrzeit stehen. Die Wunschstunde steht in den
Erinnerungs-Einstellungen (`lauf_stunde`) und wird hier als `stunde` übergeben.

Die Entscheidung selbst ist frei von DB und Uhr, damit sie sich testen lässt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Ein Merker je Lauf-Art, deshalb ein fester `detail`-Wert: Die Lauf-Arten trennt
# schon der `event_type` (`termin_erinnerung_lauf`, `ticket_erinnerung_lauf`).
DETAIL = 'lauf'
KATEGORIE = 'system'

# Der Tick trifft den Zeitpunkt nie genau; ohne diese Toleranz verschöbe sich ein
# 24-Stunden-Lauf mit jedem Tag um eine Tick-Länge nach hinten. Mit Wunschstunde
# erübrigt sie sich – dort rundet schon der Anker.
TOLERANZ = timedelta(minutes=1)


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


def _tages_anker(zeitpunkt: datetime, stunde: int, jetzt: datetime) -> datetime:
    """Die Wunschstunde an dem Kalendertag, an dem `zeitpunkt` liegt.

    Gerechnet wird in der Zone von `jetzt` — im Sidecar ist das die Ortszeit
    (`TZ` im Container), im Test die der übergebenen Zeitstempel. Über einen
    Zeitzonenwechsel hinweg kann der Anker damit eine Stunde danebenliegen; das
    kostet einen Lauf, der einmal eine Stunde zu früh oder zu spät kommt und sich
    am Tag darauf von selbst wieder einfängt.
    """
    return zeitpunkt.astimezone(jetzt.tzinfo).replace(
        hour=stunde, minute=0, second=0, microsecond=0)


def ist_faellig(letzter: Any, jetzt: datetime, abstand: timedelta,
                stunde: Optional[int] = None) -> bool:
    """Fällig, wenn seit `letzter` mindestens `abstand` vergangen ist.

    Kein Merker heißt fällig (erster Lauf nach dem Update). Ein Merker aus der
    Zukunft ebenfalls: Das ist eine zurückgestellte Uhr, und ohne diese Regel
    stünden die Erinnerungen still, bis die Zukunft eingeholt ist.

    Der Abstand wird knapp bemessen verglichen (`>=` minus einer Toleranz von einer
    Minute): Der Sidecar tickt in festen Abständen, und ohne Toleranz verschöbe
    sich ein 24-Stunden-Lauf mit jedem Tag um eine Tick-Länge nach hinten, bis er
    irgendwann mitten in der Nacht läge.

    `stunde` ist die Wunschstunde des Vereins (0–23, aus den Erinnerungs-
    Einstellungen): Vor ihr läuft nichts, und der Abstand zählt ab dem **Anker** —
    der Wunschstunde des Tages, an dem der letzte Lauf war — statt ab dessen
    tatsächlicher Uhrzeit. Das ist der Unterschied zwischen „alle 24 Stunden" und
    „täglich um sieben": Ein Lauf, der nach einer Störung erst abends durchkam,
    bliebe sonst für immer am Abend kleben; so ist er am nächsten Morgen wieder
    zur Wunschzeit dran. Ein Lauf von Hand verschiebt den täglichen ebenso wenig.
    Eine Toleranz braucht es dafür nicht: Der Anker ist bereits auf die volle
    Stunde gerundet, der Lauf wandert also gar nicht erst.

    Die Ankerrechnung setzt einen Tagesrhythmus voraus. Bei einem Abstand unter
    24 h bleibt es deshalb bei der reinen Abstands-Regel, und die Stunde sagt dann
    nur, wann der erste Lauf des Tages frühestens darf. Eine unsinnige Stunde wird
    ignoriert — sie darf den Lauf nicht anhalten.
    """
    zeitpunkt = _als_zeitpunkt(letzter)
    if zeitpunkt is None or zeitpunkt > jetzt:
        return True
    if stunde is None or not 0 <= stunde <= 23:
        return (jetzt - zeitpunkt) >= (abstand - TOLERANZ)
    if jetzt.hour < stunde:
        return False
    if abstand < timedelta(hours=24):
        return (jetzt - zeitpunkt) >= (abstand - TOLERANZ)
    return jetzt >= _tages_anker(zeitpunkt, stunde, jetzt) + abstand


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
