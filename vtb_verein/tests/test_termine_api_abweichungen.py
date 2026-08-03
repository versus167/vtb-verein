"""API-Schicht der Termin-Abweichungen (backend/api/termine.py, #95 Etappe 4).

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_termine_api_gaeste): Geprüft
werden Zugriff (nur wer die Termine der Mannschaft verwaltet), die Vorbedingungen
der Entscheidung (offen, passende Version) und dass der Zähler fürs Badge an den
Termin-Dicts hängt. Die Fachlogik selbst deckt test_dfbnet_dry_run_integration ab.
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

from app.models.termin import Termin  # noqa: E402
from app.models.termin_abweichung import TerminAbweichung  # noqa: E402
from backend.api import termine as api  # noqa: E402

_TERMIN = Termin(id=1, mannschaft_id=5, serie_id=None, typ='spiel',
                 beginn='2026-08-15T15:00', ende=None, ort='Platz',
                 spielstaette_id=1, treffpunkt=None, treffpunkt_zeit=None,
                 gegner='SV Fremd', heim_auswaerts='heim', extern_ref='900000001',
                 extern_stand={'beginn': '2026-08-15T15:00'}, status='geplant',
                 beschreibung=None, version=3,
                 created_at='x', created_by='t', updated_at='x', updated_by='t')

_SPIELER = SimpleNamespace(role='mitglied', username='spieler', id=7,
                           has_permission=lambda p: False)
_BETREUER = SimpleNamespace(role='mitglied', username='betreuer', id=9,
                            has_permission=lambda p: False)


def _abweichung(status='offen', version=1, feld='beginn'):
    return TerminAbweichung(
        id=42, termin_id=_TERMIN.id, quelle='dfbnet', feld=feld,
        wert_app='2026-08-15T16:00', wert_extern='2026-08-15T17:30',
        spielstaette_id=None, erkannt_am='x', status=status,
        entschieden_von=None, entschieden_am=None, version=version,
        created_at='x', created_by='import', updated_at='x', updated_by='import')


def _db(abweichung=None, *, zugriff='verwalten', ergebnis=True, offen=None):
    return SimpleNamespace(
        termine=SimpleNamespace(
            get=lambda tid: _TERMIN,
            get_access_for_user=lambda uid, mid: zugriff,
        ),
        termin_abweichungen=SimpleNamespace(
            get=lambda aid: abweichung,
            list_for_termin=lambda tid, nur_offen=False: offen or [],
            counts_offen=lambda ids: {i: 2 for i in ids},
        ),
        entschieden=[],
    )


# --------------------------------------------------------------- Lese-Zugriff
def test_liste_nur_fuer_verwalter():
    db = _db(offen=[_abweichung()], zugriff='lesen')
    with pytest.raises(HTTPException) as e:
        api.list_abweichungen(_TERMIN.id, _SPIELER, db)
    assert e.value.status_code == 403


def test_liste_liefert_die_abweichungen():
    db = _db(offen=[_abweichung()])
    ergebnis = api.list_abweichungen(_TERMIN.id, _BETREUER, db)
    assert [a['feld'] for a in ergebnis] == ['beginn']


def test_badge_zaehler_haengt_am_termin():
    """Ohne den Zähler bliebe die offene Frage in der Terminliste unsichtbar."""
    termine = [{'id': 1}, {'id': 2}]
    api._enrich_abweichungen(_db(), termine)
    assert [t['abweichungen_offen'] for t in termine] == [2, 2]


# --------------------------------------------------------------- Entscheidung
def _daten(entscheidung='uebernommen', version=1, benachrichtigen=False):
    return api.AbweichungEntscheidung(entscheidung=entscheidung,
                                      expected_version=version,
                                      benachrichtigen=benachrichtigen)


def test_unbekannte_abweichung_404():
    with pytest.raises(HTTPException) as e:
        api.entscheide_abweichung(42, _daten(), _BETREUER, _db(None))
    assert e.value.status_code == 404


def test_entscheiden_nur_fuer_verwalter():
    db = _db(_abweichung(), zugriff='lesen')
    with pytest.raises(HTTPException) as e:
        api.entscheide_abweichung(42, _daten(), _SPIELER, db)
    assert e.value.status_code == 403


def test_ungueltige_entscheidung_422():
    with pytest.raises(HTTPException) as e:
        api.entscheide_abweichung(42, _daten('vielleicht'), _BETREUER,
                                  _db(_abweichung()))
    assert e.value.status_code == 422


def test_bereits_entschieden_422():
    db = _db(_abweichung(status='verworfen'))
    with pytest.raises(HTTPException) as e:
        api.entscheide_abweichung(42, _daten(), _BETREUER, db)
    assert e.value.status_code == 422


def test_veraltete_version_409():
    db = _db(_abweichung(version=2))
    with pytest.raises(HTTPException) as e:
        api.entscheide_abweichung(42, _daten(version=1), _BETREUER, db)
    assert e.value.status_code == 409


def test_entscheidung_geht_an_den_service(monkeypatch):
    db = _db(_abweichung())
    gerufen = {}

    def _fake(db_, abw, entscheidung, *, actor, notify=None):
        gerufen.update(entscheidung=entscheidung, actor=actor, notify=notify)
        return True

    monkeypatch.setattr(api.dfbnet, 'entscheiden', _fake)
    antwort = api.entscheide_abweichung(42, _daten(), _BETREUER, db)
    assert gerufen['entscheidung'] == 'uebernommen'
    assert gerufen['actor'] == 'betreuer'
    assert gerufen['notify'] is None            # ohne Opt-in kein Versand
    assert antwort['uebernommen'] is True


def test_benachrichtigung_nur_mit_flag(monkeypatch):
    db = _db(_abweichung())
    gerufen = {}

    def _fake(db_, abw, entscheidung, *, actor, notify=None):
        gerufen['notify'] = notify
        return True

    monkeypatch.setattr(api.dfbnet, 'entscheiden', _fake)
    api.entscheide_abweichung(42, _daten(benachrichtigen=True), _BETREUER, db)
    assert callable(gerufen['notify'])


def test_versionskonflikt_im_service_wird_durchgereicht(monkeypatch):
    db = _db(_abweichung())
    monkeypatch.setattr(api.dfbnet, 'entscheiden', lambda *a, **kw: False)
    with pytest.raises(HTTPException) as e:
        api.entscheide_abweichung(42, _daten(), _BETREUER, db)
    assert e.value.status_code == 409
