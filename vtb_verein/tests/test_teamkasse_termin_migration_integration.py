"""Teamkassen-Schema v98–v101 (#167) – Fresh == Migriert.

Der Frischaufbau wird von den übrigen Integrationstests mitgeprüft (VereinsDB legt
das Schema beim Connect an). Hier geht es um den *Upgrade*-Pfad: Eine v97-Datenbank
wird nachgestellt – Spalte, Fremdschlüssel und Index weg, die Audit-Funktionen auf
den alten Spaltenstand zurückgedreht – und dann migriert. Genau dort steckt der
Fallstrick: Die Audit-Funktionen sind f-Strings über _CLUBDECKEL_BUCHUNG_COLS. Wer
nur die Tabelle erweitert und die Funktionen stehen lässt, bekommt eine History,
die den Termin nicht kennt, ohne dass irgendetwas kracht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-termin -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=termin -p 55490:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55490/termin \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_teamkasse_termin_migration_integration.py
"""
import itertools
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Spaltenstand vor v97 – Grundlage der zurückgedrehten Audit-Funktionen.
_V97_COLS = (
    "id, version, deckel_id, mitglied_id, artikel_id, typ, menge, betrag, "
    "paar_ref, beitrag_monat, notiz, artikel_name, gegen_name, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-termin-migration-uploads")
    yield d
    d.close()


@pytest.fixture()
def auf_v97(db):
    """Die Buchungstabelle auf den Stand vor v100 zurückdrehen."""
    _setze_v96(db)
    yield
    # Für nachfolgende Tests wieder auf v97 heben – die Modul-DB ist geteilt.
    db._database._migrate_v97_to_v98()


def _setze_v96(db):
    vals = ", ".join("NEW." + c.strip() for c in _V97_COLS.split(","))
    with db.cursor() as cur:
        cur.execute("ALTER TABLE clubdeckel_buchung "
                    "DROP CONSTRAINT IF EXISTS fk_clubdeckel_buchung_termin")
        cur.execute("DROP INDEX IF EXISTS idx_clubdeckel_buchung_termin_id")
        cur.execute("ALTER TABLE clubdeckel_buchung DROP COLUMN IF EXISTS termin_id")
        cur.execute("ALTER TABLE clubdeckel_buchung_history "
                    "DROP COLUMN IF EXISTS termin_id")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_clubdeckel_buchung_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO clubdeckel_buchung_history ({_V97_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)


# Fortlaufende Mitgliedsnummern: Die Fixture läuft mehrfach je Modul, und
# mitgliedsnummer ist eindeutig – eine feste Nummer kollidierte mit sich selbst.
_NUMMER = itertools.count(97001)


def _spalten(db, tabelle):
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def _hat_constraint(db, name):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
        return cur.fetchone() is not None


def _reste_weg(db):
    """Alles wegräumen, was diese Tests je anlegen — in Kind-vor-Eltern-Reihenfolge."""
    with db.cursor() as cur:
        cur.execute("SELECT c.id FROM clubdeckel c "
                    "JOIN mannschaft m ON m.id = c.mannschaft_id "
                    "WHERE m.name = 'Termin-Migrationstest'")
        deckel_ids = [r['id'] for r in cur.fetchall()]
        for did in deckel_ids:
            cur.execute("SELECT to_regclass('clubdeckel_artikel_preis') IS NOT NULL AS da")
            if cur.fetchone()['da']:
                cur.execute("DELETE FROM clubdeckel_artikel_preis WHERE deckel_id = %s", (did,))
            cur.execute("DELETE FROM clubdeckel_buchung WHERE deckel_id = %s", (did,))
            cur.execute("DELETE FROM clubdeckel_artikel WHERE deckel_id = %s", (did,))
            cur.execute("DELETE FROM clubdeckel_gruppe WHERE deckel_id = %s", (did,))
            cur.execute("DELETE FROM clubdeckel WHERE id = %s", (did,))
        if deckel_ids:
            cur.execute("SELECT to_regclass('clubdeckel_artikel_preis_history') IS NOT NULL AS da")
            if cur.fetchone()['da']:
                cur.execute("DELETE FROM clubdeckel_artikel_preis_history")
            for tbl in ("clubdeckel_buchung_history", "clubdeckel_artikel_history",
                        "clubdeckel_gruppe_history"):
                cur.execute(f"DELETE FROM {tbl}")
            cur.execute("DELETE FROM clubdeckel_history WHERE id = ANY(%s)", (deckel_ids,))
        cur.execute("DELETE FROM termine WHERE created_by = 'migtest'")
        cur.execute("DELETE FROM termine_history WHERE created_by = 'migtest'")
        cur.execute("DELETE FROM mitglied_history WHERE nachname = 'Migrationstest'")
        cur.execute("DELETE FROM mitglied WHERE nachname = 'Migrationstest'")
        cur.execute("DELETE FROM mannschaft_history WHERE name = 'Termin-Migrationstest'")
        cur.execute("DELETE FROM mannschaft WHERE name = 'Termin-Migrationstest'")
        cur.execute("DELETE FROM abteilung_history WHERE name = 'Termin-Mig-Abt'")
        cur.execute("DELETE FROM abteilung WHERE name = 'Termin-Mig-Abt'")


def _tabellen(db):
    with db.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'")
        return {r['table_name'] for r in cur.fetchall()}


def _hat_index(db, name):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,))
        return cur.fetchone() is not None


