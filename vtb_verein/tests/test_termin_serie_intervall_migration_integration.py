"""14-tägige Terminserien (Schema v121, #95-Nachgang) – Fresh == Migriert.

Den Frischaufbau prüfen die übrigen Serien-Tests mit (VereinsDB legt das Schema
beim Connect an). Hier geht es um den *Upgrade*-Pfad: Eine v120-Datenbank wird
nachgestellt – Spalte `intervall_wochen` weg, Audit-Funktionen auf den alten
Spaltensatz zurückgedreht – und dann migriert.

Zwei Fallstricke, die genau hier auffallen sollen:

1. Der Bestand muss wöchentlich bleiben. Eine Serie ohne Takt gab es vorher
   nicht anders; ein DEFAULT 2 oder ein NULL würde jeden bestehenden
   Trainingsplan still verschieben.
2. Die Audit-Funktionen sind f-Strings über die Spaltenliste. Wer nur die
   Tabelle erweitert und die Funktionen stehen lässt, bekommt eine History,
   die den Takt nie mitschreibt – ohne dass irgendetwas kracht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB), Beispiel siehe
test_termin_serie_integration.py.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

# Spaltenstand vor v121 – Grundlage der zurückgedrehten Audit-Funktionen.
_V120_COLS = (
    "id, version, mannschaft_id, typ, beginn_zeit, ende_zeit, ort, spielstaette_id, "
    "treffpunkt, treffpunkt_zeit, beschreibung, start_datum, ende_datum, "
    "materialisiert_bis, created_at, created_by, updated_at, updated_by, "
    "deleted_at, deleted_by"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-serie-intervall-migration-uploads")
    yield d
    d.close()


@pytest.fixture()
def auf_v120(db):
    """Spalte entfernen UND die Audit-Funktionen auf den v120-Spaltensatz drehen."""
    vals = ", ".join("NEW." + c.strip() for c in _V120_COLS.split(","))
    with db.cursor() as cur:
        cur.execute("TRUNCATE termin_serie, termin_serie_history, "
                    "termine, termine_history, mannschaft, mannschaft_history "
                    "RESTART IDENTITY CASCADE")
        cur.execute("ALTER TABLE termin_serie DROP COLUMN IF EXISTS intervall_wochen")
        cur.execute("ALTER TABLE termin_serie_history "
                    "DROP COLUMN IF EXISTS intervall_wochen")
        for wann in ('insert', 'update'):
            bedingung = ("IF NEW.version != OLD.version THEN" if wann == 'update'
                         else "IF TRUE THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_termin_serie_audit_{wann}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {bedingung}
                        INSERT INTO termin_serie_history ({_V120_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
        cur.execute("UPDATE schema_version SET version = 120 WHERE id = 1")
    yield
    db._database._migrate_v120_to_v121()
    with db.cursor() as cur:
        cur.execute("TRUNCATE termin_serie, termin_serie_history, "
                    "termine, termine_history, mannschaft, mannschaft_history "
                    "RESTART IDENTITY CASCADE")


def _spalten(db, tabelle) -> set:
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def _mannschaft(db) -> int:
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES ('Takt-Abt','t','t') RETURNING id")
        aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,'Erste','2026/27','t','t') RETURNING id", (aid,))
        return cur.fetchone()['id']


def _platz(db) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT id FROM spielstaette WHERE platzhalter = 'auswaerts'")
        return cur.fetchone()['id']


def _bestandsserie(db, mannschaft_id) -> int:
    """Serie im v120-Stand anlegen – ohne die Spalte, also per rohem SQL."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO termin_serie (mannschaft_id,typ,beginn_zeit,start_datum,"
            "materialisiert_bis,spielstaette_id,created_by,updated_by) "
            "VALUES (%s,'training','19:00',%s,%s,%s,'t','t') RETURNING id",
            (mannschaft_id, TOMORROW, YESTERDAY, _platz(db)))
        return cur.fetchone()['id']


def test_migration_ergaenzt_spalte_in_tabelle_und_history(db, auf_v120):
    assert 'intervall_wochen' not in _spalten(db, 'termin_serie')

    db._database._migrate_v120_to_v121()

    assert 'intervall_wochen' in _spalten(db, 'termin_serie')
    assert 'intervall_wochen' in _spalten(db, 'termin_serie_history')


def test_migration_setzt_schema_version(db, auf_v120):
    db._database._migrate_v120_to_v121()
    with db.cursor() as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 121


def test_bestandsserien_bleiben_woechentlich(db, auf_v120):
    """Der Altbestand kannte keinen Takt – er darf nur wöchentlich sein."""
    mid = _mannschaft(db)
    sid = _bestandsserie(db, mid)

    db._database._migrate_v120_to_v121()

    assert db.termin_serien.get(sid).intervall_wochen == 1
    db.termin_serien.materialize_due([mid])
    with db.cursor() as cur:
        cur.execute("SELECT beginn FROM termine WHERE serie_id=%s AND deleted_at IS NULL "
                    "ORDER BY beginn", (sid,))
        tage = [date.fromisoformat(r['beginn'][:10]) for r in cur.fetchall()]
    assert len(tage) >= 2
    assert {(tage[i + 1] - tage[i]).days for i in range(len(tage) - 1)} == {7}


def test_check_greift_nach_der_migration(db, auf_v120):
    db._database._migrate_v120_to_v121()
    mid = _mannschaft(db)
    with db.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO termin_serie (mannschaft_id,typ,beginn_zeit,start_datum,"
                "intervall_wochen,materialisiert_bis,spielstaette_id,created_by,updated_by) "
                "VALUES (%s,'training','19:00',%s,3,%s,%s,'t','t')",
                (mid, TOMORROW, YESTERDAY, _platz(db)))


def test_history_traegt_den_takt_nach_der_migration(db, auf_v120):
    """Der eigentliche Fallstrick: Audit-Funktion mit dem neuen Spaltensatz."""
    db._database._migrate_v120_to_v121()
    mid = _mannschaft(db)
    s = db.termin_serien.create(mid, 'training', "19:00", None, None, None, None, None,
                                TOMORROW, None, 't', spielstaette_id=_platz(db),
                                intervall_wochen=2)
    db.termin_serien.update(s.id, 'training', "20:00", None, None, None, None, None,
                            None, 'chef', s.version, spielstaette_id=_platz(db))
    with db.cursor() as cur:
        cur.execute("SELECT version, intervall_wochen, beginn_zeit FROM "
                    "termin_serie_history WHERE id=%s ORDER BY version", (s.id,))
        zeilen = [(r['version'], r['intervall_wochen'], r['beginn_zeit'])
                  for r in cur.fetchall()]
    assert zeilen == [(1, 2, "19:00"), (2, 2, "20:00")]


def test_migration_ist_wiederholbar(db, auf_v120):
    """Idempotenz: Ein zweiter Durchlauf darf weder krachen noch den Takt zurücksetzen."""
    mid = _mannschaft(db)
    db._database._migrate_v120_to_v121()
    s = db.termin_serien.create(mid, 'training', "19:00", None, None, None, None, None,
                                TOMORROW, None, 't', spielstaette_id=_platz(db),
                                intervall_wochen=2)

    db._database._migrate_v120_to_v121()

    assert db.termin_serien.get(s.id).intervall_wochen == 2
