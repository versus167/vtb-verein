"""
Tests für TTLockClient (rein HTTP-Ebene, ohne echte Netzwerk-/DB-Zugriffe).

Geprüft:
- Login hasht das Passwort als MD5 (lowercase hex) und persistiert via Callback.
- Signierte GET-Requests tragen clientId + accessToken + date.
- TTLock-Fehler-Envelope (errcode != 0) → TTLockError.
- Proaktiver Token-Refresh kurz vor Ablauf.
- Re-Login + Retry bei Auth-errcode (Token ungültig).
"""
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.ttlock_client import TTLockClient, TTLockError


def _resp(json_body):
    """Fake-requests-Response mit .json() und no-op .raise_for_status()."""
    r = MagicMock()
    r.json.return_value = json_body
    r.raise_for_status.return_value = None
    return r


def _client(**kwargs):
    defaults = dict(
        endpoint="https://euapi.ttlock.com",
        client_id="cid",
        client_secret="csecret",
        username="user@example.com",
        password="geheim123",
    )
    defaults.update(kwargs)
    c = TTLockClient(**defaults)
    c.session = MagicMock()
    return c


def _far_future():
    return datetime.now(timezone.utc) + timedelta(days=30)


class TestLogin:
    def test_login_hashes_password_md5_and_stores_token(self):
        updates = []
        c = _client(on_token_update=updates.append)
        c.session.post.return_value = _resp({
            "access_token": "AT", "refresh_token": "RT",
            "expires_in": 7776000, "uid": 42,
        })

        c.login()

        sent = c.session.post.call_args.kwargs["data"]
        assert sent["password"] == hashlib.md5(b"geheim123").hexdigest()
        assert sent["grant_type"] == "password"
        assert c.access_token == "AT"
        assert c.uid == 42
        assert c.token_expires_at is not None
        # Persistenz-Callback bekam den frischen Token-Stand
        assert updates and updates[-1]["access_token"] == "AT"

    def test_login_without_access_token_raises(self):
        c = _client()
        c.session.post.return_value = _resp({
            "errcode": 10007, "errmsg": "invalid account or invalid password",
        })
        with pytest.raises(TTLockError) as exc:
            c.login()
        assert exc.value.errcode == 10007


class TestSignedGet:
    def test_get_adds_signature_params(self):
        c = _client(access_token="AT", token_expires_at=_far_future())
        c.session.get.return_value = _resp({"list": [], "total": 0})

        c.lock_list()

        params = c.session.get.call_args.kwargs["params"]
        assert params["clientId"] == "cid"
        assert params["accessToken"] == "AT"
        assert isinstance(params["date"], int) and params["date"] > 0
        assert params["pageNo"] == 1

    def test_errcode_envelope_raises(self):
        c = _client(access_token="AT", token_expires_at=_far_future())
        c.session.get.return_value = _resp({"errcode": 20002, "errmsg": "lock not exist"})
        with pytest.raises(TTLockError) as exc:
            c.lock_detail(123)
        assert exc.value.errcode == 20002

    def test_errcode_zero_is_ok(self):
        c = _client(access_token="AT", token_expires_at=_far_future())
        c.session.get.return_value = _resp({"errcode": 0, "list": [1, 2]})
        assert c.lock_list()["list"] == [1, 2]


class TestTokenLifecycle:
    def test_proactive_refresh_when_near_expiry(self):
        c = _client(
            access_token="OLD", refresh_token="RT",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        c.session.post.return_value = _resp({
            "access_token": "NEW", "refresh_token": "RT2", "expires_in": 7776000,
        })
        c.session.get.return_value = _resp({"list": []})

        c.lock_list()

        assert c.session.post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
        assert c.access_token == "NEW"

    def test_login_when_no_token(self):
        c = _client()  # kein access_token
        c.session.post.return_value = _resp({"access_token": "AT", "expires_in": 7776000})
        c.session.get.return_value = _resp({"list": []})

        c.lock_list()

        assert c.session.post.call_args.kwargs["data"]["grant_type"] == "password"
        assert c.access_token == "AT"

    def test_relogin_and_retry_on_auth_errcode(self):
        c = _client(access_token="STALE", token_expires_at=_far_future())
        c.session.post.return_value = _resp({"access_token": "FRESH", "expires_in": 7776000})
        # Erst Auth-Fehler (10003), nach Re-Login dann Erfolg.
        c.session.get.side_effect = [
            _resp({"errcode": 10003, "errmsg": "token is expired"}),
            _resp({"list": [{"lockId": 1}]}),
        ]

        result = c.lock_list()

        assert c.session.post.called  # Re-Login erfolgte
        assert result["list"] == [{"lockId": 1}]
