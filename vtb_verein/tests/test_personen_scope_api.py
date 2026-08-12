"""Stufe E gilt auch für ID-adressierte Endpunkte, nicht nur für Listen.

Bis hierher setzte der Abteilungs-Scope nur die Personen-/Mitgliederliste durch
(`visible_mitglied_ids`). Ein Abteilungsleiter mit abteilungsgebundenem
`personen.read` sah die Liste zwar gefiltert, konnte die übersprungenen
Datensätze aber weiterhin einzeln über ihre ID abrufen und ändern — inklusive
Änderungshistorie (Adresse, Geburtsdatum, IBAN über alle Versionen). Die
Filterung war damit Kosmetik.

Geprüft wird beides: dass der scoped Bearbeiter im eigenen Bereich weiterarbeiten
kann und außerhalb 403 bekommt — und dass für vereinsweit Berechtigte nichts
enger wird (kein Regress).

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_tresor_api).
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

from app.db.mitglied_funktion_repository import MitgliedFunktion  # noqa: E402
from app.models.permission import Permission  # noqa: E402
from backend.core.scope import (  # noqa: E402
    darf_mitglied, require_abteilung, require_mitglied, require_person,
)

FUSSBALL, HANDBALL = 1, 2


# --------------------------------------------------------------------- Stubs
def _scoped_user(abteilungen=(FUSSBALL,), rechte=(Permission.PERSONEN_READ,
                                                  Permission.PERSONEN_WRITE,
                                                  Permission.PERSONEN_DELETE)):
    """Abteilungsleiter: Rechte ausschließlich abteilungsgebunden geerbt."""
    scoped = {p: set(abteilungen) for p in rechte}
    return SimpleNamespace(
        id=7, username='al_fussball', role='mitglied', active=True,
        has_permission=lambda p: p in rechte,          # lenient, wie im Original
        has_permission_global=lambda p: False,
        has_permission_for_abteilung=lambda p, a: a in scoped.get(p, set()),
        allowed_abteilungen=lambda p: set(scoped[p]) if p in scoped else set(),
    )


def _globaler_user():
    """Geschäftsstelle: Rechte vereinsweit – allowed_abteilungen liefert None."""
    return SimpleNamespace(
        id=8, username='geschaeftsstelle', role='mitglied', active=True,
        has_permission=lambda p: True,
        has_permission_global=lambda p: True,
        has_permission_for_abteilung=lambda p, a: True,
        allowed_abteilungen=lambda p: None,
    )


class _Cursor:
    """Minimal-Cursor: beantwortet die EXISTS-Abfrage aus darf_mitglied."""

    def __init__(self, zuordnungen):
        self._zuordnungen = zuordnungen
        self._treffer = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        mitglied_id, abteilungen = params
        self._treffer = any(
            (mitglied_id, a) in self._zuordnungen for a in abteilungen
        )

    def fetchone(self):
        return {'?column?': 1} if self._treffer else None


def _db(zuordnungen=((100, FUSSBALL), (200, HANDBALL)), user_zu_mitglied=None):
    """zuordnungen: Menge von (mitglied_id, abteilung_id)."""
    zuordnungen = set(zuordnungen)
    abbildung = user_zu_mitglied if user_zu_mitglied is not None else {10: 100, 20: 200}
    return SimpleNamespace(
        conn=SimpleNamespace(cursor=lambda: _Cursor(zuordnungen)),
        get_mitglied_by_user_id=lambda uid: (
            SimpleNamespace(id=abbildung[uid]) if uid in abbildung else None),
    )


# ------------------------------------------------------- darf_mitglied (Kern)
def test_eigene_abteilung_ist_erlaubt():
    assert darf_mitglied(_scoped_user(), _db(), 100) is True


def test_fremde_abteilung_ist_gesperrt():
    assert darf_mitglied(_scoped_user(), _db(), 200) is False


def test_vereinsweites_recht_bleibt_unbeschraenkt():
    """Kein Regress: Wer das Recht global hat, sieht weiterhin alles."""
    assert darf_mitglied(_globaler_user(), _db(), 200) is True


def test_ohne_jede_abteilung_ist_nichts_erlaubt():
    leer = _scoped_user(abteilungen=())
    assert darf_mitglied(leer, _db(), 100) is False


def test_scope_gilt_je_recht_einzeln():
    """Lesen für Fußball heißt nicht Löschen für Fußball."""
    nur_lesen = _scoped_user(rechte=(Permission.PERSONEN_READ,))
    assert darf_mitglied(nur_lesen, _db(), 100, Permission.PERSONEN_READ) is True
    assert darf_mitglied(nur_lesen, _db(), 100, Permission.PERSONEN_DELETE) is False


# ------------------------------------------------------------ require_mitglied
def test_require_mitglied_wirft_403_ausserhalb():
    with pytest.raises(HTTPException) as e:
        require_mitglied(_scoped_user(), _db(), 200)
    assert e.value.status_code == 403


def test_require_mitglied_laesst_eigenen_bereich_durch():
    require_mitglied(_scoped_user(), _db(), 100)  # kein Fehler


# -------------------------------------------------------------- require_person
def test_require_person_loest_ueber_die_user_id_auf():
    require_person(_scoped_user(), _db(), 10)  # user 10 → mitglied 100 (Fußball)
    with pytest.raises(HTTPException) as e:
        require_person(_scoped_user(), _db(), 20)  # user 20 → mitglied 200
    assert e.value.status_code == 403


def test_konto_ohne_mitglied_ist_fuer_scoped_bearbeiter_tabu():
    """Ein reines Benutzerkonto hat keine Abteilung – die Personenliste blendet es
    für scoped Leser aus, die ID-Endpunkte müssen dasselbe tun."""
    db = _db(user_zu_mitglied={})
    with pytest.raises(HTTPException) as e:
        require_person(_scoped_user(), db, 99)
    assert e.value.status_code == 403


def test_konto_ohne_mitglied_bleibt_fuer_vereinsweite_offen():
    require_person(_globaler_user(), _db(user_zu_mitglied={}), 99)  # kein Fehler


# ----------------------------------------------------------- require_abteilung
def test_zuordnung_in_die_eigene_abteilung_ist_erlaubt():
    require_abteilung(_scoped_user(), FUSSBALL, Permission.PERSONEN_WRITE)


def test_zuordnung_in_eine_fremde_abteilung_ist_gesperrt():
    with pytest.raises(HTTPException) as e:
        require_abteilung(_scoped_user(), HANDBALL, Permission.PERSONEN_WRITE)
    assert e.value.status_code == 403


def test_zuordnung_prueft_die_abteilung_nicht_das_mitglied():
    """Der Grund für die eigene Prüfung: Ein Neuzugang hängt an keiner Abteilung
    und wäre über require_mitglied für jeden Abteilungsleiter unerreichbar —
    auch für den, der ihn gerade aufnehmen soll."""
    al = _scoped_user()
    neuzugang = 300  # noch keine einzige Zuordnung
    assert darf_mitglied(al, _db(), neuzugang) is False
    require_abteilung(al, FUSSBALL, Permission.PERSONEN_WRITE)  # trotzdem erlaubt


def test_vereinsweite_zuordnung_verlangt_das_vereinsweite_recht():
    """abteilung_id=None heißt „gilt im ganzen Verein" – das darf ein
    abteilungsgebundener Bearbeiter nicht vergeben."""
    with pytest.raises(HTTPException) as e:
        require_abteilung(_scoped_user(), None, Permission.PERSONEN_WRITE)
    assert e.value.status_code == 403
    require_abteilung(_globaler_user(), None, Permission.PERSONEN_WRITE)  # kein Fehler


# ------------------------------------------- Scope-Ausbruch über Funktionen
def test_funktion_fuer_fremde_abteilung_ist_gesperrt():
    """Der gefährlichste Fall: Funktionsrechte tragen den Abteilungs-Scope. Wer
    sich selbst „Abteilungsleiter Handball" eintragen könnte, hätte Handball beim
    nächsten Request im Scope – der Scope wäre dann selbst-erweiterbar."""
    from backend.api import mitglied_funktionen as api
    al = _scoped_user()
    daten = api.FunktionWrite(abteilung_id=HANDBALL, funktion='abteilungsleiter',
                              von='2026-01-01')
    with pytest.raises(HTTPException) as e:
        api.create_funktion(100, daten, al, _db())   # 100 = eigenes Mitglied
    assert e.value.status_code == 403


def test_funktion_fuer_die_eigene_abteilung_bleibt_moeglich():
    from backend.api import mitglied_funktionen as api
    db = _db()
    db.funktionen = SimpleNamespace(list_keys=lambda: ['uebungsleiter'])
    db.create_mitglied_funktion = lambda *a, **kw: MitgliedFunktion(
        id=1, mitglied_id=100, abteilung_id=FUSSBALL, funktion='uebungsleiter',
        von='2026-01-01')
    daten = api.FunktionWrite(abteilung_id=FUSSBALL, funktion='uebungsleiter',
                              von='2026-01-01')
    # zuordnungsbeginn_or_400 braucht das Mitglied für die Eintrittsdatum-Prüfung
    db.get_mitglied = lambda mid: SimpleNamespace(id=mid, eintrittsdatum='2020-01-01',
                                                  austrittsdatum=None)
    api.create_funktion(100, daten, al := _scoped_user(), db)
    assert al is not None  # Aufruf lief ohne 403 durch


# ------------------------------------------------------------- Endpunkt-Ebene
def test_history_endpunkt_setzt_den_scope_durch():
    """Der teuerste Einzelfund: Die Historie trägt Adresse, Geburtsdatum und
    IBAN über alle Versionen."""
    from backend.api import personen as api
    with pytest.raises(HTTPException) as e:
        api.get_person_history(20, _scoped_user(), _db())
    assert e.value.status_code == 403


def test_mitglied_detail_endpunkt_setzt_den_scope_durch():
    from backend.api import mitglieder as api
    with pytest.raises(HTTPException) as e:
        api.get_mitglied(200, _scoped_user(), _db())
    assert e.value.status_code == 403


def test_kontakte_endpunkt_setzt_den_scope_durch():
    from backend.api import mitglied_kontakte as api
    with pytest.raises(HTTPException) as e:
        api.list_kontakte(200, _scoped_user(), _db())
    assert e.value.status_code == 403


# ------------------------------------------------------------- Regressionen
def test_jeder_id_endpunkt_der_personen_router_traegt_eine_scope_wache():
    """Wächter gegen den Rückfall: Ein neu ergänzter ID-Endpunkt ohne Scope-Prüfung
    reißt die Lücke wieder auf, und zwar unauffällig."""
    import re
    basis = _ROOT / 'backend' / 'api'
    ohne = []
    for name in ('personen.py', 'mitglieder.py', 'mitglied_kontakte.py',
                 'mitglied_abteilungen.py', 'mitglied_funktionen.py'):
        for teil in re.split(r'\n(?=@router\.)', (basis / name).read_text()):
            m = re.match(r'@router\.(get|post|put|patch|delete)\("([^"]*)"', teil)
            if not m or not re.search(r'\{(user_id|mitglied_id)\}', m.group(2)):
                continue
            if not re.search(r'require_mitglied|require_person|require_abteilung'
                             r'|_require_freischalt_zugriff', teil):
                ohne.append(f"{name}: {m.group(1).upper()} {m.group(2)}")
    assert ohne == []
