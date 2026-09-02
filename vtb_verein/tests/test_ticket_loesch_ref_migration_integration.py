"""Batch-Löschung der Tickets, Schema v116 (#190) – Fresh == Migriert.

Den Frischaufbau prüft test_ticket_verbergen_batch_integration mit. Hier geht es um
den *Upgrade*-Pfad, und der hat einen zweiten Teil, den eine reine
Spalten-Migration nicht hätte: **die Reparatur des Bestands**.

Jedes Ticket, das vor v116 verborgen wurde, hat noch aktive Kinder und bleibt
deshalb über Tor 4 dauerhaft im Papierkorb — genau die Tickets, für die #190
geschrieben wurde. Die Migration muss ihnen nachträglich eine `loesch_ref` geben
und die Kinder nachziehen, sonst ändert der Fix für den Bestand nichts.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-t190 -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=t190 -p 55445:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55445/t190 \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_ticket_loesch_ref_migration_integration.py
"""
import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_TABELLEN = ("tickets", "ticket_kommentare", "ticket_anhaenge", "ticket_teilnehmer")


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-t190-migration-uploads")
    yield d
    d.close()


@pytest.fixture()
def auf_v115(db):
    """Das Schema auf den Stand vor v116 zurückdrehen."""
    _leeren(db)
    with db.cursor() as cur:
        for tabelle in _TABELLEN:
            cur.execute(f"ALTER TABLE {tabelle} DROP COLUMN IF EXISTS loesch_ref")
    yield
    # Die Modul-DB ist geteilt – für nachfolgende Tests wieder anheben.
    db._database._migrate_v115_to_v116()
    _leeren(db)


def _leeren(db):
    with db.cursor() as cur:
        cur.execute("TRUNCATE ticket_anhaenge, ticket_teilnehmer, "
                    "ticket_teilnehmer_history, ticket_kommentare, "
                    "ticket_kommentare_history, tickets, tickets_history "
                    "RESTART IDENTITY CASCADE")
        cur.execute("DELETE FROM users WHERE username LIKE 'mig190_%'")


def _spalten(db, tabelle):
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s", (tabelle,))
        return {r["column_name"] for r in cur.fetchall()}


def _altbestand(db, verborgen: bool):
    """Ein Ticket im v115-Zustand: Kinder aktiv, auch wenn das Ticket verborgen ist."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO users (username, email, password_hash, role, created_by, "
                    "updated_by) VALUES ('mig190_a','mig190@x.invalid','h','admin','t','t') "
                    "ON CONFLICT DO NOTHING RETURNING id")
        zeile = cur.fetchone()
        if zeile is None:
            cur.execute("SELECT id FROM users WHERE username='mig190_a'")
            zeile = cur.fetchone()
        uid = zeile["id"]
        cur.execute("INSERT INTO tickets (titel, beschreibung, gemeldet_von, created_by, "
                    "updated_by) VALUES ('Alt','B',%s,'t','t') RETURNING id", (uid,))
        tid = cur.fetchone()["id"]
        cur.execute("INSERT INTO ticket_kommentare (ticket_id, autor_id, inhalt, "
                    "created_by, updated_by) VALUES (%s,%s,'alt','t','t') RETURNING id",
                    (tid, uid))
        kid = cur.fetchone()["id"]
        cur.execute("INSERT INTO ticket_anhaenge (ticket_id, original_name, stored_name, "
                    "mime_type, dateigroesse, hochgeladen_von) "
                    "VALUES (%s,'a.png',%s,'image/png',6,%s) RETURNING id",
                    (tid, f"mig190-{tid}.png", uid))
        aid = cur.fetchone()["id"]
        if verborgen:
            # Genau der alte Weg: nur das Ticket, die Kinder bleiben stehen.
            cur.execute("UPDATE tickets SET deleted_at = CURRENT_TIMESTAMP, "
                        "deleted_by = 'chef', version = version + 1 WHERE id = %s", (tid,))
    return tid, kid, aid


def test_v115_ausgangslage_kennt_die_spalte_nicht(db, auf_v115):
    """Absicherung des Testaufbaus selbst – sonst prüfte alles Weitere nichts."""
    for tabelle in _TABELLEN:
        assert "loesch_ref" not in _spalten(db, tabelle)
    with pytest.raises(psycopg.errors.UndefinedColumn):
        with db.cursor() as cur:
            cur.execute("SELECT loesch_ref FROM tickets")


def test_migration_legt_spalten_und_indexe_an(db, auf_v115):
    db._database._migrate_v115_to_v116()

    for tabelle in _TABELLEN:
        assert "loesch_ref" in _spalten(db, tabelle)
    with db.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE indexname LIKE %s",
                    ("idx_ticket%_loesch_ref",))
        namen = {r["indexname"] for r in cur.fetchall()}
    assert namen == {"idx_ticket_kommentare_loesch_ref",
                     "idx_ticket_anhaenge_loesch_ref",
                     "idx_ticket_teilnehmer_loesch_ref"}


def test_bestand_verborgener_tickets_wird_nachgezogen(db, auf_v115):
    """Der eigentliche Punkt: Ohne diesen Schritt blieben genau die Tickets hängen,
    für die #190 geschrieben wurde."""
    tid, kid, aid = _altbestand(db, verborgen=True)

    db._database._migrate_v115_to_v116()

    with db.cursor() as cur:
        cur.execute("SELECT deleted_at, deleted_by, loesch_ref FROM tickets WHERE id=%s",
                    (tid,))
        ticket = dict(cur.fetchone())
        cur.execute("SELECT deleted_at, deleted_by, loesch_ref FROM ticket_kommentare "
                    "WHERE id=%s", (kid,))
        kommentar = dict(cur.fetchone())
        cur.execute("SELECT deleted_at, deleted_by, loesch_ref FROM ticket_anhaenge "
                    "WHERE id=%s", (aid,))
        anhang = dict(cur.fetchone())

    assert ticket["loesch_ref"], "das verborgene Ticket hat keinen Batch-Marker bekommen"
    for kind in (kommentar, anhang):
        assert kind["deleted_at"] == ticket["deleted_at"], \
            "das Kind muss den Löschzeitpunkt des Tickets erben, nicht den der Migration"
        assert kind["deleted_by"] == "chef"
        assert kind["loesch_ref"] == ticket["loesch_ref"]


