"""Fachregeln rund um die Vereinsmitgliedschaft (framework-agnostisch).

Eine Zuordnung (Abteilung/Funktion/Mannschaft) gehört immer zur aktiven
Vereinsmitgliedschaft: Ihr Beginn darf weder vor dem Vereinseintritt noch – da
der Vereinsaustritt alles beendet – nach dem Vereinsaustritt liegen.
"""
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
