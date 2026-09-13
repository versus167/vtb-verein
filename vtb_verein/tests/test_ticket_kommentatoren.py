"""Mitkommentiert zählt als beteiligt (#206).

Wer an einem Ticket nur kommentiert hatte – weder Melder noch zuständig –, fiel aus
dem Filter „Nur meine" und erfuhr nichts mehr davon, wenn sich am Ticket etwas tat.
Seit #206 gehört er zum Kreis: abgeleitet aus seinen (nicht gelöschten) Kommentaren,
ohne eigene Teilnahme-Zeile – so zählen auch Kommentare von vorher mit.

Zwei Ebenen, beide ohne DB:
  * Empfängerkreis im TicketService (Muster: test_ticket_anhang_benachrichtigung.py)
  * Liste und Kommentar-Endpunkt am API-Router (Muster: test_ticket_intern.py)
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.ticket import Ticket, TicketBereich, TicketKommentar  # noqa: E402
from app.services import notification_service as ns  # noqa: E402
from app.services.ticket_service import TicketService  # noqa: E402
from backend.api.tickets import (  # noqa: E402
    KommentarWrite, create_kommentar, list_tickets,
)

MELDER, BEARBEITER = 10, 11


# ======================================================= Empfängerkreis (Service)

def _service(ticket, autoren, *, mit_recht=(), admins=()):
    ticket_repo = SimpleNamespace(get=lambda tid: ticket,
                                  update=lambda t, by: True)
    kommentar_repo = SimpleNamespace(list_autor_ids=lambda tid: list(autoren),
                                     create=lambda k, by: k)
    teilnehmer_repo = SimpleNamespace(list_by_ticket=lambda tid: [])
    berechtigung_repo = SimpleNamespace(
        list_user_ids_bearbeiten_oder_schliessen=lambda bid: [BEARBEITER],
        user_hat_bereichsrecht=lambda bid, uid: uid in mit_recht)

    def _user(uid):
        return SimpleNamespace(id=uid, username=f"u{uid}", active=True,
                               role="admin" if uid in admins else "mitglied")

    user_repo = SimpleNamespace(
        get_by_id=_user,
        get_by_username=lambda name: _user(int(name[1:])))
    return TicketService(ticket_repo, kommentar_repo, None, None, None,
                         teilnehmer_repo, berechtigung_repo, user_repo)


def _ticket(*, intern=False):
    return Ticket(id=5, titel="Automat kaputt", status="offen", bereich_id=1,
                  gemeldet_von=MELDER, intern=intern)


@pytest.fixture()
def gesendet(monkeypatch):
    treffer = []
    monkeypatch.setattr(
        ns.NotificationService, "send_notification_async",
        staticmethod(lambda user, title, message, push_service=None, url="/":
                     treffer.append(user.username)),
    )
    return treffer


def test_statuswechsel_erreicht_wer_mitkommentiert_hat(gesendet):
    svc = _service(_ticket(), autoren=[20])
    svc.change_status(_ticket(), "in_pruefung", changed_by=f"u{BEARBEITER}", version=1)
    assert set(gesendet) == {"u10", "u20"}


def test_neuer_kommentar_erreicht_die_frueheren_kommentatoren(gesendet):
    """Der neue Kommentar ist beim Melden schon gespeichert – sein Autor steht also
    unter den Kommentatoren, bekommt als Auslöser aber keine eigene Meldung."""
    svc = _service(_ticket(), autoren=[20, 21])
    svc.add_kommentar(TicketKommentar(ticket_id=5, autor_id=21, inhalt="Bei mir auch"),
                      created_by="u21")
    assert set(gesendet) == {"u10", "u11", "u20"}


def test_interner_kommentar_geht_nicht_an_kommentatoren(gesendet):
    """Interne Kommentare kann ein einfacher Kommentator gar nicht lesen – die
    Meldung trüge ihren Anfang aber im Text."""
    svc = _service(_ticket(), autoren=[20])
    svc.add_kommentar(TicketKommentar(ticket_id=5, autor_id=BEARBEITER, inhalt="heikel",
                                      sichtbarkeit="intern"),
                      created_by=f"u{BEARBEITER}")
    assert "u20" not in gesendet


def test_internes_ticket_nur_an_kommentatoren_mit_leserecht(gesendet):
    """Wer sein Bereichsrecht seither verloren hat, liest nicht über die Meldungen
    weiter mit; Bereichsberechtigte und Admins schon."""
    svc = _service(_ticket(intern=True), autoren=[20, 21, 22],
                   mit_recht=[21], admins=[22])
    svc.change_status(_ticket(intern=True), "in_pruefung",
                      changed_by=f"u{BEARBEITER}", version=1)
    assert set(gesendet) == {"u10", "u21", "u22"}


# ========================================================= API-Router (ohne DB)

class _FakeTicketService:
    def __init__(self, tickets, kommentiert=()):
        self._tickets = list(tickets)
        self._kommentiert = set(kommentiert)
        self.kommentare = []

    def get_ticket(self, ticket_id):
        return next(t for t in self._tickets if t.id == ticket_id)

    def list_tickets_with_counts(self, nur_geloeschte=False):
        return list(self._tickets)

    def ids_ungelesen(self, user):
        return set()

    def ids_kommentiert(self, user_id):
        return self._kommentiert

    def get_bereiche(self):
        return [TicketBereich(id=1, name="Bereich")]

    def add_kommentar(self, kommentar, created_by):
        kommentar.id = len(self.kommentare) + 1
        self.kommentare.append(kommentar)
        return kommentar


class _FakeDB:
    def __init__(self, tickets, kommentiert=()):
        self.tickets = _FakeTicketService(tickets, kommentiert)
        self.ticket_bereich_berechtigungen = SimpleNamespace(
            user_hat_bereichsrecht=lambda bid, uid: False,
            get_bereich_ids_mit_recht=lambda uid: set())
        # UserService(db) im Listen-Endpunkt braucht diese beiden Repos.
        self.user_repository = SimpleNamespace(list_all=lambda: [])
        self.auth_token_repository = None

    def get_username(self, user_id):
        return f"u{user_id}"


def _user(uid):
    return SimpleNamespace(id=uid, username=f"u{uid}", role="mitglied")


def test_liste_markiert_mitkommentierte_tickets():
    db = _FakeDB([Ticket(id=1, bereich_id=1, gemeldet_von=MELDER),
                  Ticket(id=2, bereich_id=1, gemeldet_von=MELDER)], kommentiert=[2])
    ergebnis = {t["id"]: t["kommentiert"] for t in list_tickets(_user(20), db)}
    assert ergebnis == {1: False, 2: True}


def test_fremder_kann_sich_nicht_per_kommentar_in_internes_ticket_einschreiben():
    db = _FakeDB([Ticket(id=1, bereich_id=1, gemeldet_von=MELDER, intern=True)])
    with pytest.raises(HTTPException) as exc:
        create_kommentar(1, KommentarWrite(inhalt="Hallo"), _user(20), db)
    assert exc.value.status_code == 403
    assert db.tickets.kommentare == []


def test_offenes_ticket_darf_weiter_jeder_kommentieren():
    db = _FakeDB([Ticket(id=1, bereich_id=1, gemeldet_von=MELDER)])
    create_kommentar(1, KommentarWrite(inhalt="Bei mir auch"), _user(20), db)
    assert [k.autor_id for k in db.tickets.kommentare] == [20]


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
