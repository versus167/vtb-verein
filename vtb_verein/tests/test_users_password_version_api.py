"""POST /api/users/{id}/password liefert die neue User-version.

Hintergrund: Passwort setzen erhöht users.version (Optimistic Locking). Die
Bearbeiten-Dialoge merken sich beim Öffnen ein expected_version; ohne die neue
Version in der Antwort lief das anschließende Speichern in den Versionskonflikt.

Stub-basiert nach dem Muster von test_mein_mitglied_kontakte_api: direkter
Endpunkt-Aufruf mit SimpleNamespace-DB, UserService als Stub.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.api import users as api  # noqa: E402

_ACTOR = SimpleNamespace(id=1, username='admin', role='admin',
                         has_permission=lambda p: True)


class _ServiceStub:
    """Passwortwechsel erhöht die Version – wie user_repository.update_password."""

    def __init__(self, db):
        self._db = db

    def change_password(self, user_id, new_password, updated_by):
        if len(new_password) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen lang sein")
        self._db.user.version += 1
        return True


def _db(version=3):
    user = SimpleNamespace(id=7, username='max', email='max@example.de',
                           role='mitglied', active=True, last_login=None,
                           last_seen=None, version=version)
    ns = SimpleNamespace(user=user)
    ns.get_user_by_id = lambda uid: user if uid == user.id else None
    return ns


def test_change_password_liefert_neue_version(monkeypatch):
    monkeypatch.setattr(api, 'UserService', _ServiceStub)
    res = api.change_password(7, api.PasswordChange(new_password='geheim1'),
                              _ACTOR, _db(version=3))
    assert res == {"ok": True, "version": 4}


def test_change_password_kurzes_passwort_ist_400(monkeypatch):
    monkeypatch.setattr(api, 'UserService', _ServiceStub)
    with pytest.raises(HTTPException) as exc:
        api.change_password(7, api.PasswordChange(new_password='kurz'),
                            _ACTOR, _db())
    assert exc.value.status_code == 400