def test_v97_ausgangslage_kennt_keinen_termin(db, auf_v97):
    """Absicherung des Testaufbaus selbst – sonst prüfte alles Weitere nichts."""
    assert 'termin_id' not in _spalten(db, 'clubdeckel_buchung')
    assert 'termin_id' not in _spalten(db, 'clubdeckel_buchung_history')


def test_migration_ergaenzt_spalte_fk_und_index(db, auf_v97):
    db._database._migrate_v97_to_v98()

    assert 'termin_id' in _spalten(db, 'clubdeckel_buchung')
    assert 'termin_id' in _spalten(db, 'clubdeckel_buchung_history')
    assert _hat_constraint(db, 'fk_clubdeckel_buchung_termin')
    assert _hat_index(db, 'idx_clubdeckel_buchung_termin_id')


def test_migration_zieht_audit_funktionen_nach(db, auf_v97, buchungsdaten):
    """Der eigentliche Prüfstein: Nach der Migration muss die History den Termin
    mitschreiben – die Funktionen kennen die Spalte vorher nicht."""
    db._database._migrate_v97_to_v98()
    deckel_id, mitglied_id, termin_id = buchungsdaten

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO clubdeckel_buchung "
            "(deckel_id, mitglied_id, typ, betrag, termin_id, created_by, updated_by) "
            "VALUES (%s,%s,'kauf',-1.50,%s,'migtest','migtest') RETURNING id",
            (deckel_id, mitglied_id, termin_id),
        )
        buchung_id = cur.fetchone()['id']
        cur.execute("SELECT termin_id FROM clubdeckel_buchung_history "
                    "WHERE id = %s AND version = 1", (buchung_id,))
        assert cur.fetchone()['termin_id'] == termin_id


def test_v98_laeuft_ohne_die_preistabelle_von_v98(db, auf_v97):
    """Regression: Die v98-Migration darf NICHTS an clubdeckel_artikel_preis
    anfassen — auf einer echten v97-Datenbank gibt es die Tabelle noch nicht.
    (Der Fehler blieb verborgen, solange nur gegen ein v99-Schema getestet wurde,
    in dem die Tabelle zufällig schon stand.)"""
    with db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS clubdeckel_artikel_preis")
        cur.execute("DROP TABLE IF EXISTS clubdeckel_artikel_preis_history")

    db._database._migrate_v97_to_v98()          # darf nicht krachen

    assert 'termin_id' in _spalten(db, 'clubdeckel_buchung')
    db._database._migrate_v98_to_v99()          # Schema wieder vollständig


