"""Kommentar- und Anhang-Zähler am Ticket (#54-Nachgang).

Die Ticketliste zeigt je Zeile zwei Symbole mit Zahl. Die Oberfläche ersetzt eine
Listenzeile durch die Antwort der Detail- und Schreib-Endpunkte (Status ändern,
zuweisen, bearbeiten) — liefert die Einzel-Abfrage die Zähler nicht mit, sind die
Symbole nach jeder Bearbeitung weg, bis jemand neu lädt. Genau das war zu sehen:
Ticket #49 hatte zwei Anhänge und zeigte keinen.

Deshalb prüft dieser Test beide Wege gegeneinander: `get` (ein Ticket) und
`list_all_with_counts` (die Liste) müssen dieselbe Zahl sagen.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB); VereinsDB legt das
Schema beim Connect an.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.ticket import Ticket, TicketBereich, TicketKommentar  # noqa: E402
from app.services import notification_service as ns  # noqa: E402
from backend.api.tickets import (  # noqa: E402
    StatusChange, TicketUpdate, change_status, update_ticket,
)

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-counts-uploads")
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
            "TRUNCATE ticket_anhaenge, "
            "ticket_kommentare, ticket_kommentare_history, tickets, tickets_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username LIKE 'tz_%'")
    yield


@pytest.fixture()
def melder(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES ('tz_melder','tz@example.com','x','mitglied',1,'test','test') RETURNING id"
        )
        return cur.fetchone()["id"]


@pytest.fixture()
def ticket(db, melder):
    bereich = db.tickets.create_bereich(TicketBereich(name="TZ-Bereich"), "test")
    return db.tickets.create_ticket(
        Ticket(titel="Mit Anhängen", bereich_id=bereich.id, gemeldet_von=melder),
        created_by="tz_melder", notify=False)


def _anhang(db, ticket_id, melder, name, *, kommentar_id=None):
    """Anhang ohne Datei anlegen – gezählt wird die Zeile, nicht der Inhalt."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO ticket_anhaenge (ticket_id, kommentar_id, original_name, "
            "stored_name, mime_type, dateigroesse, hochgeladen_von) "
            "VALUES (%s, %s, %s, %s, 'image/png', 1, %s) RETURNING id",
            (ticket_id, kommentar_id, name, f"att_{name}", melder),
        )
        return cur.fetchone()["id"]


def _aus_liste(db, ticket_id):
    return next(t for t in db.tickets.list_tickets_with_counts() if t.id == ticket_id)


def test_einzelnes_ticket_zaehlt_wie_die_liste(db, ticket, melder):
    """Der eigentliche Fehler: die Liste wusste es, das einzelne Ticket nicht."""
    _anhang(db, ticket.id, melder, 'a.png')
    _anhang(db, ticket.id, melder, 'b.png')
    db.tickets.add_kommentar(
        TicketKommentar(ticket_id=ticket.id, autor_id=melder, inhalt="Notiz"), "tz_melder")

    einzeln = db.tickets.get_ticket(ticket.id)
    assert (einzeln.kommentar_count, einzeln.anhang_count) == (1, 2)

    aus_liste = _aus_liste(db, ticket.id)
    assert (einzeln.kommentar_count, einzeln.anhang_count) == \
           (aus_liste.kommentar_count, aus_liste.anhang_count)


def test_ohne_kommentare_und_anhaenge_sind_es_null(db, ticket):
    """Null ist nicht dasselbe wie „unbekannt" – die Oberfläche blendet bei 0 aus."""
    einzeln = db.tickets.get_ticket(ticket.id)
    assert (einzeln.kommentar_count, einzeln.anhang_count) == (0, 0)


def test_geloeschter_anhang_zaehlt_nicht_mehr(db, ticket, melder):
    anhang_id = _anhang(db, ticket.id, melder, 'weg.png')
    _anhang(db, ticket.id, melder, 'bleibt.png')
    db.tickets.mark_anhang_deleted(anhang_id, deleted_by="test")

    assert db.tickets.get_ticket(ticket.id).anhang_count == 1
    assert _aus_liste(db, ticket.id).anhang_count == 1


def test_anhang_am_kommentar_zaehlt_zum_ticket(db, ticket, melder):
    """Angehängt wird auch an einen Kommentar – für die Liste ist es dasselbe Ticket."""
    kommentar = db.tickets.add_kommentar(
        TicketKommentar(ticket_id=ticket.id, autor_id=melder, inhalt="mit Bild"), "tz_melder")
    _anhang(db, ticket.id, melder, 'am-kommentar.png', kommentar_id=kommentar.id)

    assert db.tickets.get_ticket(ticket.id).anhang_count == 1


def test_status_wechsel_verliert_die_zaehler_nicht(db, ticket, melder):
    """Der Auslöser in der Praxis: erledigt setzen, Zeile war danach leer."""
    _anhang(db, ticket.id, melder, 'a.png')
    _anhang(db, ticket.id, melder, 'b.png')

    db.tickets.change_status(ticket, 'erledigt', 'tz_melder', ticket.version)

    nachher = db.tickets.get_ticket(ticket.id)
    assert (nachher.status, nachher.anhang_count) == ('erledigt', 2)


# ------------------------------------------------- der gemeldete Weg (über die API)
# Genau die Folge aus der Meldung: Ticket auf „intern" setzen, schließen, zurück in
# die Liste. Die Oberfläche ersetzt die Listenzeile durch die ANTWORT dieser beiden
# Endpunkte – deshalb wird hier die Antwort geprüft und nicht die Datenbank.

def _admin(user_id):
    return SimpleNamespace(id=user_id, username='tz_melder', role='admin')


def test_intern_setzen_behaelt_die_zaehler_in_der_antwort(db, ticket, melder):
    _anhang(db, ticket.id, melder, 'a.png')
    _anhang(db, ticket.id, melder, 'b.png')

    antwort = update_ticket(
        ticket.id,
        TicketUpdate(titel=ticket.titel, intern=True, bereich_id=ticket.bereich_id,
                     expected_version=ticket.version),
        _admin(melder), db)

    assert antwort['intern'] is True
    assert antwort['anhang_count'] == 2


def test_schliessen_behaelt_die_zaehler_in_der_antwort(db, ticket, melder):
    _anhang(db, ticket.id, melder, 'a.png')
    db.tickets.add_kommentar(
        TicketKommentar(ticket_id=ticket.id, autor_id=melder, inhalt="Notiz"), "tz_melder")

    antwort = change_status(
        ticket.id, StatusChange(status='erledigt', expected_version=ticket.version),
        _admin(melder), db)

    assert (antwort['status'], antwort['kommentar_count'], antwort['anhang_count']) \
        == ('erledigt', 1, 1)
