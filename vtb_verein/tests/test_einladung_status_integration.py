"""
Versandstand der Einladung am Konto (Schema v97) – Fresh == Migriert.

Die Zugänge-Übersicht zeigt, ob die letzte Einladung überhaupt rausging. Getragen
wird das von zwei Spalten an `users`, die ohne version-Bump geschrieben werden (wie
last_login) – und genau das lässt sich nur an echtem Postgres prüfen: dass die
Spalten in beiden Schema-Pfaden entstehen, dass der Audit-Trigger dabei keine
History-Zeile schreibt und dass ein entwerteter Magic-Link danach nicht mehr greift.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an):
    docker run -d --name vtb-pg-v97 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=v97test -p 55441:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55441/v97test \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_einladung_status_integration.py
"""
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.mitglied import Mitglied  # noqa: E402
from app.models.permission import Permission  # noqa: E402
from app.services.user_service import UserService  # noqa: E402
from backend.api import personen as personen_api  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_PRAEFIX = 'einladung-'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-einladung-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    """Eigene Zeilen vor UND nach dem Test wegräumen – die Wegwerf-DB teilen sich
    alle Integrationstests, und einige zählen Benutzer."""
    def weg():
        with db.conn.cursor() as cur:
            cur.execute("DELETE FROM auth_tokens WHERE user_id IN "
                        "(SELECT id FROM users WHERE username LIKE %s)", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mitglied_history WHERE nachname LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mitglied WHERE nachname LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM users_history WHERE username LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM users WHERE username LIKE %s", (_PRAEFIX + '%',))
        db.conn.commit()
    weg()
    yield
    weg()


def _anlegen(db, name):
    return UserService(db).create(
        username=_PRAEFIX + name, email=f'{_PRAEFIX}{name}@example.org', role='mitglied',
        active=True, created_by='tester', password='geheim123', send_magic_link=False,
    )


def _mitglied_mit_zugang(db, name):
    u = _anlegen(db, name)
    m = db.create_mitglied(
        Mitglied(vorname='Erika', nachname=_PRAEFIX + name, art='mitglied',
                 eintrittsdatum='2020-01-01', zahlungsart='ueberweisung', user_id=u.id),
        created_by='tester')
    return u, m


class _Freischalter:
    """Handelnder mit vereinsweitem Freischalt-Recht (Scope-Abfrage entfällt damit)."""
    id = 0
    username = 'tester'
    role = 'mitglied'

    def has_permission(self, p):
        return p in (Permission.PERSONEN_FREISCHALTEN, Permission.PERSONEN_PERMISSIONS)

    def has_permission_global(self, p):
        return self.has_permission(p)

    def allowed_abteilungen(self, p):
        return None


def _spalten(db) -> dict:
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users' "
            "AND column_name IN ('einladung_zuletzt', 'einladung_status')"
        )
        return {r['column_name']: r['data_type'] for r in cur.fetchall()}


# --- Frischaufbau -----------------------------------------------------------

def test_frisches_schema_kennt_die_spalten(db):
    assert _spalten(db) == {
        'einladung_zuletzt': 'timestamp with time zone',
        'einladung_status': 'text',
    }


def test_neues_konto_startet_ohne_versandstand(db):
    u = _anlegen(db, 'neu')
    with db.conn.cursor() as cur:
        cur.execute("SELECT einladung_zuletzt, einladung_status FROM users WHERE id = %s",
                    (u.id,))
        row = cur.fetchone()
    assert row['einladung_zuletzt'] is None and row['einladung_status'] is None


@pytest.mark.parametrize("versendet,erwartet", [(True, 'ok'), (False, 'fehler')])
def test_versandstand_wird_festgehalten(db, versendet, erwartet):
    u = _anlegen(db, 'stand')
    assert db.user_repository.setze_einladung_status(u.id, versendet) is True
    with db.conn.cursor() as cur:
        cur.execute("SELECT einladung_zuletzt, einladung_status FROM users WHERE id = %s",
                    (u.id,))
        row = cur.fetchone()
    assert row['einladung_status'] == erwartet
    assert row['einladung_zuletzt'] is not None


