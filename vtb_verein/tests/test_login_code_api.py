"""Login-Code-Endpunkt (Ticket #208) mit Stubs.

Die Einlöse-Logik selbst (eine Zeile für Link und Code, Versuchsgrenze) prüft
test_login_code_integration gegen echtes PostgreSQL. Hier geht es um den
Endpunkt drumherum: gleiche Antwort für jeden Fehlschlag, Protokoll, IP-Bremse,
Eingabe-Toleranz und dass der Code in der Mail landet.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import backend.core.config as cfg  # noqa: E402
from backend.api import auth as api  # noqa: E402


class _AccessLog:
    def __init__(self):
        self.eintraege = []
        self.zaehler = 0

    def log(self, event_type, **kw):
        self.eintraege.append({'event_type': event_type, **kw})

    def count(self, **kw):
        return self.zaehler

    def typen(self):
        return [e['event_type'] for e in self.eintraege]


class _Tokens:
    def __init__(self, gueltig=None):
        self.gueltig = gueltig   # Code-Klartext, der passt
        self.aufrufe = []

    def loese_code_ein(self, user_id, code_hash, max_versuche):
        self.aufrufe.append((user_id, code_hash, max_versuche))
        return self.gueltig is not None and code_hash == api._login_code_hash(self.gueltig)


def _user(aktiv=True):
    return SimpleNamespace(id=5, username='maxi', active=aktiv, email='maxi@example.org',
                           role='user', permissions=set())


def _db(user=None, gueltig=None):
    return SimpleNamespace(
        access_log_repository=_AccessLog(),
        auth_token_repository=_Tokens(gueltig),
        get_user_by_kennung=lambda kennung: user,
    )


def _request():
    return SimpleNamespace(client=SimpleNamespace(host='198.51.100.7'),
                           headers={'user-agent': 'pytest'})


@pytest.fixture
def session(monkeypatch):
    """Session-Anlage abklemmen – die ist beim Login-Link schon getestet."""
    angelegt = []
    monkeypatch.setattr(api, '_mail_login_session',
                        lambda db, req, resp, user, remember: angelegt.append((user.id, remember)) or 'ok')
    return angelegt


def _code(db, code, kennung='maxi', remember=False):
    return api.validate_login_code(
        api.MagicLinkCode(kennung=kennung, code=code, remember=remember),
        _request(), SimpleNamespace(), db)


def _fehler(db, code, **kw):
    with pytest.raises(HTTPException) as e:
        _code(db, code, **kw)
    return e.value


# ------------------------------------------------------------------- Erfolg
def test_richtiger_code_meldet_an(session):
    db = _db(_user(), gueltig='483912')
    assert _code(db, '483912', remember=True) == 'ok'
    assert session == [(5, True)]
    assert 'magic_code_login' in db.access_log_repository.typen()


def test_leerzeichen_im_code_sind_egal(session):
    """In der Mail steht „483 912" – so tippt man es auch ab."""
    db = _db(_user(), gueltig='483912')
    assert _code(db, ' 483 912 ') == 'ok'


def test_versuchsgrenze_wird_durchgereicht(session):
    db = _db(_user(), gueltig='483912')
    _code(db, '483912')
    assert db.auth_token_repository.aufrufe[0][2] == api.LOGIN_CODE_MAX_VERSUCHE


# ---------------------------------------------------------------- Fehlschlag
def test_alle_fehlschlaege_klingen_gleich(session):
    """Unbekanntes Konto, inaktives Konto, falscher Code, Unsinn – nach außen
    derselbe Text, sonst verriete der Endpunkt, welche Konten es gibt."""
    fehler = [
        _fehler(_db(None), '123456'),
        _fehler(_db(_user(aktiv=False), gueltig='123456'), '123456'),
        _fehler(_db(_user(), gueltig='483912'), '123456'),
        _fehler(_db(_user(), gueltig='483912'), 'abc'),
    ]
    assert {(f.status_code, f.detail) for f in fehler} == {(401, 'Code falsch oder abgelaufen')}
    assert session == []


def test_unsinn_zaehlt_keinen_versuch():
    """Ein Vertipper wie „48391" soll nicht einen der 5 Versuche kosten."""
    db = _db(_user(), gueltig='483912')
    _fehler(db, '48391')
    assert db.auth_token_repository.aufrufe == []


def test_fehlschlag_steht_im_protokoll():
    db = _db(_user(), gueltig='483912')
    _fehler(db, '000000')
    eintrag = db.access_log_repository.eintraege[-1]
    assert eintrag['event_type'] == 'magic_code_failed'
    assert eintrag['user_id'] == 5 and eintrag['detail'] == 'falsch · maxi'


def test_unbekanntes_konto_steht_mit_kennung_im_protokoll():
    db = _db(None)
    _fehler(db, '000000', kennung='gibtsnicht')
    assert db.access_log_repository.eintraege[-1]['detail'] == 'no_match · gibtsnicht'


def test_ip_bremse(session):
    db = _db(_user(), gueltig='483912')
    db.access_log_repository.zaehler = api.LOGIN_CODE_MAX_PER_IP
    f = _fehler(db, '483912')
    assert f.status_code == 429
    assert db.auth_token_repository.aufrufe == []   # nicht einmal geprüft
    assert db.access_log_repository.typen() == ['magic_link_rate_limited']


# ------------------------------------------------------------------ Hashing
def test_code_hash_haengt_am_geheimnis(monkeypatch):
    """Ohne das Server-Geheimnis ließe sich ein 6-stelliger Hash sofort
    zurückrechnen – wer nur die DB liest, hätte jeden offenen Code."""
    vorher = api._login_code_hash('483912')
    monkeypatch.setattr(cfg.settings, 'SECRET_KEY', 'ein-ganz-anderes-geheimnis-mit-laenge')
    assert api._login_code_hash('483912') != vorher


# --------------------------------------------------------------------- Mail
@pytest.fixture
def smtp_konfiguriert():
    alt = (cfg.settings.SMTP_USERNAME, cfg.settings.SMTP_PASSWORD)
    cfg.settings.SMTP_USERNAME, cfg.settings.SMTP_PASSWORD = 'user', 'pass'
    yield
    cfg.settings.SMTP_USERNAME, cfg.settings.SMTP_PASSWORD = alt


def test_anforderung_schickt_link_und_code(monkeypatch, smtp_konfiguriert):
    gesendet = []
    monkeypatch.setattr(api, '_send_magic_link_email',
                        lambda ziel, name, token, code: gesendet.append((token, code)))
    angelegt = []

    def anlegen(**kw):
        angelegt.append(kw)
        return 'tok', '483912'

    db = SimpleNamespace(
        access_log_repository=_AccessLog(),
        get_user_by_kennung=lambda k: _user(),
        auth_token_repository=SimpleNamespace(create_magic_link_mit_code=anlegen),
    )
    api.request_magic_link(api.MagicLinkRequest(kennung='maxi'), _request(), db)
    assert gesendet == [('tok', '483912')]
    assert angelegt[0]['code_minuten'] == api.LOGIN_CODE_MINUTEN
    assert angelegt[0]['code_hash_fn'] is api._login_code_hash
