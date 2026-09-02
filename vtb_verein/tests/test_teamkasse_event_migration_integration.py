"""Teamkassen-Sammlungen, Schema v114 (#181) – Fresh == Migriert.

Der Frischaufbau wird von test_clubdeckel_integration mitgeprüft (VereinsDB legt
das Schema beim Connect an). Hier geht es um den *Upgrade*-Pfad: Eine
v113-Datenbank wird nachgestellt – die beiden Event-Tabellen weg, `event_id`
und der erweiterte typ-CHECK an der Buchung zurückgedreht, die Audit-Funktionen
auf den alten Spaltenstand – und dann migriert.

Der Fallstrick ist derselbe wie bei v98 (#167): Die Audit-Funktionen sind
f-Strings über _CLUBDECKEL_BUCHUNG_COLS. Wer nur die Tabelle erweitert und die
Funktionen stehen lässt, bekommt eine History, die die Sammlung nicht kennt,
ohne dass irgendetwas kracht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-event -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=event -p 55491:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55491/event \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_teamkasse_event_migration_integration.py
"""
import itertools
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Spaltenstand vor v114 – Grundlage der zurückgedrehten Audit-Funktionen.
_V113_COLS = (
    "id, version, deckel_id, mitglied_id, artikel_id, typ, menge, betrag, "
    "paar_ref, beitrag_monat, notiz, artikel_name, gegen_name, termin_id, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)

_NUMMER = itertools.count(114001)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-event-migration-uploads")
    yield d
    d.close()


@pytest.fixture()
def auf_v113(db):
    """Das Schema auf den Stand vor v114 zurückdrehen."""
    _reste_weg(db)
    _setze_v113(db)
    yield
    # Die Modul-DB ist geteilt – für nachfolgende Tests wieder anheben.
    db._database._migrate_v113_to_v114()
    _reste_weg(db)


def _setze_v113(db):
    vals = ", ".join("NEW." + c.strip() for c in _V113_COLS.split(","))
    with db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS clubdeckel_event_opt_out_history")
        cur.execute("DROP TABLE IF EXISTS clubdeckel_event_opt_out")
        cur.execute("ALTER TABLE clubdeckel_buchung "
                    "DROP CONSTRAINT IF EXISTS fk_clubdeckel_buchung_event")
        cur.execute("DROP INDEX IF EXISTS uix_clubdeckel_buchung_event")
        cur.execute("DROP INDEX IF EXISTS idx_clubdeckel_buchung_event_id")
        cur.execute("ALTER TABLE clubdeckel_buchung DROP COLUMN IF EXISTS event_id")
        cur.execute("ALTER TABLE clubdeckel_buchung_history "
                    "DROP COLUMN IF EXISTS event_id")
        cur.execute("DROP TABLE IF EXISTS clubdeckel_event_history")
        cur.execute("DROP TABLE IF EXISTS clubdeckel_event")
        cur.execute("ALTER TABLE clubdeckel_buchung "
                    "DROP CONSTRAINT IF EXISTS clubdeckel_buchung_typ_check")
        cur.execute(
            "ALTER TABLE clubdeckel_buchung ADD CONSTRAINT clubdeckel_buchung_typ_check "
            "CHECK (typ IN ('konsum','verkauf','kauf','einkauf','zahlung','beitrag'))")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_clubdeckel_buchung_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO clubdeckel_buchung_history ({_V113_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)


def _reste_weg(db):
    """Alles wegräumen, was diese Tests anlegen – Kind vor Eltern.

    Die verwaisten *_history-Zeilen müssen mit: Die Wegwerf-DB ist über alle
    Testdateien geteilt, und ein TRUNCATE ... RESTART IDENTITY anderswo lässt
    ids erneut vergeben – eine übrig gebliebene History-Zeile kollidierte dann
    mit dem Primärschlüssel (id, version) der Neuanlage.
    """
    with db.cursor() as cur:
        cur.execute("SELECT c.id FROM clubdeckel c JOIN mannschaft m "
                    "ON m.id = c.mannschaft_id WHERE m.name = 'Event-Migrationstest'")
        for r in cur.fetchall():
            did = r['id']
            cur.execute("DELETE FROM clubdeckel_buchung WHERE deckel_id = %s", (did,))
            for kind in ("clubdeckel_event_opt_out", "clubdeckel_event"):
                cur.execute("SELECT to_regclass(%s) IS NOT NULL AS da", (kind,))
                if cur.fetchone()['da']:
                    cur.execute(f"DELETE FROM {kind} WHERE deckel_id = %s", (did,))
            cur.execute("DELETE FROM clubdeckel WHERE id = %s", (did,))
        cur.execute("DELETE FROM mitglied WHERE nachname = 'Eventmigration'")
        cur.execute("DELETE FROM mannschaft WHERE name = 'Event-Migrationstest'")
        cur.execute("DELETE FROM abteilung WHERE name = 'Event-Mig-Abt'")
        for tabelle, eltern in (("clubdeckel_history", "clubdeckel"),
                                ("clubdeckel_buchung_history", "clubdeckel_buchung"),
                                ("clubdeckel_event_history", "clubdeckel_event"),
                                ("clubdeckel_event_opt_out_history",
                                 "clubdeckel_event_opt_out"),
                                ("mitglied_history", "mitglied"),
                                ("mannschaft_history", "mannschaft"),
                                ("abteilung_history", "abteilung")):
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS da", (tabelle,))
            if not cur.fetchone()['da']:
                continue
            cur.execute(f"DELETE FROM {tabelle} h WHERE NOT EXISTS "
                        f"(SELECT 1 FROM {eltern} e WHERE e.id = h.id)")


@pytest.fixture()
def buchungsdaten(db, auf_v113):
    """Deckel + Kader-Mitglied, angelegt im v113-Zustand."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES ('Event-Mig-Abt','migtest','migtest') RETURNING id")
        aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,'Event-Migrationstest','2026/27','migtest','migtest') "
                    "RETURNING id", (aid,))
        man = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,mitgliedsnummer,zahlungsart,"
                    "created_by,updated_by) VALUES ('Anna','Eventmigration',%s,'sonstiges',"
                    "'migtest','migtest') RETURNING id", (str(next(_NUMMER)),))
        mitglied = cur.fetchone()['id']
        cur.execute("INSERT INTO clubdeckel (mannschaft_id,name,created_by,updated_by) "
                    "VALUES (%s,'Teamkasse','migtest','migtest') RETURNING id", (man,))
        deckel = cur.fetchone()['id']
    return deckel, mitglied


def _spalten(db, tabelle):
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def _tabellen(db):
    with db.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'")
        return {r['table_name'] for r in cur.fetchall()}


def _hat_constraint(db, name):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
        return cur.fetchone() is not None


def _hat_index(db, name):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,))
        return cur.fetchone() is not None


def test_v113_ausgangslage_kennt_keine_sammlungen(db, auf_v113):
    """Absicherung des Testaufbaus selbst – sonst prüfte alles Weitere nichts."""
    assert 'clubdeckel_event' not in _tabellen(db)
    assert 'clubdeckel_event_opt_out' not in _tabellen(db)
    assert 'event_id' not in _spalten(db, 'clubdeckel_buchung')
    assert 'event_id' not in _spalten(db, 'clubdeckel_buchung_history')


def test_migration_legt_tabellen_spalte_fk_und_indexe_an(db, auf_v113):
    db._database._migrate_v113_to_v114()

    for tabelle in ('clubdeckel_event', 'clubdeckel_event_history',
                    'clubdeckel_event_opt_out', 'clubdeckel_event_opt_out_history'):
        assert tabelle in _tabellen(db)
    assert 'event_id' in _spalten(db, 'clubdeckel_buchung')
    assert 'event_id' in _spalten(db, 'clubdeckel_buchung_history')
    assert 'loesch_ref' in _spalten(db, 'clubdeckel_event')
    assert 'loesch_ref' in _spalten(db, 'clubdeckel_event_opt_out')
    assert _hat_constraint(db, 'fk_clubdeckel_buchung_event')
    assert _hat_index(db, 'idx_clubdeckel_buchung_event_id')
    assert _hat_index(db, 'uix_clubdeckel_buchung_event')
    assert _hat_index(db, 'uix_clubdeckel_event_opt_out_active')


def test_migration_erweitert_den_typ_check(db, buchungsdaten):
    """Vorher lehnt der CHECK 'event' ab, nachher nimmt er ihn – und nur ihn."""
    deckel, mitglied = buchungsdaten
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,"
                        "betrag,created_by,updated_by) "
                        "VALUES (%s,%s,'event',-5.00,'migtest','migtest')",
                        (deckel, mitglied))

    db._database._migrate_v113_to_v114()

    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,"
                    "betrag,created_by,updated_by) "
                    "VALUES (%s,%s,'event',-5.00,'migtest','migtest')",
                    (deckel, mitglied))
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,"
                        "betrag,created_by,updated_by) "
                        "VALUES (%s,%s,'unfug',-5.00,'migtest','migtest')",
                        (deckel, mitglied))


def test_migration_zieht_audit_funktionen_nach(db, buchungsdaten):
    """Der eigentliche Prüfstein: Nach der Migration muss die History die
    Sammlung mitschreiben – die Funktionen kennen die Spalte vorher nicht."""
    deckel, mitglied = buchungsdaten
    db._database._migrate_v113_to_v114()

    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_event (deckel_id,name,betrag,"
                    "created_by,updated_by) "
                    "VALUES (%s,'Geschenk',5.00,'migtest','migtest') RETURNING id",
                    (deckel,))
        event_id = cur.fetchone()['id']
        cur.execute("INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,betrag,"
                    "event_id,created_by,updated_by) "
                    "VALUES (%s,%s,'event',-5.00,%s,'migtest','migtest') RETURNING id",
                    (deckel, mitglied, event_id))
        buchung_id = cur.fetchone()['id']
        cur.execute("SELECT event_id FROM clubdeckel_buchung_history "
                    "WHERE id = %s AND version = 1", (buchung_id,))
        assert cur.fetchone()['event_id'] == event_id


def test_migration_setzt_audit_trigger_der_neuen_tabellen(db, buchungsdaten):
    """Die Event-Tabellen brauchen ihre eigenen History-Trigger – ohne sie
    entstünde eine Tabelle ohne Nachweis, was niemandem auffiele."""
    deckel, mitglied = buchungsdaten
    db._database._migrate_v113_to_v114()

    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_event (deckel_id,name,betrag,"
                    "created_by,updated_by) "
                    "VALUES (%s,'Geschenk',5.00,'migtest','migtest') RETURNING id",
                    (deckel,))
        event_id = cur.fetchone()['id']
        cur.execute("UPDATE clubdeckel_event SET name='Geschenk XL', betrag=7.00, "
                    "version=version+1 WHERE id=%s", (event_id,))
        cur.execute("SELECT version,name,betrag FROM clubdeckel_event_history "
                    "WHERE id=%s ORDER BY version", (event_id,))
        assert [(r['version'], r['name'], r['betrag']) for r in cur.fetchall()] == [
            (1, 'Geschenk', Decimal('5.00')), (2, 'Geschenk XL', Decimal('7.00'))]

        cur.execute("INSERT INTO clubdeckel_event_opt_out (deckel_id,mitglied_id,"
                    "created_by,updated_by) VALUES (%s,%s,'migtest','migtest') "
                    "RETURNING id", (deckel, mitglied))
        opt_out_id = cur.fetchone()['id']
        cur.execute("SELECT COUNT(*) AS n FROM clubdeckel_event_opt_out_history "
                    "WHERE id=%s", (opt_out_id,))
        assert cur.fetchone()['n'] == 1


def test_migration_ist_wiederholbar(db, auf_v113):
    """Migrationen müssen auf einem schon weitergedrehten Schema replaybar sein –
    die Migrationstests drehen schema_version zurück und lassen die ganze Kette
    erneut laufen."""
    db._database._migrate_v113_to_v114()
    db._database._migrate_v113_to_v114()          # darf nicht krachen

    assert 'event_id' in _spalten(db, 'clubdeckel_buchung')
    assert _hat_constraint(db, 'fk_clubdeckel_buchung_event')
