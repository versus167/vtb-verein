"""Tests für das Wiedereröffnen abgeschlossener Tickets (Ticket #136).

Hintergrund: „Erledigt" war eine Sackgasse – ein Fehlgriff ließ sich nicht mehr
korrigieren, und Kommentare/Anhänge blieben gesperrt. Jetzt führt genau ein Weg
zurück ('offen'), und zwar nur für den, der auch schließen darf.

Zwei Ebenen:
  * Rechte am API-Router – mit Fakes, ohne DB (Muster: test_aufgaben_hinweis.py)
  * Statusübergang, Abschluss-Stempel und Benachrichtigung – gegen echtes
    PostgreSQL (Muster: test_ticket_gesehen_verlauf_integration.py)
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.ticket import Ticket, TicketBereich, TicketStatus  # noqa: E402
from app.services import notification_service as ns  # noqa: E402
from app.services.ticket_service import UngueltigerStatusWechselError  # noqa: E402
from backend.api.tickets import StatusChange, change_status  # noqa: E402


# =========================================================== Rechte (ohne DB)

class _FakeBerechtigungen:
    def __init__(self, bearbeiten=(), schliessen=()):
        self._bearbeiten = set(bearbeiten)
        self._schliessen = set(schliessen)

    def user_darf_bearbeiten(self, bereich_id, user_id):
        return user_id in self._bearbeiten

    def user_darf_schliessen(self, bereich_id, user_id):
        return user_id in self._schliessen


class _FakeTicketService:
    def __init__(self, ticket):
        self.ticket = ticket
        self.wechsel = []

    def get_ticket(self, ticket_id):
        return self.ticket

    def change_status(self, ticket, new_status, changed_by, version):
        self.wechsel.append((new_status, changed_by, version))
        ticket.status = new_status
        return True

    def get_bereich(self, bereich_id):
        return SimpleNamespace(name="Bereich")


class _FakeDB:
    def __init__(self, ticket, bearbeiten=(), schliessen=()):
        self.tickets = _FakeTicketService(ticket)
        self.ticket_bereich_berechtigungen = _FakeBerechtigungen(bearbeiten, schliessen)

    def get_username(self, user_id):
        return f"u{user_id}"


def _erledigtes_ticket():
    return Ticket(id=5, titel="Aus Versehen zu", status=TicketStatus.ERLEDIGT,
                  bereich_id=1, gemeldet_von=99, version=3)


def _user(uid, role="mitglied"):
    return SimpleNamespace(id=uid, username=f"u{uid}", role=role)


def test_bearbeiter_ohne_schliessrecht_darf_nicht_wiedereroeffnen():
    """Wer nicht schließen darf, darf auch keinen Abschluss kassieren."""
    db = _FakeDB(_erledigtes_ticket(), bearbeiten={7})
    with pytest.raises(HTTPException) as exc:
        change_status(5, StatusChange(status="offen", expected_version=3), _user(7), db)
    assert exc.value.status_code == 403
    assert "wieder zu öffnen" in exc.value.detail
    assert db.tickets.wechsel == []


def test_schliesser_darf_wiedereroeffnen():
    # Die Rechte-Kaskade vergibt mit 'schliessen' immer auch 'bearbeiten'
    # (set_bereich_berechtigung) – hier genauso abgebildet.
    db = _FakeDB(_erledigtes_ticket(), bearbeiten={7}, schliessen={7})
    change_status(5, StatusChange(status="offen", expected_version=3), _user(7), db)
    assert db.tickets.wechsel == [("offen", "u7", 3)]


def test_admin_darf_wiedereroeffnen():
    db = _FakeDB(_erledigtes_ticket())          # keinerlei Bereichsrechte
    change_status(5, StatusChange(status="offen", expected_version=3), _user(1, "admin"), db)
    assert db.tickets.wechsel == [("offen", "u1", 3)]


# ====================================================== Statuswechsel (mit DB)

_URL = os.getenv("VTB_TEST_DATABASE_URL")
_braucht_db = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    if not _URL:
        pytest.skip("VTB_TEST_DATABASE_URL nicht gesetzt")
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-reopen-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def benachrichtigungen(monkeypatch):
    """Fängt den Versand ab – kein echter Mail-/Push-Weg, dafür prüfbar."""
    gesendet = []
    monkeypatch.setattr(
        ns.NotificationService, "send_notification_async",
        staticmethod(lambda user, title, message, push_service=None, url="/":
                     gesendet.append((user.username, title, message))),
    )
    return gesendet


@pytest.fixture()
def clean(db):
    """Bewusst nicht autouse: die Rechte-Tests oben kommen ohne Datenbank aus."""
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_zugriff_log, ticket_teilnehmer, ticket_teilnehmer_history, "
            "ticket_kommentare, ticket_kommentare_history, tickets, tickets_history, "
            "ticket_bereich_berechtigungen, ticket_bereich_berechtigungen_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username LIKE 'we_%'")
    yield


def _mk_user(db, name):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES (%s,%s,'x','mitglied',1,'test','test') RETURNING id",
            (name, f"{name}@example.com"),
        )
        return cur.fetchone()["id"]


@pytest.fixture()
def scenario(db, clean):
    melder = _mk_user(db, "we_melder")
    schliesser = _mk_user(db, "we_schliesser")
    bereich = db.tickets.create_bereich(TicketBereich(name="WE-Bereich"), "test")
    db.ticket_bereich_berechtigungen.set_berechtigung(
        bereich.id, schliesser, True, True, True, "test")
    ticket = db.tickets.create_ticket(
        Ticket(titel="Testticket", bereich_id=bereich.id, gemeldet_von=melder),
        created_by="we_melder", notify=False,
    )
    return dict(melder=melder, schliesser=schliesser, bereich=bereich, ticket=ticket)


def _wechsel(db, ticket_id, status, by="we_schliesser"):
    t = db.tickets.get_ticket(ticket_id)
    ok = db.tickets.change_status(t, status, changed_by=by, version=t.version)
    assert ok is True
    return db.tickets.get_ticket(ticket_id)


@_braucht_db
@pytest.mark.parametrize("abschluss", [TicketStatus.ERLEDIGT, TicketStatus.ABGELEHNT])
def test_abgeschlossenes_ticket_laesst_sich_wieder_oeffnen(db, scenario, abschluss):
    tid = scenario["ticket"].id
    zu = _wechsel(db, tid, abschluss)
    assert zu.status == abschluss
    assert zu.geschlossen_am is not None

    auf = _wechsel(db, tid, TicketStatus.OFFEN)
    assert auf.status == TicketStatus.OFFEN
    # Der Abschluss-Stempel muss mit weg – sonst gilt das Ticket im Verlauf
    # weiter als „geschlossen am …".
    assert auf.geschlossen_am is None
    assert auf.geschlossen_von is None


@_braucht_db
def test_abschluss_vermerkt_wer_geschlossen_hat(db, scenario):
    zu = _wechsel(db, scenario["ticket"].id, TicketStatus.ERLEDIGT)
    assert zu.geschlossen_von == scenario["schliesser"]


@_braucht_db
def test_aus_dem_abschluss_geht_nur_offen(db, scenario):
    tid = scenario["ticket"].id
    _wechsel(db, tid, TicketStatus.ERLEDIGT)
    t = db.tickets.get_ticket(tid)
    with pytest.raises(UngueltigerStatusWechselError):
        db.tickets.change_status(t, TicketStatus.IN_PRUEFUNG,
                                 changed_by="we_schliesser", version=t.version)


@_braucht_db
def test_wiedereroeffnetes_ticket_zaehlt_wieder_als_aufgabe(db, scenario):
    """Gegenprobe zum Aufgaben-Hinweis (#133): die Zahl folgt dem Status."""
    tid = scenario["ticket"].id
    schliesser = db.get_user_by_id(scenario["schliesser"])
    assert db.tickets.anzahl_zustaendig(schliesser) == 1

    _wechsel(db, tid, TicketStatus.ERLEDIGT)
    assert db.tickets.anzahl_zustaendig(schliesser) == 0

    _wechsel(db, tid, TicketStatus.OFFEN)
    assert db.tickets.anzahl_zustaendig(schliesser) == 1


@_braucht_db
def test_wiedereroeffnen_benachrichtigt_den_kreis_ohne_den_ausloeser(db, scenario, benachrichtigungen):
    tid = scenario["ticket"].id
    _wechsel(db, tid, TicketStatus.ERLEDIGT)
    benachrichtigungen.clear()

    _wechsel(db, tid, TicketStatus.OFFEN)
    empfaenger = {name for name, _, _ in benachrichtigungen}
    assert empfaenger == {"we_melder"}          # der Schließer löst aus, sich selbst nicht
    assert "wieder geöffnet" in benachrichtigungen[0][1]


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
