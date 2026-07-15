"""
Regressionsschutz (Ticket #57): Nach der TIMESTAMPTZ-Umstellung (Schema v51)
liefern migrierte Audit-Spalten (users.last_login/last_seen,
user_sessions.created_at) datetime-Objekte statt Strings. Die str-typisierten
Response-Modelle UserInfo/SessionInfo scheiterten daran (Pydantic v2:
datetime ist kein str) → /api/auth/me und /me/sessions lieferten 500, das Profil
blieb leer. Der Boundary-Helfer _ts_iso() vereinheitlicht zu ISO-Strings.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

# backend/ ist kein Bestandteil des app-Pakets – Repo-Wurzel für den Import ergänzen.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.api.auth import UserInfo, SessionInfo, _ts_iso  # noqa: E402


class TestTsIso:
    def test_datetime_wird_iso_string(self):
        v = _ts_iso(datetime(2026, 6, 23, 9, 12, 34, tzinfo=timezone.utc))
        assert isinstance(v, str)
        assert v == '2026-06-23T09:12:34+00:00'

    def test_string_bleibt_unveraendert(self):
        # Alt-TEXT-Format (Space + 2-stelliger Offset) darf NICHT umgeparst werden.
        assert _ts_iso('2026-06-23 09:12:34.123+00') == '2026-06-23 09:12:34.123+00'

    def test_none_bleibt_none(self):
        assert _ts_iso(None) is None


class TestUserInfoMitDatetime:
    def test_datetime_felder_validieren(self):
        ui = UserInfo(
            id=1, username='vsuess', display_name='Volker Süß',
            email='v@example.org', role='admin',
            permissions=[],
            last_login=_ts_iso(datetime(2026, 6, 23, 9, 12, 34, tzinfo=timezone.utc)),
            last_seen=_ts_iso(datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)),
            version=3,
        )
        assert ui.username == 'vsuess'
        assert ui.last_login == '2026-06-23T09:12:34+00:00'


class TestSessionInfoMitDatetime:
    def test_gemischte_zeitstempel_validieren(self):
        si = SessionInfo(
            id=5, device_label='Firefox', user_agent='UA', ip='1.2.3.4',
            created_at=_ts_iso(datetime(2026, 6, 20, 8, 0, 0, tzinfo=timezone.utc)),
            last_seen_at=_ts_iso('2026-06-23 09:12:34.123+00'),   # TEXT-Spalte
            expires_at=_ts_iso('2026-07-23T09:12:34+00:00'),
            current=True,
        )
        assert si.created_at == '2026-06-20T08:00:00+00:00'
        assert si.last_seen_at == '2026-06-23 09:12:34.123+00'
