"""Integrationstests der Kader-Kandidatenliste (``list_kandidaten``).

Kernregel: Wer nicht mehr im Verein ist, taucht nicht als Kandidat auf. Eine
Kaderzuordnung gehört zur laufenden Mitgliedschaft — ihr Beginn darf nicht nach
dem Vereinsaustritt liegen (``mitgliedschaft.pruefe_von_in_mitgliedschaft``),
ausgetretene Vorschläge liefen also zwangsläufig in eine Fehlermeldung.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB; VereinsDB legt das
Schema beim Connect an).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

HEUTE = date.today().isoformat()
GESTERN = (date.today() - timedelta(days=1)).isoformat()
MORGEN = (date.today() + timedelta(days=1)).isoformat()
LASTWEEK = (date.today() - timedelta(days=7)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-kandidaten-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE mitglied_mannschaft, mitglied_mannschaft_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        # Kinder vor Eltern, sonst greift der FK auf mitglied_abteilung
        cur.execute("DELETE FROM mitglied_abteilung WHERE mitglied_id IN "
                    "(SELECT id FROM mitglied WHERE vorname='Kand')")
        cur.execute("DELETE FROM mitglied WHERE vorname='Kand'")
        cur.execute("DELETE FROM abteilung WHERE name='Kand-Fussball'")


@pytest.fixture(autouse=True)
def clean(db):
    # Vorher UND nachher: die Mitglieder hier zählen sonst in vereinsweiten
    # Auswertungen anderer Testmodule mit (z. B. Statistik-KPIs).
    _aufraeumen(db)
    yield
    _aufraeumen(db)


def _abteilung(db, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES (%s,'t','t') RETURNING id", (name,))
        return cur.fetchone()['id']


def _mannschaft(db, abteilung_id, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,created_by,updated_by) "
                    "VALUES (%s,%s,'t','t') RETURNING id", (abteilung_id, name))
        return cur.fetchone()['id']


def _mitglied(db, abteilung_id, nachname, austritt=None):
    """Mitglied der Abteilung; `austritt` als Text wie in der Spalte (TEXT!)."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied (vorname,nachname,zahlungsart,austrittsdatum,"
            "created_by,updated_by) VALUES ('Kand',%s,'lastschrift',%s,'t','t') "
            "RETURNING id", (nachname, austritt))
        mid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,von,"
                    "created_by,updated_by) VALUES (%s,%s,%s,'t','t')",
                    (mid, abteilung_id, LASTWEEK))
        return mid


def _namen(db, mannschaft_id):
    return {r['nachname'] for r in db.mannschaften.list_kandidaten(mannschaft_id)}


def test_ausgetretene_sind_keine_kandidaten(db):
    """Austritt in der Vergangenheit → raus; Austritt heute/morgen → noch drin."""
    abt = _abteilung(db, 'Kand-Fussball')
    team = _mannschaft(db, abt, 'Erste')
    _mitglied(db, abt, 'Aktiv')                      # kein Austritt
    _mitglied(db, abt, 'Ausgetreten', austritt=GESTERN)
    _mitglied(db, abt, 'AustrittHeute', austritt=HEUTE)
    _mitglied(db, abt, 'AustrittMorgen', austritt=MORGEN)

    assert _namen(db, team) == {'Aktiv', 'AustrittHeute', 'AustrittMorgen'}


def test_kaputtes_austrittsdatum_schliesst_nicht_aus(db):
    """Unbrauchbare Datumstexte (die Spalte ist TEXT) dürfen niemanden verschlucken:
    safe_to_date liefert NULL, die Zeile bleibt Kandidat."""
    abt = _abteilung(db, 'Kand-Fussball')
    team = _mannschaft(db, abt, 'Erste')
    _mitglied(db, abt, 'Leer', austritt='')
    _mitglied(db, abt, 'Unmoeglich', austritt='2026-02-30')
    _mitglied(db, abt, 'Kraut', austritt='keine Ahnung')

    assert _namen(db, team) == {'Leer', 'Unmoeglich', 'Kraut'}


def test_bereits_im_team_bleibt_draussen(db):
    """Die bestehende Abgrenzung gilt weiter: wer schon im Kader steht, ist kein
    Kandidat mehr — unabhängig vom Austrittsfilter."""
    abt = _abteilung(db, 'Kand-Fussball')
    team = _mannschaft(db, abt, 'Erste')
    drin = _mitglied(db, abt, 'ImKader')
    _mitglied(db, abt, 'Frei')
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,"
                    "von,created_by,updated_by) VALUES (%s,%s,'spieler',%s,'t','t')",
                    (drin, team, LASTWEEK))

    assert _namen(db, team) == {'Frei'}