def test_aktive_tickets_bleiben_unberuehrt(db, auf_v115):
    """Die Reparatur darf nur greifen, wo das Ticket wirklich verborgen ist."""
    tid, kid, aid = _altbestand(db, verborgen=False)

    db._database._migrate_v115_to_v116()

    with db.cursor() as cur:
        cur.execute("SELECT loesch_ref, deleted_at FROM tickets WHERE id=%s", (tid,))
        assert dict(cur.fetchone()) == {"loesch_ref": None, "deleted_at": None}
        cur.execute("SELECT COUNT(*) AS n FROM ticket_kommentare "
                    "WHERE ticket_id=%s AND deleted_at IS NOT NULL", (tid,))
        assert cur.fetchone()["n"] == 0


def test_nachgezogener_bestand_laesst_sich_wiederherstellen(db, auf_v115):
    """Die Reparatur muss die Restore-Zusage einlösen, nicht nur den Prune entsperren."""
    tid, kid, aid = _altbestand(db, verborgen=True)

    db._database._migrate_v115_to_v116()
    assert db.tickets.restore_ticket(tid, restored_by="chef") is True

    with db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM ticket_kommentare WHERE id=%s", (kid,))
        assert cur.fetchone()["deleted_at"] is None
        cur.execute("SELECT deleted_at FROM ticket_anhaenge WHERE id=%s", (aid,))
        assert cur.fetchone()["deleted_at"] is None


def test_migration_ist_wiederholbar(db, auf_v115):
    """Migrationen müssen auf einem schon weitergedrehten Schema replaybar sein.
    Kritisch hier: Der zweite Lauf darf keine ZWEITE loesch_ref vergeben."""
    tid, *_ = _altbestand(db, verborgen=True)

    db._database._migrate_v115_to_v116()
    with db.cursor() as cur:
        cur.execute("SELECT loesch_ref FROM tickets WHERE id=%s", (tid,))
        erste = cur.fetchone()["loesch_ref"]
    db._database._migrate_v115_to_v116()

    with db.cursor() as cur:
        cur.execute("SELECT loesch_ref FROM tickets WHERE id=%s", (tid,))
        assert cur.fetchone()["loesch_ref"] == erste
