"""Geburtstage im Terminfenster (#192).

Ein Geburtstag ist kein Termin: In der Datenbank steht nur ein Datum am
Mitglied, keine Zeile in ``termine``. Für die Terminliste werden die
Geburtsdaten des Kaders deshalb hier zu Vorkommnissen im angefragten Fenster
ausgerollt — ein Eintrag je Person und Jahr, ohne dass irgendwo etwas
gespeichert wird.

Wer die Geburtstage welcher Mannschaft überhaupt sehen darf, entscheidet der
Router (``backend/api/termine.py``) — bewusst nicht die Termin-ACL, sondern die
eigene Kader-Zugehörigkeit bzw. ``personen.read``.
"""
from datetime import date, timedelta
from typing import Optional

# Fensterlänge, wenn kein `bis` mitkommt — und zugleich die Obergrenze.
# Die Terminliste ist nach hinten offen („alles ab heute"); Geburtstage
# wiederholen sich dagegen jährlich, eine unbegrenzte Ausrollung liefe endlos.
# 364 Tage Vorlauf ergeben ein Fenster von genau einem Jahr: Jeder Kalendertag
# kommt darin einmal vor, also jede Person genau einmal. Ein längeres Fenster
# brächte keine weiteren Geburtstage, nur Wiederholungen — deshalb gekappt.
FENSTER_TAGE = 364


def _im_jahr(geburtsdatum: date, jahr: int) -> date:
    """Der Geburtstag in einem bestimmten Jahr.

    Der 29.02. hat in drei von vier Jahren keinen eigenen Tag; gefeiert wird
    dann am 28.02. — im Februar, nicht erst im März.
    """
    try:
        return geburtsdatum.replace(year=jahr)
    except ValueError:
        return date(jahr, 2, 28)


def _als_datum(wert) -> Optional[date]:
    """`geburtsdatum` liegt als TEXT in der DB und kann aus Altbestand oder
    Importen alles enthalten. Was sich nicht als Datum lesen lässt, fällt still
    heraus — eine kaputte Zeile darf nicht die ganze Liste kosten."""
    if isinstance(wert, date):
        return wert
    try:
        return date.fromisoformat(str(wert)[:10])
    except (TypeError, ValueError):
        return None


def geburtstage_im_fenster(personen: list[dict], von: date,
                           bis: Optional[date] = None) -> list[dict]:
    """Kader-Personen → Geburtstags-Einträge zwischen `von` und `bis` (inklusiv).

    Erwartet je Person mindestens ein `geburtsdatum`; alle übrigen Felder werden
    unverändert übernommen und um `datum` (das Vorkommnis im Fenster) und
    `alter` (das an diesem Tag erreichte Alter) ergänzt. Sortiert chronologisch,
    bei gleichem Tag nach Namen.
    """
    grenze = von + timedelta(days=FENSTER_TAGE)
    bis = grenze if bis is None else min(bis, grenze)
    eintraege = []
    for p in personen:
        geb = _als_datum(p.get('geburtsdatum'))
        if geb is None:
            continue
        for jahr in range(von.year, bis.year + 1):
            tag = _im_jahr(geb, jahr)
            if not von <= tag <= bis:
                continue
            alter = jahr - geb.year
            # Ein Geburtsdatum in der Zukunft ist ein Tippfehler in den
            # Stammdaten. Den Tag trotzdem zeigen, aber ohne „wird -12".
            eintraege.append(p | {'datum': tag.isoformat(),
                                  'alter': alter if alter >= 0 else None})
    eintraege.sort(key=lambda e: (e['datum'], (e.get('nachname') or '').lower(),
                                  (e.get('vorname') or '').lower()))
    return eintraege
