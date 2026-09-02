"""Verbergen und Wiederherstellen eines Tickets als Batch (#190, Schema v116).

Das Verbergen ließ Kommentare, Anhänge und Teilnehmer bisher aktiv — bewusst,
damit `restore_ticket` das Ticket vollständig zurückbringt. Die Folge war
unbeabsichtigt: Tor 4 des Prune fragt `NOT EXISTS` OHNE `deleted_at`-Filter, also
nach der PHYSISCHEN Existenz einer Kind-Zeile. Ein aktiv gebliebener Kommentar
hielt das verborgene Ticket damit dauerhaft im Papierkorb — es wurde nie
endgültig gelöscht, und niemandem fiel es auf.

Die `loesch_ref` löst beides zugleich. Geprüft wird deshalb nicht nur, DASS
kaskadiert wird, sondern auch, dass das Wiederherstellen weiterhin genau das
zurückholt, was mit dem Ticket verschwunden ist — und nichts darüber hinaus.

Gegen echtes PostgreSQL, weil Audit-Trigger und die Tor-Semantik dazugehören.
Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-t190 -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=t190 -e TZ=Europe/Berlin -p 55445:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55445/t190 \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_ticket_verbergen_batch_integration.py
"""
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-batch-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_anhaenge, ticket_teilnehmer, ticket_teilnehmer_history, "
            "ticket_kommentare, ticket_kommentare_history, tickets, tickets_history "
            "RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username LIKE 'batch_%'")
    yield


def _user(db, name="batch_a"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role, created_by, updated_by) "
            "VALUES (%s, %s, 'h', 'admin', 't', 't') RETURNING id",
            (name, f"{name}@example.invalid"))
        return cur.fetchone()["id"]


