"""Login-Verlängerung bei Nutzung (Ticket #211) mit Stubs.

Nur Sessions mit „Angemeldet bleiben" gleiten: Ist mehr als die halbe Laufzeit um,
stellt `get_current_user` ein frisches Token mit derselben sid aus und die
Middleware setzt es als Cookie – an jede Antwort, aber nie über ein Cookie, das
der Endpunkt selbst setzt oder löscht (Logout). Ohne Haken bleibt es bei der
festen kurzen Frist ab Login.

Das Repository (`extend_session`) prüft test_login_verlaengerung_integration
gegen echtes PostgreSQL.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core import deps  # noqa: E402
from backend.core.config import settings  # noqa: E402
from backend.core.db import get_db  # noqa: E402
from backend.core.security import (  # noqa: E402
    REMEMBER_ME_LIFETIME, create_access_token, decode_token)
from backend.main import app  # noqa: E402

KURZ = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
SID = "sid-abc"


@pytest.fixture(autouse=True)
def _schluessel(monkeypatch):
    # Der Platzhalter ist kürzer als PyJWT mag – dessen Warnung wäre hier ein Fehler.
    monkeypatch.setattr(settings, "SECRET_KEY", "test-schluessel-mit-ausreichender-laenge")


class _Sessions:
    def __init__(self, laufzeit=REMEMBER_ME_LIFETIME, lebt=True):
        jetzt = datetime.now(timezone.utc)
        self.zeile = {"id": 1, "user_id": 5, "sid": SID, "revoked_at": None,
                      "created_at": jetzt.isoformat(),
                      "expires_at": (jetzt + laufzeit).isoformat()}
        self.lebt = lebt
        self.verlaengert = []
        self.widerrufen = []

    def get_active_session(self, sid):
        return self.zeile if sid == SID else None

    def touch_session(self, sid):
        return True

    def extend_session(self, sid, expires_at):
        self.verlaengert.append((sid, expires_at))
        return self.lebt

    def revoke_by_sid(self, sid, revoked_by):
        self.widerrufen.append(sid)
        return True

    def revoke_others(self, user_id, keep_sid, revoked_by):
        return 0


def _db(sessions):
    user = SimpleNamespace(id=5, username="maxi", active=True, role="user", permissions=set())
    return SimpleNamespace(
        user_session_repository=sessions,
        get_user_by_id=lambda uid: user if uid == 5 else None,
        update_last_seen=lambda uid: None,
        access_log_repository=SimpleNamespace(log=lambda *a, **kw: None),
    )


def _token(rest, remember=True, sid=SID):
    """Token, dessen Laufzeit noch `rest` beträgt."""
    return create_access_token(5, expires_delta=rest, session_id=sid, remember=remember)


def _verlaengern(token, sessions):
    request = SimpleNamespace(state=SimpleNamespace())
    payload = decode_token(token)
    deps._verlaengere_bei_nutzung(request, _db(sessions), payload, sessions.zeile)
    return getattr(request.state, "session_cookie", None)


# ── Entscheidung in get_current_user ──────────────────────────────────────────

def test_nach_halbzeit_gibt_es_ein_frisches_token():
    sessions = _Sessions()
    neu = _verlaengern(_token(REMEMBER_ME_LIFETIME / 2 - timedelta(minutes=1)), sessions)

    assert neu is not None
    token, max_age = neu
    assert max_age == int(REMEMBER_ME_LIFETIME.total_seconds())
    payload = decode_token(token)
    # Dieselbe Session (Gerät abmelden wirkt weiter), wieder als „angemeldet bleiben"
    assert payload["sid"] == SID and payload["sub"] == "5" and payload["rem"] is True
    exp = datetime.fromtimestamp(payload["exp"], timezone.utc)
    assert exp - datetime.now(timezone.utc) > REMEMBER_ME_LIFETIME - timedelta(minutes=1)
    # Die Session-Zeile zieht mit – sonst wiese get_active_session das Token ab
    (sid, bis), = sessions.verlaengert
    assert sid == SID and abs(bis - exp) < timedelta(seconds=5)


def test_vor_halbzeit_bleibt_alles_wie_es_ist():
    sessions = _Sessions()
    assert _verlaengern(_token(REMEMBER_ME_LIFETIME / 2 + timedelta(minutes=1)), sessions) is None
    assert sessions.verlaengert == []


def test_ohne_haken_keine_verlaengerung():
    """Ohne „Angemeldet bleiben" endet die Session fest nach der kurzen Frist."""
    sessions = _Sessions(laufzeit=KURZ)
    assert _verlaengern(_token(timedelta(minutes=5), remember=False), sessions) is None
    assert sessions.verlaengert == []


def test_widerrufene_session_bekommt_kein_token():
    """Gerät zwischen Prüfung und Verlängerung abgemeldet → kein neues Cookie."""
    sessions = _Sessions(lebt=False)
    assert _verlaengern(_token(timedelta(days=1)), sessions) is None


@pytest.mark.parametrize("laufzeit, gleitet", [(REMEMBER_ME_LIFETIME, True), (KURZ, False)])
def test_token_von_vor_211_nach_session_laufzeit(laufzeit, gleitet):
    """Alte Token tragen kein `rem`; ob der Haken gesetzt war, verrät dann die
    Laufzeit der (nie verlängerten) Session-Zeile."""
    sessions = _Sessions(laufzeit=laufzeit)
    alt = create_access_token(5, expires_delta=timedelta(minutes=5), session_id=SID)
    assert "rem" not in decode_token(alt)
    assert (_verlaengern(alt, sessions) is not None) is gleitet


# ── Cookie an der Antwort (Middleware) ────────────────────────────────────────

@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _session_cookies(antwort):
    return [c for c in antwort.headers.get_list("set-cookie")
            if c.startswith(f"{settings.COOKIE_NAME}=")]


def _aufruf(client, sessions, token, pfad="/api/auth/me/sessions/revoke-others"):
    app.dependency_overrides[get_db] = lambda: _db(sessions)
    # Bearer statt Cookie: Das Cookie ist ggf. `secure`, und httpx kennt keine
    # Cookies mehr pro Request – den Auth-Pfad durchläuft beides gleich.
    return client.post(pfad, headers={"Authorization": f"Bearer {token}"})


def test_middleware_setzt_das_frische_cookie(client):
    antwort = _aufruf(client, _Sessions(), _token(timedelta(days=1)))
    assert antwort.status_code == 200
    cookie, = _session_cookies(antwort)
    token = cookie.split(";", 1)[0].split("=", 1)[1]
    assert decode_token(token)["sid"] == SID
    assert "httponly" in cookie.lower()
    assert f"max-age={int(REMEMBER_ME_LIFETIME.total_seconds())}" in cookie.lower()


def test_ohne_verlaengerung_kein_cookie(client):
    antwort = _aufruf(client, _Sessions(), _token(REMEMBER_ME_LIFETIME))
    assert antwort.status_code == 200
    assert _session_cookies(antwort) == []


def test_logout_loescht_trotz_faelliger_verlaengerung(client):
    """Der Logout löscht das Cookie selbst – das darf die Verlängerung nicht
    wieder überschreiben, sonst bliebe man nach dem Abmelden angemeldet."""
    sessions = _Sessions()
    antwort = _aufruf(client, sessions, _token(timedelta(days=1)), pfad="/api/auth/logout")
    assert antwort.status_code == 200
    assert sessions.widerrufen == [SID]
    cookie, = _session_cookies(antwort)
    assert cookie.startswith(f'{settings.COOKIE_NAME}="";') or "max-age=0" in cookie.lower()
