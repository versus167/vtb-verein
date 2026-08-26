"""API der Termin-Erinnerungs-Einstellungen (backend/api/termine.py, #95-Nachgang).

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_termine_api_gaeste). Der Punkt
dieser Datei ist die Zuständigkeit: Die Zeile gilt vereinsweit, also entscheidet
hier ausnahmsweise NICHT die Kader-ACL, sondern das globale Recht – ein Betreuer
seiner Mannschaft darf sie nicht verstellen. Dazu die Grenzen des Schreib-Schemas.
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
from pydantic import ValidationError  # noqa: E402

from app.models.termin import TerminErinnerungEinstellungen  # noqa: E402
from backend.api import termine as api  # noqa: E402

_ADMIN = SimpleNamespace(role='admin', username='chef', id=1,
                         has_permission=lambda p: True)
_VERWALTER = SimpleNamespace(role='mitglied', username='orga', id=3,
                             has_permission=lambda p: p == 'termine.verwalten')
# Betreuer seiner Mannschaft: verwaltet deren Termine über die Kader-ACL, hat aber
# kein globales Recht – die vereinsweite Einstellung geht ihn nichts an.
_BETREUER = SimpleNamespace(role='mitglied', username='betreuer', id=7,
                            has_permission=lambda p: False)


def _db(calls=None, gespeichert=TerminErinnerungEinstellungen()):
    calls = calls if calls is not None else []

    def update(e, updated_by):
        calls.append((e, updated_by))
        return e

    return SimpleNamespace(
        termin_erinnerung_einstellungen=SimpleNamespace(
            get=lambda: gespeichert, update=update))


class TestZugriff:
    @pytest.mark.parametrize("user", [_ADMIN, _VERWALTER])
    def test_verwalter_und_admin_duerfen_lesen(self, user):
        assert api.erinnerung_einstellungen_lesen(user, _db())['erste_stufe_tage'] == 3

    def test_betreuer_ohne_globales_recht_darf_nicht(self):
        with pytest.raises(HTTPException) as e:
            api.erinnerung_einstellungen_lesen(_BETREUER, _db())
        assert e.value.status_code == 403

    def test_betreuer_darf_auch_nicht_speichern(self):
        with pytest.raises(HTTPException) as e:
            api.erinnerung_einstellungen_speichern(
                api.ErinnerungEinstellungenWrite(), _BETREUER, _db())
        assert e.value.status_code == 403


class TestSpeichern:
    def test_werte_gehen_mit_dem_benutzernamen_durch(self):
        calls = []
        daten = api.ErinnerungEinstellungenWrite(aktiv=False, erste_stufe_tage=5,
                                                 zweite_stufe_tage=2,
                                                 spieltag_aktiv=False)
        ergebnis = api.erinnerung_einstellungen_speichern(daten, _VERWALTER, _db(calls))
        (gespeichert, updated_by), = calls
        assert (gespeichert.aktiv, gespeichert.erste_stufe_tage,
                gespeichert.zweite_stufe_tage,
                gespeichert.spieltag_aktiv) == (False, 5, 2, False)
        assert updated_by == 'orga'
        assert ergebnis['zweite_stufe_tage'] == 2

    def test_vorgabe_ist_drei_und_ein_tag_plus_spieltag(self):
        daten = api.ErinnerungEinstellungenWrite()
        assert (daten.aktiv, daten.erste_stufe_tage, daten.zweite_stufe_tage,
                daten.spieltag_aktiv) == (True, 3, 1, True)


class TestGrenzen:
    def test_null_ist_erlaubt_und_schaltet_die_stufe_ab(self):
        assert api.ErinnerungEinstellungenWrite(zweite_stufe_tage=0).zweite_stufe_tage == 0

    def test_negativer_vorlauf_wird_abgelehnt(self):
        with pytest.raises(ValidationError):
            api.ErinnerungEinstellungenWrite(erste_stufe_tage=-1)

    def test_vorlauf_ueber_der_obergrenze_wird_abgelehnt(self):
        assert api.ErinnerungEinstellungenWrite(
            erste_stufe_tage=api.VORLAUF_MAX_TAGE).erste_stufe_tage == api.VORLAUF_MAX_TAGE
        with pytest.raises(ValidationError):
            api.ErinnerungEinstellungenWrite(erste_stufe_tage=api.VORLAUF_MAX_TAGE + 1)
