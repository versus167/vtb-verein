"""Belegungsplan der eigenen Plätze (#152, backend/api/spielstaetten.py).

Drei Fragen, die der Endpoint beantwortet und die man leicht falsch baut:

* **Wer darf?** `spielstaetten.belegung` ist das gemeinte Recht. Wer die Plätze pflegt
  oder alle Termine verwaltet, sieht denselben Plan, ohne dass ihm jemand ein zweites
  Recht zuteilen müsste. Alle anderen bekommen 403 — auch Kader-Mitglieder, die ihre
  eigenen Termine sehr wohl sehen dürfen.
* **Was kommt zurück?** Plätze UND Termine getrennt: Ein Platz ohne Belegung ist die
  Information, auf die ein Platzwart wartet.
* **Wie groß darf das Fenster sein?** Begrenzt, damit ein aufgeklapptes Jahr nicht
  Tausende Zeilen an eine Wochenansicht liefert.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_gastspieler_api).
"""
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from backend.api import spielstaetten as api  # noqa: E402


def _user(*perms, role='mitglied'):
    keys = set(perms)
    return SimpleNamespace(
        id=1, username='platzwart', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in keys,
    )


@dataclass
class _Platz:
    id: int = 1
    name: str = 'Platz 1'
    ist_eigen: bool = True
    parallel_moeglich: int = 1
    untergrund: str = 'Rasen'


@dataclass
class _Termin:
    id: int = 7
    spielstaette_id: int = 1
    beginn: str = '2026-09-09T18:00'
    ende: str = '2026-09-09T19:30'
    typ: str = 'training'
    status: str = 'geplant'
    mannschaft_name: str = 'Erste'


class _DB:
    def __init__(self, plaetze=None, termine=None):
        self.gefragt = None
        self.spielstaetten = SimpleNamespace(list_eigene=lambda: plaetze or [_Platz()])
        self.termine = SimpleNamespace(belegung=self._belegung)
        self._termine = termine if termine is not None else [_Termin()]

    def _belegung(self, von, bis):
        self.gefragt = (von, bis)
        return self._termine


WOCHE = {"von": "2026-09-07", "bis": "2026-09-13"}


class TestWerDarf:

    def test_eigenes_recht_genuegt(self):
        antwort = api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), _DB(), **WOCHE)
        assert len(antwort["plaetze"]) == 1

    @pytest.mark.parametrize("recht", [Permission.SPIELSTAETTEN_VERWALTEN,
                                       Permission.TERMINE_VERWALTEN])
    def test_die_beiden_obermengen_sehen_denselben_plan(self, recht):
        """Wer die Plätze pflegt oder alle Termine verwaltet, braucht kein zweites
        Recht — sonst wäre der Belegungsplan Verwaltungsarbeit ohne Erkenntnisgewinn."""
        antwort = api.belegung(_user(recht), _DB(), **WOCHE)
        assert len(antwort["termine"]) == 1

    def test_ohne_recht_403(self):
        """Auch ein Kader-Mitglied kommt hier nicht rein: Es sieht die Termine SEINER
        Mannschaft über die ACL, nicht die aller anderen."""
        with pytest.raises(HTTPException) as e:
            api.belegung(_user(), _DB(), **WOCHE)
        assert e.value.status_code == 403

    def test_admin_darf(self):
        assert api.belegung(_user(role='admin'), _DB(), **WOCHE)["plaetze"]


class TestAntwort:

    def test_platz_ohne_belegung_bleibt_in_der_antwort(self):
        """Der eigentliche Zweck der getrennten Listen: Die freie Zeile ist die
        Aussage. Käme der Platz nur über seine Termine mit, verschwände er genau
        dann, wenn er interessant wird."""
        antwort = api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG),
                               _DB(termine=[]), **WOCHE)
        assert [p["name"] for p in antwort["plaetze"]] == ["Platz 1"]
        assert antwort["termine"] == []

    def test_kapazitaet_steht_am_platz(self):
        """`parallel_moeglich` entscheidet, ob eine Überschneidung ein Konflikt ist
        oder ein geteiltes Kleinfeld — ohne den Wert könnte die Ansicht das nicht
        unterscheiden."""
        antwort = api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG),
                               _DB(plaetze=[_Platz(parallel_moeglich=2)]), **WOCHE)
        assert antwort["plaetze"][0]["parallel_moeglich"] == 2

    def test_fenster_wird_durchgereicht(self):
        db = _DB()
        antwort = api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), db, **WOCHE)
        assert db.gefragt == ("2026-09-07", "2026-09-13")
        assert (antwort["von"], antwort["bis"]) == ("2026-09-07", "2026-09-13")


class TestFenster:

    def test_kaputtes_datum_422(self):
        with pytest.raises(HTTPException) as e:
            api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), _DB(),
                         von="09.09.2026", bis="2026-09-13")
        assert e.value.status_code == 422

    def test_bis_vor_von_422(self):
        with pytest.raises(HTTPException) as e:
            api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), _DB(),
                         von="2026-09-13", bis="2026-09-07")
        assert e.value.status_code == 422

    def test_zu_grosses_fenster_422(self):
        """Kein Schutz vor Angreifern — das Recht hat man oder nicht —, sondern vor
        dem Versehen, ein ganzes Jahr an eine Wochenansicht zu liefern."""
        with pytest.raises(HTTPException) as e:
            api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), _DB(),
                         von="2026-01-01", bis="2026-12-31")
        assert e.value.status_code == 422

    def test_groesstes_erlaubtes_fenster_geht_noch(self):
        """Die Grenze ist inklusiv — ein Off-by-one hier wäre unsichtbar, bis jemand
        genau zwei Monate aufklappt."""
        db = _DB()
        api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), db,
                     von="2026-01-01", bis="2026-03-03")   # 62 Tage
        assert db.gefragt == ("2026-01-01", "2026-03-03")

    def test_ein_tag_geht(self):
        db = _DB()
        api.belegung(_user(Permission.SPIELSTAETTEN_BELEGUNG), db,
                     von="2026-09-09", bis="2026-09-09")
        assert db.gefragt == ("2026-09-09", "2026-09-09")
