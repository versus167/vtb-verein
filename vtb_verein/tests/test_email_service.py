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
    assert f'{APP_URL}/icons/logo-512.png' in html


def test_app_link_nicht_in_weiss_auf_gelb():
    """Vereinsfarben-Regel: auf gelbem Grund kein heller Text — der Link ist blau."""
    html = _render()
    fusszeile = html.split('Die App erreichst du jederzeit unter', 1)[1]
    assert EmailService._FLAECHE_DEFAULT in fusszeile.split('</a>', 1)[0]


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


# ── Vereinsneutralität: Namen, Farben, Logo-Schalter ────────────────────────
# Die Mail entsteht zur Laufzeit, deshalb genügen Env-Werte. Geprüft wird
# beides: dass ein fremder Verein seine Mail bekommt UND dass sich für den VTB
# nichts ändert — der Umbau von festen Hexwerten auf Rechnung wäre sonst eine
# stille Optik-Änderung in allen System-Mails.

def _render_mit(env, **kwargs):
    with patch.dict(os.environ, {'BASE_URL': APP_URL, **env}, clear=False):
        return EmailService.render_vtb_email(
            headline='Dein Login-Link', username='tester',
            intro_html='Text', button_label='Los', button_url=f'{APP_URL}/x',
            hints=['Hinweis'], preheader='Vorschau', **kwargs)


def test_vereinsname_und_kuerzel_kommen_aus_der_env():
    html = _render_mit({'VTB_VEREIN_NAME': 'BSC Rapid Kappel', 'VTB_VEREIN_KURZ': 'BSC'})
    assert '>BSC Rapid Kappel</div>' in html
    assert 'BSC Vereinsverwaltung' in html
    assert 'VTB' not in html


def test_farben_kommen_aus_der_env():
    html = _render_mit({'VTB_MAIL_FARBE_FLAECHE': '#7b1020',
                        'VTB_MAIL_FARBE_AKZENT': '#f0f0f0'})
    assert '#7b1020' in html and '#f0f0f0' in html
    assert EmailService._FLAECHE_DEFAULT not in html


def test_unsinnige_farbe_faellt_auf_den_standard_zurueck():
    """Ein Tippfehler in der Env darf keine kaputte Mail erzeugen."""
    html = _render_mit({'VTB_MAIL_FARBE_FLAECHE': 'dunkelblau'})
    assert EmailService._FLAECHE_DEFAULT in html


def test_logo_kann_abgeschaltet_werden():
    """VTB_MAIL_LOGO=aus → schlichte Bauform ohne Bild.

    Der Schalter hängt bewusst nicht an einer fehlenden Datei: Ausgeliefert wird
    immer ein Logo (die Wortmarke der Software), das ein fremder Verein nicht
    zwingend in seinen Mails haben will.
    """
    mit = _render_mit({})
    ohne = _render_mit({'VTB_MAIL_LOGO': 'aus'})
    assert '<img' in mit
    assert '<img' not in ohne
    # Der Vereinsname bleibt — die Mail ist schlicht, nicht anonym.
    assert 'VTB Chemnitz e.V.' in ohne


def test_button_bleibt_lesbar_bei_zwei_dunklen_farben():
    """Zwei dunkle Vereinsfarben ergäben dunkel auf dunkel — dann greift Weiß.

    Beim VTB (Blau auf Gelb, Kontrast ~8,5) ändert die Regel nichts; sie fängt
    den Verein ab, der zwei dunkle Farben einträgt und dessen Button sonst
    unlesbar wäre.
    """
    from app.services.email_service import _kontrast, _lesbar_auf
    flaeche, akzent = '#101820', '#1a2a3a'
    assert _kontrast(akzent, flaeche) < 4.5, 'Testfarben sind nicht kontrastarm genug'

    gewaehlt = _lesbar_auf(akzent, flaeche)
    assert gewaehlt == '#ffffff'
    assert _kontrast(akzent, gewaehlt) >= 4.5

    html = _render_mit({'VTB_MAIL_FARBE_FLAECHE': flaeche,
                        'VTB_MAIL_FARBE_AKZENT': akzent})
    assert f'color: {gewaehlt}; text-decoration: none' in html


def test_vtb_button_behaelt_seine_farbe():
    """Gegenprobe: Bei ausreichendem Kontrast bleibt es beim Wunschton."""
    from app.services.email_service import _lesbar_auf
    assert _lesbar_auf(EmailService._AKZENT_DEFAULT,
                       EmailService._FLAECHE_DEFAULT) == EmailService._FLAECHE_DEFAULT
    html = _render_mit({})
    assert f'color: {EmailService._FLAECHE_DEFAULT}; text-decoration: none' in html


def test_gemischte_toene_entsprechen_den_frueheren_festwerten():
    """Der Umbau auf Rechnung darf die VTB-Mail nicht verändern.

    Die drei Mischtöne standen früher als Hexwerte im Code (weiß 65 %/75 % auf
    Wappenblau, schwarz 45 % auf Wappengelb). Sie müssen exakt reproduziert
    werden, sonst verschiebt sich die Optik aller System-Mails still.
    """
    from app.services.email_service import _mischen, _SCHWARZ, _WEISS
    blau, gelb = EmailService._FLAECHE_DEFAULT, EmailService._AKZENT_DEFAULT
    assert _mischen(_WEISS, blau, 0.65) == '#a6bad8'
    assert _mischen(_WEISS, blau, 0.75) == '#c0cee3'
    assert _mischen(_SCHWARZ, gelb, 0.45) == '#8c8102'


def test_vtb_mail_bleibt_unveraendert():
    """Gegenprobe am ganzen Dokument: Ohne gesetzte Env sieht die Mail aus wie bisher."""
    html = _render_mit({})
    assert '>VTB Chemnitz e.V.</div>' in html
    assert 'VTB Vereinsverwaltung' in html
    for farbe in ('#023a90', '#feeb03', '#a6bad8', '#c0cee3', '#8c8102'):
        assert farbe in html, f'{farbe} fehlt — die VTB-Optik hat sich verschoben'
