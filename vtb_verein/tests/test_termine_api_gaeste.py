"""API-Zugriffslogik der Termin-Gäste (backend/api/termine.py).

Direkte Endpunkt-/Helper-Aufrufe mit Stubs (Muster wie
test_termine_api_benachrichtigung): Gäste (aktive Zusage ohne Kader) erhalten
Lese- und Selbst-Antwort-Zugriff auf genau ihren Termin; Verwalter dürfen
neben dem Kader auch Abteilungs-Mitglieder (Gast) eintragen, Fremde nur mit dem
Recht `termine.gaeste_vereinsweit`. Ebenfalls hier: das Einladen (Zeile ohne
Antwort) als eigener Weg neben dem Eintragen.
Die Datenbank-Seite deckt test_termin_gaeste_integration ab.
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
from app.models.termin_zusage import TerminZusage  # noqa: E402
from backend.api import termine as api  # noqa: E402

_TERMIN = Termin(id=1, mannschaft_id=5, serie_id=None, typ='training',
                 beginn='2026-07-22T18:30', ende=None, ort=None,
                 spielstaette_id=1, treffpunkt=None,
                 treffpunkt_zeit=None, gegner=None, heim_auswaerts=None,
                 extern_ref=None, extern_stand=None, status='geplant',
                 beschreibung=None, version=1,
                 created_at='x', created_by='t', updated_at='x', updated_by='t')

_SPIELER = SimpleNamespace(role='mitglied', username='gast', id=7,
                           has_permission=lambda p: False)
_ADMIN = SimpleNamespace(role='admin', username='chef', id=1,
                         has_permission=lambda p: True)
# Verwalter der Mannschaft ohne vereinsweites Gäste-Recht: darf den Termin
# verwalten, aber nur aus der eigenen Abteilung einladen.
_VERWALTER = SimpleNamespace(role='mitglied', username='betreuer', id=3,
                             has_permission=lambda p: p == 'termine.verwalten')


def _zusage(termin_id, mitglied_id, antwort, kommentar):
    return TerminZusage(id=1, termin_id=termin_id, mitglied_id=mitglied_id,
                        antwort=antwort, kommentar=kommentar, version=1,
                        created_at='x', created_by='t', updated_at='x', updated_by='t')


def _db(*, acl=None, kader_mitglied=None, mitglied=None, hat_zusage=False,
        in_kader=False, in_abteilung=False, calls=None, kennt_mitglied=True,
        schon_dabei=()):
    calls = calls if calls is not None else []

    def get_mitglied(mid):
        if not kennt_mitglied:
            raise KeyError(mid)
        return SimpleNamespace(id=mid, user_id=None)

    def lade_ein(tid, mid, von):
        calls.append(('einladen', tid, mid))
        return mid not in schon_dabei
    return SimpleNamespace(
        termine=SimpleNamespace(
            get=lambda tid: _TERMIN,
            get_access_for_user=lambda uid, mid: acl,
            get_kader_mitglied_id=lambda uid, mid, tag=None: kader_mitglied,
            is_mitglied_in_kader=lambda mid, man, tag=None: in_kader,
            is_mitglied_in_abteilung=lambda mid, man, tag=None: in_abteilung,
        ),
        termin_zusagen=SimpleNamespace(
            has_active_zusage=lambda tid, uid: hat_zusage,
            set_antwort=lambda tid, mid, antwort, kommentar, von:
                (calls.append((tid, mid, antwort)), _zusage(tid, mid, antwort, kommentar))[1],
            remove_antwort=lambda tid, mid, von: calls.append(('remove', tid, mid)),
            lade_ein=lade_ein,
        ),
        get_mitglied=get_mitglied,
        get_mitglied_by_user_id=lambda uid: mitglied,
        calls=calls,
    )


# ------------------------------------------------------------ Lese-Zugriff
def test_require_lesen_termin_gast_mit_zusage():
    db = _db(acl=None, hat_zusage=True)
    assert api._require_lesen_termin(db, _SPIELER, _TERMIN) == 'lesen'


def test_require_lesen_termin_fremder_403():
    db = _db(acl=None, hat_zusage=False)
    with pytest.raises(HTTPException) as e:
        api._require_lesen_termin(db, _SPIELER, _TERMIN)
    assert e.value.status_code == 403


def test_require_lesen_termin_kader_hat_vorrang():
    db = _db(acl='verwalten', hat_zusage=False)
    assert api._require_lesen_termin(db, _SPIELER, _TERMIN) == 'verwalten'


# ------------------------------------------------------- eigene Zu-/Absage
def test_gast_darf_eigene_antwort_aendern():
    db = _db(acl=None, kader_mitglied=None, hat_zusage=True,
             mitglied=SimpleNamespace(id=42))
    z = api.set_eigene_zusage(_TERMIN.id, api.ZusageSet(antwort='ab', kommentar='verletzt'),
                              _SPIELER, db)
    assert db.calls == [(_TERMIN.id, 42, 'ab')]
    assert z['mitglied_id'] == 42


def test_ohne_einladung_keine_eigene_antwort():
    db = _db(acl=None, kader_mitglied=None, hat_zusage=False,
             mitglied=SimpleNamespace(id=42))
    with pytest.raises(HTTPException) as e:
        api.set_eigene_zusage(_TERMIN.id, api.ZusageSet(antwort='zu'), _SPIELER, db)
    assert e.value.status_code == 403


def test_gast_darf_zuruecknehmen():
    db = _db(acl=None, kader_mitglied=None, hat_zusage=True,
             mitglied=SimpleNamespace(id=42))
    api.remove_eigene_zusage(_TERMIN.id, _SPIELER, db)
    assert db.calls == [('remove', _TERMIN.id, 42)]


# ------------------------------------------------- Eintragen durch Verwalter
def test_verwalter_traegt_abteilungs_gast_ein():
    db = _db(in_kader=False, in_abteilung=True)
    z = api.set_fremde_zusage(_TERMIN.id, 42, api.ZusageSet(antwort='zu'), _VERWALTER, db)
    assert db.calls == [(_TERMIN.id, 42, 'zu')]
    assert z['antwort'] == 'zu'


def test_verwalter_kann_keine_fremden_eintragen():
    db = _db(in_kader=False, in_abteilung=False)
    with pytest.raises(HTTPException) as e:
        api.set_fremde_zusage(_TERMIN.id, 42, api.ZusageSet(antwort='zu'), _VERWALTER, db)
    assert e.value.status_code == 422


# ------------------------------------------- vereinsweite Gäste (Ad-hoc-Recht)

def test_vereinsweites_recht_traegt_abteilungsfremde_ein():
    """Mit `termine.gaeste_vereinsweit` fällt die Abteilungsgrenze – der Admin
    steht hier stellvertretend für jeden, der das Recht hat."""
    db = _db(in_kader=False, in_abteilung=False)
    api.set_fremde_zusage(_TERMIN.id, 42, api.ZusageSet(antwort='zu'), _ADMIN, db)
    assert db.calls == [(_TERMIN.id, 42, 'zu')]


def test_vereinsweites_recht_braucht_trotzdem_ein_mitglied():
    db = _db(in_kader=False, in_abteilung=False, kennt_mitglied=False)
    with pytest.raises(HTTPException) as e:
        api.set_fremde_zusage(_TERMIN.id, 42, api.ZusageSet(antwort='zu'), _ADMIN, db)
    assert e.value.status_code == 422


def test_kandidaten_ohne_recht_bleiben_in_der_abteilung():
    gefragt = {}
    db = _db(acl='verwalten')
    db.termine.list_gast_kandidaten = lambda man, tag, vereinsweit=False: (
        gefragt.update(vereinsweit=vereinsweit) or [])
    antwort = api.gast_kandidaten(_TERMIN.id, _VERWALTER, db)
    assert gefragt == {'vereinsweit': False}
    assert antwort['vereinsweit'] is False


def test_kandidaten_mit_recht_gehen_vereinsweit():
    gefragt = {}
    db = _db()
    db.termine.list_gast_kandidaten = lambda man, tag, vereinsweit=False: (
        gefragt.update(vereinsweit=vereinsweit) or [])
    antwort = api.gast_kandidaten(_TERMIN.id, _ADMIN, db)
    assert gefragt == {'vereinsweit': True}
    assert antwort['vereinsweit'] is True


# --------------------------------------------------------------- Einladen

def test_einladen_legt_zeilen_ohne_antwort_an(monkeypatch):
    """Einladen heißt NICHT zusagen: es entsteht nur die Zeile, die Antwort
    holt sich der Eingeladene selbst."""
    gemeldet = {}
    monkeypatch.setattr(api.terminmeldung, 'notify_einladung',
                        lambda db, t, ids, actor: gemeldet.update(ids=ids))
    db = _db(in_kader=False, in_abteilung=True)
    antwort = api.lade_gaeste_ein(_TERMIN.id, api.EinladungCreate(mitglied_ids=[42, 43]),
                                  _VERWALTER, db)
    assert antwort == {"eingeladen": 2, "schon_dabei": 0}
    assert db.calls == [('einladen', _TERMIN.id, 42), ('einladen', _TERMIN.id, 43)]
    assert gemeldet['ids'] == [42, 43]


def test_einladen_meldet_nur_die_neuen(monkeypatch):
    """Wer schon geantwortet hat, wird nicht zurückgesetzt und nicht erneut behelligt."""
    gemeldet = {}
    monkeypatch.setattr(api.terminmeldung, 'notify_einladung',
                        lambda db, t, ids, actor: gemeldet.update(ids=ids))
    db = _db(in_kader=False, in_abteilung=True, schon_dabei={42})
    antwort = api.lade_gaeste_ein(_TERMIN.id, api.EinladungCreate(mitglied_ids=[42, 43]),
                                  _VERWALTER, db)
    assert antwort == {"eingeladen": 1, "schon_dabei": 1}
    assert gemeldet['ids'] == [43]


def test_einladen_ohne_benachrichtigung(monkeypatch):
    monkeypatch.setattr(api.terminmeldung, 'notify_einladung',
                        lambda *a, **k: pytest.fail("darf nicht melden"))
    db = _db(in_kader=False, in_abteilung=True)
    api.lade_gaeste_ein(_TERMIN.id,
                        api.EinladungCreate(mitglied_ids=[42], benachrichtigen=False),
                        _VERWALTER, db)


def test_einladen_haelt_sich_an_die_abteilungsgrenze():
    db = _db(in_kader=False, in_abteilung=False)
    with pytest.raises(HTTPException) as e:
        api.lade_gaeste_ein(_TERMIN.id, api.EinladungCreate(mitglied_ids=[42]),
                            _VERWALTER, db)
    assert e.value.status_code == 422
