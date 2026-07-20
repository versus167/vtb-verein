"""Unit-Test des Push-Deep-Links für Ticket-Benachrichtigungen (#117).

Klick auf eine Ticket-Push-Nachricht soll direkt ins betroffene Ticket führen,
nicht auf die Home-Seite. Dazu reicht TicketService._notify eine url an
NotificationService.send_notification_async durch. Reiner Unit-Test: nur
user_repo + push_service werden von _notify berührt, der Versand ist gepatcht.
"""
from types import SimpleNamespace

from app.services import notification_service as ns
from app.services.ticket_service import TicketService


def _service(user_repo, push_service='PUSH'):
    # _notify nutzt nur user_repo + push_service; übrige Repos bleiben None.
    return TicketService(None, None, None, None, None, None, None,
                         user_repo, push_service=push_service)


def test_ticket_url_ist_deeplink():
    assert TicketService._ticket_url(42) == '/tickets?ticket=42'


def test_notify_reicht_deeplink_url_durch(monkeypatch):
    active_user = SimpleNamespace(id=7, username='u', active=True)
    user_repo = SimpleNamespace(get_by_id=lambda uid: active_user)
    svc = _service(user_repo)

    calls = []
    monkeypatch.setattr(
        ns.NotificationService, 'send_notification_async',
        staticmethod(lambda user, title, message, push_service=None, url='/':
                     calls.append((user, url, push_service))),
    )

    svc._notify([7], exclude_user_id=None, title='t', message='m',
                url=svc._ticket_url(42))

    assert calls == [(active_user, '/tickets?ticket=42', 'PUSH')]


def test_notify_ueberspringt_ausloeser_und_inaktive(monkeypatch):
    users = {
        7: SimpleNamespace(id=7, username='u', active=True),
        8: SimpleNamespace(id=8, username='inaktiv', active=False),
        9: SimpleNamespace(id=9, username='actor', active=True),
    }
    user_repo = SimpleNamespace(get_by_id=lambda uid: users.get(uid))
    svc = _service(user_repo)

    sent = []
    monkeypatch.setattr(
        ns.NotificationService, 'send_notification_async',
        staticmethod(lambda user, title, message, push_service=None, url='/':
                     sent.append(user.id)),
    )

    # 9 ist der Auslöser (exclude), 8 ist inaktiv → nur 7 wird beliefert.
    svc._notify([7, 8, 9, 7], exclude_user_id=9, title='t', message='m',
                url=svc._ticket_url(1))

    assert sent == [7]
