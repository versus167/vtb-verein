"""Mitkommentiert (#206) – die beiden Abfragen gegen echtes PostgreSQL.

Die Logik drumherum prüft test_ticket_kommentatoren.py mit Fakes; hier geht es nur
darum, dass die SQL-Seite stimmt: je Autor einmal, gelöschte Kommentare zählen nicht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB); VereinsDB legt das
Schema beim Connect an.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.ticket import Ticket, TicketBereich, TicketKommentar  # noqa: E402
from app.services import notification_service as ns  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-kommentatoren-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch):
    monkeypatch.setattr(
        ns.NotificationService, "send_notification_async",
        staticmethod(lambda *a, **k: None),
    )


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_kommentare, ticket_kommentare_history, tickets, tickets_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username LIKE 'tk_%'")
    yield


def _user(db, name):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES (%s,%s,'x','mitglied',1,'test','test') RETURNING id",
            (name, f"{name}@example.com"),
        )
        return cur.fetchone()["id"]


def _kommentiere(db, ticket_id, autor_id, name):
    return db.tickets.add_kommentar(
        TicketKommentar(ticket_id=ticket_id, autor_id=autor_id, inhalt="…"), created_by=name)


def test_kommentatoren_je_autor_einmal_ohne_geloeschte(db):
    melder, anna, bernd = _user(db, "tk_melder"), _user(db, "tk_anna"), _user(db, "tk_bernd")
    bereich = db.tickets.create_bereich(TicketBereich(name="TK-Bereich"), "test")
    t1 = db.tickets.create_ticket(Ticket(titel="Eins", bereich_id=bereich.id, gemeldet_von=melder),
                                  created_by="tk_melder", notify=False)
    t2 = db.tickets.create_ticket(Ticket(titel="Zwei", bereich_id=bereich.id, gemeldet_von=melder),
                                  created_by="tk_melder", notify=False)

    _kommentiere(db, t1.id, anna, "tk_anna")
    _kommentiere(db, t1.id, anna, "tk_anna")
    zurueckgezogen = _kommentiere(db, t1.id, bernd, "tk_bernd")
    _kommentiere(db, t2.id, bernd, "tk_bernd")
    db.tickets.mark_kommentar_deleted(zurueckgezogen.id, deleted_by="tk_bernd")

    repo = db.tickets._kommentar_repo
    assert sorted(repo.list_autor_ids(t1.id)) == [anna]
    assert db.tickets.ids_kommentiert(anna) == {t1.id}
    assert db.tickets.ids_kommentiert(bernd) == {t2.id}
    assert db.tickets.ids_kommentiert(melder) == set()
