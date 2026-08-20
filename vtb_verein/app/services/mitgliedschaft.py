"""Fachregeln rund um die Vereinsmitgliedschaft (framework-agnostisch).

Eine Zuordnung (Abteilung/Funktion/Mannschaft) gehört immer zur aktiven
Vereinsmitgliedschaft: Ihr Beginn darf weder vor dem Vereinseintritt noch – da
der Vereinsaustritt alles beendet – nach dem Vereinsaustritt liegen.
"""
from datetime import date
from typing import Optional


def pruefe_von_in_mitgliedschaft(eintrittsdatum: Optional[str],
                                 austrittsdatum: Optional[str],
                                 von: Optional[str]) -> None:
    """Stellt sicher, dass der Beginn `von` innerhalb der Vereinsmitgliedschaft
    liegt. Erwartet ISO-Datumsstrings (YYYY-MM-DD); ohne `von` ist nichts zu
    prüfen. Wirft ValueError bei Verletzung.
    """
    if not (von or '').strip():
        return
    v = von.strip()[:10]
    eintritt = (eintrittsdatum or '').strip()[:10]
    if eintritt and v < eintritt:
        raise ValueError(
            f"Beginn ({v}) darf nicht vor dem Vereinseintritt ({eintritt}) liegen."
        )
    austritt = (austrittsdatum or '').strip()[:10]
    if austritt and v > austritt:
        raise ValueError(
            f"Beginn ({v}) darf nicht nach dem Vereinsaustritt ({austritt}) liegen."
        )


def _iso(wert: Optional[str]) -> str:
    return (wert or '').strip()[:10]


def zuordnung_beendet(bis: Optional[str], heute: Optional[date] = None) -> bool:
    """Ob eine Zuordnung abgelaufen ist. Am Ende-Tag selbst gilt sie noch."""
    ende = _iso(bis)
    return bool(ende) and ende < (heute or date.today()).isoformat()


def pruefe_wechselstichtag(von: Optional[str], bis: Optional[str],
                           ab: Optional[str]) -> None:
    """Prüft den Stichtag eines Wechsels: ab diesem Tag gilt die neue Zuordnung,
    die bisherige endet am Vortag.

    Der Stichtag ist **immer ein Monatserster**, und das ist keine Kosmetik: Die
    Beitragsrechnung zählt einen Monat voll, sobald ihn ein Zeitraum an einem
    einzigen Tag berührt (`aktive_monate_menge`) – und zwar für beide Zeilen. Ein
    Schnitt zum 15. legt den Monat damit in die alte *und* in die neue Zeile: bei
    zwei beitragspflichtigen Abteilungen doppelt berechnet, bei aktiv → passiv
    voll berechnet. Beides ohne Fehlermeldung, weil rechnerisch alles aufgeht.

    Wirft ValueError mit erklärendem Text.
    """
    stichtag = _iso(ab)
    if not stichtag:
        raise ValueError("Stichtag (Ab) ist erforderlich.")
    try:
        tag = date.fromisoformat(stichtag)
    except ValueError:
        raise ValueError(f"Stichtag ({stichtag}) ist kein gültiges Datum.")
    if tag.day != 1:
        raise ValueError(
            f"Stichtag ({stichtag}) muss ein Monatserster sein – sonst zählt der "
            "Monat in beiden Zeilen und wird doppelt berechnet."
        )
    beginn = _iso(von)
    if beginn and stichtag <= beginn:
        raise ValueError(
            f"Stichtag ({stichtag}) muss nach dem Beginn der bisherigen Zuordnung "
            f"({beginn}) liegen – davor wäre es eine Korrektur, kein Wechsel."
        )
    ende = _iso(bis)
    if ende and stichtag > ende:
        raise ValueError(
            f"Stichtag ({stichtag}) liegt nach dem Ende der bisherigen "
            f"Zuordnung ({ende})."
        )