def test_v99_ruestet_deckel_id_nach(db, auf_v98, buchungsdaten):
    """Regression: Eine Datenbank, die eine frühere Fassung von v99 gelaufen ist,
    steht ohne deckel_id da und läuft die Migration nie wieder — die Nachrüstung
    muss die Spalte samt Inhalt ergänzen."""
    deckel_id, _, _ = buchungsdaten
    artikel = db.clubdeckel_artikel.create(
        deckel_id, None, 'Cola', Decimal('1.80'), 1, 0, 'migtest')
    db._database._migrate_v98_to_v99()
    # Zustand „alte Fassung": Spalte weg, Zeile bleibt stehen.
    with db.cursor() as cur:
        cur.execute("ALTER TABLE clubdeckel_artikel_preis "
                    "DROP CONSTRAINT IF EXISTS fk_clubdeckel_artikel_preis_deckel")
        cur.execute("ALTER TABLE clubdeckel_artikel_preis DROP COLUMN deckel_id")
        cur.execute("ALTER TABLE clubdeckel_artikel_preis_history DROP COLUMN deckel_id")
    assert 'deckel_id' not in _spalten(db, 'clubdeckel_artikel_preis')

    db._database._migrate_v98_to_v99()

    assert 'deckel_id' in _spalten(db, 'clubdeckel_artikel_preis')
    assert 'deckel_id' in _spalten(db, 'clubdeckel_artikel_preis_history')
    assert _hat_constraint(db, 'fk_clubdeckel_artikel_preis_deckel')
    with db.cursor() as cur:
        cur.execute("SELECT deckel_id FROM clubdeckel_artikel_preis "
                    "WHERE artikel_id = %s", (artikel.id,))
        assert cur.fetchone()['deckel_id'] == deckel_id      # nachgefüllt, nicht NULL


def test_migration_ist_wiederholbar(db, auf_v97):
    """Zweimal migrieren darf nicht krachen (ADD COLUMN IF NOT EXISTS, DROP/ADD
    CONSTRAINT) – sonst stolpert ein wiederholter Start über sich selbst."""
    db._database._migrate_v97_to_v98()
    db._database._migrate_v97_to_v98()

    assert _hat_constraint(db, 'fk_clubdeckel_buchung_termin')


def test_fk_weist_unbekannten_termin_ab(db, buchungsdaten):
    """Der Fremdschlüssel muss nach der Migration wirklich greifen."""
    from psycopg.errors import ForeignKeyViolation
    deckel_id, mitglied_id, _ = buchungsdaten

    with pytest.raises(ForeignKeyViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_buchung "
                "(deckel_id, mitglied_id, typ, betrag, termin_id, created_by, updated_by) "
                "VALUES (%s,%s,'kauf',-1.50,999999,'migtest','migtest')",
                (deckel_id, mitglied_id),
            )


# --- v98 → v99: Sortiments-Stände hängen an der Gruppe ------------------------

