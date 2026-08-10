"""
API-Ebene der Zutritts-Auswertung (backend/api/schliessanlage.py).

Die Rechenarbeit prüfen die Service- und Integrationstests; hier geht es um das,
was der Endpunkt selbst entscheidet: das Protokoll-Recht (verdichtete Bewegungs-
daten sind dieselbe DSGVO-Klasse wie das Log), der Abteilungs-Scope und die
Begrenzung auf die auswählbaren Zeiträume.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from backend.api import schliessanlage as api  # noqa: E402


def _user(*perms, role='mitglied', abteilungen=None):
    keys = set(perms)
    return SimpleNamespace(
        id=1, username='pruefer', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in keys,
        has_permission_global=lambda p: role == 'admin' or p in keys,
        allowed_abteilungen=lambda p: abteilungen,
    )


class _Cursor:
    """Minimaler Cursor für visible_schloss_ids (liefert die Schlösser der Abteilung)."""
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a):
        pass

    def fetchall(self):
        return self.rows


def _db(aufrufe, schloss_rows=()):
    def auswertung(*, schloss_ids=None, von=None):
        aufrufe.append({'schloss_ids': schloss_ids, 'von': von})
        return {'kennzahlen': {'oeffnungen': 0, 'aktive_tage': 0, 'akteure': 0,
                               'schloesser': 0, 'erster_tag': None, 'letzter_tag': None,
                               'fehlversuche': 0, 'alarme': 0, 'ereignisse': 0},
                'schloesser': [], 'stunden': [], 'wochentage': [], 'methoden': [],
                'personen': [], 'tage': [], 'frueheste': None, 'spaeteste': None,
                'wochenende': None, 'nachtaktiv': None, 'vielfalt': None}
    return SimpleNamespace(
        tuer_zutritt_logs=SimpleNamespace(auswertung=auswertung),
        conn=SimpleNamespace(cursor=lambda: _Cursor(list(schloss_rows))),
    )


def test_auswertung_braucht_das_protokollrecht():
    with pytest.raises(HTTPException) as e:
        api.auswertung(_user(Permission.SCHLIESSANLAGE_READ), _db([]))
    assert e.value.status_code == 403 and 'Zutrittsprotokoll' in e.value.detail


def test_vereinsweites_recht_sieht_alle_schloesser():
    aufrufe = []
    api.auswertung(_user(Permission.SCHLIESSANLAGE_PROTOKOLL), _db(aufrufe))
    assert aufrufe[0]['schloss_ids'] is None


def test_abteilungsgebundenes_recht_wird_auf_seine_schloesser_begrenzt():
    aufrufe = []
    user = _user(Permission.SCHLIESSANLAGE_PROTOKOLL, abteilungen={5})
    api.auswertung(user, _db(aufrufe, schloss_rows=[{'id': 3}, {'id': 4}]))
    assert aufrufe[0]['schloss_ids'] == [3, 4]


def test_recht_ohne_passende_abteilung_sieht_nichts():
    aufrufe = []
    user = _user(Permission.SCHLIESSANLAGE_PROTOKOLL, abteilungen=set())
    api.auswertung(user, _db(aufrufe))
    assert aufrufe[0]['schloss_ids'] == []


def test_unbekannter_zeitraum_faellt_auf_den_standard_zurueck():
    aufrufe = []
    user = _user(Permission.SCHLIESSANLAGE_PROTOKOLL)
    api.auswertung(user, _db(aufrufe), tage=99999)
    api.auswertung(user, _db(aufrufe), tage=0)
    assert aufrufe[0]['von'] is not None      # 99999 → Standard 90 Tage
    assert aufrufe[1]['von'] is None          # 0 ist erlaubt: seit jeher