def test_versandstand_bumpt_die_version_nicht(db):
    """Betriebszustand, keine fachliche Änderung – die History soll davon nicht
    volllaufen (wie bei last_login)."""
    u = _anlegen(db, 'ohnebump')
    with db.conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM users_history WHERE id = %s", (u.id,))
        vorher = cur.fetchone()['n']
    db.user_repository.setze_einladung_status(u.id, True)
    with db.conn.cursor() as cur:
        cur.execute("SELECT version FROM users WHERE id = %s", (u.id,))
        assert cur.fetchone()['version'] == u.version
        cur.execute("SELECT count(*) AS n FROM users_history WHERE id = %s", (u.id,))
        assert cur.fetchone()['n'] == vorher


def test_geloeschtes_konto_bekommt_keinen_stand(db):
    u = _anlegen(db, 'geloescht')
    with db.conn.cursor() as cur:
        cur.execute("UPDATE users SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", (u.id,))
    db.conn.commit()
    assert db.user_repository.setze_einladung_status(u.id, True) is False


# --- Entwertung offener Magic-Links -----------------------------------------

def test_entwerteter_link_fuehrt_nicht_mehr_ins_konto(db):
    """Der Link an die alte Adresse muss nach dem Adresswechsel tot sein."""
    u = _anlegen(db, 'wechsel')
    token = db.auth_token_repository.create_token(u.id, 'magic_link', expires_days=7)
    assert db.auth_token_repository.entwerte_offene_tokens(u.id, 'magic_link') == 1
    assert db.auth_token_repository.validate_and_use_token(token) is None
    # Entwertet, nicht gelöscht: die Zeile bleibt als Spur stehen.
    with db.conn.cursor() as cur:
        cur.execute("SELECT used_at FROM auth_tokens WHERE user_id = %s", (u.id,))
        assert cur.fetchone()['used_at'] is not None


def test_entwertung_laesst_andere_konten_in_ruhe(db):
    u1 = _anlegen(db, 'eins')
    u2 = _anlegen(db, 'zwei')
    fremd = db.auth_token_repository.create_token(u2.id, 'magic_link', expires_days=7)
    db.auth_token_repository.create_token(u1.id, 'magic_link', expires_days=7)
    db.auth_token_repository.entwerte_offene_tokens(u1.id, 'magic_link')
    assert db.auth_token_repository.validate_and_use_token(fremd)['user_id'] == u2.id


# --- Zugänge-Liste ----------------------------------------------------------

def test_zugaenge_liste_liefert_den_versandstand(db):
    """Die Liste hinter der Zugänge-Oberfläche liest den Stand direkt vom Konto.

    Vorher stand dort ein max() über das Zugriffsprotokoll, das den Handelnden in
    user_id führt und deshalb praktisch nie etwas fand – der Zeitpunkt blieb leer.
    """
    u, m = _mitglied_mit_zugang(db, 'liste')
    db.user_repository.setze_einladung_status(u.id, False)
    zeilen = personen_api.list_freischaltung(_Freischalter(), db)
    zeile = next(z for z in zeilen if z['mitglied_id'] == m.id)
    assert zeile['einladung_status'] == 'fehler'
    assert zeile['einladung_zuletzt'] is not None
    # _ts_iso macht daraus einen String – strikte response_model-Felder gäbe es
    # sonst nicht geschenkt (vgl. Ticket #57).
    assert isinstance(zeile['einladung_zuletzt'], str)


# --- Migration --------------------------------------------------------------

def test_migration_v96_v97_zieht_die_spalten_nach(db):
    """v96-Stand nachbauen (Spalten weg, Version zurück) und migrieren – danach muss
    das Schema aussehen wie frisch aufgebaut."""
    frisch = _spalten(db)
    with db.conn.cursor() as cur:
        cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS einladung_zuletzt")
        cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS einladung_status")
        cur.execute("UPDATE schema_version SET version = 96 WHERE id = 1")
    db.conn.commit()
    assert _spalten(db) == {}

    db._database._migrate_v96_to_v97()

    assert _spalten(db) == frisch
    with db.conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 97
