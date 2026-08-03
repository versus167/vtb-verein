"""
Integrationstest des Spielstätten-Schemas (v80) gegen echtes PostgreSQL – Ticket #95.

Prüft beide Schema-Pfade: den Frischaufbau (VereinsDB legt beim Connect an) und die
Migration v79→v80, die auf einem nachgebauten v79-Stand läuft. Der Migrationsteil ist
der eigentliche Grund für diesen Test — dort entscheidet sich, ob der Altbestand einen
Wert bekommt, bevor die Spalte auf NOT NULL gezogen wird.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(z.B. ein ephemerer Postgres-Container):
    docker run -d --name vtb-pg-v80 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=v80test -p 55440:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55440/v80test \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_spielstaette_migration_integration.py
"""
import os
from contextlib import contextmanager

import psycopg
import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# created_by-Stempel aller hier angelegten Zeilen – daran erkennt die clean-Fixture,
# was ihr gehört (die Wegwerf-DB teilen sich alle Integrationstests).
_MARKE = 'spielstaettetest'

# Spaltensatz der Audit-Funktionen VOR v80 – für den Nachbau des v79-Stands.
_V79_TERMINE_COLS = (
    "id, version, mannschaft_id, serie_id, typ, beginn, ende, ort, treffpunkt, "
    "treffpunkt_zeit, gegner, heim_auswaerts, extern_ref, status, beschreibung, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_V79_SERIE_COLS = (
    "id, version, mannschaft_id, typ, beginn_zeit, ende_zeit, ort, treffpunkt, "
    "treffpunkt_zeit, beschreibung, start_datum, ende_datum, materialisiert_bis, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-spielstaette-uploads")
    yield d
    d.close()


@contextmanager
def _cur(db):
    """Cursor mit Commit/Rollback wie in BaseRepository.

    Nötig, weil dieser Test rohes SQL fährt: Ohne das Rollback nach einer
    erwarteten Verletzung (Unique/Check) bliebe die Transaktion abgebrochen und
    jeder Folgetest liefe auf „current transaction is aborted".
    """
    cur = db.conn.cursor()
    try:
        yield cur
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    finally:
        cur.close()


@pytest.fixture(autouse=True)
def clean(db):
    """Nur die eigenen Zeilen wegräumen (Muster der übrigen Integrationstests)."""
    yield
    with _cur(db) as cur:
        cur.execute("DELETE FROM termine_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM termine WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mitglied_mannschaft WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mannschaft_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mannschaft WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM abteilung WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM spielstaette_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM spielstaette WHERE created_by = %s", (_MARKE,))


def _platzhalter_id(cur, schluessel):
    cur.execute("SELECT id FROM spielstaette WHERE platzhalter = %s AND deleted_at IS NULL",
                (schluessel,))
    row = cur.fetchone()
    return row['id'] if row else None


# Andere Testmodule setzen per TRUNCATE ... RESTART IDENTITY die Sequenzen zurück,
# während die *_history-Zeilen stehen bleiben – je nach Testreihenfolge kollidiert
# der Audit-Trigger sonst im History-PK. Gleiches Vorgehen wie test_rechnung_export.
_SEQ_TABELLEN = ("abteilung", "mannschaft", "termine", "spielstaette")


def _resync_sequenzen(cur):
    for tabelle in _SEQ_TABELLEN:
        cur.execute(
            f"""
            SELECT setval(pg_get_serial_sequence('{tabelle}', 'id'), GREATEST(
                (SELECT COALESCE(MAX(id), 0) FROM {tabelle}),
                (SELECT COALESCE(MAX(id), 0) FROM {tabelle}_history),
                1))
            """
        )


def _mannschaft_anlegen(cur):
    _resync_sequenzen(cur)
    cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                "VALUES ('Testabteilung', %s, %s) RETURNING id", (_MARKE, _MARKE))
    abteilung_id = cur.fetchone()['id']
    cur.execute("INSERT INTO mannschaft (abteilung_id, name, created_by, updated_by) "
                "VALUES (%s, 'Testteam', %s, %s) RETURNING id",
                (abteilung_id, _MARKE, _MARKE))
    return cur.fetchone()['id']


# --------------------------------------------------------------- Frischaufbau

