"""Konten ohne Zugang: Benutzer, die nur ein Name sind (Schema v96).

Hintergrund ist die Schlüsselzuordnung: Ein Chip gehört einem Mitglied ODER einem
Benutzerkonto ohne Mitgliedsdatensatz — Platzwart, Hausmeister, Betreuer eines
Gastvereins. Diese Leute tragen einen Schlüssel, bekommen aber kein App-Konto.
Damit ihr Name an einem Chip stehen kann, darf ein Benutzer ohne E-Mail und ohne
Passwort angelegt werden; anmelden kann sich damit niemand.

Geprüft wird hier die Regel ohne Datenbank (die DB-Seite steckt in
test_benutzer_ohne_zugang_integration.py): Was zählt als Anmeldeweg, und dass
der historische Platzhalter-Hash keiner ist.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.user_service import UserService, _PLATZHALTER_PASSWORT  # noqa: E402


# --- Anmeldeweg-Regel -------------------------------------------------------

def test_konto_ohne_anmeldeweg_darf_nicht_aktiv_sein():
    with pytest.raises(ValueError, match="E-Mail oder ein Passwort"):
        UserService._pruefe_anmeldeweg(True, None, '')


def test_inaktives_konto_ohne_anmeldeweg_ist_erlaubt():
    """Genau der Schlüsselträger: kein Login, nur ein Name."""
    UserService._pruefe_anmeldeweg(False, None, '')


@pytest.mark.parametrize("email,hash_", [
    ("platzwart@example.invalid", ''),          # nur Magic-Link
    (None, '$2b$12$irgendein-hash'),            # nur Passwort
    ("platzwart@example.invalid", '$2b$12$x'),  # beides
])
def test_ein_anmeldeweg_genuegt_fuer_aktiv(email, hash_):
    UserService._pruefe_anmeldeweg(True, email, hash_)


# --- Anmeldung --------------------------------------------------------------

def _service(user):
    """UserService mit Stub-Repository – authenticate braucht sonst nichts."""
    repo = SimpleNamespace(
        get_by_username=lambda name: user if user and user.username == name else None,
        update_last_login=lambda uid: True,
    )
    return UserService(SimpleNamespace(user_repository=repo, auth_token_repository=None))


def _konto(username='platzwart', *, password_hash='', active=True):
    return SimpleNamespace(id=7, username=username, password_hash=password_hash,
                           active=active)


def test_konto_ohne_passwort_meldet_sich_nicht_an():
    """Leerer Hash heißt „kein Passwort gesetzt" – kein Passwort darf darauf passen."""
    service = _service(_konto())
    for versuch in ('', ' ', 'geheim', _PLATZHALTER_PASSWORT):
        assert service.authenticate('platzwart', versuch) is None


def test_platzhalter_text_ist_kein_passwort():
    """Altbestand: Konten ohne Passwort trugen einen bcrypt-Hash über einen festen
    Text aus dem Quelltext. Wer den kennt, käme sonst in jedes dieser Konten."""
    alt_hash = bcrypt.hashpw(_PLATZHALTER_PASSWORT.encode(), bcrypt.gensalt()).decode()
    service = _service(_konto(password_hash=alt_hash))

    assert service.authenticate('platzwart', _PLATZHALTER_PASSWORT) is None


def test_echtes_passwort_meldet_sich_weiterhin_an():
    hash_ = bcrypt.hashpw(b'geheim123', bcrypt.gensalt()).decode()
    service = _service(_konto(password_hash=hash_))

    angemeldet = service.authenticate('platzwart', 'geheim123')

    assert angemeldet is not None and angemeldet.id == 7
