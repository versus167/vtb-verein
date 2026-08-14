"""Konten ohne Zugang in der Datenbank (Schema v96) – Fresh == Migriert.

Ein Schlüsselträger ohne App-Konto (Platzwart, Hausmeister, Betreuer eines
Gastvereins) wird als Benutzer ohne E-Mail und ohne Passwort geführt, damit ihm
ein Chip zugeordnet werden kann. Das steht und fällt mit zwei Dingen, die nur
echtes Postgres zeigt: `users.email` muss NULL erlauben, und der Unique-Index auf
der Adresse darf mehrere solche Konten nebeneinander zulassen – vorher galt er
für alle nicht gelöschten Zeilen und hätte beim zweiten Hausmeister zugeschlagen.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --name vtb-pg-ohnezugang -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=ohnezugang -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55433/ohnezugang \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_benutzer_ohne_zugang_integration.py
"""
import os
import sys
from pathlib import Path

import pytest
from psycopg.errors import NotNullViolation, UniqueViolation

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.schliessanlage import SchluesselChip  # noqa: E402
from app.services.user_service import UserService  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_PRAEFIX = 'ohnezugang-'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ohnezugang-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    """Eigene Zeilen vor UND nach dem Test wegräumen – andere Integrationstests
    zählen User und stolpern sonst über unsere."""
    def weg():
        with db.conn.cursor() as cur:
            cur.execute("DELETE FROM schluessel_chip_history")
            cur.execute("DELETE FROM schluessel_chip")
            cur.execute("DELETE FROM users_history WHERE username LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM users WHERE username LIKE %s", (_PRAEFIX + '%',))
        db.conn.commit()
    weg()
    yield
    weg()


def _anlegen(db, name, *, email=None, password=None, active=False):
    return UserService(db).create(
        username=_PRAEFIX + name, email=email, role='mitglied', active=active,
        created_by='tester', password=password, send_magic_link=False,
    )


# --- Anlegen ----------------------------------------------------------------

def test_konto_ohne_mail_und_passwort_wird_angelegt(db):
    hausmeister = _anlegen(db, 'hausmeister')

    geladen = db.get_user_by_id(hausmeister.id)
    assert geladen.email is None            # NULL, nicht Leerstring
    assert geladen.password_hash == ''      # kein Passwort, auch kein Platzhalter
    assert geladen.active is False


def test_mehrere_konten_ohne_mail_stehen_nebeneinander(db):
    """Der Prüfstein für den Index: „keine Adresse" ist kein Duplikat."""
    _anlegen(db, 'hausmeister')
    _anlegen(db, 'platzwart')

    ohne_mail = [u for u in UserService(db).list_all()
                 if u.username.startswith(_PRAEFIX) and u.email is None]
    assert len(ohne_mail) == 2


def test_doppelte_echte_mail_bleibt_verboten(db):
    _anlegen(db, 'echt-eins', email='doppelt@example.invalid', active=True)

    with pytest.raises(ValueError, match="bereits vergeben"):
        _anlegen(db, 'echt-zwei', email='doppelt@example.invalid', active=True)


def test_aktives_konto_ohne_anmeldeweg_wird_abgelehnt(db):
    with pytest.raises(ValueError, match="E-Mail oder ein Passwort"):
        _anlegen(db, 'karteileiche', active=True)


def test_leere_mail_wird_als_keine_gespeichert(db):
    """Aus dem Formular kommt '' statt None – sonst kollidierten zwei Leerstrings."""
    erst = _anlegen(db, 'leerstring-eins', email='   ')
    zweit = _anlegen(db, 'leerstring-zwei', email='')

    assert db.get_user_by_id(erst.id).email is None
    assert db.get_user_by_id(zweit.id).email is None


# --- Anmeldung / Suche ------------------------------------------------------

def test_leere_adresse_findet_kein_konto(db):
    """Sonst träfe eine leer abgeschickte Magic-Link-Anfrage ein fremdes Konto."""
    _anlegen(db, 'hausmeister')

    assert db.get_user_by_email('') is None
    assert db.get_user_by_email('   ') is None


def test_magic_link_fuer_konto_ohne_mail_geht_nicht(db):
    _anlegen(db, 'hausmeister')

    assert UserService(db).send_magic_link('') is False


# --- Schlüsselzuordnung (der Anlass) ----------------------------------------

def test_chip_laeuft_auf_ein_konto_ohne_zugang(db):
    platzwart = _anlegen(db, 'platzwart')

    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer='96-4711', bezeichnung='Chip grün',
                       user_id=platzwart.id), 'tester')

    geladen = db.schluessel_chips.get(chip.id)
    assert (geladen.user_id, geladen.mitglied_id) == (platzwart.id, None)
    assert geladen.user_username == _PRAEFIX + 'platzwart'


