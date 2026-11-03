"""Rechteübersicht gegen echtes PostgreSQL: Gesamt- == Einzelberechnung.

``get_effective_permissions_all`` holt die Rechte aller User mit zwei Queries
statt 2×N. Das lohnt nur, solange das Ergebnis für jeden User exakt dem von
``get_effective_permissions`` entspricht – die Berechtigungsseite des Users und
die Übersicht dürfen nie auseinanderlaufen. Abgedeckt: Funktion vereinsweit und
abteilungsgebunden, abgelaufene Funktion, Grant, Deny, User ganz ohne Rechte
(nur Sockel) und Mitglied ohne Konto (taucht nicht auf).

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB; VereinsDB legt das
Schema beim Connect an).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root

from app.models.permission import Permission  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
_FUNKTION = 'ruebersicht_test'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ruebersicht-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    def weg():
        with db.cursor() as cur:
            cur.execute("DELETE FROM user_permissions WHERE user_id IN "
                        "(SELECT id FROM users WHERE username LIKE 'rutester%')")
            cur.execute("DELETE FROM mitglied_funktion WHERE funktion = %s", (_FUNKTION,))
            cur.execute("DELETE FROM funktion_permission WHERE funktion_id IN "
                        "(SELECT id FROM funktion WHERE key = %s)", (_FUNKTION,))
            cur.execute("DELETE FROM funktion WHERE key = %s", (_FUNKTION,))
            cur.execute("DELETE FROM mitglied WHERE vorname = 'RUebersicht'")
            cur.execute("DELETE FROM users WHERE username LIKE 'rutester%'")
            cur.execute("DELETE FROM abteilung WHERE name = 'RU-Fussball'")
    weg()
    yield
    weg()


def _user_mitglied(db, username, mit_user=True):
    with db.cursor() as cur:
        uid = None
        if mit_user:
            cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                        "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                        (username, f"{username}@x.de"))
            uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES ('RUebersicht',%s,'lastschrift',%s,'t','t') RETURNING id",
                    (username, uid))
        return uid, cur.fetchone()['id']


def test_gesamt_gleich_einzel(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES ('RU-Fussball','t','t') RETURNING id")
        fussball = cur.fetchone()['id']
        cur.execute("INSERT INTO funktion (key,name,created_by) VALUES (%s,'RU-Test','t') "
                    "RETURNING id", (_FUNKTION,))
        funktion_id = cur.fetchone()['id']
    db.funktion_permissions.set_permissions_for_funktion(
        funktion_id, {Permission.BEITRAEGE_READ, Permission.MANNSCHAFTEN_WRITE}, actor='t')

    global_uid, global_mid = _user_mitglied(db, 'rutester_global')
    scoped_uid, scoped_mid = _user_mitglied(db, 'rutester_scoped')
    alt_uid, alt_mid = _user_mitglied(db, 'rutester_abgelaufen')
    leer_uid, _ = _user_mitglied(db, 'rutester_leer')
    _user_mitglied(db, 'rutester_ohnekonto', mit_user=False)

    db.create_mitglied_funktion(global_mid, None, _FUNKTION, LASTWEEK, None, 't')
    db.create_mitglied_funktion(scoped_mid, fussball, _FUNKTION, LASTWEEK, None, 't')
    db.create_mitglied_funktion(alt_mid, None, _FUNKTION, LASTWEEK, YESTERDAY, 't')
    db.permissions.set_overrides_for_user(
        global_uid, {Permission.KASSEN_VERWALTEN}, {Permission.MANNSCHAFTEN_WRITE}, actor='t')

    alle = db.permissions.get_effective_permissions_all()

    for uid in (global_uid, scoped_uid, alt_uid, leer_uid):
        einzel = db.permissions.get_effective_permissions(uid)
        assert alle[uid].global_perms == einzel.global_perms
        assert alle[uid].scoped == einzel.scoped
        assert alle[uid].sources == einzel.sources

    # Stichproben, damit „gleich" nicht „gleich leer" heißt
    assert {Permission.BEITRAEGE_READ, Permission.KASSEN_VERWALTEN} <= alle[global_uid].global_perms
    assert Permission.MANNSCHAFTEN_WRITE not in alle[global_uid].keys()
    assert alle[scoped_uid].scoped[Permission.BEITRAEGE_READ] == {fussball}
    assert Permission.BEITRAEGE_READ not in alle[alt_uid].keys()
    assert alle[leer_uid].keys() == {Permission.TICKETS_ACCESS}
