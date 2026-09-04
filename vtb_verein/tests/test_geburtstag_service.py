"""Ausrollen der Geburtstage ins Terminfenster (#192) – die reine Datumslogik.

Geprüft wird, was zwischen den Terminkarten landet: ein Eintrag je Person im
Fenster, das erreichte Alter, der 29.02. in Nicht-Schaltjahren, unbrauchbare
Geburtsdaten aus dem Altbestand und die Kappung auf ein Jahr (ein längeres
Fenster brächte nur Wiederholungen). Ohne DB, ohne API.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import geburtstag_service as gb  # noqa: E402


def _person(geburtsdatum, nachname="Muster", vorname="Max", mid=1):
    return {"mitglied_id": mid, "vorname": vorname, "nachname": nachname,
            "geburtsdatum": geburtsdatum, "mannschaft_name": "Erste"}


def test_ein_eintrag_je_person_im_jahresfenster():
    """Ohne `bis` reicht das Fenster genau ein Jahr – jeder kommt einmal vor."""
    personen = [_person("1990-01-15", mid=1), _person("1990-11-30", mid=2)]
    eintraege = gb.geburtstage_im_fenster(personen, date(2026, 6, 1))
    assert [e['datum'] for e in eintraege] == ["2026-11-30", "2027-01-15"]
    assert {e['mitglied_id'] for e in eintraege} == {1, 2}


def test_alter_ist_das_am_tag_erreichte():
    eintraege = gb.geburtstage_im_fenster([_person("1990-07-20")],
                                          date(2026, 1, 1), date(2026, 12, 31))
    assert eintraege[0]['alter'] == 36


def test_uebrige_felder_bleiben_erhalten():
    eintraege = gb.geburtstage_im_fenster([_person("1990-07-20")],
                                          date(2026, 7, 1), date(2026, 7, 31))
    assert eintraege[0]['mannschaft_name'] == "Erste"
    assert eintraege[0]['nachname'] == "Muster"


def test_29_februar_faellt_auf_den_28():
    """Gefeiert wird im Februar – nicht erst am 1. März."""
    schaltjahr = gb.geburtstage_im_fenster([_person("2000-02-29")],
                                           date(2028, 1, 1), date(2028, 12, 31))
    assert schaltjahr[0]['datum'] == "2028-02-29"
    normaljahr = gb.geburtstage_im_fenster([_person("2000-02-29")],
                                           date(2027, 1, 1), date(2027, 12, 31))
    assert normaljahr[0]['datum'] == "2027-02-28"
    assert normaljahr[0]['alter'] == 27


def test_grenzen_sind_inklusiv():
    personen = [_person("1990-03-01")]
    assert gb.geburtstage_im_fenster(personen, date(2026, 3, 1), date(2026, 3, 1))
    assert not gb.geburtstage_im_fenster(personen, date(2026, 3, 2), date(2026, 4, 1))


def test_jahreswechsel_im_fenster():
    """Ein Fenster über den Silvestertag hinweg findet beide Seiten."""
    personen = [_person("1990-12-28", mid=1), _person("1990-01-03", mid=2)]
    eintraege = gb.geburtstage_im_fenster(personen, date(2026, 12, 20),
                                          date(2027, 1, 10))
    assert [e['datum'] for e in eintraege] == ["2026-12-28", "2027-01-03"]


def test_unbrauchbare_geburtsdaten_fallen_still_raus():
    """geburtsdatum ist TEXT: Altbestand und Importe liefern auch Unsinn."""
    personen = [_person(None, mid=1), _person("", mid=2), _person("keine Ahnung", mid=3),
                _person("2026-02-30", mid=4), _person("1990-05-05", mid=5)]
    eintraege = gb.geburtstage_im_fenster(personen, date(2026, 1, 1), date(2026, 12, 31))
    assert [e['mitglied_id'] for e in eintraege] == [5]


def test_geburtsdatum_in_der_zukunft_zeigt_den_tag_ohne_alter():
    """Tippfehler in den Stammdaten – lieber ohne Alter als mit „wird -2“."""
    eintraege = gb.geburtstage_im_fenster([_person("2028-04-10")],
                                          date(2026, 1, 1), date(2026, 12, 31))
    assert eintraege[0]['datum'] == "2026-04-10"
    assert eintraege[0]['alter'] is None


def test_fenster_wird_auf_ein_jahr_gekappt():
    """Wer drei Jahre anfragt, bekommt trotzdem jeden Geburtstag nur einmal."""
    von = date(2026, 6, 1)
    eintraege = gb.geburtstage_im_fenster([_person("1990-01-15")],
                                          von, von + timedelta(days=3 * 365))
    assert [e['datum'] for e in eintraege] == ["2027-01-15"]


def test_sortierung_chronologisch_dann_nach_namen():
    personen = [_person("1990-05-05", nachname="Zander", mid=1),
                _person("1990-05-05", nachname="Albers", mid=2),
                _person("1990-04-04", nachname="Meier", mid=3)]
    eintraege = gb.geburtstage_im_fenster(personen, date(2026, 1, 1), date(2026, 12, 31))
    assert [e['nachname'] for e in eintraege] == ["Meier", "Albers", "Zander"]


def test_leere_eingabe():
    assert gb.geburtstage_im_fenster([], date(2026, 1, 1)) == []
