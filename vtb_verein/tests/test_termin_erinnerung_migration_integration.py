"""Termin-Erinnerungs-Einstellungen (Schema v112/v113, #95-Nachgang) – Fresh == Migriert.

Der Frischaufbau wird von den übrigen Integrationstests mitgeprüft (VereinsDB legt
das Schema beim Connect an). Hier geht es um den *Upgrade*-Pfad: Eine v111-Datenbank
wird nachgestellt – Tabelle, History, Audit-Funktionen und Trigger weg – und dann
migriert. Danach muss dieselbe Zeile mit denselben Vorgaben dastehen und die
History wieder mitschreiben; ein Frischaufbau, der die Migration überholt,
fiele genau hier auf.

v122 hängt die Uhrzeit des Laufs an dieselbe Tabelle – und in derselben Migration
auch an die der Ticket-Erinnerungen; deshalb steht der Ticket-Teil hier mit.

v113 hängt die Spieltags-Stufe an dieselbe Tabelle. Dort steckt der zweite
Fallstrick: Die Audit-Funktionen sind f-Strings über die Spaltenliste. Wer nur die
Tabelle erweitert und die Funktionen stehen lässt, bekommt eine History, die die
neue Spalte nie mitschreibt – ohne dass irgendetwas kracht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB), Beispiel siehe
test_termin_erinnerung_integration.py.
"""
import os
import sys
from pathlib import Path

import psycopg
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
    _zuruecksetzen(db)


def _zuruecksetzen(db) -> None:
    """Die Modul-DB ist geteilt – Tabelle wieder auf Vorgabestand bringen.

    Nicht nur die Migration nachziehen: Ein Test, der den Vorlauf verstellt, würde
    seinen Wert sonst allen folgenden Tests (und einem Trockenlauf gegen dieselbe
    DB) unterschieben.
    """
    db._database._migrate_v111_to_v112()
    db._database._migrate_v112_to_v113()
    db._database._migrate_v121_to_v122()
    with db.cursor() as cur:
        cur.execute("DELETE FROM termin_erinnerung_einstellungen_history")
        cur.execute("DELETE FROM termin_erinnerung_einstellungen")
        cur.execute("INSERT INTO termin_erinnerung_einstellungen (id) VALUES (1)")
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


# --------------------------------------------------------------- v112 → v113
# Spaltenstand vor v113 – Grundlage der zurückgedrehten Audit-Funktionen.
_V112_COLS = ("id, version, aktiv, erste_stufe_tage, zweite_stufe_tage, "
              "created_at, created_by, updated_at, updated_by")


