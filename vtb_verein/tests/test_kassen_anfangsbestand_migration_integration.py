"""Stichtag am Anfangsbestand, Schema v115 (#189) – Fresh == Migriert.

Den Frischaufbau prüft test_kassen_saldovortrag_integration mit (VereinsDB legt das
Schema beim Connect an). Hier geht es um den *Upgrade*-Pfad: Eine v114-Datenbank wird
nachgestellt – die Spalte `anfangsbestand_ab` weg, die Audit-Funktionen auf dem alten
Spaltenstand – und dann migriert.

Der Fallstrick ist der übliche: Die Audit-Funktionen zählen ihre Spalten einzeln auf.
Wer nur die Tabelle erweitert, bekommt eine kassen_history, die den Stichtag nie
mitschreibt, ohne dass irgendetwas kracht — und damit wäre ausgerechnet der
Saldovortrag nicht mehr nachvollziehbar, dessen einziger Zweck Nachvollziehbarkeit ist.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-eb -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=ebtest -p 55437:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55437/ebtest \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_kassen_anfangsbestand_migration_integration.py
"""
import os

import psycopg
import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Spaltenstand vor v115 – Grundlage der zurückgedrehten Audit-Funktionen.
_V114_COLS = (
    "id, version, name, beschreibung, anfangsbestand_cent, abteilung_id, sachkonto, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-eb-migration-uploads")
    yield d
    d.close()


@pytest.fixture()
def auf_v114(db):
    """Das Schema auf den Stand vor v115 zurückdrehen."""
    _reste_weg(db)
    _setze_v114(db)
    yield
    # Die Modul-DB ist geteilt – für nachfolgende Tests wieder anheben.
    db._database._migrate_v114_to_v115()
    _reste_weg(db)


def _setze_v114(db):
    vals = ", ".join("NEW." + c.strip() for c in _V114_COLS.split(","))
    with db.cursor() as cur:
        cur.execute("ALTER TABLE kassen DROP COLUMN IF EXISTS anfangsbestand_ab")
        cur.execute("ALTER TABLE kassen_history DROP COLUMN IF EXISTS anfangsbestand_ab")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_kassen_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO kassen_history ({_V114_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)


def _reste_weg(db):
    """Alles wegräumen, was diese Tests anlegen – Kind vor Eltern, History zuletzt.

    Die verwaisten kassen_history-Zeilen müssen mit: Die Wegwerf-DB ist über alle
    Testdateien geteilt, und ein TRUNCATE ... RESTART IDENTITY anderswo lässt ids
    erneut vergeben – eine übrig gebliebene History-Zeile kollidierte dann mit dem
    Primärschlüssel (id, version) der Neuanlage.
    """
    with db.cursor() as cur:
        cur.execute("SELECT id FROM kassen WHERE name = 'EB-Migrationstest'")
        for r in cur.fetchall():
            cur.execute("DELETE FROM kassenbuchungen WHERE kasse_id = %s", (r['id'],))
            cur.execute("DELETE FROM kassen WHERE id = %s", (r['id'],))
        cur.execute("DELETE FROM kassen_history h WHERE NOT EXISTS "
                    "(SELECT 1 FROM kassen k WHERE k.id = h.id)")
        cur.execute("DELETE FROM kassenbuchungen_history h WHERE NOT EXISTS "
                    "(SELECT 1 FROM kassenbuchungen b WHERE b.id = h.id)")


def _spalten(db, tabelle):
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def _kasse_anlegen(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO kassen (name, anfangsbestand_cent, created_by, "
                    "updated_by) VALUES ('EB-Migrationstest', 10000, 'migtest', "
                    "'migtest') RETURNING id")
        return cur.fetchone()['id']


def test_v114_ausgangslage_kennt_den_stichtag_nicht(db, auf_v114):
    """Absicherung des Testaufbaus selbst – sonst prüfte alles Weitere nichts."""
    assert 'anfangsbestand_ab' not in _spalten(db, 'kassen')
    assert 'anfangsbestand_ab' not in _spalten(db, 'kassen_history')
    with pytest.raises(psycopg.errors.UndefinedColumn):
        with db.cursor() as cur:
            cur.execute("SELECT anfangsbestand_ab FROM kassen")


def test_migration_legt_die_spalte_an(db, auf_v114):
    db._database._migrate_v114_to_v115()

    assert 'anfangsbestand_ab' in _spalten(db, 'kassen')
    assert 'anfangsbestand_ab' in _spalten(db, 'kassen_history')


def test_bestandskassen_bleiben_ohne_stichtag(db, auf_v114):
    """NULL heißt „gilt seit Bestehen der Kasse" – vor dem ersten Vortrag ist das
    für jede Bestandskasse die richtige Aussage."""
    kasse_id = _kasse_anlegen(db)

    db._database._migrate_v114_to_v115()

    with db.cursor() as cur:
        cur.execute("SELECT anfangsbestand_ab FROM kassen WHERE id = %s", (kasse_id,))
        assert cur.fetchone()['anfangsbestand_ab'] is None


def test_migration_zieht_audit_funktionen_nach(db, auf_v114):
    """Der eigentliche Prüfstein: Nach der Migration muss die History den Stichtag
    mitschreiben – die Funktionen kennen die Spalte vorher nicht."""
    db._database._migrate_v114_to_v115()

    kasse_id = _kasse_anlegen(db)
    with db.cursor() as cur:
        cur.execute("UPDATE kassen SET anfangsbestand_cent = 15000, "
                    "anfangsbestand_ab = '2016-01-01', version = version + 1 "
                    "WHERE id = %s", (kasse_id,))
        cur.execute("SELECT version, anfangsbestand_cent, anfangsbestand_ab "
                    "FROM kassen_history WHERE id = %s ORDER BY version", (kasse_id,))
        zeilen = [dict(r) for r in cur.fetchall()]

    assert [(z['version'], z['anfangsbestand_cent'], z['anfangsbestand_ab'])
            for z in zeilen] == [(1, 10000, None), (2, 15000, '2016-01-01')]


def test_migration_ist_wiederholbar(db, auf_v114):
    """Migrationen müssen auf einem schon weitergedrehten Schema replaybar sein –
    die Migrationstests drehen schema_version zurück und lassen die ganze Kette
    erneut laufen."""
    db._database._migrate_v114_to_v115()
    db._database._migrate_v114_to_v115()          # darf nicht krachen

    assert 'anfangsbestand_ab' in _spalten(db, 'kassen')
