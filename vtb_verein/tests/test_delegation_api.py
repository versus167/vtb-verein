"""Delegationsregel: Niemand vergibt weiter, was er selbst nicht hat.

Zwei Türen verändern die Rechte eines anderen Users: die individuellen Grants
(`PUT /users/{id}/permissions`) und die Funktionszuordnung
(`POST /mitglieder/{id}/funktionen`, denn eine Funktion gibt ihre Rechte an den
Träger weiter). Beide standen offen: `personen.write` genügte, um über eine
Funktion Rechte zu verteilen, die weit über den eigenen lagen.

Zwei Eigenschaften der Regel fallen dabei von selbst ab und werden hier
festgehalten, weil sie leicht wieder verlorengehen:
  * Admins bestehen sie ohne Sonderfall – sie haben jedes Recht.
  * Funktionen ohne hinterlegte Rechte bleiben frei zuordenbar – die leere Menge
    erfüllt die Bedingung. „Vorstand" oder „Kampfrichter" kostet also nichts.

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

from app.models.permission import Permission  # noqa: E402
from backend.core.authz import authorize_permission_delegation  # noqa: E402

FUSSBALL, HANDBALL = 1, 2


# --------------------------------------------------------------------- Stubs
def _user(global_rechte=(), scoped=None, role='mitglied'):
    scoped = scoped or {}
    return SimpleNamespace(
        id=7, username='bearbeiter', role=role, active=True,
        has_permission=lambda p: (role == 'admin' or p in global_rechte
                                  or p in scoped),
        has_permission_global=lambda p: role == 'admin' or p in global_rechte,
        has_permission_for_abteilung=lambda p, a: (
            role == 'admin' or p in global_rechte or a in scoped.get(p, set())),
        allowed_abteilungen=lambda p: None if role == 'admin' else set(scoped.get(p, set())),
    )


# ------------------------------------------------------------- Kernregel
def test_eigenes_recht_darf_weitergegeben_werden():
    authorize_permission_delegation(_user(global_rechte=(Permission.BEITRAEGE_READ,)),
                                    {Permission.BEITRAEGE_READ})


def test_fremdes_recht_ist_gesperrt():
    with pytest.raises(HTTPException) as e:
        authorize_permission_delegation(_user(global_rechte=(Permission.BEITRAEGE_READ,)),
                                        {Permission.KASSEN_VERWALTEN})
    assert e.value.status_code == 403


def test_fehlermeldung_nennt_die_fehlenden_rechte():
    """Ein „verboten" ohne Begründung führt zu Rätselraten; die Meldung muss
    sagen, an welchem Recht es liegt."""
    with pytest.raises(HTTPException) as e:
        authorize_permission_delegation(
            _user(global_rechte=(Permission.BEITRAEGE_READ,)),
            {Permission.KASSEN_VERWALTEN, Permission.SYSTEM_CONFIG})
    assert Permission.KASSEN_VERWALTEN in e.value.detail
    assert Permission.SYSTEM_CONFIG in e.value.detail
    assert Permission.BEITRAEGE_READ not in e.value.detail


def test_admin_besteht_ohne_sonderfall():
    authorize_permission_delegation(_user(role='admin'), set(Permission.all()))


def test_leere_rechtemenge_ist_immer_erlaubt():
    """Rein beschreibende Funktionen bleiben frei zuordenbar."""
    authorize_permission_delegation(_user(), set())


# ------------------------------------------------------------ Reichweite
def test_abteilungsrecht_wird_nicht_zum_vereinsweiten():
    """Der subtile Fall: Ein AL Fußball besitzt das Recht nur für Fußball. Ein
    individueller Grant wirkt vereinsweit – er würde also mehr weitergeben, als
    er selbst hat."""
    al = _user(scoped={Permission.UL_STUNDEN_BESTAETIGEN: {FUSSBALL}})
    with pytest.raises(HTTPException) as e:
        authorize_permission_delegation(al, {Permission.UL_STUNDEN_BESTAETIGEN})
    assert e.value.status_code == 403


def test_abteilungsrecht_darf_in_der_eigenen_abteilung_weitergegeben_werden():
    al = _user(scoped={Permission.UL_STUNDEN_BESTAETIGEN: {FUSSBALL}})
    authorize_permission_delegation(al, {Permission.UL_STUNDEN_BESTAETIGEN},
                                    abteilung_id=FUSSBALL)


def test_abteilungsrecht_greift_nicht_in_fremder_abteilung():
    al = _user(scoped={Permission.UL_STUNDEN_BESTAETIGEN: {FUSSBALL}})
    with pytest.raises(HTTPException) as e:
        authorize_permission_delegation(al, {Permission.UL_STUNDEN_BESTAETIGEN},
                                        abteilung_id=HANDBALL)
    assert e.value.status_code == 403


def test_vereinsweites_recht_deckt_jede_abteilung_ab():
    gs = _user(global_rechte=(Permission.UL_STUNDEN_BESTAETIGEN,))
    authorize_permission_delegation(gs, {Permission.UL_STUNDEN_BESTAETIGEN},
                                    abteilung_id=HANDBALL)


# ------------------------------------------- Tür 1: Funktionszuordnung
def _funktions_db(rechte_der_funktion, *, mitglied_in=(FUSSBALL,)):
    class _Cursor:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params):
            self._treffer = any(a in mitglied_in for a in params[1])
        def fetchone(self):
            return {'x': 1} if self._treffer else None

    return SimpleNamespace(
        conn=SimpleNamespace(cursor=lambda: _Cursor()),
        funktionen=SimpleNamespace(
            get_by_key=lambda k: SimpleNamespace(id=5, key=k),
            list_keys=lambda: ['uebungsleiter', 'kampfrichter'],
        ),
        funktion_permissions=SimpleNamespace(
            get_permissions_for_funktion=lambda fid: set(rechte_der_funktion)),
        get_mitglied=lambda mid: SimpleNamespace(
            id=mid, eintrittsdatum='2020-01-01', austrittsdatum=None),
    )


def test_funktion_mit_fremden_rechten_ist_nicht_zuordenbar():
    """Der Auslöser: Wer nur Stammdaten pflegen darf, konnte eine Funktion
    vergeben, die Rechte weit über seinen eigenen mitbringt."""
    from backend.api import mitglied_funktionen as api
    bearbeiter = _user(scoped={Permission.PERSONEN_WRITE: {FUSSBALL}})
    db = _funktions_db({Permission.KASSEN_VERWALTEN})
    daten = api.FunktionWrite(abteilung_id=FUSSBALL, funktion='uebungsleiter',
                              von='2026-01-01')
    with pytest.raises(HTTPException) as e:
        api.create_funktion(100, daten, bearbeiter, db)
    assert e.value.status_code == 403
    assert Permission.KASSEN_VERWALTEN in e.value.detail


def test_funktion_ohne_rechte_bleibt_frei_zuordenbar():
    """Der Preis der Regel soll nur dort anfallen, wo tatsächlich Rechte
    weitergereicht werden."""
    from backend.api import mitglied_funktionen as api
    bearbeiter = _user(scoped={Permission.PERSONEN_WRITE: {FUSSBALL}})
    db = _funktions_db(set())
    db.create_mitglied_funktion = lambda *a, **kw: _mf()
    daten = api.FunktionWrite(abteilung_id=FUSSBALL, funktion='kampfrichter',
                              von='2026-01-01')
    api.create_funktion(100, daten, bearbeiter, db)  # kein Fehler


def test_funktion_mit_eigenen_rechten_bleibt_zuordenbar():
    from backend.api import mitglied_funktionen as api
    bearbeiter = _user(scoped={Permission.PERSONEN_WRITE: {FUSSBALL},
                               Permission.UL_STUNDEN_ERFASSEN: {FUSSBALL}})
    db = _funktions_db({Permission.UL_STUNDEN_ERFASSEN})
    db.create_mitglied_funktion = lambda *a, **kw: _mf()
    daten = api.FunktionWrite(abteilung_id=FUSSBALL, funktion='uebungsleiter',
                              von='2026-01-01')
    api.create_funktion(100, daten, bearbeiter, db)  # kein Fehler


def _mf():
    from app.db.mitglied_funktion_repository import MitgliedFunktion
    return MitgliedFunktion(id=1, mitglied_id=100, abteilung_id=FUSSBALL,
                            funktion='uebungsleiter', von='2026-01-01')


# --------------------------------------------- Tür 2: individuelle Grants
def _users_db(bestehende_grants=()):
    from app.models.permission import EffectivePermissions
    return SimpleNamespace(
        get_user_by_id=lambda uid: SimpleNamespace(
            id=uid, username='ziel', email='ziel@example.org', role='mitglied',
            active=True, last_login=None, last_seen=None, version=1,
            password_hash='$2b$12$hash'),
        permissions=SimpleNamespace(
            get_overrides_for_user=lambda uid: {'grants': set(bestehende_grants),
                                                'denies': set()},
            set_overrides_for_user=lambda *a, **kw: None,
            set_permissions_for_user=lambda *a, **kw: None,
            # Wird nur für die Antwort gebraucht, nicht für die Prüfung.
            get_effective_permissions=lambda uid: EffectivePermissions(),
        ),
    )


def test_grant_oberhalb_der_eigenen_rechte_ist_gesperrt():
    from backend.api import users as api
    verwalter = _user(global_rechte=(Permission.PERSONEN_PERMISSIONS,))
    daten = api.PermissionsUpdate(grants=[Permission.KASSEN_VERWALTEN], denies=[])
    with pytest.raises(HTTPException) as e:
        api.set_permissions(9, daten, verwalter, _users_db())
    assert e.value.status_code == 403


def test_bestehender_grant_blockiert_das_speichern_nicht():
    """Der Endpunkt setzt die Grants als Ganzes. Geprüft wird nur, was
    hinzukommt – sonst wäre ein User mit einem höheren Recht für jeden
    Bearbeiter unspeicherbar, auch bei einer völlig anderen Änderung."""
    from backend.api import users as api
    verwalter = _user(global_rechte=(Permission.PERSONEN_PERMISSIONS,
                                     Permission.BEITRAEGE_READ))
    db = _users_db(bestehende_grants=[Permission.KASSEN_VERWALTEN])
    daten = api.PermissionsUpdate(
        grants=[Permission.KASSEN_VERWALTEN, Permission.BEITRAEGE_READ], denies=[])
    api.set_permissions(9, daten, verwalter, db)  # kein Fehler


def test_entziehen_bleibt_frei():
    """Denies fallen nicht unter die Regel: Wer Rechte entzieht, verschafft sich
    selbst keine."""
    from backend.api import users as api
    verwalter = _user(global_rechte=(Permission.PERSONEN_PERMISSIONS,))
    daten = api.PermissionsUpdate(grants=[], denies=[Permission.KASSEN_VERWALTEN])
    api.set_permissions(9, daten, verwalter, _users_db())  # kein Fehler
