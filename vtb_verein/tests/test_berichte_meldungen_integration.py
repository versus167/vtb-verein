"""
Meldungen im Bereich „Berichte" (#155): LSB-Bestandsmeldung zum Stichtag.

Die Wegwerf-DB teilen sich alle Integrationstests. Darum zählen die Tests nicht
vereinsweite Summen, sondern eigene Jahrgänge (1901/1902) und eigene Abteilungen.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an):
    docker run -d --name vtb-pg-155 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=t155 -p 55455:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55455/t155 \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_berichte_meldungen_integration.py
"""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Wurzel

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_MARKE = 'meldungtest'
STICHTAG = date(2026, 12, 31)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-meldung-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    def weg():
        with db.cursor() as cur:
            for tabelle in ("mitglied_mannschaft", "mannschaft", "mitglied_funktion",
                            "mitglied_abteilung", "mitglied_history", "mitglied",
                            "abteilung"):
                cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (_MARKE,))
    weg()
    yield
    weg()


def _mitglied(db, nachname, *, geburt='1901-05-01', geschlecht='w', eintritt='2000-01-01',
              austritt=None, art='mitglied'):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied (vorname, nachname, zahlungsart, status, art, geburtsdatum, "
            "geschlecht, eintrittsdatum, austrittsdatum, created_by, updated_by) "
            "VALUES ('Mt', %s, 'ueberweisung', 'aktiv', %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (nachname, art, geburt, geschlecht, eintritt, austritt, _MARKE, _MARKE))
        return cur.fetchone()['id']


def _abteilung(db, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", (name, _MARKE, _MARKE))
        return cur.fetchone()['id']


def _zuordnung(db, mid, aid, von=None, bis=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, von, bis, "
                    "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s)",
                    (mid, aid, von, bis, _MARKE, _MARKE))


def _funktion(db, mid, funktion, abteilung_id=None, von='2000-01-01', bis=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_funktion (mitglied_id, abteilung_id, funktion, von, bis, "
                    "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (mid, abteilung_id, funktion, von, bis, _MARKE, _MARKE))


def _jahrgang(tabelle, jahr):
    return next((z for z in tabelle["zeilen"] if z["jahrgang"] == jahr), None)


def _abt(meldung, aid):
    return next(x for x in meldung["b"] if x["abteilung_id"] == aid)


# --- A-Meldung ----------------------------------------------------------------

def test_a_zaehlt_jede_person_einmal_nach_jahrgang_und_geschlecht(db):
    fb, tt = _abteilung(db, 'MT-Fußball'), _abteilung(db, 'MT-Tischtennis')
    doppelt = _mitglied(db, 'Doppelt', geschlecht='m')
    _zuordnung(db, doppelt, fb)
    _zuordnung(db, doppelt, tt)
    _mitglied(db, 'OhneAbteilung', geschlecht='w')
    passiv = _mitglied(db, 'Passiv', geschlecht='d')
    _zuordnung(db, passiv, fb)
    _funktion(db, passiv, 'passiv')
    _mitglied(db, 'Gast', art='gastspieler')

    z = _jahrgang(db.statistik.lsb_meldung(STICHTAG)["a"], 1901)
    assert (z["m"], z["w"], z["d"], z["ohne"], z["summe"]) == (1, 1, 1, 0, 3)


def test_a_stichtag_eintritt_danach_fehlt_austritt_am_stichtag_zaehlt(db):
    _mitglied(db, 'AmStichtagRaus', austritt='2026-12-31')
    _mitglied(db, 'VorherRaus', austritt='2026-12-30')
    _mitglied(db, 'SpaeterRein', eintritt='2027-01-01')
    _mitglied(db, 'AmStichtagRein', eintritt='2026-12-31')

    assert _jahrgang(db.statistik.lsb_meldung(STICHTAG)["a"], 1901)["summe"] == 2


def test_a_ohne_angaben_gehen_nicht_verloren(db):
    _mitglied(db, 'OhneGeschlecht', geburt='1902-01-01', geschlecht=None)
    _mitglied(db, 'Unbekannt', geburt='1902-01-01', geschlecht='x')
    ohne_geb = _mitglied(db, 'OhneGeburt', geburt=None)

    meldung = db.statistik.lsb_meldung(STICHTAG)
    assert _jahrgang(meldung["a"], 1902)["ohne"] == 2
    assert _jahrgang(meldung["a"], None)["summe"] >= 1
    assert meldung["a"]["zeilen"][-1]["jahrgang"] is None  # „ohne Geburtsdatum" zuletzt

    luecken = {z["mitglied_id"]: z for z in db.berichtslisten.fehlende_meldeangaben(STICHTAG)}
    assert luecken[ohne_geb]["ohne_geburtsdatum"] and not luecken[ohne_geb]["ohne_geschlecht"]
    assert {z["nachname"] for z in luecken.values()} >= {'OhneGeschlecht', 'Unbekannt', 'OhneGeburt'}


# --- B-Meldung ----------------------------------------------------------------

def test_b_zaehlt_je_abteilung_nur_aktive_zum_stichtag(db):
    fb, tt = _abteilung(db, 'MT-Fußball'), _abteilung(db, 'MT-Tischtennis')
    doppelt = _mitglied(db, 'Doppelt', geschlecht='m')
    _zuordnung(db, doppelt, fb)
    _zuordnung(db, doppelt, tt)
    # Zwei überlappende Zeilen derselben Abteilung bleiben eine Person.
    _zuordnung(db, doppelt, fb, von='2010-01-01')
    passiv = _mitglied(db, 'Passiv')
    _zuordnung(db, passiv, fb)
    _funktion(db, passiv, 'passiv', abteilung_id=fb)
    beendet = _mitglied(db, 'Beendet')
    _zuordnung(db, beendet, tt, bis='2026-06-30')
    bis_stichtag = _mitglied(db, 'BisStichtag', geschlecht='d')
    _zuordnung(db, bis_stichtag, tt, bis='2026-12-31')
    spaeter = _mitglied(db, 'Spaeter')
    _zuordnung(db, spaeter, tt, von='2027-01-01')

    meldung = db.statistik.lsb_meldung(STICHTAG)
    assert _abt(meldung, fb)["anzahl"] == 1
    tt_zeile = _abt(meldung, tt)
    assert (tt_zeile["anzahl"], _jahrgang(tt_zeile, 1901)["d"]) == (2, 1)


def test_b_passiv_nur_in_der_eigenen_abteilung(db):
    fb, tt = _abteilung(db, 'MT-Fußball'), _abteilung(db, 'MT-Tischtennis')
    mid = _mitglied(db, 'HalbPassiv')
    _zuordnung(db, mid, fb)
    _zuordnung(db, mid, tt)
    _funktion(db, mid, 'passiv', abteilung_id=tt)

    meldung = db.statistik.lsb_meldung(STICHTAG)
    assert (_abt(meldung, fb)["anzahl"], _abt(meldung, tt)["anzahl"]) == (1, 0)


def test_b_ohne_abteilung_ist_kontrollzahl(db):
    vorher = db.statistik.lsb_meldung(STICHTAG)["ohne_abteilung"]
    fb = _abteilung(db, 'MT-Fußball')
    _mitglied(db, 'Niemand')
    nur_passiv = _mitglied(db, 'NurPassiv')
    _zuordnung(db, nur_passiv, fb)
    _funktion(db, nur_passiv, 'passiv')
    drin = _mitglied(db, 'Drin')
    _zuordnung(db, drin, fb)

    meldung = db.statistik.lsb_meldung(STICHTAG)
    assert meldung["ohne_abteilung"] == vorher + 2
    assert _abt(meldung, fb)["anzahl"] == 1
