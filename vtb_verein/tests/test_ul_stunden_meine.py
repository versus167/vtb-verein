"""Tests für den Endpoint /ul-stunden/meine (#88).

Ein Fremderfasser/Admin ohne verknüpftes Mitglied hat keine "eigenen" Abrechnungen.
Das darf keinen Fehler werfen (sonst scheitert der initiale Seitenaufbau der
Stundenerfassung mit "Fehler beim Laden"), sondern liefert eine leere Liste.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from app.models.ul_stunden import ULAbrechnung, STATUS_ENTWURF  # noqa: E402
from backend.api.ul_stunden import list_meine  # noqa: E402


def _abr(id, mitglied_id):
    return ULAbrechnung(id=id, mitglied_id=mitglied_id, abteilung_id=1,
                        zeitraum_von='2026-06-01', zeitraum_bis='2026-06-30',
                        status=STATUS_ENTWURF, mitglied_nachname='M', mitglied_vorname='A')


class _User:
    def __init__(self, *perms, admin=False, id=1):
        self._perms = set(perms)
        self._admin = admin
        self.id = id

    def has_permission(self, p):
        return self._admin or p in self._perms


class _AbrRepo:
    def __init__(self, by_mitglied):
        self._by_mitglied = by_mitglied

    def list_for_mitglied(self, mitglied_id, status=None):
        return list(self._by_mitglied.get(mitglied_id, []))

    def list_stunden(self, abrechnung_id):
        return []


class _DB:
    def __init__(self, mitglied_by_user, by_mitglied=None):
        self._mitglied_by_user = mitglied_by_user
        self.ul_abrechnungen = _AbrRepo(by_mitglied or {})
        self.ul_saetze = SimpleNamespace(resolve=lambda *a, **k: None)

    def get_mitglied_by_user_id(self, uid):
        return self._mitglied_by_user.get(uid)


class TestMeine:
    def test_admin_ohne_mitglied_bekommt_leere_liste(self):
        # Admin (alle Rechte) ohne verknüpftes Mitglied, kein mitglied_id → [] statt 400 (#88).
        user = _User(admin=True)
        db = _DB(mitglied_by_user={})
        assert list_meine(user, db) == []

    def test_eigener_ul_sieht_seine_abrechnungen(self):
        user = _User(Permission.UL_STUNDEN_ERFASSEN)
        own = SimpleNamespace(id=622)
        db = _DB(mitglied_by_user={7: own}, by_mitglied={622: [_abr(1, 622)]})
        user.id = 7
        rows = list_meine(user, db)
        assert [r['id'] for r in rows] == [1]

    def test_fremd_zugriff_ohne_recht_403(self):
        # Reiner ÜL (nur eigene Erfassung) darf keine fremde mitglied_id abfragen.
        user = _User(Permission.UL_STUNDEN_ERFASSEN)
        own = SimpleNamespace(id=622)
        db = _DB(mitglied_by_user={7: own})
        user.id = 7
        with pytest.raises(HTTPException) as exc:
            list_meine(user, db, mitglied_id=999)
        assert exc.value.status_code == 403

    def test_ohne_jede_berechtigung_403(self):
        user = _User()   # keine ÜL-Rechte
        user.id = 7
        db = _DB(mitglied_by_user={})
        with pytest.raises(HTTPException) as exc:
            list_meine(user, db)
        assert exc.value.status_code == 403
