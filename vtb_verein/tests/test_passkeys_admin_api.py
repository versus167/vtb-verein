"""Admin-Sicht auf die Passkeys eines Accounts (Personen → Account bearbeiten).

Für den Notfall „Handy weg": Wer Konten verwaltet (personen.permissions), sieht die
Passkeys eines Kontos und widerruft sie einzeln oder alle. Repository-Semantik prüft
test_webauthn_integration gegen PostgreSQL; hier stehen Stubs.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.api import users as api  # noqa: E402
from app.models.permission import Permission  # noqa: E402


class _AccessLog:
    def __init__(self):
        self.eintraege = []

    def log(self, event_type, **kw):
        self.eintraege.append({'event_type': event_type, **kw})


class _WebAuthn:
    def __init__(self):
        jetzt = datetime.now(timezone.utc)
        self.creds = {
            1: dict(id=1, user_id=7, geraet_label="Chrome auf Android", backed_up=True,
                    created_at=jetzt, last_used_at=None, revoked=False),
            2: dict(id=2, user_id=7, geraet_label="Safari auf iOS", backed_up=True,
                    created_at=jetzt, last_used_at=jetzt, revoked=False),
            3: dict(id=3, user_id=8, geraet_label="Fremd", backed_up=False,
                    created_at=jetzt, last_used_at=None, revoked=False),
        }

    def list_active_for_user(self, user_id):
        return [dict(c) for c in self.creds.values() if c["user_id"] == user_id and not c["revoked"]]

    def widerrufen(self, cred_id, user_id, revoked_by):
        c = self.creds.get(cred_id)
        if not c or c["user_id"] != user_id or c["revoked"]:
            return False
        c.update(revoked=True, revoked_by=revoked_by)
        return True

    def widerrufen_alle_fuer_user(self, user_id, revoked_by):
        n = 0
        for c in self.creds.values():
            if c["user_id"] == user_id and not c["revoked"]:
                c.update(revoked=True, revoked_by=revoked_by)
                n += 1
        return n


def _admin(rechte=(Permission.PERSONEN_PERMISSIONS,)):
    return SimpleNamespace(id=1, username="vorstand", has_permission=lambda p: p in rechte)


def _db():
    ziele = {7: SimpleNamespace(id=7, username="mitglied7"), 8: SimpleNamespace(id=8, username="m8")}
    return SimpleNamespace(webauthn=_WebAuthn(), access_log_repository=_AccessLog(),
                           get_user_by_id=lambda uid: ziele.get(uid))


def _request():
    return SimpleNamespace(client=SimpleNamespace(host='198.51.100.7'), headers={'user-agent': 'pytest'})


def test_liste_zeigt_nur_die_passkeys_des_kontos():
    liste = api.list_user_passkeys(7, _admin(), _db())
    assert [p["id"] for p in liste] == [1, 2]
    assert liste[0]["name"] == "Chrome auf Android" and "public_key" not in liste[0]


@pytest.mark.parametrize("aufruf", [
    lambda u, db: api.list_user_passkeys(7, u, db),
    lambda u, db: api.revoke_user_passkey(7, 1, _request(), u, db),
    lambda u, db: api.revoke_all_user_passkeys(7, _request(), u, db),
])
def test_ohne_kontoverwaltung_kein_zugriff(aufruf):
    nur_lesen = _admin(rechte=(Permission.PERSONEN_READ,))
    db = _db()
    with pytest.raises(HTTPException) as e:
        aufruf(nur_lesen, db)
    assert e.value.status_code == 403
    assert not any(c["revoked"] for c in db.webauthn.creds.values())


def test_unbekanntes_konto():
    with pytest.raises(HTTPException) as e:
        api.list_user_passkeys(99, _admin(), _db())
    assert e.value.status_code == 404


def test_einzeln_widerrufen_und_protokollieren():
    db = _db()
    api.revoke_user_passkey(7, 2, _request(), _admin(), db)
    assert db.webauthn.creds[2]["revoked"] and db.webauthn.creds[2]["revoked_by"] == "vorstand"
    assert not db.webauthn.creds[1]["revoked"]
    eintrag = db.access_log_repository.eintraege[-1]
    assert eintrag["event_type"] == "passkey_revoked" and eintrag["user_id"] == 7
    assert eintrag["detail"] == "2 · durch vorstand"


def test_passkey_eines_anderen_kontos_ist_nicht_erreichbar():
    db = _db()
    with pytest.raises(HTTPException) as e:
        api.revoke_user_passkey(7, 3, _request(), _admin(), db)
    assert e.value.status_code == 404 and not db.webauthn.creds[3]["revoked"]


def test_alle_widerrufen():
    db = _db()
    assert api.revoke_all_user_passkeys(7, _request(), _admin(), db)["widerrufen"] == 2
    assert api.list_user_passkeys(7, _admin(), db) == []
    assert not db.webauthn.creds[3]["revoked"]
    assert db.access_log_repository.eintraege[-1]["detail"] == "alle (2) · durch vorstand"


def test_alle_widerrufen_ohne_passkeys_protokolliert_nichts():
    db = _db()
    api.revoke_all_user_passkeys(7, _request(), _admin(), db)
    db.access_log_repository.eintraege.clear()
    assert api.revoke_all_user_passkeys(7, _request(), _admin(), db)["widerrufen"] == 0
    assert db.access_log_repository.eintraege == []
