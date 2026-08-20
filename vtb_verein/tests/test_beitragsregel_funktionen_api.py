"""Funktions-Schlüssel in Beitragsregeln werden geprüft (backend/api/beitraege.py).

Bis v105 stand die Beitragsrelevanz im Feld „Beitragspflichtiger Abteilungs-Status",
und ein Validator ließ dort nur bekannte Werte zu – aus gutem Grund: Eine Bedingung
mit Tippfehler passt auf niemanden, die Regel bleibt **stumm**, und auffallen würde
das erst, wenn die Beiträge eines Quartals fehlen.

Das Feld ist weg; ausgedrückt wird dasselbe über Bedingung und Ausnahme. Damit
wandert der Schutz auf die Funktions-Schlüssel – und wird wichtiger, denn an einem
davon (`passiv`) hängt jetzt die Beitragsfreiheit.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.api.beitraege import _bekannte_funktionen_or_422  # noqa: E402


def _db(*keys):
    return SimpleNamespace(funktionen=SimpleNamespace(list_keys=lambda: list(keys)))


def _daten(bedingung=(), ausnahme=()):
    return SimpleNamespace(bedingung_funktionen=list(bedingung),
                           ausnahme_funktionen=list(ausnahme))


def test_bekannte_schluessel_gehen_durch():
    _bekannte_funktionen_or_422(_db('passiv', 'uebungsleiter'),
                                _daten(bedingung=['uebungsleiter'], ausnahme=['passiv']))


def test_ohne_funktionen_ist_nichts_zu_pruefen():
    _bekannte_funktionen_or_422(_db(), _daten())


@pytest.mark.parametrize("bedingung,ausnahme", [
    (['uebungsleter'], []),          # Tippfehler in der Bedingung
    ([], ['pasiv']),                 # Tippfehler in der Ausnahme
    (['uebungsleiter'], ['pasiv']),  # eine von zweien falsch
])
def test_tippfehler_wird_abgewiesen(bedingung, ausnahme):
    with pytest.raises(HTTPException) as e:
        _bekannte_funktionen_or_422(_db('passiv', 'uebungsleiter'), _daten(bedingung, ausnahme))
    assert e.value.status_code == 422
    assert "Unbekannte Funktion" in e.value.detail


def test_meldung_nennt_alle_unbekannten_einmal():
    with pytest.raises(HTTPException) as e:
        _bekannte_funktionen_or_422(_db('passiv'), _daten(['a', 'b'], ['a']))
    assert "a, b" in e.value.detail
