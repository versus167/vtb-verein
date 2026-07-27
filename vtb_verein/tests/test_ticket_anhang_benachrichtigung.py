"""Benachrichtigung über neue Ticket-Anhänge (Ticket #136).

Ein nachgereichtes Foto lief bisher stumm durch: Wer nicht zufällig gerade ins
Ticket schaute, erfuhr nichts davon. Jetzt geht dieselbe Meldung raus wie beim
öffentlichen Kommentar – mit zwei Ausnahmen, die hier festgehalten sind:
Entwürfe schweigen, und ein fehlgeschlagener Upload meldet nichts.

Reiner Unit-Test mit Fakes (Muster: test_ticket_notification_deeplink.py) –
Dateisystem und Datenbank sind für die Frage nicht nötig.
"""
from types import SimpleNamespace

import pytest

from app.models.ticket import Ticket
from app.services import notification_service as ns
from app.services.ticket_service import TicketService


class _AnhangRepo:
    def __init__(self):
        self.geloescht = []

    def create(self, anhang):
        anhang.id = 1
        anhang.stored_name = "tick_000001.jpg"
        return anhang

    def mark_deleted(self, id, deleted_by):
        self.geloescht.append((id, deleted_by))
        return True


class _AnhangService:
    def __init__(self, fehler=None):
        self.fehler = fehler
        self.geschrieben = []

    def validiere(self, mime_type, dateigroesse):
        pass

    def schreibe(self, stored_name, data):
        if self.fehler:
            raise self.fehler
        self.geschrieben.append(stored_name)


def _service(anhang_service, ticket=None):
    ticket = ticket or Ticket(id=5, titel="Automat kaputt", bereich_id=1,
                              gemeldet_von=10, zugewiesen_an=11)
    ticket_repo = SimpleNamespace(get=lambda tid: ticket if tid == ticket.id else None)
    teilnehmer_repo = SimpleNamespace(
        list_by_ticket=lambda tid: [SimpleNamespace(user_id=12)])
    berechtigung_repo = SimpleNamespace(
        list_user_ids_bearbeiten_oder_schliessen=lambda bid: [11, 13])
    user_repo = SimpleNamespace(
        get_by_id=lambda uid: SimpleNamespace(id=uid, username=f"u{uid}", active=True))
    return TicketService(ticket_repo, None, _AnhangRepo(), None, None,
                         teilnehmer_repo, berechtigung_repo, user_repo,
                         anhang_service=anhang_service)


@pytest.fixture()
def gesendet(monkeypatch):
    treffer = []
    monkeypatch.setattr(
        ns.NotificationService, "send_notification_async",
        staticmethod(lambda user, title, message, push_service=None, url="/":
                     treffer.append((user.username, title, message, url))),
    )
    return treffer


def _lade_hoch(svc, notify=True, hochgeladen_von=10):
    return svc.add_anhang(ticket_id=5, kommentar_id=None, original_name="beleg.jpg",
                          mime_type="image/jpeg", inhalt=b"xxx",
                          hochgeladen_von=hochgeladen_von, notify=notify)


def test_neuer_anhang_meldet_dem_ticket_kreis(gesendet):
    """Melder (10) lädt hoch → Zugewiesener, Teilnehmer und Bereich erfahren es."""
    svc = _service(_AnhangService())
    _lade_hoch(svc)

    assert {name for name, _, _, _ in gesendet} == {"u11", "u12", "u13"}
    titel, text, url = gesendet[0][1], gesendet[0][2], gesendet[0][3]
    assert "Neuer Anhang" in titel and "#5" in titel
    assert "beleg.jpg" in text          # damit man weiß, was dazugekommen ist
    assert url == "/tickets?ticket=5"   # Deep-Link direkt ins Ticket (#117)


def test_hochladender_bekommt_keine_eigene_meldung(gesendet):
    svc = _service(_AnhangService())
    _lade_hoch(svc, hochgeladen_von=11)          # der Zugewiesene lädt selbst hoch
    assert {name for name, _, _, _ in gesendet} == {"u10", "u12", "u13"}


def test_anhang_am_entwurf_meldet_niemandem(gesendet):
    """Beim Anlegen hängt der Beleg an einem Ticket, das noch niemand kennt –
    die Meldung darf nicht vor dem Ticket selbst rausgehen."""
    svc = _service(_AnhangService())
    _lade_hoch(svc, notify=False)
    assert gesendet == []


def test_fehlgeschlagener_upload_meldet_nichts(gesendet):
    """Erst schreiben, dann melden – sonst kündigt die Nachricht eine Datei an,
    die es nie auf die Platte geschafft hat."""
    svc = _service(_AnhangService(fehler=OSError("Platte voll")))
    with pytest.raises(IOError):
        _lade_hoch(svc)
    assert gesendet == []
    assert svc._anhang_repo.geloescht == [(1, "SYSTEM_FEHLER")]


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
