"""API-Logik der Meldungen im Bereich „Berichte" (#155, backend/api/berichte.py).

Direkte Endpunkt-Aufrufe mit Stubs: Wer sieht Namen, wie greift der
Abteilungs-Scope, welcher Stichtag gilt ohne Angabe. Die Zahlen selbst deckt
test_berichte_meldungen_integration ab.
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from backend.api import berichte as api  # noqa: E402


def _user(*rechte, scope=None):
    """``scope`` None = vereinsweit, sonst die erlaubten Abteilungen für personen.read."""
    return SimpleNamespace(role='mitglied', has_permission=lambda p: p in rechte,
                           allowed_abteilungen=lambda p: scope)


class _Cursor:
    """Antwortet auf die eine Abfrage von ``visible_mitglied_ids``."""
    def __init__(self, ids):
        self.ids = ids

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return [{'mitglied_id': i} for i in self.ids]


def _db(luecken=(), sichtbar=()):
    stichtage = []

    def lsb_meldung(stichtag):
        stichtage.append(stichtag)
        return {"stichtag": stichtag.isoformat()}

    return SimpleNamespace(
        statistik=SimpleNamespace(lsb_meldung=lsb_meldung),
        berichtslisten=SimpleNamespace(fehlende_meldeangaben=lambda s: list(luecken)),
        conn=SimpleNamespace(cursor=lambda: _Cursor(sichtbar)),
        stichtage=stichtage,
    )


_LUECKEN = [{"mitglied_id": 1, "nachname": "A"}, {"mitglied_id": 2, "nachname": "B"}]


def test_lsb_ohne_berichte_recht_403():
    with pytest.raises(HTTPException) as e:
        api.get_lsb_meldung(_user(Permission.PERSONEN_READ), _db())
    assert e.value.status_code == 403


def test_lsb_stichtag_vorgabe_ist_31_12_vorjahr():
    db = _db()
    api.get_lsb_meldung(_user(Permission.BERICHTE_READ), db)
    assert db.stichtage == [date(date.today().year - 1, 12, 31)]


def test_lsb_ohne_personenrecht_keine_namen():
    res = api.get_lsb_meldung(_user(Permission.BERICHTE_READ), _db(_LUECKEN),
                              stichtag=date(2026, 12, 31))
    assert res["luecken"] is None


def test_lsb_namen_vereinsweit():
    res = api.get_lsb_meldung(_user(Permission.BERICHTE_READ, Permission.PERSONEN_READ),
                              _db(_LUECKEN), stichtag=date(2026, 12, 31))
    assert [z["mitglied_id"] for z in res["luecken"]] == [1, 2]


def test_lsb_namen_nur_im_abteilungs_scope():
    res = api.get_lsb_meldung(_user(Permission.BERICHTE_READ, Permission.PERSONEN_READ, scope={5}),
                              _db(_LUECKEN, sichtbar=[2]), stichtag=date(2026, 12, 31))
    assert [z["mitglied_id"] for z in res["luecken"]] == [2]


# --- Ehrungen -----------------------------------------------------------------

def test_ehrungen_ohne_personenrecht_403():
    with pytest.raises(HTTPException) as e:
        api.get_ehrungen(_user(Permission.BERICHTE_READ), _db())
    assert e.value.status_code == 403


@pytest.mark.parametrize("heute, erwartet", [
    (date(2027, 1, 15), date(2027, 3, 31)),   # Januar: Hauptausschuss fürs laufende Jahr
    (date(2027, 3, 31), date(2027, 3, 31)),
    (date(2026, 11, 6), date(2027, 3, 31)),   # ab April schon das kommende Jahr
])
def test_ehrungen_vorgabe_naechster_31_maerz(heute, erwartet):
    assert api._naechster_31_maerz(heute) == erwartet


def test_ehrungen_nur_im_abteilungs_scope():
    db = _db(sichtbar=[2])
    db.berichtslisten.ehrungen = lambda s: list(_LUECKEN)
    res = api.get_ehrungen(_user(Permission.BERICHTE_READ, Permission.PERSONEN_READ, scope={5}),
                           db, stichtag=date(2027, 3, 31))
    assert [z["mitglied_id"] for z in res["ehrungen"]] == [2]
    assert res["stufen"] == [25, 40, 50, 60, 70, 75, 80]


# --- Übungsleiter -------------------------------------------------------------

def test_uebungsleiter_ohne_personenrecht_403():
    with pytest.raises(HTTPException) as e:
        api.get_uebungsleiter(_user(Permission.BERICHTE_READ), _db())
    assert e.value.status_code == 403


def test_uebungsleiter_nur_im_abteilungs_scope():
    db = _db(sichtbar=[1])
    db.berichtslisten.uebungsleiter = lambda: list(_LUECKEN)
    res = api.get_uebungsleiter(_user(Permission.BERICHTE_READ, Permission.PERSONEN_READ, scope={5}), db)
    assert [z["mitglied_id"] for z in res] == [1]


# --- Altersgruppen ------------------------------------------------------------

def test_altersgruppen_vorgabe_heute_und_ohne_personenrecht():
    tage = []
    db = SimpleNamespace(statistik=SimpleNamespace(altersgruppen_am=lambda s: tage.append(s)))
    api.get_altersgruppen(_user(Permission.BERICHTE_READ), db)
    assert tage == [date.today()]
    with pytest.raises(HTTPException):
        api.get_altersgruppen(_user(Permission.PERSONEN_READ), db)
