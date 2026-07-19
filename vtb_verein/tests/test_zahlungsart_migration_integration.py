"""Datenmigration v73→v74 gegen echtes PostgreSQL: Einzugsermächtigung aus Bestand.

Wer zum Zeitpunkt der Migration eine IBAN hinterlegt hat, bekommt
zahlungsart='lastschrift' (Einzugs-Haken im Profil-Bank-Panel); ohne IBAN,
soft-gelöscht oder bereits 'lastschrift' bleibt alles unangetastet. Der
version-Bump muss die Umstellung in mitglied_history schreiben.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB, Muster wie
test_mitglied_kontakte_integration); die Migrationsmethode wird direkt auf dem
frischen Schema aufgerufen — sie ist eine reine, idempotente Datenmigration.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-migration-uploads")
    yield d
    d.close()


NACHNAME = 'Migrationstest'


def _mk(db, vorname, nummer, iban, zahlungsart, geloescht=False):
    from app.models.mitglied import Mitglied
    m = db.create_mitglied(
        Mitglied(vorname=vorname, nachname=NACHNAME, mitgliedsnummer=nummer,
                 iban=iban, zahlungsart=zahlungsart),
        created_by="migtest",
    )
    if geloescht:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE mitglied SET deleted_at = CURRENT_TIMESTAMP, deleted_by = 'migtest', "
                "version = version + 1 WHERE id = %s", (m.id,))
    return m.id


@pytest.fixture()
def bestand(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM mitglied_history WHERE nachname = %s", (NACHNAME,))
        cur.execute("DELETE FROM mitglied WHERE nachname = %s", (NACHNAME,))
    ids = {
        'mit_iban': _mk(db, 'Anna', 91001, 'DE02120300000000202051', 'sonstiges'),
        'ohne_iban': _mk(db, 'Bernd', 91002, None, 'sonstiges'),
        'leere_iban': _mk(db, 'Clara', 91003, '  ', 'sonstiges'),
        'schon_lastschrift': _mk(db, 'Doro', 91004, 'DE02120300000000202051', 'lastschrift'),
        'geloescht': _mk(db, 'Emil', 91005, 'DE02120300000000202051', 'sonstiges', geloescht=True),
    }
    yield ids
    with db.cursor() as cur:
        cur.execute("DELETE FROM mitglied_history WHERE nachname = %s", (NACHNAME,))
        cur.execute("DELETE FROM mitglied WHERE nachname = %s", (NACHNAME,))


def _zeile(db, mid):
    with db.cursor() as cur:
        cur.execute("SELECT zahlungsart, version, updated_by FROM mitglied WHERE id = %s", (mid,))
        return dict(cur.fetchone())


def test_iban_bestand_bekommt_lastschrift(db, bestand):
    db._database._migrate_v73_to_v74()

    assert _zeile(db, bestand['mit_iban'])['zahlungsart'] == 'lastschrift'
    assert _zeile(db, bestand['mit_iban'])['updated_by'] == 'migration_v74'
    # ohne/leere IBAN, soft-gelöscht: unangetastet
    assert _zeile(db, bestand['ohne_iban'])['zahlungsart'] == 'sonstiges'
    assert _zeile(db, bestand['leere_iban'])['zahlungsart'] == 'sonstiges'
    assert _zeile(db, bestand['geloescht'])['zahlungsart'] == 'sonstiges'
    # bereits Lastschrift: kein unnötiger version-Bump (History-Leerrauschen vermeiden)
    assert _zeile(db, bestand['schon_lastschrift'])['version'] == 1

    # Umstellung landet über den Audit-Trigger in der History
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM mitglied_history WHERE id = %s AND version = 2 "
            "AND zahlungsart = 'lastschrift'", (bestand['mit_iban'],))
        assert cur.fetchone()['n'] == 1


def test_migration_ist_idempotent(db, bestand):
    db._database._migrate_v73_to_v74()
    v1 = _zeile(db, bestand['mit_iban'])['version']
    db._database._migrate_v73_to_v74()
    assert _zeile(db, bestand['mit_iban'])['version'] == v1

    # schema_version wieder auf den echten Stand heben (die Methode setzt 74;
    # das Schema IST v74 – nur zur Sicherheit für nachfolgende Tests herstellen)
    with db.cursor() as cur:
        from app.db.database import SCHEMA_VERSION
        cur.execute("UPDATE schema_version SET version = %s WHERE id = 1", (SCHEMA_VERSION,))
