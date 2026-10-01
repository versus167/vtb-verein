"""Login-Verlängerung bei Nutzung (Ticket #211) gegen echtes PostgreSQL.

Was sich nur an einer echten DB zeigt:

* `extend_session` schiebt `expires_at` hinaus, ohne `version` zu erhöhen –
  eine Verlängerung ist kein Änderungsstand für die History.
* Widerrufene oder schon abgelaufene Sessions lassen sich nicht wiederbeleben.
* Für Token von vor #211 (ohne `rem`) liest `get_current_user` aus
  `expires_at − created_at` ab, ob „Angemeldet bleiben" gesetzt war – das muss
  mit den Spaltentypen der echten DB funktionieren.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-verlaengerung-uploads")
    yield d
    d.close()


@pytest.fixture
def user_id(db):
    name = f"verl{uuid.uuid4().hex[:8]}"
    return db.create_user(name, f"{name}@example.org", "", "mitglied", "tester").id


def _session(db, user_id, laufzeit):
    return db.user_session_repository.create_session(
        user_id=user_id, expires_at=datetime.now(timezone.utc) + laufzeit)


def _version(db, sid):
    with db.user_session_repository.db.cursor() as cur:
        cur.execute("SELECT version FROM user_sessions WHERE sid = %s", (sid,))
        return cur.fetchone()["version"]


def _ablauf(zeile):
    wert = zeile["expires_at"]
    z = wert if isinstance(wert, datetime) else datetime.fromisoformat(str(wert))
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


def test_verlaengert_ohne_versions_bump(db, user_id):
    repo = db.user_session_repository
    sid = _session(db, user_id, timedelta(days=1))
    neu = datetime.now(timezone.utc) + timedelta(days=30)

    assert repo.extend_session(sid, neu) is True

    assert abs(_ablauf(repo.get_active_session(sid)) - neu) < timedelta(seconds=1)
    assert _version(db, sid) == 1


def test_widerrufene_session_bleibt_tot(db, user_id):
    repo = db.user_session_repository
    sid = _session(db, user_id, timedelta(days=1))
    repo.revoke_by_sid(sid, revoked_by="tester")

    assert repo.extend_session(sid, datetime.now(timezone.utc) + timedelta(days=30)) is False
    assert repo.get_active_session(sid) is None


def test_abgelaufene_session_bleibt_tot(db, user_id):
    repo = db.user_session_repository
    sid = _session(db, user_id, timedelta(seconds=-1))

    assert repo.extend_session(sid, datetime.now(timezone.utc) + timedelta(days=30)) is False
    assert repo.get_active_session(sid) is None


@pytest.mark.parametrize("remember, erwartet", [(True, True), (False, False)])
def test_alttoken_erkennt_haken_an_der_session(db, user_id, remember, erwartet):
    from backend.core import deps
    from backend.core.security import session_lifetime

    sid = _session(db, user_id, session_lifetime(remember))
    zeile = db.user_session_repository.get_active_session(sid)

    assert deps._bleibt_angemeldet({"sub": str(user_id), "sid": sid}, zeile) is erwartet