def test_history_haelt_das_konto_ohne_mail_fest(db):
    """Der Audit-Trigger schreibt users_history – die Spalte muss dort ebenfalls
    NULL erlauben, sonst scheitert jede Änderung an einem solchen Konto."""
    hausmeister = _anlegen(db, 'hausmeister')

    UserService(db).update(user_id=hausmeister.id, username=hausmeister.username,
                           email=None, role='mitglied', active=False,
                           updated_by='tester', expected_version=hausmeister.version)

    with db.conn.cursor() as cur:
        cur.execute("SELECT version, email FROM users_history WHERE id = %s "
                    "ORDER BY version", (hausmeister.id,))
        verlauf = [(r['version'], r['email']) for r in cur.fetchall()]
    assert verlauf == [(1, None), (2, None)]


def test_letzter_anmeldeweg_kann_einem_aktiven_konto_nicht_entzogen_werden(db):
    """E-Mail löschen und aktiv lassen ergäbe ein Konto, an dem niemand mehr
    herankommt – auch der Betroffene nicht."""
    nutzer = _anlegen(db, 'wird-still', email='still@example.invalid', active=True)

    with pytest.raises(ValueError, match="E-Mail oder ein Passwort"):
        UserService(db).update(user_id=nutzer.id, username=nutzer.username,
                               email=None, role='mitglied', active=True,
                               updated_by='tester', expected_version=nutzer.version)


# --- Fresh == Migriert ------------------------------------------------------

class TestMigration:
    """v95 → v96: NOT NULL fällt, der Unique-Index bekommt seine Bedingung."""

    @staticmethod
    def _auf_v95_zuruecksetzen(db):
        with db.conn.cursor() as cur:
            cur.execute("UPDATE users SET email = '' WHERE email IS NULL")
            for tbl in ("users", "users_history"):
                cur.execute(f"ALTER TABLE {tbl} ALTER COLUMN email SET NOT NULL")
            cur.execute("DROP INDEX IF EXISTS uix_users_email_active")
            cur.execute("CREATE UNIQUE INDEX uix_users_email_active "
                        "ON users (email) WHERE deleted_at IS NULL")
            cur.execute("UPDATE schema_version SET version = 95 WHERE id = 1")
        db.conn.commit()

    @staticmethod
    def _index_bedingung(db):
        with db.conn.cursor() as cur:
            cur.execute("SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = 'uix_users_email_active'")
            return cur.fetchone()['indexdef']

    def test_vorzustand_verbietet_das_zweite_konto_ohne_mail(self, db):
        """Zeigt, warum die Migration nötig ist – ohne sie schlägt genau das fehl."""
        self._auf_v95_zuruecksetzen(db)
        try:
            with db.conn.cursor() as cur:
                with pytest.raises(NotNullViolation):
                    cur.execute(
                        "INSERT INTO users (username, email, password_hash, role, "
                        "created_by, updated_by) VALUES (%s, NULL, '', 'mitglied', 't', 't')",
                        (_PRAEFIX + 'alt',))
            db.conn.rollback()
        finally:
            db._database._migrate_v95_to_v96()
            db.conn.commit()

    def test_migration_erlaubt_mehrere_konten_ohne_mail(self, db):
        self._auf_v95_zuruecksetzen(db)
        db._database._migrate_v95_to_v96()
        db.conn.commit()

        _anlegen(db, 'hausmeister')
        _anlegen(db, 'platzwart')       # vor v96 ein Unique-Verstoß

        assert 'email IS NOT NULL' in self._index_bedingung(db)

    def test_migration_haelt_die_echte_mail_weiter_eindeutig(self, db):
        self._auf_v95_zuruecksetzen(db)
        db._database._migrate_v95_to_v96()
        db.conn.commit()

        _anlegen(db, 'echt', email='eindeutig@example.invalid', active=True)
        with pytest.raises(UniqueViolation):
            with db.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, role, "
                    "created_by, updated_by) VALUES (%s, 'eindeutig@example.invalid', "
                    "'', 'mitglied', 't', 't')", (_PRAEFIX + 'doppelt',))
        db.conn.rollback()

    def test_migration_ist_idempotent(self, db):
        self._auf_v95_zuruecksetzen(db)
        db._database._migrate_v95_to_v96()
        db._database._migrate_v95_to_v96()      # darf nicht scheitern
        db.conn.commit()

        assert 'email IS NOT NULL' in self._index_bedingung(db)
