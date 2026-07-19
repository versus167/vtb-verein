"""Self-Service-Kontakte im Profil (backend/api/mitglied_kontakte.py, /personen/mein-mitglied/*).

Stub-basiert nach dem Muster von test_gastspieler_api: direkte Endpunkt-Aufrufe mit
SimpleNamespace-DB. Autorisierung läuft über Eigentümerschaft (eigener Mitglied-Datensatz),
nicht über PERSONEN_*-Rechte. Die Primär-Regel selbst (SQL) deckt
test_mitglied_kontakte_integration ab; hier wird nur das Durchreichen als 422 geprüft.
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

from app.models.mitglied import Mitglied  # noqa: E402
from app.db.mitglied_kontakt_repository import (  # noqa: E402
    MitgliedKontakt, KontaktPrimaerRegelError,
)
from backend.api import mitglied_kontakte as api  # noqa: E402
from backend.api import personen as personen_api  # noqa: E402

_USER = SimpleNamespace(id=5, username='ich', role='mitglied',
                        has_permission=lambda p: False)


def _kontakt(**kw):
    base = dict(id=1, mitglied_id=11, typ='telefon', wert='0711 123', label=None,
                ist_primaer=True, version=1)
    base.update(kw)
    return MitgliedKontakt(**base)


def _db(mitglied=..., **overrides):
    if mitglied is ...:
        mitglied = Mitglied(id=11, vorname='V', nachname='S')
    ns = SimpleNamespace(
        get_mitglied_by_user_id=lambda uid: mitglied,
        list_mitglied_kontakte=lambda mid: [_kontakt()],
        get_mitglied_kontakt=lambda kid: _kontakt(),
        create_mitglied_kontakt=lambda *a, **k: _kontakt(),
        update_mitglied_kontakt=lambda *a, **k: True,
        mark_mitglied_kontakt_deleted=lambda *a, **k: True,
    )
    for key, val in overrides.items():
        setattr(ns, key, val)
    return ns


# ------------------------------------------------------------- Eigentümerschaft
def test_liste_ohne_mitglied_datensatz_404():
    with pytest.raises(HTTPException) as exc:
        api.list_meine_kontakte(_USER, _db(mitglied=None))
    assert exc.value.status_code == 404


def test_liste_liefert_eigene_kontakte():
    seen = []
    db = _db(list_mitglied_kontakte=lambda mid: (seen.append(mid), [_kontakt()])[1])
    result = api.list_meine_kontakte(_USER, db)
    assert seen == [11]
    assert result[0]['wert'] == '0711 123'


def test_update_fremder_kontakt_404():
    db = _db(get_mitglied_kontakt=lambda kid: _kontakt(mitglied_id=99))
    data = api.KontaktUpdate(typ='telefon', wert='x', ist_primaer=False, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        api.update_mein_kontakt(1, data, _USER, db)
    assert exc.value.status_code == 404


def test_delete_fremder_kontakt_404():
    db = _db(get_mitglied_kontakt=lambda kid: _kontakt(mitglied_id=99))
    with pytest.raises(HTTPException) as exc:
        api.delete_mein_kontakt(1, _USER, db)
    assert exc.value.status_code == 404


# ------------------------------------------------------------------ Validierung
def test_create_leerer_wert_422():
    data = api.KontaktWrite(typ='telefon', wert='   ')
    with pytest.raises(HTTPException) as exc:
        api.create_mein_kontakt(data, _USER, _db())
    assert exc.value.status_code == 422


def test_create_ungueltiger_typ_422():
    data = api.KontaktWrite(typ='brieftaube', wert='x')
    with pytest.raises(HTTPException) as exc:
        api.create_mein_kontakt(data, _USER, _db())
    assert exc.value.status_code == 422


def test_create_nutzt_eigene_mitglied_id():
    calls = []

    def create(mid, typ, wert, label, primaer, created_by):
        calls.append((mid, typ, wert, created_by))
        return _kontakt(typ=typ, wert=wert)

    db = _db(create_mitglied_kontakt=create)
    api.create_mein_kontakt(api.KontaktWrite(typ='mobil', wert=' 0170 1 '), _USER, db)
    assert calls == [(11, 'mobil', '0170 1', 'ich')]


# ------------------------------------------------------------ Primär-Regel → 422
def _raise_regel(*a, **k):
    raise KontaktPrimaerRegelError('Pro Typ muss ein Kontakt primär sein')


def test_update_primaer_regel_wird_422():
    db = _db(update_mitglied_kontakt=_raise_regel)
    data = api.KontaktUpdate(typ='telefon', wert='x', ist_primaer=False, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        api.update_mein_kontakt(1, data, _USER, db)
    assert exc.value.status_code == 422
    assert 'primär' in exc.value.detail


def test_delete_primaer_regel_wird_422():
    db = _db(mark_mitglied_kontakt_deleted=_raise_regel)
    with pytest.raises(HTTPException) as exc:
        api.delete_mein_kontakt(1, _USER, db)
    assert exc.value.status_code == 422


def test_update_versionskonflikt_409():
    db = _db(update_mitglied_kontakt=lambda *a, **k: False)
    data = api.KontaktUpdate(typ='telefon', wert='x', ist_primaer=True, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        api.update_mein_kontakt(1, data, _USER, db)
    assert exc.value.status_code == 409


# --------------------------------------------- mein-mitglied PUT: Einzug & Telefon
def _personen_db(mitglied):
    return SimpleNamespace(
        get_mitglied_by_user_id=lambda uid: mitglied,
        update_mitglied=lambda m, updated_by: True,
    )


def test_einzug_erlaubt_setzt_lastschrift():
    m = Mitglied(id=11, vorname='V', nachname='S', zahlungsart='sonstiges', version=3)
    data = personen_api.MeinMitgliedUpdate(einzug_erlaubt=True, expected_version=3)
    personen_api.update_mein_mitglied(data, _USER, _personen_db(m))
    assert m.zahlungsart == 'lastschrift'


def test_einzug_verboten_setzt_sonstiges():
    m = Mitglied(id=11, vorname='V', nachname='S', zahlungsart='lastschrift', version=3)
    data = personen_api.MeinMitgliedUpdate(einzug_erlaubt=False, expected_version=3)
    personen_api.update_mein_mitglied(data, _USER, _personen_db(m))
    assert m.zahlungsart == 'sonstiges'


def test_einzug_none_laesst_zahlungsart_unangetastet():
    m = Mitglied(id=11, vorname='V', nachname='S', zahlungsart='lastschrift', version=3)
    data = personen_api.MeinMitgliedUpdate(expected_version=3)
    personen_api.update_mein_mitglied(data, _USER, _personen_db(m))
    assert m.zahlungsart == 'lastschrift'


def test_telefon_laeuft_nicht_mehr_ueber_mein_mitglied():
    # Telefon wird über die Self-Service-Kontakte gepflegt; das alte Einzelfeld
    # existiert im Update-Schema nicht mehr (Payloads mit telefon werden ignoriert).
    assert 'telefon' not in personen_api.MeinMitgliedUpdate.model_fields
