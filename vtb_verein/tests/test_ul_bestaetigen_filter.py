"""Status-Filter der Bestätigen-Sicht /ul-stunden/zu-bestaetigen (#180).

„Alle" drückt das Frontend dadurch aus, dass es `status_filter` **weglässt** —
genau wie bei den Nachbar-Endpunkten. Der Endpunkt hatte dafür aber einen
versteckten Default ('eingereicht') in der Signatur stehen: Auf „Alle" kam damit
stillschweigend wieder nur „Zu bestätigen", und waren die gerade alle bestätigt,
blieb die Liste leer — mit dem irreführenden Hinweis „Keine Abrechnungen in
diesem Status".

Der Zuschnitt dieser Sicht ist die Abteilungs-Beschränkung, nicht ein fester
Status. Beides wird hier getrennt festgehalten, damit der Default nicht wieder
unbemerkt zum Filter wird.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_ul_stunden_uebersicht).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from app.models.ul_stunden import (  # noqa: E402
    ULAbrechnung, STATUS_ENTWURF, STATUS_EINGEREICHT,
    STATUS_BESTAETIGT, STATUS_ABGELEHNT,
)
from backend.api.ul_stunden import (  # noqa: E402
    anzahl_zu_bestaetigen, list_zu_bestaetigen,
)


def _abr(id, status, abteilung_id=1):
    return ULAbrechnung(id=id, mitglied_id=id, abteilung_id=abteilung_id,
                        zeitraum_von='2026-06-01', zeitraum_bis='2026-06-30',
                        status=status, mitglied_nachname='M', mitglied_vorname='A')


class _User:
    def __init__(self, *perms, abteilungen=None):
        self._perms = set(perms)
        self._abteilungen = abteilungen

    def has_permission(self, p):
        return p in self._perms

    def allowed_abteilungen(self, _p):
        return self._abteilungen


class _AbrRepo:
    def __init__(self, abrechnungen):
        self._abr = list(abrechnungen)

    def list_for_abteilungen(self, abteilung_ids, status=None):
        return [a for a in self._abr
                if (not status or a.status == status)
                and (abteilung_ids is None or a.abteilung_id in abteilung_ids)]

    def count_for_abteilungen(self, abteilung_ids, status=None):
        return len(self.list_for_abteilungen(abteilung_ids, status))

    def list_stunden(self, abrechnung_id):
        return []


class _DB:
    def __init__(self, abrechnungen):
        self.ul_abrechnungen = _AbrRepo(abrechnungen)
        self.ul_saetze = SimpleNamespace(resolve=lambda *a, **k: None)


ALLE = [
    _abr(1, STATUS_ENTWURF), _abr(2, STATUS_EINGEREICHT),
    _abr(3, STATUS_BESTAETIGT), _abr(4, STATUS_ABGELEHNT),
]


def _verwalter():
    return _User(Permission.UL_STUNDEN_VERWALTEN)


# ------------------------------------------------------------------- „Alle"
def test_ohne_filter_kommen_alle_status():
    """Der Kern von #180: kein Filter heißt alle – nicht „eingereicht"."""
    rows = list_zu_bestaetigen(_verwalter(), _DB(ALLE))
    assert {r['id'] for r in rows} == {1, 2, 3, 4}


def test_alle_zeigt_auch_wenn_nichts_mehr_offen_ist():
    """Der gemeldete Fall: alles bestätigt, „Alle" gewählt – und die Liste blieb
    leer mit „Keine Abrechnungen in diesem Status"."""
    erledigt = [_abr(3, STATUS_BESTAETIGT), _abr(4, STATUS_ABGELEHNT)]
    rows = list_zu_bestaetigen(_verwalter(), _DB(erledigt))
    assert {r['id'] for r in rows} == {3, 4}


def test_leerer_filter_wirkt_wie_kein_filter():
    """Ältere Clients könnten `status_filter=` als leeren Wert schicken."""
    rows = list_zu_bestaetigen(_verwalter(), _DB(ALLE), status_filter='')
    assert {r['id'] for r in rows} == {1, 2, 3, 4}


# ----------------------------------------------------------- Einzelne Status
@pytest.mark.parametrize("status,erwartet", [
    (STATUS_ENTWURF, {1}),
    (STATUS_EINGEREICHT, {2}),
    (STATUS_BESTAETIGT, {3}),
    (STATUS_ABGELEHNT, {4}),
])
def test_einzelner_status_grenzt_ein(status, erwartet):
    rows = list_zu_bestaetigen(_verwalter(), _DB(ALLE), status_filter=status)
    assert {r['id'] for r in rows} == erwartet


# ------------------------------------------------------- Zuschnitt der Sicht
def test_abteilungs_scope_greift_weiterhin():
    """Was diese Sicht ausmacht, ist die Abteilungs-Beschränkung – die darf der
    gelockerte Default nicht mitgenommen haben."""
    daten = ALLE + [_abr(9, STATUS_EINGEREICHT, abteilung_id=2)]
    al = _User(Permission.UL_STUNDEN_BESTAETIGEN, abteilungen={1})
    rows = list_zu_bestaetigen(al, _DB(daten))
    assert {r['id'] for r in rows} == {1, 2, 3, 4}


def test_ohne_berechtigung_403():
    user = _User(Permission.UL_STUNDEN_ERFASSEN)   # nur eigene Erfassung
    with pytest.raises(HTTPException) as exc:
        list_zu_bestaetigen(user, _DB(ALLE))
    assert exc.value.status_code == 403


def test_aufgaben_zahl_bleibt_bei_den_offenen():
    """Die Zahl an Kachel und Nav meint ausdrücklich die zu bestätigenden – sie
    hing nie am Default und darf jetzt nicht mit „Alle" mitwachsen (#133)."""
    assert anzahl_zu_bestaetigen(_verwalter(), _DB(ALLE)) == 1
