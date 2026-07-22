"""Integrationstests der Mannschaften-Sichtbarkeit für Kader-ÜL/Betreuer (#121).

Prüft die beiden Scope-Repository-Methoden gegen echtes PostgreSQL:
  * ``scope_abteilungen_kader``  – abteilungsweite Lesesicht: wer in einem Team
    einer Abteilung ÜL/Betreuer ist, sieht alle Teams dieser Abteilung.
  * ``kader_verwalten_mannschaften`` – team-genaue Kader-Pflege: nur die Teams,
    in denen der User selbst ÜL/Betreuer ist.
Inkl. Aktiv-am-Stichtag-Semantik (von/bis), Rollen-Abgrenzung (spieler zählt
nicht) und Mehrfach-/Mehr-Abteilungs-Zugehörigkeit.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB; VereinsDB legt das
Schema beim Connect an) – siehe test_termine_integration.py für ein Beispiel.
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

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-mannscope-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE mitglied_mannschaft, mitglied_mannschaft_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied WHERE vorname='MannScope'")
        cur.execute("DELETE FROM users WHERE username LIKE 'mstester%'")
        cur.execute("DELETE FROM abteilung WHERE name IN ('MS-Fussball','MS-Handball')")
    yield


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


def _user_mitglied(db, username, mit_user=True):
    """User (optional) + Mitglied. Gibt (user_id|None, mitglied_id)."""
    with db.cursor() as cur:
        uid = None
        if mit_user:
            cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                        "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                        (username, f"{username}@x.de"))
            uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES ('MannScope','Tester','lastschrift',%s,'t','t') RETURNING id", (uid,))
        return uid, cur.fetchone()['id']


def _kader(db, mitglied_id, mannschaft_id, rolle, von=LASTWEEK, bis=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,bis,created_by,updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,'t','t')", (mitglied_id, mannschaft_id, rolle, von, bis))


def test_uebungsleiter_sieht_ganze_abteilung(db):
    """ÜL in einem Team → alle Teams der Abteilung im Scope, fremde Abteilung nicht."""
    fussball = _abteilung(db, 'MS-Fussball')
    handball = _abteilung(db, 'MS-Handball')
    team_a = _mannschaft(db, fussball, 'Erste')
    _mannschaft(db, fussball, 'Zweite')          # zweites Team derselben Abteilung
    _mannschaft(db, handball, 'HB-Erste')        # fremde Abteilung
    uid, mid = _user_mitglied(db, 'mstester_ul')
    _kader(db, mid, team_a, 'uebungsleiter')

    scope = db.mannschaft_scope_abteilungen(uid)
    assert scope == {fussball}                    # ganze Fußball-Abteilung, nicht Handball


def test_betreuer_wie_uebungsleiter(db):
    fussball = _abteilung(db, 'MS-Fussball')
    team_a = _mannschaft(db, fussball, 'Erste')
    uid, mid = _user_mitglied(db, 'mstester_be')
    _kader(db, mid, team_a, 'betreuer')

    assert db.mannschaft_scope_abteilungen(uid) == {fussball}
    assert db.mannschaft_kader_verwalten_ids(uid) == {team_a}


def test_spieler_bekommt_keinen_scope(db):
    fussball = _abteilung(db, 'MS-Fussball')
    team_a = _mannschaft(db, fussball, 'Erste')
    uid, mid = _user_mitglied(db, 'mstester_sp')
    _kader(db, mid, team_a, 'spieler')

    assert db.mannschaft_scope_abteilungen(uid) == set()
    assert db.mannschaft_kader_verwalten_ids(uid) == set()


def test_nur_aktive_zuordnung_am_stichtag(db):
    """Abgelaufene (bis in der Vergangenheit) und künftige (von in der Zukunft)
    Kader-Zuordnungen zählen nicht."""
    fussball = _abteilung(db, 'MS-Fussball')
    abgelaufen = _mannschaft(db, fussball, 'Alt')
    kuenftig = _mannschaft(db, fussball, 'Neu')
    uid, mid = _user_mitglied(db, 'mstester_zeit')
    _kader(db, mid, abgelaufen, 'uebungsleiter', von=LASTWEEK, bis=YESTERDAY)
    _kader(db, mid, kuenftig, 'uebungsleiter', von=TOMORROW, bis=None)

    assert db.mannschaft_scope_abteilungen(uid) == set()
    assert db.mannschaft_kader_verwalten_ids(uid) == set()


def test_kader_pflege_nur_eigene_teams(db):
    """Abteilungsweite Sicht, aber Kader-Pflege nur im eigenen ÜL/Betreuer-Team:
    ÜL in Team A, nur Spieler in Team B (gleiche Abteilung)."""
    fussball = _abteilung(db, 'MS-Fussball')
    team_a = _mannschaft(db, fussball, 'Erste')
    team_b = _mannschaft(db, fussball, 'Zweite')
    uid, mid = _user_mitglied(db, 'mstester_mix')
    _kader(db, mid, team_a, 'uebungsleiter')
    _kader(db, mid, team_b, 'spieler')

    assert db.mannschaft_scope_abteilungen(uid) == {fussball}   # sieht A und B
    assert db.mannschaft_kader_verwalten_ids(uid) == {team_a}   # pflegt nur A


def test_mehrere_abteilungen(db):
    fussball = _abteilung(db, 'MS-Fussball')
    handball = _abteilung(db, 'MS-Handball')
    team_a = _mannschaft(db, fussball, 'Erste')
    team_c = _mannschaft(db, handball, 'HB-Erste')
    uid, mid = _user_mitglied(db, 'mstester_multi')
    _kader(db, mid, team_a, 'uebungsleiter')
    _kader(db, mid, team_c, 'betreuer')

    assert db.mannschaft_scope_abteilungen(uid) == {fussball, handball}
    assert db.mannschaft_kader_verwalten_ids(uid) == {team_a, team_c}


def test_mitglied_ohne_user_kein_scope(db):
    """Ein Kader-Mitglied ohne verknüpften User taucht in keinem User-Scope auf."""
    fussball = _abteilung(db, 'MS-Fussball')
    team_a = _mannschaft(db, fussball, 'Erste')
    _uid, mid = _user_mitglied(db, 'mstester_none', mit_user=False)
    _kader(db, mid, team_a, 'uebungsleiter')

    # Kein User → nichts zu prüfen außer: ein beliebiger anderer User hat keinen Scope
    uid_other, _mid_other = _user_mitglied(db, 'mstester_other')
    assert db.mannschaft_scope_abteilungen(uid_other) == set()


def test_abteilung_loeschguard_erkennt_aktive_mannschaften(db):
    """Abteilung mit aktivem Team darf nicht löschbar sein (#130-Nachgang):
    has_active_mannschaft_references speist den _can_delete-Guard der API."""
    fussball = _abteilung(db, 'MS-Fussball')
    assert db.has_active_mannschaft_references(fussball) is False  # noch leer

    team = _mannschaft(db, fussball, 'Erste')
    assert db.has_active_mannschaft_references(fussball) is True   # aktives Team blockiert

    # Nach Soft-Delete des Teams ist die Abteilung wieder freigegeben
    with db.cursor() as cur:
        cur.execute("UPDATE mannschaft SET deleted_at=CURRENT_TIMESTAMP, deleted_by='t', "
                    "version=version+1 WHERE id=%s", (team,))
    assert db.has_active_mannschaft_references(fussball) is False
