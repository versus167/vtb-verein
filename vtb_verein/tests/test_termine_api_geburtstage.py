"""Wer sieht die Geburtstage in der Terminliste (#192)?

Der Kern des Tickets: Geburtstage hängen NICHT an der Termin-ACL. Wer über
`termine.verwalten` alle Mannschafts-Tabs öffnen kann, aber kein
`personen.read` hat, bekommt dort keine Geburtsdaten zu sehen – nur in den
Mannschaften, in deren Kader er selbst steht.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_termine_api_gaeste); die
Datumslogik steckt in test_geburtstag_service, die Kader-Abfrage in
test_termine_integration.
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

from backend.api import termine as api  # noqa: E402

_EIGENE = [{"id": 5, "name": "Erste", "saison": "2026/27",
            "abteilung_name": "Fußball", "zugriff": 'lesen'}]

# Spieler der Mannschaft 5: keine globalen Rechte, aber im eigenen Kader.
_SPIELER = SimpleNamespace(role='mitglied', username='spieler', id=7,
                           has_permission=lambda p: False)
# Darf alle Termine verwalten, aber keine Personendaten lesen – der Fall aus #192.
_TERMINCHEF = SimpleNamespace(role='mitglied', username='chef', id=3,
                              has_permission=lambda p: p == 'termine.verwalten')
_TERMINCHEF_MIT_PERSONEN = SimpleNamespace(
    role='mitglied', username='chef2', id=4,
    has_permission=lambda p: p in ('termine.verwalten', 'personen.read'))
_ADMIN = SimpleNamespace(role='admin', username='admin', id=1,
                         has_permission=lambda p: True)


def _db(*, acl=None, eigene=(), kader=(), calls=None):
    """acl = Stufe aus der Kader-ACL ('lesen'/'verwalten'/None), kader = Rohdaten
    der Geburtstags-Abfrage. `calls` sammelt die abgefragten Mannschaften."""
    calls = calls if calls is not None else []

    def list_kader_geburtstage(ids, stichtag=None):
        calls.append(list(ids))
        # Wie das echte Repository: ohne Mannschaften gibt es nichts zu holen.
        return list(kader) if ids else []

    return SimpleNamespace(
        termine=SimpleNamespace(
            get_access_for_user=lambda uid, mid: acl,
            list_mannschaften_for_user=lambda uid: list(eigene),
            list_kader_geburtstage=list_kader_geburtstage,
        ),
    )


def _person(mid=11, geburtsdatum="1990-05-05"):
    return {"mitglied_id": mid, "vorname": "Max", "nachname": "Muster",
            "geburtsdatum": geburtsdatum, "mannschaft_name": "Erste"}


# --------------------------------------------------------------- Meine Termine
def test_meine_termine_liefert_die_eigenen_kader_mannschaften():
    calls = []
    db = _db(eigene=_EIGENE, kader=[_person()], calls=calls)
    ergebnis = api.geburtstage(_SPIELER, db, von="2026-01-01", bis="2026-12-31")
    assert calls == [[5]]
    assert [e['datum'] for e in ergebnis] == ["2026-05-05"]


def test_ohne_eigenen_kader_bleibt_die_liste_leer():
    """Reiner Verwalter ohne Mannschaft: „Meine Termine" hat keine Geburtstage."""
    calls = []
    db = _db(eigene=[], kader=[_person()], calls=calls)
    assert api.geburtstage(_TERMINCHEF, db) == []
    assert calls == [[]]


def test_termine_verwalten_erweitert_meine_termine_nicht():
    """`termine.verwalten` öffnet Tabs, macht aber keine fremde Mannschaft zur
    eigenen – „Meine Termine" bleibt beim eigenen Kader."""
    calls = []
    db = _db(eigene=_EIGENE, kader=[], calls=calls)
    api.geburtstage(_TERMINCHEF, db)
    assert calls == [[5]]


# ------------------------------------------------------------- Mannschafts-Tab
def test_eigener_kader_sieht_die_geburtstage_der_mannschaft():
    db = _db(acl='lesen', kader=[_person()])
    ergebnis = api.geburtstage(_SPIELER, db, von="2026-01-01", bis="2026-12-31",
                               mannschaft_id=5)
    assert len(ergebnis) == 1


def test_fremde_mannschaft_ohne_personen_read_bleibt_leer():
    """Der Fall aus #192: alle Termine sichtbar, aber keine Geburtsdaten."""
    calls = []
    db = _db(acl=None, kader=[_person()], calls=calls)
    assert api.geburtstage(_TERMINCHEF, db, mannschaft_id=9) == []
    # Gar nicht erst abgefragt – die Daten verlassen die DB nicht.
    assert calls == []


def test_fremde_mannschaft_mit_personen_read_ist_sichtbar():
    db = _db(acl=None, kader=[_person()])
    ergebnis = api.geburtstage(_TERMINCHEF_MIT_PERSONEN, db, von="2026-01-01",
                               bis="2026-12-31", mannschaft_id=9)
    assert len(ergebnis) == 1


def test_admin_sieht_alles():
    db = _db(acl=None, kader=[_person()])
    ergebnis = api.geburtstage(_ADMIN, db, von="2026-01-01", bis="2026-12-31",
                               mannschaft_id=9)
    assert len(ergebnis) == 1


def test_ohne_lesezugriff_auf_die_termine_gibt_es_403():
    """Erst die Termin-ACL, dann die Geburtstags-Frage: Wer die Mannschaft gar
    nicht sehen darf, soll ihre Existenz auch nicht abfragen können."""
    db = _db(acl=None)
    with pytest.raises(HTTPException) as e:
        api.geburtstage(_SPIELER, db, mannschaft_id=9)
    assert e.value.status_code == 403


# ------------------------------------------------------------------- Parameter
def test_ohne_von_beginnt_das_fenster_heute():
    db = _db(eigene=_EIGENE, kader=[_person(geburtsdatum="1990-05-05")])
    ergebnis = api.geburtstage(_SPIELER, db)
    assert ergebnis and ergebnis[0]['datum'] >= date.today().isoformat()


def test_kaputtes_datum_ist_ein_422():
    db = _db(eigene=_EIGENE)
    with pytest.raises(HTTPException) as e:
        api.geburtstage(_SPIELER, db, von="gestern")
    assert e.value.status_code == 422
