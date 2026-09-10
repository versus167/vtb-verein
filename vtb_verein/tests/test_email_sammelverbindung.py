"""Eine Anmeldung für viele Mails (EmailService.sammel_verbindung).

Anlass ist der 10.09.2026: Der Erinnerungslauf baute für jede Mail eine eigene
Verbindung auf und meldete sich neu an — ein Dutzend Anmeldungen in Sekunden von
derselben IP. Google hat den Login daraufhin gesperrt (534 5.7.9 WebLoginRequired).

Geprüft wird deshalb genau das, was dort schiefging: dass ein Block mit mehreren
Mails EINMAL anmeldet, dass ohne Block alles bleibt wie vorher (eine Verbindung je
Mail — der Request-Pfad der App schickt Einzelmails), und dass eine mitten im Lauf
weggebrochene Verbindung neu aufgebaut wird, statt den Rest des Laufs mitzureißen.
"""
import smtplib

import pytest

from app.services import email_service as mail


class _FakeSMTP:
    """Zählt Anmeldungen und Nachrichten; kann auf Wunsch einmal wegbrechen."""

    instanzen: list = []

    def __init__(self, server, port, timeout=None):
        self.server, self.port, self.timeout = server, port, timeout
        self.logins = 0
        self.gesendet: list = []
        self.tls = False
        self.beendet = False
        self.abbruch_bei = None
        _FakeSMTP.instanzen.append(self)

    # smtplib-Oberfläche, so weit der Service sie nutzt
    def starttls(self):
        self.tls = True

    def login(self, user, passwort):
        self.logins += 1

    def sendmail(self, absender, empfaenger, inhalt):
        if self.abbruch_bei is not None and len(self.gesendet) == self.abbruch_bei:
            raise smtplib.SMTPServerDisconnected("Verbindung weg")
        self.gesendet.append(empfaenger)

    def quit(self):
        self.beendet = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.quit()
        return False


@pytest.fixture(autouse=True)
def _smtp(monkeypatch):
    _FakeSMTP.instanzen = []
    monkeypatch.setattr(mail.smtplib, 'SMTP', _FakeSMTP)
    monkeypatch.setattr(mail.smtplib, 'SMTP_SSL', _FakeSMTP)
    monkeypatch.setenv('SMTP_SERVER', 'smtp.example.org')
    monkeypatch.setenv('SMTP_PORT', '587')
    monkeypatch.setenv('SMTP_USERNAME', 'app@example.org')
    monkeypatch.setenv('SMTP_PASSWORD', 'geheim')
    monkeypatch.setenv('MAIL_FROM', 'Verein <app@example.org>')
    return _FakeSMTP


def _schicke(anzahl: int) -> None:
    for i in range(anzahl):
        assert mail.EmailService.send_text_email(f"m{i}@example.org", "Betreff", "Text")


def test_ohne_block_baut_jede_mail_ihre_eigene_verbindung():
    _schicke(3)
    assert len(_FakeSMTP.instanzen) == 3
    assert [v.logins for v in _FakeSMTP.instanzen] == [1, 1, 1]


def test_im_block_genuegt_eine_anmeldung():
    with mail.sammel_verbindung():
        _schicke(5)
    assert len(_FakeSMTP.instanzen) == 1
    verbindung = _FakeSMTP.instanzen[0]
    assert verbindung.logins == 1
    assert len(verbindung.gesendet) == 5


def test_der_block_meldet_sich_am_ende_ab():
    with mail.sammel_verbindung():
        _schicke(1)
    assert _FakeSMTP.instanzen[0].beendet is True
    # Danach ist wieder Einzelversand – die Sitzung darf nicht hängen bleiben.
    _schicke(1)
    assert len(_FakeSMTP.instanzen) == 2


def test_verschachtelt_bleibt_es_eine_verbindung():
    with mail.sammel_verbindung():
        with mail.sammel_verbindung():
            _schicke(2)
        _schicke(1)
    assert len(_FakeSMTP.instanzen) == 1
    assert _FakeSMTP.instanzen[0].logins == 1


def test_weggebrochene_verbindung_wird_einmal_neu_aufgebaut():
    """Mailserver trennen nach Leerlauf oder nach N Nachrichten je Verbindung."""
    with mail.sammel_verbindung():
        _FakeSMTP.instanzen[0].abbruch_bei = 2      # die dritte Mail fliegt raus
        _schicke(4)
    assert len(_FakeSMTP.instanzen) == 2
    assert [len(v.gesendet) for v in _FakeSMTP.instanzen] == [2, 2]


def test_port_465_spricht_implizites_tls(monkeypatch):
    """Mit SMTP statt SMTP_SSL liefe ein 465er-Server in den Timeout."""
    monkeypatch.setenv('SMTP_PORT', '465')
    gerufen = {}
    monkeypatch.setattr(mail.smtplib, 'SMTP_SSL',
                        lambda *a, **k: gerufen.setdefault('ssl', _FakeSMTP(*a, **k)))
    _schicke(1)
    assert 'ssl' in gerufen
    assert gerufen['ssl'].tls is False           # kein STARTTLS auf einer SSL-Verbindung


def test_ohne_konfiguration_bleibt_der_block_folgenlos(monkeypatch):
    """Eine Instanz ohne SMTP-Zugang soll im Lauf nicht anders aussehen als vorher."""
    monkeypatch.delenv('SMTP_USERNAME', raising=False)
    with mail.sammel_verbindung():
        assert mail.EmailService.send_text_email("m@example.org", "B", "T") is False
    assert _FakeSMTP.instanzen == []