@pytest.fixture()
def auf_v112(db):
    """Die Spalte spieltag_aktiv entfernen UND die Audit-Funktionen zurückdrehen."""
    vals = ", ".join("NEW." + c.strip() for c in _V112_COLS.split(","))
    with db.cursor() as cur:
        cur.execute("ALTER TABLE termin_erinnerung_einstellungen "
                    "DROP COLUMN IF EXISTS spieltag_aktiv")
        cur.execute("ALTER TABLE termin_erinnerung_einstellungen_history "
                    "DROP COLUMN IF EXISTS spieltag_aktiv")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_termin_erinnerung_einst_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO termin_erinnerung_einstellungen_history
                            ({_V112_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
    yield
    _zuruecksetzen(db)


def test_v113_ergaenzt_die_spieltags_stufe(db, auf_v112):
    assert 'spieltag_aktiv' not in _spalten(db, 'termin_erinnerung_einstellungen')

    db._database._migrate_v112_to_v113()

    # Vorgabe an: Wer die Stufe nicht will, schaltet sie in der App ab.
    assert db.termin_erinnerung_einstellungen.get().spieltag_aktiv is True
    assert 'spieltag_aktiv' in _spalten(db, 'termin_erinnerung_einstellungen_history')
    with db.cursor() as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 113


def test_v113_zieht_die_audit_funktionen_nach(db, auf_v112):
    """Der eigentliche Fallstrick: History ohne die neue Spalte, ganz ohne Fehler."""
    db._database._migrate_v112_to_v113()
    db.termin_erinnerung_einstellungen.update(
        TerminErinnerungEinstellungen(spieltag_aktiv=False), 'chef')
    with db.cursor() as cur:
        cur.execute("SELECT spieltag_aktiv FROM termin_erinnerung_einstellungen_history "
                    "ORDER BY version DESC LIMIT 1")
        # NULL statt False wäre die stehen gebliebene Funktion – die Spalte gibt es
        # dann zwar, geschrieben hat sie aber niemand.
        assert cur.fetchone()['spieltag_aktiv'] is False


def test_v113_ist_wiederholbar(db, auf_v112):
    db._database._migrate_v112_to_v113()
    db.termin_erinnerung_einstellungen.update(
        TerminErinnerungEinstellungen(spieltag_aktiv=False), 'chef')
    db._database._migrate_v112_to_v113()
    # Kein Reset auf die Vorgabe – ADD COLUMN IF NOT EXISTS lässt die Spalte in Ruhe.
    assert db.termin_erinnerung_einstellungen.get().spieltag_aktiv is False


# --------------------------------------------------------------- v121 → v122
# Die Uhrzeit hängt an BEIDEN Erinnerungs-Einstellungen und kommt aus einer
# einzigen Migration – der Ticket-Teil wird deshalb hier mitgeprüft.
_V121_COLS = ("id, version, aktiv, erste_stufe_tage, zweite_stufe_tage, spieltag_aktiv, "
              "created_at, created_by, updated_at, updated_by")

_BEIDE = ('termin_erinnerung_einstellungen', 'ticket_erinnerung_einstellungen')


@pytest.fixture()
def auf_v121(db):
    """`lauf_stunde` aus beiden Tabellen entfernen UND die Audit-Funktionen der
    Termin-Tabelle zurückdrehen (die Ticket-Seite prüft dieselbe Mechanik)."""
    vals = ", ".join("NEW." + c.strip() for c in _V121_COLS.split(","))
    with db.cursor() as cur:
        for tabelle in _BEIDE:
            cur.execute(f"ALTER TABLE {tabelle} DROP COLUMN IF EXISTS lauf_stunde")
            cur.execute(f"ALTER TABLE {tabelle}_history DROP COLUMN IF EXISTS lauf_stunde")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_termin_erinnerung_einst_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO termin_erinnerung_einstellungen_history
                            ({_V121_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
    yield
    _zuruecksetzen(db)
    with db.cursor() as cur:
        cur.execute("DELETE FROM ticket_erinnerung_einstellungen_history")
        cur.execute("UPDATE ticket_erinnerung_einstellungen SET lauf_stunde = 7, "
                    "version = 1 WHERE id = 1")
        cur.execute("DELETE FROM ticket_erinnerung_einstellungen_history")


def test_v122_ergaenzt_die_uhrzeit_in_beiden_tabellen(db, auf_v121):
    for tabelle in _BEIDE:
        assert 'lauf_stunde' not in _spalten(db, tabelle)

    db._database._migrate_v121_to_v122()

    # Vorgabe 7 Uhr: früh genug vor dem ersten Anpfiff, spät genug für den Schlaf.
    assert db.termin_erinnerung_einstellungen.get().lauf_stunde == 7
    assert db.ticket_erinnerung_einstellungen.get().lauf_stunde == 7
    for tabelle in _BEIDE:
        assert 'lauf_stunde' in _spalten(db, f'{tabelle}_history')
    with db.cursor() as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 122


def test_v122_zieht_die_audit_funktionen_nach(db, auf_v121):
    """Derselbe Fallstrick wie in v113: History ohne die neue Spalte, ganz ohne Fehler."""
    db._database._migrate_v121_to_v122()
    db.termin_erinnerung_einstellungen.update(
        TerminErinnerungEinstellungen(lauf_stunde=5), 'chef')
    with db.cursor() as cur:
        cur.execute("SELECT lauf_stunde FROM termin_erinnerung_einstellungen_history "
                    "ORDER BY version DESC LIMIT 1")
        assert cur.fetchone()['lauf_stunde'] == 5


def test_v122_haelt_unmoegliche_uhrzeiten_draussen(db, auf_v121):
    """Der CHECK gehört zur Spalte und muss aus der Migration genauso kommen wie
    aus dem Frischaufbau – sonst stünde in der einen Instanz 25 Uhr in der Zeile."""
    db._database._migrate_v121_to_v122()
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("UPDATE termin_erinnerung_einstellungen SET lauf_stunde = 24 "
                        "WHERE id = 1")


def test_v122_ist_wiederholbar(db, auf_v121):
    db._database._migrate_v121_to_v122()
    db.termin_erinnerung_einstellungen.update(
        TerminErinnerungEinstellungen(lauf_stunde=5), 'chef')
    db._database._migrate_v121_to_v122()
    # Kein Reset auf die Vorgabe – ADD COLUMN IF NOT EXISTS lässt die Spalte in Ruhe.
    assert db.termin_erinnerung_einstellungen.get().lauf_stunde == 5