# Spaltenstand der Gruppe vor v100 – Grundlage der zurückgedrehten Audit-Funktionen.
_V99_GRUPPE_COLS = (
    "id, version, deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


@pytest.fixture()
def auf_v98(db):
    """Die Preistabelle auf den Stand vor v100 zurückdrehen (also weg)."""
    with db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS clubdeckel_artikel_preis")
        cur.execute("DROP TABLE IF EXISTS clubdeckel_artikel_preis_history")
    yield
    db._database._migrate_v98_to_v99()
    db._database._migrate_v99_to_v100()


@pytest.fixture()
def auf_v99(db):
    """Die Gruppen-Generationen zurückdrehen und die v99-Preistabelle
    wiederherstellen — der Zustand, den eine v99-Datenbank wirklich hat.

    Die Audit-Funktionen der Gruppe müssen mit zurück: Sie sind f-Strings über
    die Spaltenliste und schrieben sonst in Spalten, die es gerade nicht gibt."""
    vals = ", ".join("NEW." + c.strip() for c in _V99_GRUPPE_COLS.split(","))
    with db.cursor() as cur:
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_clubdeckel_gruppe_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO clubdeckel_gruppe_history ({_V99_GRUPPE_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
        cur.execute("ALTER TABLE clubdeckel_gruppe "
                    "DROP CONSTRAINT IF EXISTS fk_clubdeckel_gruppe_stamm")
        cur.execute("ALTER TABLE clubdeckel_gruppe "
                    "DROP CONSTRAINT IF EXISTS fk_clubdeckel_gruppe_gilt_ab")
        for tbl in ("clubdeckel_gruppe", "clubdeckel_gruppe_history"):
            cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS stamm_id")
            cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS gilt_ab_termin_id")
    db._database._migrate_v98_to_v99()      # legt die Preistabelle wieder an
    yield
    db._database._migrate_v99_to_v100()


def test_v99_ausgangslage_kennt_keine_generationen(db, auf_v99):
    """Absicherung des Testaufbaus — sonst prüfte alles Weitere nichts."""
    assert 'stamm_id' not in _spalten(db, 'clubdeckel_gruppe')
    assert 'clubdeckel_artikel_preis' in _tabellen(db)


def test_v100_ergaenzt_generationen_und_setzt_den_stamm(db, auf_v99, buchungsdaten):
    """Jede vorhandene Gruppe wird ihre eigene erste Generation und gilt von
    Anfang an — rückwirkend gab es keine Stände, die wir kennen."""
    deckel_id, _, _ = buchungsdaten
    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_gruppe "
                    "(deckel_id, name, aktiv, sortierung, created_by, updated_by) "
                    "VALUES (%s,'Getränke',1,0,'migtest','migtest') RETURNING id",
                    (deckel_id,))
        gruppe_id = cur.fetchone()['id']

    db._database._migrate_v99_to_v100()

    assert 'stamm_id' in _spalten(db, 'clubdeckel_gruppe')
    assert 'gilt_ab_termin_id' in _spalten(db, 'clubdeckel_gruppe_history')
    assert _hat_constraint(db, 'fk_clubdeckel_gruppe_stamm')
    assert _hat_constraint(db, 'fk_clubdeckel_gruppe_gilt_ab')
    g = db.clubdeckel_gruppen.get(gruppe_id)
    assert g.stamm_id == gruppe_id and g.gilt_ab_termin_id is None


def test_v100_entfernt_die_preistabelle_aus_v98(db, auf_v99):
    """Die Artikel-Preisstände sind mit dem Gruppen-Modell gegenstandslos."""
    assert 'clubdeckel_artikel_preis' in _tabellen(db)

    db._database._migrate_v99_to_v100()

    assert 'clubdeckel_artikel_preis' not in _tabellen(db)
    assert 'clubdeckel_artikel_preis_history' not in _tabellen(db)


def test_v100_ist_wiederholbar(db, auf_v99):
    db._database._migrate_v99_to_v100()
    db._database._migrate_v99_to_v100()

    assert _hat_constraint(db, 'fk_clubdeckel_gruppe_stamm')


def test_v100_zieht_die_audit_funktion_der_gruppe_nach(db, auf_v99, buchungsdaten):
    """Prüfstein wie bei v97: Die Audit-Funktion ist ein f-String über die
    Spaltenliste und kennt die neuen Felder sonst nicht."""
    deckel_id, _, termin_id = buchungsdaten
    db._database._migrate_v99_to_v100()
    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_gruppe "
                    "(deckel_id, name, aktiv, sortierung, stamm_id, "
                    " gilt_ab_termin_id, created_by, updated_by) "
                    "VALUES (%s,'Essen',1,0,NULL,%s,'migtest','migtest') RETURNING id",
                    (deckel_id, termin_id))
        gid = cur.fetchone()['id']
        cur.execute("SELECT gilt_ab_termin_id FROM clubdeckel_gruppe_history "
                    "WHERE id = %s AND version = 1", (gid,))
        assert cur.fetchone()['gilt_ab_termin_id'] == termin_id


# --- v100 → v101: Artikel, die nur der Wart bucht ------------------------------

# Spaltenstand des Artikels vor v101 – Grundlage der zurückgedrehten Audit-Funktionen.
_V100_ARTIKEL_COLS = (
    "id, version, deckel_id, gruppe_id, name, preis, aktiv, sortierung, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


@pytest.fixture()
def auf_v100(db):
    """Den Artikel auf den Stand vor v101 zurückdrehen: Spalte weg, Audit-
    Funktionen auf die alte Spaltenliste."""
    vals = ", ".join("NEW." + c.strip() for c in _V100_ARTIKEL_COLS.split(","))
    with db.cursor() as cur:
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_clubdeckel_artikel_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO clubdeckel_artikel_history ({_V100_ARTIKEL_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
        for tbl in ("clubdeckel_artikel", "clubdeckel_artikel_history"):
            cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS nur_wart")
    yield
    db._database._migrate_v100_to_v101()


def test_v100_ausgangslage_kennt_keinen_wart_artikel(db, auf_v100):
    """Absicherung des Testaufbaus — sonst prüfte alles Weitere nichts."""
    assert 'nur_wart' not in _spalten(db, 'clubdeckel_artikel')
    assert 'nur_wart' not in _spalten(db, 'clubdeckel_artikel_history')


def test_v101_ergaenzt_die_spalte_und_laesst_bestand_am_tresen(db, auf_v100,
                                                               buchungsdaten):
    """Was bisher im Katalog stand, stand auch am Tresen — Bestand bekommt 0."""
    deckel_id, _, _ = buchungsdaten
    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_artikel "
                    "(deckel_id, name, preis, aktiv, sortierung, created_by, updated_by) "
                    "VALUES (%s,'Bier',1.50,1,0,'migtest','migtest') RETURNING id",
                    (deckel_id,))
        artikel_id = cur.fetchone()['id']

    db._database._migrate_v100_to_v101()

    assert 'nur_wart' in _spalten(db, 'clubdeckel_artikel')
    assert 'nur_wart' in _spalten(db, 'clubdeckel_artikel_history')
    assert db.clubdeckel_artikel.get(artikel_id).nur_wart == 0


def test_v101_zieht_die_audit_funktion_des_artikels_nach(db, auf_v100, buchungsdaten):
    """Prüfstein wie bei v98/v100: Die Audit-Funktion ist ein f-String über die
    Spaltenliste und schriebe sonst eine History ohne das neue Feld."""
    deckel_id, _, _ = buchungsdaten
    db._database._migrate_v100_to_v101()

    artikel = db.clubdeckel_artikel.create(
        deckel_id, None, 'Wäsche', Decimal('3.00'), 1, 0, 'migtest', nur_wart=1)

    with db.cursor() as cur:
        cur.execute("SELECT nur_wart FROM clubdeckel_artikel_history "
                    "WHERE id = %s AND version = 1", (artikel.id,))
        assert cur.fetchone()['nur_wart'] == 1


def test_v101_ist_wiederholbar(db, auf_v100):
    db._database._migrate_v100_to_v101()
    db._database._migrate_v100_to_v101()

    assert 'nur_wart' in _spalten(db, 'clubdeckel_artikel')


@pytest.fixture()
def buchungsdaten(db):
    """Mannschaft + Mitglied + Deckel + Termin, an denen eine Buchung hängen kann.

    Räumt VOR dem Aufbau auf: Bricht ein Test mittendrin ab, überlebt sein
    Mitglied den Lauf, und die eindeutige Mitgliedsnummer kollidierte beim
    nächsten Start gegen dieselbe Wegwerf-Datenbank.
    """
    from app.models.mitglied import Mitglied
    _reste_weg(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES ('Termin-Mig-Abt','migtest','migtest') RETURNING id")
        abteilung_id = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO mannschaft (abteilung_id, name, created_by, updated_by) "
            "VALUES (%s,'Termin-Migrationstest','migtest','migtest') RETURNING id",
            (abteilung_id,))
        mannschaft_id = cur.fetchone()['id']
    mitglied = db.create_mitglied(
        Mitglied(vorname='Termin', nachname='Migrationstest',
                 mitgliedsnummer=next(_NUMMER)),
        created_by='migtest')
    deckel = db.clubdeckel.create(mannschaft_id, 'Teamkasse Test', 'migtest')
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM spielstaette WHERE deleted_at IS NULL ORDER BY id LIMIT 1")
        spielstaette_id = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO termine (mannschaft_id, typ, beginn, spielstaette_id, "
            " status, created_by, updated_by) "
            "VALUES (%s,'training','2026-08-16T19:00',%s,'geplant','migtest','migtest') "
            "RETURNING id", (mannschaft_id, spielstaette_id))
        termin_id = cur.fetchone()['id']

    yield deckel.id, mitglied.id, termin_id

    _reste_weg(db)