def _ticket_mit_kindern(db, uid):
    """Ticket mit je einem Kommentar, Anhang und Teilnehmer."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO tickets (titel, beschreibung, gemeldet_von, created_by, "
                    "updated_by) VALUES ('Batch','B',%s,'t','t') RETURNING id", (uid,))
        tid = cur.fetchone()["id"]
        cur.execute("INSERT INTO ticket_kommentare (ticket_id, autor_id, inhalt, "
                    "created_by, updated_by) VALUES (%s,%s,'hallo','t','t') RETURNING id",
                    (tid, uid))
        kid = cur.fetchone()["id"]
        # stored_name ist UNIQUE – aus der Ticket-ID ableiten, damit zwei Tickets
        # im selben Test nicht kollidieren.
        cur.execute("INSERT INTO ticket_anhaenge (ticket_id, original_name, stored_name, "
                    "mime_type, dateigroesse, hochgeladen_von) "
                    "VALUES (%s,'shot.png',%s,'image/png',6,%s) RETURNING id",
                    (tid, f"b190-{tid}.png", uid))
        aid = cur.fetchone()["id"]
        cur.execute("INSERT INTO ticket_teilnehmer (ticket_id, user_id, hinzugefuegt_von, "
                    "created_by, updated_by) VALUES (%s,%s,%s,'t','t') RETURNING id",
                    (tid, uid, uid))
        pid = cur.fetchone()["id"]
    return tid, kid, aid, pid


def _zustand(db, tid):
    """Wer ist noch aktiv, und mit welcher loesch_ref?"""
    ergebnis = {}
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at, loesch_ref FROM tickets WHERE id=%s", (tid,))
        ergebnis["ticket"] = dict(cur.fetchone())
        for tabelle in ("ticket_kommentare", "ticket_anhaenge", "ticket_teilnehmer"):
            cur.execute(f"SELECT id, deleted_at, loesch_ref FROM {tabelle} "
                        f"WHERE ticket_id=%s ORDER BY id", (tid,))
            ergebnis[tabelle] = [dict(r) for r in cur.fetchall()]
    return ergebnis


class TestVerbergen:

    def test_kinder_gehen_mit(self, db):
        uid = _user(db)
        tid, *_ = _ticket_mit_kindern(db, uid)

        assert db.tickets.mark_ticket_deleted(tid, deleted_by="chef") is True

        z = _zustand(db, tid)
        ref = z["ticket"]["loesch_ref"]
        assert ref, "das Ticket selbst muss den Batch-Marker tragen"
        for tabelle in ("ticket_kommentare", "ticket_anhaenge", "ticket_teilnehmer"):
            zeile = z[tabelle][0]
            assert zeile["deleted_at"] is not None, f"{tabelle} blieb aktiv"
            assert zeile["loesch_ref"] == ref, f"{tabelle} hat eine fremde loesch_ref"

    def test_jeder_vorgang_bekommt_eine_eigene_ref(self, db):
        """Sonst würde ein Restore fremde Tickets mitreißen."""
        uid = _user(db)
        a, *_ = _ticket_mit_kindern(db, uid)
        b, *_ = _ticket_mit_kindern(db, uid)

        db.tickets.mark_ticket_deleted(a, deleted_by="chef")
        db.tickets.mark_ticket_deleted(b, deleted_by="chef")

        assert _zustand(db, a)["ticket"]["loesch_ref"] != \
            _zustand(db, b)["ticket"]["loesch_ref"]

    def test_zweites_verbergen_meldet_false(self, db):
        uid = _user(db)
        tid, *_ = _ticket_mit_kindern(db, uid)
        assert db.tickets.mark_ticket_deleted(tid, deleted_by="chef") is True
        assert db.tickets.mark_ticket_deleted(tid, deleted_by="chef") is False

    def test_kaskade_schreibt_history(self, db):
        """Die Kinder mit History brauchen den version-Bump — ohne ihn schriebe der
        Audit-Trigger nichts, und der Soft-Delete wäre nicht nachvollziehbar."""
        uid = _user(db)
        tid, kid, _, pid = _ticket_mit_kindern(db, uid)

        db.tickets.mark_ticket_deleted(tid, deleted_by="chef")

        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM ticket_kommentare_history WHERE id=%s",
                        (kid,))
            assert cur.fetchone()["n"] == 2          # Anlage + Soft-Delete
            cur.execute("SELECT COUNT(*) AS n FROM ticket_teilnehmer_history WHERE id=%s",
                        (pid,))
            assert cur.fetchone()["n"] == 2


class TestWiederherstellen:

    def test_holt_den_ganzen_batch_zurueck(self, db):
        uid = _user(db)
        tid, *_ = _ticket_mit_kindern(db, uid)
        db.tickets.mark_ticket_deleted(tid, deleted_by="chef")

        assert db.tickets.restore_ticket(tid, restored_by="chef") is True

        z = _zustand(db, tid)
        assert z["ticket"]["deleted_at"] is None
        assert z["ticket"]["loesch_ref"] is None
        for tabelle in ("ticket_kommentare", "ticket_anhaenge", "ticket_teilnehmer"):
            zeile = z[tabelle][0]
            assert zeile["deleted_at"] is None, f"{tabelle} kam nicht zurück"
            assert zeile["loesch_ref"] is None, f"{tabelle} trägt noch den Batch-Marker"

    def test_vorher_einzeln_geloeschtes_bleibt_geloescht(self, db):
        """Der Grund für die loesch_ref statt eines pauschalen „alles wieder an":
        Ein bewusst gelöschter Kommentar darf beim Restore nicht auferstehen."""
        uid = _user(db)
        tid, kid, *_ = _ticket_mit_kindern(db, uid)
        with db.cursor() as cur:                     # zweiter Kommentar, bleibt aktiv
            cur.execute("INSERT INTO ticket_kommentare (ticket_id, autor_id, inhalt, "
                        "created_by, updated_by) VALUES (%s,%s,'zweiter','t','t')",
                        (tid, uid))
        db.tickets.mark_kommentar_deleted(kid, deleted_by="autor")

        db.tickets.mark_ticket_deleted(tid, deleted_by="chef")
        db.tickets.restore_ticket(tid, restored_by="chef")

        z = {r["id"]: r for r in _zustand(db, tid)["ticket_kommentare"]}
        assert z[kid]["deleted_at"] is not None, "der einzeln gelöschte kam zurück"
        assert [r["deleted_at"] for r in z.values() if r["id"] != kid] == [None]

    def test_fremdes_ticket_bleibt_unberuehrt(self, db):
        uid = _user(db)
        a, *_ = _ticket_mit_kindern(db, uid)
        b, *_ = _ticket_mit_kindern(db, uid)
        db.tickets.mark_ticket_deleted(a, deleted_by="chef")
        db.tickets.mark_ticket_deleted(b, deleted_by="chef")

        db.tickets.restore_ticket(a, restored_by="chef")

        z = _zustand(db, b)
        assert z["ticket"]["deleted_at"] is not None
        assert all(r["deleted_at"] is not None for r in z["ticket_kommentare"])

    def test_nicht_verborgenes_ticket_meldet_false(self, db):
        uid = _user(db)
        tid, *_ = _ticket_mit_kindern(db, uid)
        assert db.tickets.restore_ticket(tid, restored_by="chef") is False


class TestPrunePfad:

    def test_verborgenes_ticket_wird_endgueltig_loeschbar(self, db):
        """Der eigentliche Befund aus #190: Ohne Kaskade blieben die Kinder aktiv,
        wurden nie Prune-Kandidat, und Tor 4 hielt das Ticket für immer fest."""
        from app.services.prune_service import (
            PRUNE_REGISTRY, build_original_candidate_count_sql)
        uid = _user(db)
        tid, *_ = _ticket_mit_kindern(db, uid)
        db.tickets.mark_ticket_deleted(tid, deleted_by="chef")

        # Fristen ablaufen lassen (keep_min=0 blendet Tor 3 aus)
        with db.cursor() as cur:
            for tabelle in ("tickets", "ticket_kommentare", "ticket_anhaenge",
                            "ticket_teilnehmer"):
                cur.execute(f"UPDATE {tabelle} SET deleted_at = deleted_at - "
                            f"interval '400 days' WHERE deleted_at IS NOT NULL")
                cur.execute("SELECT to_regclass(%s) IS NOT NULL AS da",
                            (tabelle + "_history",))
                if cur.fetchone()["da"]:
                    cur.execute(f"UPDATE {tabelle}_history SET "
                                f"created_at = created_at - interval '400 days', "
                                f"updated_at = updated_at - interval '400 days', "
                                f"deleted_at = deleted_at - interval '400 days'")

        def kandidaten(name, hold=0):
            e = replace(next(x for x in PRUNE_REGISTRY if x.name == name), keep_min=0)
            sql, params = build_original_candidate_count_sql(
                e, e.retention_days, 0, 365, parent_hold_days=hold)
            with db.cursor() as cur:
                cur.execute(sql, tuple(params))
                return cur.fetchone()["n"]

        # Die Kinder sind jetzt überhaupt erst Kandidat — ohne Kaskade wären es 0.
        assert kandidaten("ticket_anhang", hold=365) == 1
        assert kandidaten("ticket_kommentar") == 1
        assert kandidaten("ticket") == 0             # Tor 4: die Kinder liegen noch da

        with db.cursor() as cur:                     # einen Lauf später sind sie weg
            for tabelle in ("ticket_anhaenge", "ticket_kommentare", "ticket_teilnehmer"):
                cur.execute(f"DELETE FROM {tabelle} WHERE ticket_id=%s", (tid,))
        assert kandidaten("ticket") == 1
