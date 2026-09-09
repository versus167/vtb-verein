"""Schreib-Schema des Serien-Takts (backend/api/termine.py, Schema v121).

Das Verhalten des Generators prüft test_termin_serie_integration gegen echtes
Postgres. Hier geht es nur um den API-Vertrag, und der trägt zwei Entscheidungen:

* Ohne Angabe bleibt es wöchentlich – ein Client, der den Takt nicht kennt,
  darf keine 14-tägige Serie erzeugen.
* Der Takt ist beim Anlegen zu haben und nur dort. Zusammen mit `start_datum`
  bestimmt er, an welchen Tagen Instanzen entstehen; nachträglich geändert
  müssten materialisierte Instanzen verschwinden und andere entstehen, was
  `update()` nicht kann – deshalb fehlt das Feld in SerieUpdate.
"""
import sys
from pathlib import Path

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from backend.api import termine as api  # noqa: E402

_PFLICHT = dict(beginn_zeit="18:30", spielstaette_id=3, start_datum="2026-09-16")


def test_ohne_angabe_woechentlich():
    assert api.SerieCreate(**_PFLICHT).intervall_wochen == 1


def test_14_taegig_erlaubt():
    assert api.SerieCreate(**_PFLICHT, intervall_wochen=2).intervall_wochen == 2


@pytest.mark.parametrize("wert", [0, api.MAX_INTERVALL_WOCHEN + 1])
def test_takt_ausserhalb_der_grenzen(wert):
    with pytest.raises(ValidationError):
        api.SerieCreate(**_PFLICHT, intervall_wochen=wert)


def test_update_kennt_den_takt_nicht():
    """Sonst nähme die API eine Änderung entgegen, die niemand ausführt."""
    s = api.SerieUpdate(beginn_zeit="18:30", spielstaette_id=3, expected_version=1,
                        intervall_wochen=2)
    assert not hasattr(s, 'intervall_wochen')
