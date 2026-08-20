"""API-Logik der Personenart 'gastspieler' (#95 Teil 2, backend/api/mitglieder.py).

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_termine_api_gaeste):
Gastspieler verbrauchen keine Mitgliedsnummer; das Eintrittsdatum ist auch für
sie Pflicht (Beginn der Gastspielgenehmigung, Ticket #29). Bei der Umwandlung
Gastspieler → Mitglied wird die Nummer nachgezogen. Die Datenbank-Seite deckt
test_gastspieler_integration ab.
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

from app.models.mitglied import Mitglied  # noqa: E402
from backend.api import mitglieder as api  # noqa: E402

# allowed_abteilungen gehört zum User-Vertrag, den die Scope-Prüfung der
# ID-Endpunkte abfragt; None = vereinsweit, also keine Einschränkung.
_ADMIN = SimpleNamespace(role='admin', username='chef', id=1,
                         has_permission=lambda p: True,
                         has_permission_global=lambda p: True,
                         allowed_abteilungen=lambda p: None)


def _db(existing: Mitglied | None = None, next_nummer: int = 42):
    calls = []

    def create(m, created_by):
        calls.append(('create', m))
        m.id = 7
        return m

    def update(m, updated_by):
        calls.append(('update', m))
        return True

    return SimpleNamespace(
        get_next_mitgliedsnummer=lambda: (calls.append(('next',)), next_nummer)[1],
        is_mitgliedsnummer_available=lambda n: True,
        get_mitglied=lambda mid: existing,
        create_mitglied=create,
        update_mitglied=update,
        calls=calls,
    )


def _gast_payload(**extra):
    return api.MitgliedCreate(vorname='GS', nachname='Gastl', art='gastspieler',
                              eintrittsdatum='2026-07-01', **extra)


# ---------------------------------------------------------------- Validierung
def test_art_nur_mitglied_oder_gastspieler():
    with pytest.raises(ValidationError):
        api.MitgliedCreate(vorname='a', nachname='b', art='ehrenmitglied')


def test_mitglied_braucht_eintrittsdatum():
    db = _db()
    data = api.MitgliedCreate(vorname='a', nachname='b')  # art default 'mitglied'
    with pytest.raises(HTTPException) as e:
        api.create_mitglied(data, _ADMIN, db)
    assert e.value.status_code == 422


def test_gastspieler_braucht_eintrittsdatum():
    """Auch Gastspieler brauchen ein Eintrittsdatum (Beginn der Genehmigung)."""
    db = _db()
    data = api.MitgliedCreate(vorname='GS', nachname='Gastl', art='gastspieler')
    with pytest.raises(HTTPException) as e:
        api.create_mitglied(data, _ADMIN, db)
    assert e.value.status_code == 422


# ------------------------------------------------------------------- Anlegen
def test_gastspieler_ohne_mitgliedsnummer():
    db = _db()
    result = api.create_mitglied(_gast_payload(), _ADMIN, db)
    assert result['art'] == 'gastspieler'
    assert result['mitgliedsnummer'] is None
    assert ('next',) not in db.calls          # keine Mitgliedsnummer verbraucht


def test_mitglied_bekommt_nummer():
    db = _db()
    data = api.MitgliedCreate(vorname='a', nachname='b', eintrittsdatum='2026-01-01')
    result = api.create_mitglied(data, _ADMIN, db)
    assert result['mitgliedsnummer'] == 42
    assert ('next',) in db.calls


# ---------------------------------------------------------------- Umwandlung
def test_umwandlung_gast_zu_mitglied_zieht_nummer_nach():
    bestand = Mitglied(id=7, mitgliedsnummer=None, vorname='GS', nachname='Gastl',
                       art='gastspieler')
    db = _db(existing=bestand)
    data = api.MitgliedCreate(vorname='GS', nachname='Gastl', art='mitglied',
                              eintrittsdatum='2026-07-01')
    api.update_mitglied(7, data, _ADMIN, db)
    updated = next(c[1] for c in db.calls if c[0] == 'update')
    assert updated.art == 'mitglied'
    assert updated.mitgliedsnummer == 42


def test_umwandlung_zu_mitglied_braucht_eintrittsdatum():
    bestand = Mitglied(id=7, mitgliedsnummer=None, vorname='GS', nachname='Gastl',
                       art='gastspieler')
    db = _db(existing=bestand)
    data = api.MitgliedCreate(vorname='GS', nachname='Gastl', art='mitglied')
    with pytest.raises(HTTPException) as e:
        api.update_mitglied(7, data, _ADMIN, db)
    assert e.value.status_code == 422


def test_gastspieler_update_behaelt_null_nummer():
    bestand = Mitglied(id=7, mitgliedsnummer=None, vorname='GS', nachname='Gastl',
                       art='gastspieler')
    db = _db(existing=bestand)
    api.update_mitglied(7, _gast_payload(ort='Birkenfeld'), _ADMIN, db)
    updated = next(c[1] for c in db.calls if c[0] == 'update')
    assert updated.mitgliedsnummer is None
    assert ('next',) not in db.calls


# --- Mitgliedsstatus (#173): nur noch die Form der Mitgliedschaft -----------

@pytest.mark.parametrize("wert", ['ausgetreten', 'inaktiv', 'irgendwas'])
def test_status_ausgetreten_wird_abgelehnt(wert):
    """Ausgetreten steht im Austrittsdatum – ein zweiter Ort dafür ginge auseinander."""
    with pytest.raises(ValidationError):
        api.MitgliedCreate(vorname='a', nachname='b', status=wert)


@pytest.mark.parametrize("wert", ['aktiv', 'passiv'])
def test_status_aktiv_und_passiv_bleiben(wert):
    assert api.MitgliedCreate(vorname='a', nachname='b', status=wert).status == wert


def test_austritt_ohne_statuswechsel_ist_zulaessig():
    """Der Normalfall nach der Umstellung: Datum gesetzt, Status bleibt 'aktiv'."""
    data = api.MitgliedCreate(vorname='a', nachname='b', eintrittsdatum='2020-01-01',
                              austrittsdatum='2026-06-30')
    assert data.status == 'aktiv' and data.austrittsdatum == '2026-06-30'
