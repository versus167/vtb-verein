"""
Tests für die Mail-Vorlage (EmailService.render_vtb_email).

Schwerpunkt Ticket #140: Jede System-Mail muss den direkten Weg zur App
enthalten — sonst steht man vor einem verbrauchten Magic-Link ohne Ausweg —
und der Einmal-Charakter des Links muss deutlich benannt sein.
"""
import os
import sys
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

from app.services.email_service import EmailService


APP_URL = 'https://app.vtbchemnitz.de'


def _render(base_url=APP_URL, hints=None):
    with patch.dict(os.environ, {'BASE_URL': base_url}):
        return EmailService.render_vtb_email(
            headline='Dein Login-Link',
            username='tester',
            intro_html='hier ist dein Login-Link:',
            button_label='Jetzt einloggen',
            button_url=f"{base_url.rstrip('/')}/auth/magic-link?token=abc",
            hints=hints if hints is not None else EmailService._MAGIC_LINK_HINTS,
            preheader='Vorschautext',
        )


def test_vorlage_enthaelt_direkten_app_link():
    """#140: Die Fußzeile verlinkt die App selbst, nicht nur den Button-Link."""
    html = _render()
    assert f'<a href="{APP_URL}"' in html
    # ohne Schema angezeigt, damit die Fußzeile lesbar bleibt
    assert '>app.vtbchemnitz.de</a>' in html


def test_app_link_ohne_doppelten_slash():
    """BASE_URL mit Schrägstrich am Ende darf keine //-URLs erzeugen."""
    html = _render(base_url=f'{APP_URL}/')
    assert f'{APP_URL}//' not in html
    assert f'{APP_URL}/icons/vtb-wappen-512.png' in html


def test_app_link_nicht_in_weiss_auf_gelb():
    """Vereinsfarben-Regel: auf gelbem Grund kein heller Text — der Link ist blau."""
    html = _render()
    fusszeile = html.split('Die App erreichst du jederzeit unter', 1)[1]
    assert EmailService._VTB_BLAU in fusszeile.split('</a>', 1)[0]


def test_magic_link_hinweis_nennt_einmalige_nutzung():
    """#140: Der Hinweis auf die Einmal-Nutzung steht sichtbar unter dem Button."""
    html = _render()
    assert 'nur ein einziges Mal' in html
    assert '7 Tage gültig' in html


def test_backend_magic_link_mail_nennt_app_und_einmal_nutzung(monkeypatch):
    """Der real genutzte Versandweg (backend/api/auth.py) muss beides
    transportieren — auch in der Text-Variante, die Mail-Clients ohne HTML zeigen."""
    # backend/ ist kein Bestandteil des app-Pakets – Repo-Wurzel für den Import ergänzen.
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from backend.api import auth as auth_api

    monkeypatch.setattr(auth_api.settings, 'BASE_URL', f'{APP_URL}/', raising=False)
    monkeypatch.setattr(auth_api.settings, 'SMTP_PORT', 587, raising=False)
    gesendet = {}

    class _FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def sendmail(self, sender, recipient, body):
            gesendet['body'] = body

        def quit(self):
            pass

    monkeypatch.setattr(auth_api.smtplib, 'SMTP', _FakeSMTP)
    with patch.dict(os.environ, {'BASE_URL': APP_URL}):
        auth_api._send_magic_link_email('tester@example.org', 'tester', 'tok123')

    # MIME kodiert den Body (quoted-printable/base64) – erst dekodiert prüfbar.
    msg = message_from_string(gesendet['body'])
    body = next(
        teil.get_payload(decode=True).decode('utf-8')
        for teil in msg.walk()
        if teil.get_content_type() == 'text/plain'
    )
    assert 'nur ein einziges Mal' in body
    assert f'{APP_URL}/auth/magic-link?token=tok123' in body
    # Der blanke App-Link steht als eigene Zeile in der Text-Variante.
    assert f'Die App erreichst du jederzeit unter:\n{APP_URL}' in body