def test_tabellen_und_spalten_existieren(db):
    with _cur(db) as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name IN ('spielstaette', 'spielstaette_history')
        """)
        assert {r['table_name'] for r in cur.fetchall()} == {'spielstaette', 'spielstaette_history'}


@pytest.mark.parametrize("tabelle", ['termine', 'termin_serie'])
def test_spielstaette_id_ist_pflicht(db, tabelle):
    with _cur(db) as cur:
        cur.execute("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = %s AND column_name = 'spielstaette_id'
        """, (tabelle,))
        assert cur.fetchone()['is_nullable'] == 'NO'


@pytest.mark.parametrize("tabelle", ['termine_history', 'termin_serie_history'])
def test_history_traegt_die_spielstaette_mit(db, tabelle):
    """History muss die Spalte kennen, sonst scheitert der Audit-Trigger zur Laufzeit."""
    with _cur(db) as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = 'spielstaette_id'
        """, (tabelle,))
        assert cur.fetchone() is not None


def test_beide_platzhalter_sind_da(db):
    with _cur(db) as cur:
        cur.execute("SELECT platzhalter, name, ist_eigen FROM spielstaette "
                    "WHERE platzhalter IS NOT NULL AND deleted_at IS NULL ORDER BY platzhalter")
        rows = cur.fetchall()
    assert [r['platzhalter'] for r in rows] == ['auswaerts', 'unbekannt']
    # Platzhalter sind nie eigenes Gelände – sonst tauchten sie im Belegungsplan auf
    assert all(r['ist_eigen'] is False for r in rows)


def test_platzhalter_kann_nicht_doppelt_angelegt_werden(db):
    with pytest.raises(psycopg.errors.UniqueViolation):
        with _cur(db) as cur:
            cur.execute("INSERT INTO spielstaette (name, platzhalter, created_by, updated_by) "
                        "VALUES ('Zweiter Platzhalter', 'unbekannt', %s, %s)", (_MARKE, _MARKE))


def test_dfbnet_nr_ist_eindeutig(db):
    with _cur(db) as cur:
        cur.execute("INSERT INTO spielstaette (name, dfbnet_nr, created_by, updated_by) "
                    "VALUES ('Platz A', '630012054', %s, %s)", (_MARKE, _MARKE))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with _cur(db) as cur:
            cur.execute("INSERT INTO spielstaette (name, dfbnet_nr, created_by, updated_by) "
                        "VALUES ('Platz B', '630012054', %s, %s)", (_MARKE, _MARKE))


def test_audit_trigger_schreibt_history(db):
    with _cur(db) as cur:
        cur.execute("INSERT INTO spielstaette (name, created_by, updated_by) "
                    "VALUES ('Sportplatz Test', %s, %s) RETURNING id", (_MARKE, _MARKE))
        neu_id = cur.fetchone()['id']
        cur.execute("UPDATE spielstaette SET name = 'Sportplatz Test 2', version = version + 1, "
                    "updated_by = %s WHERE id = %s", (_MARKE, neu_id))
        cur.execute("SELECT version, name FROM spielstaette_history WHERE id = %s ORDER BY version",
                    (neu_id,))
        rows = cur.fetchall()
    assert [(r['version'], r['name']) for r in rows] == [
        (1, 'Sportplatz Test'), (2, 'Sportplatz Test 2')]


def test_zeitstempel_sind_timestamptz(db):
    with _cur(db) as cur:
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'spielstaette'
              AND column_name IN ('created_at', 'updated_at', 'deleted_at')
        """)
        typen = {r['column_name']: r['data_type'] for r in cur.fetchall()}
    assert set(typen.values()) == {'timestamp with time zone'}


