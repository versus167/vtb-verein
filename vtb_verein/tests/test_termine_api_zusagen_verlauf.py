"""API des Zu-/Absage-Verlaufs (#215, backend/api/termine.py).

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_termine_api_gaeste): Der
Verlauf ist für alle mit Lese-Zugriff auf den Termin sichtbar – Kader wie Gäste –,
Fremde bekommen 403. Namen laufen wie im Kader-Dialog über die Spitznamen der
Mannschaft (#194), auch beim Eintragenden.
Die Ableitung der Ereignisse aus der History deckt test_termin_zusage_integration ab.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.termin import Termin  # noqa: E402
from backend.api import termine as api  # noqa: E402

_TERMIN = Termin(id=1, mannschaft_id=5, serie_id=None, typ='training',
                 beginn='2026-07-22T18:30', ende=None, ort=None,
                 spielstaette_id=1, treffpunkt=None,
                 treffpunkt_zeit=None, gegner=None, heim_auswaerts=None,
                 extern_ref=None, extern_stand=None, status='geplant',
                 beschreibung=None, version=1,
                 created_at='x', created_by='t', updated_at='x', updated_by='t')

_SPIELER = SimpleNamespace(role='mitglied', username='spieler', id=7,
                           has_permission=lambda p: False)


def _eintraege():
    return [
        {"mitglied_id": 11, "name": "Sebastian Müller", "art": "antwort",
         "antwort": "ab", "von": "zu", "kommentar": "Knie", "zeit": "z2",
         "durch_selbst": True, "durch_mitglied_id": None, "durch_name": None},
        {"mitglied_id": 12, "name": "Peter Gast", "art": "antwort",
         "antwort": "zu", "von": None, "kommentar": None, "zeit": "z1",
         "durch_selbst": False, "durch_mitglied_id": 20, "durch_name": "Trainer Echt"},
    ]


def _db(*, acl=None, hat_zusage=False, spitznamen=None):
    return SimpleNamespace(
        termine=SimpleNamespace(
            get=lambda tid: _TERMIN,
            get_access_for_user=lambda uid, mid: acl,
        ),
        termin_zusagen=SimpleNamespace(
            has_active_zusage=lambda tid, uid: hat_zusage,
            verlauf=lambda tid: _eintraege(),
        ),
        mannschaft_spitznamen=lambda mid: spitznamen or {},
    )


def test_kader_sieht_verlauf():
    res = api.zusagen_verlauf(1, _SPIELER, _db(acl='lesen'))
    assert [e['mitglied_id'] for e in res] == [11, 12]


def test_gast_sieht_verlauf():
    res = api.zusagen_verlauf(1, _SPIELER, _db(acl=None, hat_zusage=True))
    assert len(res) == 2


def test_fremder_bekommt_403():
    with pytest.raises(HTTPException) as exc:
        api.zusagen_verlauf(1, _SPIELER, _db(acl=None, hat_zusage=False))
    assert exc.value.status_code == 403


def test_spitznamen_fuer_mitglied_und_eintragenden():
    res = api.zusagen_verlauf(1, _SPIELER, _db(acl='lesen',
                                               spitznamen={11: 'Basti', 20: 'Coach'}))
    assert res[0]['name'] == 'Basti'
    assert res[1]['name'] == 'Peter Gast'          # ohne Spitzname: bürgerlich
    assert res[1]['durch_name'] == 'Coach'
