"""Kalender-Abos gegen echtes PostgreSQL (#153, Schema v89).

Geprüft wird, was sich nur an einer echten DB zeigt: dass der Klartext-Token
nirgends liegt, dass ein neu erzeugter Link den alten wirklich tötet (partieller
Unique-Index), dass der Abruf-Zähler ohne History-Wildwuchs hochläuft — und dass
die Migration dieselbe Struktur baut wie der Frischaufbau (Fresh == Migriert).

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB, Muster wie
test_zahlungsart_migration_integration).
"""
import hashlib
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
    d = VereinsDB(_URL, upload_path="/tmp/vtb-kalender-uploads")
    yield d
    d.close()


@pytest.fixture
def user_id(db):
    """Frischer User je Test – das Abo hängt am User und ist je User einmalig."""
    import uuid
    name = f"kalendertester_{uuid.uuid4().hex[:8]}"
    with db.cursor() as cur:
        cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                    "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                    (name, f"{name}@example.de"))
        return cur.fetchone()['id']


# ------------------------------------------------------------------- Struktur

def test_tabelle_und_history_existieren(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('kalender_abo') a, to_regclass('kalender_abo_history') h")
        row = cur.fetchone()
    assert row['a'] and row['h']


def test_migration_baut_dieselbe_struktur_wie_der_frischaufbau(db):
    """Fresh == Migriert: Tabelle wegnehmen, Migration laufen lassen, alles wieder da."""
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'kalender_abo' ORDER BY column_name")
        vorher = [r['column_name'] for r in cur.fetchall()]
        cur.execute("DROP TABLE kalender_abo_history, kalender_abo CASCADE")

    db._database._migrate_v88_to_v89()

    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'kalender_abo' ORDER BY column_name")
        nachher = [r['column_name'] for r in cur.fetchall()]
        cur.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'kalender_abo'::regclass "
                    "AND NOT tgisinternal ORDER BY tgname")
        trigger = [r['tgname'] for r in cur.fetchall()]
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'kalender_abo' "
                    "AND indexname = 'uix_kalender_abo_user'")
        unique = cur.fetchone()
    assert nachher == vorher
    assert trigger == ['trig_kalender_abo_audit_insert', 'trig_kalender_abo_audit_update']
    assert unique is not None


def test_migration_ist_idempotent(db):
    """Ein zweiter Lauf über bestehendes Schema darf nicht scheitern."""
    db._database._migrate_v88_to_v89()
    db._database._migrate_v88_to_v89()


def test_kalender_abo_steht_im_prune_registry():
    """Ohne Registry-Eintrag wüchsen widerrufene Abos unbegrenzt (CLAUDE.md)."""
    from app.services.prune_service import PRUNE_REGISTRY
    eintrag = next((e for e in PRUNE_REGISTRY if e.table == "kalender_abo"), None)
    assert eintrag is not None
    assert eintrag.history_table == "kalender_abo_history"


# ------------------------------------------------------------------- Token

def test_nur_der_hash_landet_in_der_datenbank(db, user_id):
    token = db.kalender_abos.create_for_user(user_id, "tester")
    with db.cursor() as cur:
        cur.execute("SELECT token_hash FROM kalender_abo WHERE user_id = %s", (user_id,))
        gespeichert = cur.fetchone()['token_hash']
    assert token not in gespeichert
    assert gespeichert == hashlib.sha256(token.encode()).hexdigest()


def test_token_fuehrt_zum_richtigen_user(db, user_id):
    token = db.kalender_abos.create_for_user(user_id, "tester")
    assert db.kalender_abos.resolve_token(token) == user_id


def test_unbekannter_token_loest_nicht_auf(db, user_id):
    db.kalender_abos.create_for_user(user_id, "tester")
    assert db.kalender_abos.resolve_token("frei-erfunden") is None


def test_abruf_wird_gezaehlt_und_datiert(db, user_id):
    token = db.kalender_abos.create_for_user(user_id, "tester")
    db.kalender_abos.resolve_token(token)
    db.kalender_abos.resolve_token(token)
    abo = db.kalender_abos.get_for_user(user_id)
    assert abo['abrufe'] == 2
    assert abo['letzter_abruf_at'] is not None


def test_abrufe_schreiben_keine_history(db, user_id):
    """Kalender pollen regelmäßig – zählte jeder Abruf die version hoch, wüchse
    die History mit jedem Poll statt mit jeder echten Änderung."""
    token = db.kalender_abos.create_for_user(user_id, "tester")
    for _ in range(5):
        db.kalender_abos.resolve_token(token)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) n FROM kalender_abo_history WHERE user_id = %s", (user_id,))
        assert cur.fetchone()['n'] == 1        # nur der Insert


# ------------------------------------------------------- Neu erzeugen / Widerruf

def test_neuer_link_macht_den_alten_sofort_ungueltig(db, user_id):
    alt = db.kalender_abos.create_for_user(user_id, "tester")
    neu = db.kalender_abos.create_for_user(user_id, "tester")
    assert db.kalender_abos.resolve_token(alt) is None
    assert db.kalender_abos.resolve_token(neu) == user_id


def test_je_user_nur_ein_aktives_abo(db, user_id):
    db.kalender_abos.create_for_user(user_id, "tester")
    db.kalender_abos.create_for_user(user_id, "tester")
    with db.cursor() as cur:
        cur.execute("SELECT count(*) n FROM kalender_abo "
                    "WHERE user_id = %s AND deleted_at IS NULL", (user_id,))
        assert cur.fetchone()['n'] == 1


def test_widerruf_beendet_den_zugriff(db, user_id):
    token = db.kalender_abos.create_for_user(user_id, "tester")
    assert db.kalender_abos.revoke_for_user(user_id, "tester") is True
    assert db.kalender_abos.resolve_token(token) is None
    assert db.kalender_abos.get_for_user(user_id) is None


def test_widerruf_ohne_abo_meldet_false(db, user_id):
    assert db.kalender_abos.revoke_for_user(user_id, "tester") is False


def test_widerruf_wird_soft_geloescht_und_historisiert(db, user_id):
    """Nie hart löschen (CLAUDE.md): Der Widerruf muss nachvollziehbar bleiben."""
    db.kalender_abos.create_for_user(user_id, "tester")
    db.kalender_abos.revoke_for_user(user_id, "widerrufer")
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at, deleted_by, version FROM kalender_abo "
                    "WHERE user_id = %s", (user_id,))
        zeile = cur.fetchone()
        cur.execute("SELECT count(*) n FROM kalender_abo_history WHERE user_id = %s", (user_id,))
        historie = cur.fetchone()['n']
    assert zeile['deleted_at'] is not None
    assert zeile['deleted_by'] == "widerrufer"
    assert zeile['version'] == 2
    assert historie == 2          # Insert + Widerruf