def test_kapazitaet_muss_mindestens_eins_sein(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with _cur(db) as cur:
            cur.execute("INSERT INTO spielstaette (name, parallel_moeglich, created_by, updated_by) "
                        "VALUES ('Platz ohne Kapazitaet', 0, %s, %s)", (_MARKE, _MARKE))


def test_spielstaette_steht_im_prune_registry():
    """Ohne Registry-Eintrag wüchsen soft-gelöschte Plätze unbegrenzt (CLAUDE.md)."""
    from app.services.prune_service import PRUNE_REGISTRY
    eintrag = next((e for e in PRUNE_REGISTRY if e.table == 'spielstaette'), None)
    assert eintrag is not None
    assert eintrag.history_table == 'spielstaette_history'
    # Kind-Referenzen halten einen Platz im Papierkorb, solange Termine darauf zeigen
    assert {(c.table, c.fk) for c in eintrag.children} == {
        ('termine', 'spielstaette_id'), ('termin_serie', 'spielstaette_id')}


# ------------------------------------------------------------------ Migration

def test_migration_v79_v80_setzt_altbestand_auf_nicht_erfasst(db):
    """Nachbau eines v79-Stands: Termin ohne Spielstätte, dann migrieren.

    Der Altbestand muss auf 'unbekannt' landen — NICHT auf 'auswaerts'. Ein
    Bestandstraining findet in aller Regel sehr wohl auf dem Platz statt; die
    Behauptung „kein Vereinsgelände" wäre für den Belegungsplan schlimmer als
    ein sichtbares „nicht erfasst".
    """
    with _cur(db) as cur:
        mannschaft_id = _mannschaft_anlegen(cur)

    # --- v79 nachbauen: Spalten und Tabelle weg, alte Audit-Funktionen zurück ---
    with _cur(db) as cur:
        for tabelle in ('termine', 'termine_history', 'termin_serie', 'termin_serie_history'):
            cur.execute(f"ALTER TABLE {tabelle} DROP COLUMN IF EXISTS spielstaette_id")
        cur.execute("DROP TABLE IF EXISTS spielstaette_history")
        cur.execute("DROP TABLE IF EXISTS spielstaette")
        for fn, cols in (('termine', _V79_TERMINE_COLS), ('termin_serie', _V79_SERIE_COLS)):
            vals = ", ".join("NEW." + c.strip() for c in cols.split(","))
            name = 'termine' if fn == 'termine' else 'termin_serie'
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_{name}_audit_insert() RETURNS TRIGGER
                LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO {name}_history ({cols}) VALUES ({vals});
                    RETURN NEW;
                END; $$;
            """)
        cur.execute("UPDATE schema_version SET version = 79 WHERE id = 1")

    # --- Altbestand anlegen, wie er vor v80 entstanden wäre ---
    with _cur(db) as cur:
        cur.execute("""
            INSERT INTO termine (mannschaft_id, typ, beginn, ort, created_by, updated_by)
            VALUES (%s, 'training', '2026-09-01T18:00', 'Irgendwo', %s, %s) RETURNING id
        """, (mannschaft_id, _MARKE, _MARKE))
        alt_termin_id = cur.fetchone()['id']

    # --- migrieren ---
    db._database._migrate_v79_to_v80()

    with _cur(db) as cur:
        cur.execute("SELECT version FROM schema_version")
        assert cur.fetchone()['version'] == 80

        unbekannt_id = _platzhalter_id(cur, 'unbekannt')
        assert unbekannt_id is not None

        cur.execute("SELECT spielstaette_id FROM termine WHERE id = %s", (alt_termin_id,))
        assert cur.fetchone()['spielstaette_id'] == unbekannt_id

        cur.execute("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'termine' AND column_name = 'spielstaette_id'
        """)
        assert cur.fetchone()['is_nullable'] == 'NO'

    # Nach der Migration muss der Audit-Trigger die neue Spalte mitschreiben
    with _cur(db) as cur:
        cur.execute("SELECT id FROM spielstaette WHERE platzhalter = 'auswaerts'")
        auswaerts_id = cur.fetchone()['id']
        cur.execute("""
            INSERT INTO termine (mannschaft_id, typ, beginn, spielstaette_id, created_by, updated_by)
            VALUES (%s, 'training', '2026-09-02T18:00', %s, %s, %s) RETURNING id
        """, (mannschaft_id, auswaerts_id, _MARKE, _MARKE))
        neu_id = cur.fetchone()['id']
        cur.execute("SELECT spielstaette_id FROM termine_history WHERE id = %s", (neu_id,))
        assert cur.fetchone()['spielstaette_id'] == auswaerts_id


def test_termin_ohne_spielstaette_wird_abgelehnt(db):
    """Das Pflichtfeld hängt an der Datenbank, nicht nur an der API."""
    with _cur(db) as cur:
        mannschaft_id = _mannschaft_anlegen(cur)
    with pytest.raises(psycopg.errors.NotNullViolation):
        with _cur(db) as cur:
            cur.execute("""
                INSERT INTO termine (mannschaft_id, typ, beginn, created_by, updated_by)
                VALUES (%s, 'training', '2026-09-03T18:00', %s, %s)
            """, (mannschaft_id, _MARKE, _MARKE))
