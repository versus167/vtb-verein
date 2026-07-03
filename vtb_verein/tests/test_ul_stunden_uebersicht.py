"""Tests für den Übersichts-Endpoint /ul-stunden/uebersicht (#73).

Fremderfasser/Verwaltung sollen den Stand ALLER Erfassungen sehen, ohne ÜL für ÜL
durchzugehen. Ohne status_filter kommen nur die offenen Abrechnungen (Entwurf +
Eingereicht); bestätigte/abgelehnte gehören in die Bestätigen-/Fibu-Sicht.
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
from app.models.ul_stunden import (  # noqa: E402
    ULAbrechnung, STATUS_ENTWURF, STATUS_EINGEREICHT,
    STATUS_BESTAETIGT, STATUS_ABGELEHNT,
)
from backend.api.ul_stunden import list_uebersicht  # noqa: E402


def _abr(id, status, nachname='M'):
    return ULAbrechnung(id=id, mitglied_id=id, abteilung_id=1,
                        zeitraum_von='2026-06-01', zeitraum_bis='2026-06-30',
                        status=status, mitglied_nachname=nachname, mitglied_vorname='A')


class _User:
    def __init__(self, *perms):
        self._perms = set(perms)

    def has_permission(self, p):
        return p in self._perms


class _AbrRepo:
    def __init__(self, abrechnungen):
        self._abr = list(abrechnungen)

    def list_all(self, status=None):
        return [a for a in self._abr if not status or a.status == status]

    def list_stunden(self, abrechnung_id):
        return []


class _DB:
    def __init__(self, abrechnungen):
        self.ul_abrechnungen = _AbrRepo(abrechnungen)
        self.ul_saetze = SimpleNamespace(resolve=lambda *a, **k: None)


ALLE = [
    _abr(1, STATUS_ENTWURF), _abr(2, STATUS_EINGEREICHT),
    _abr(3, STATUS_BESTAETIGT), _abr(4, STATUS_ABGELEHNT),
]


class TestUebersicht:
    def test_fremderfasser_sieht_nur_offene(self):
        user = _User(Permission.UL_STUNDEN_ERFASSEN_FREMD)
        rows = list_uebersicht(user, _DB(ALLE))
        assert {r['id'] for r in rows} == {1, 2}
        assert {r['status'] for r in rows} == {STATUS_ENTWURF, STATUS_EINGEREICHT}

    def test_verwaltung_ohne_fremd_recht_ebenfalls_erlaubt(self):
        user = _User(Permission.UL_STUNDEN_VERWALTEN)
        rows = list_uebersicht(user, _DB(ALLE))
        assert {r['id'] for r in rows} == {1, 2}

    def test_status_filter_grenzt_auf_einen_status_ein(self):
        user = _User(Permission.UL_STUNDEN_ERFASSEN_FREMD)
        rows = list_uebersicht(user, _DB(ALLE), status_filter=STATUS_EINGEREICHT)
        assert {r['id'] for r in rows} == {2}

    def test_ohne_berechtigung_403(self):
        user = _User(Permission.UL_STUNDEN_ERFASSEN)   # nur eigene Erfassung
        with pytest.raises(HTTPException) as exc:
            list_uebersicht(user, _DB(ALLE))
        assert exc.value.status_code == 403
