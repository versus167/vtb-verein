"""Termin-Erinnerungs-Einstellungen (Schema v112, #95-Nachgang) – Fresh == Migriert.

Der Frischaufbau wird von den übrigen Integrationstests mitgeprüft (VereinsDB legt
das Schema beim Connect an). Hier geht es um den *Upgrade*-Pfad: Eine v111-Datenbank
wird nachgestellt – Tabelle, History, Audit-Funktionen und Trigger weg – und dann
migriert. Danach muss dieselbe Zeile mit denselben Vorgaben dastehen und die
History wieder mitschreiben; ein Frischaufbau, der die Migration überholt,
fiele genau hier auf.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB), Beispiel siehe
test_termin_erinnerung_integration.py.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

from app.models.termin import TerminErinnerungEinstellungen  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-termin-erinnerung-migration-uploads")
    yield d
    d.close()


@pytest.fixture()
def auf_v111(db):
    """Den Stand vor v112 nachstellen: die Tabelle gibt es dort noch gar nicht."""
    with db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS termin_erinnerung_einstellungen_history")
        cur.execute("DROP TABLE IF EXISTS termin_erinnerung_einstellungen CASCADE")
        cur.execute("DROP FUNCTION IF EXISTS fn_termin_erinnerung_einst_audit_insert() "
                    "CASCADE")
        cur.execute("DROP FUNCTION IF EXISTS fn_termin_erinnerung_einst_audit_update() "
                    "CASCADE")
    yield
    # Die Modul-DB ist geteilt – für nachfolgende Tests sauber zurücklassen.
    db._database._migrate_v111_to_v112()
    with db.cursor() as cur:
        cur.execute("DELETE FROM termin_erinnerung_einstellungen_history")


def _spalten(db, tabelle) -> set:
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def test_migration_legt_tabelle_mit_vorgabezeile_an(db, auf_v111):
    assert _spalten(db, 'termin_erinnerung_einstellungen') == set()

    db._database._migrate_v111_to_v112()

    e = db.termin_erinnerung_einstellungen.get()
    assert (e.aktiv, e.erste_stufe_tage, e.zweite_stufe_tage) == (True, 3, 1)


def test_migration_setzt_schema_version(db, auf_v111):
    db._database._migrate_v111_to_v112()
    with db.cursor() as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 112


def test_history_traegt_dieselben_spalten(db, auf_v111):
    db._database._migrate_v111_to_v112()
    fachlich = _spalten(db, 'termin_erinnerung_einstellungen') - {'version'}
    assert fachlich <= _spalten(db, 'termin_erinnerung_einstellungen_history')


def test_audit_trigger_schreibt_nach_der_migration(db, auf_v111):
    db._database._migrate_v111_to_v112()
    db.termin_erinnerung_einstellungen.update(
        TerminErinnerungEinstellungen(erste_stufe_tage=4), 'chef')
    with db.cursor() as cur:
        cur.execute("SELECT version, erste_stufe_tage, updated_by FROM "
                    "termin_erinnerung_einstellungen_history ORDER BY version")
        zeilen = [(r['version'], r['erste_stufe_tage'], r['updated_by'])
                  for r in cur.fetchall()]
    # Nur die Änderung: Die Vorgabezeile entsteht im DDL, bevor es den Trigger
    # gibt – im Frischaufbau genauso wie hier.
    assert zeilen == [(2, 4, 'chef')]


def test_migration_ist_wiederholbar(db, auf_v111):
    """Idempotenz: Ein zweiter Durchlauf darf weder krachen noch die Zeile doppeln."""
    db._database._migrate_v111_to_v112()
    db.termin_erinnerung_einstellungen.update(
        TerminErinnerungEinstellungen(erste_stufe_tage=5), 'chef')
    db._database._migrate_v111_to_v112()
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termin_erinnerung_einstellungen")
        assert cur.fetchone()['n'] == 1
    # Der eingestellte Wert überlebt (ON CONFLICT DO NOTHING, kein Reset).
    assert db.termin_erinnerung_einstellungen.get().erste_stufe_tage == 5
