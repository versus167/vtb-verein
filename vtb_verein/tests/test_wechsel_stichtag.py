"""Stichtagsregeln des Wechsels (Abteilungs-Zuordnung und Funktion).

Ein Wechsel schneidet eine laufende Zuordnung: Die alte Zeile endet am Vortag, ab
dem Stichtag gilt die neue. Das unterscheidet ihn von der Korrektur (PUT), die die
bestehende Zeile umschreibt und damit die Vergangenheit mitverschiebt.

Kern der Regeln ist der Monatserste. Warum das keine Kosmetik ist, führt
`test_gegenprobe_*` vor: Die Beitragsrechnung zählt einen Monat voll, sobald ihn
ein Intervall an einem Tag berührt – bei einem Schnitt mitten im Monat landet er
deshalb in beiden Zeilen.

Ohne DB: reine Funktions- und Endpunkt-Tests mit Stubs.
"""
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.services.beitrags_service import (  # noqa: E402
    aktive_monate_menge, betroffene_zeitraeume, zeitraum_ende,
)
from app.services.mitgliedschaft import (  # noqa: E402
    pruefe_wechselstichtag, zuordnung_beendet,
)

GESTERN = (date.today() - timedelta(days=1)).isoformat()
MORGEN = (date.today() + timedelta(days=1)).isoformat()


# ------------------------------------------------------- Stichtag: Monatserster

def test_monatserster_geht_durch():
    pruefe_wechselstichtag('2020-01-01', None, '2026-08-01')


@pytest.mark.parametrize("tag", ['2026-08-15', '2026-08-31', '2026-08-02'])
def test_mitten_im_monat_wird_abgelehnt(tag):
    with pytest.raises(ValueError, match="Monatserster"):
        pruefe_wechselstichtag('2020-01-01', None, tag)


def test_gegenprobe_ein_schnitt_mitten_im_monat_zaehlt_den_monat_doppelt():
    """Der Grund für die Regel – hier einmal ausgerechnet.

    Wechsel zum 15.08.: Die alte Zeile endet am 14.08., die neue beginnt am 15.08.
    Beide berühren den August, beide zählen ihn voll. Bei zwei beitragspflichtigen
    Abteilungen wird er doppelt berechnet; bei aktiv → passiv bleibt er voll
    berechnet, obwohl der halbe Monat gemeint war. Ohne Fehlermeldung.
    """
    q3 = [(2026, 7), (2026, 8), (2026, 9)]
    alt = aktive_monate_menge(q3, date(2020, 1, 1), date(2026, 8, 14))
    neu = aktive_monate_menge(q3, date(2026, 8, 15), None)
    assert (2026, 8) in alt and (2026, 8) in neu

    # Zum Monatsersten geschnitten ist der August genau einmal drin.
    alt = aktive_monate_menge(q3, date(2020, 1, 1), date(2026, 7, 31))
    neu = aktive_monate_menge(q3, date(2026, 8, 1), None)
    assert alt & neu == set()
    assert alt | neu == set(q3)


# -------------------------------------------------- Stichtag: Lage zur alten Zeile

@pytest.mark.parametrize("ab", ['2020-01-01', '2019-12-01'])
def test_stichtag_vor_dem_beginn_ist_eine_korrektur(ab):
    with pytest.raises(ValueError, match="Korrektur"):
        pruefe_wechselstichtag('2020-01-01', None, ab)


def test_stichtag_hinter_einem_gesetzten_ende():
    with pytest.raises(ValueError, match="nach dem Ende"):
        pruefe_wechselstichtag('2020-01-01', '2026-06-30', '2026-08-01')


def test_stichtag_innerhalb_einer_befristeten_zuordnung_geht():
    pruefe_wechselstichtag('2020-01-01', '2026-12-31', '2026-08-01')


@pytest.mark.parametrize("ab", [None, '', '   '])
def test_stichtag_ist_pflicht(ab):
    with pytest.raises(ValueError, match="erforderlich"):
        pruefe_wechselstichtag('2020-01-01', None, ab)


def test_unsinniges_datum():
    with pytest.raises(ValueError, match="kein gültiges Datum"):
        pruefe_wechselstichtag('2020-01-01', None, '2026-02-30')


# --------------------------------------------------------------- beendet ja/nein

@pytest.mark.parametrize("bis,erwartet", [
    (GESTERN, True),
    (date.today().isoformat(), False),   # am Ende-Tag gilt sie noch
    (MORGEN, False),
    (None, False),
    ('', False),
])
def test_zuordnung_beendet(bis, erwartet):
    assert zuordnung_beendet(bis) is erwartet


# ------------------------------------------------- Betroffene Abrechnungszeiträume

@pytest.mark.parametrize("label,ende", [
    ('2026-Q3', date(2026, 9, 30)),
    ('2026-Q1', date(2026, 3, 31)),
    ('2026-08', date(2026, 8, 31)),
    ('2026-02', date(2026, 2, 28)),
    ('2026-H1', date(2026, 6, 30)),
    ('2026-H2', date(2026, 12, 31)),
    ('2026', date(2026, 12, 31)),
    ('Quatsch', None),
    ('2026-13', None),
    ('', None),
])
def test_zeitraum_ende(label, ende):
    assert zeitraum_ende(label) == ende


def test_betroffen_ist_was_der_stichtag_noch_beruehrt():
    """Ein Wechsel zum 1.8. ändert Q3 und alles danach – Q2 ist längst durch."""
    labels = ['2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4', '2027-Q1', 'Unbekannt']
    assert betroffene_zeitraeume(labels, date(2026, 8, 1)) == [
        '2026-Q3', '2026-Q4', '2027-Q1']


def test_ein_wechsel_in_der_zukunft_beruehrt_nichts_abgerechnetes():
    assert betroffene_zeitraeume(['2026-Q1', '2026-Q2'], date(2026, 8, 1)) == []


# ------------------------------------------------------------------- Endpunkte

def _user(username='pfleger'):
    return SimpleNamespace(
        id=1, username=username, role='admin', active=True,
        has_permission=lambda p: True,
        has_permission_global=lambda p: True,
        has_permission_for_abteilung=lambda p, aid: True,
        allowed_abteilungen=lambda p: None,
    )


def _zuordnung(**kwargs):
    from app.db.mitglied_abteilung_repository import MitgliedAbteilung
    daten = dict(id=7, mitglied_id=5, abteilung_id=3, status='aktiv',
                 von='2020-01-01', bis=None, version=1)
    daten.update(kwargs)
    return MitgliedAbteilung(**daten)


class _DB(SimpleNamespace):
    """Nur so viel Datastore, wie der Endpunkt anfasst."""

    def __init__(self, zuordnung, wechsel_ergebnis='neu'):
        super().__init__()
        self._zuordnung = zuordnung
        self._wechsel_ergebnis = wechsel_ergebnis
        self.wechsel_aufrufe = []

    def get_mitglied_abteilung(self, id):
        return self._zuordnung

    def get_mitglied(self, mitglied_id):
        return SimpleNamespace(eintrittsdatum='2020-01-01', austrittsdatum=None)

    def wechsel_mitglied_abteilung(self, id, ab, status, updated_by, expected_version):
        self.wechsel_aufrufe.append((id, ab, status, expected_version))
        if self._wechsel_ergebnis is None:
            return None
        return _zuordnung(id=8, status=status, von=ab, version=1)


def _wechsel(**kwargs):
    from backend.api.mitglied_abteilungen import ZuordnungWechsel
    daten = dict(ab='2026-08-01', status='passiv', expected_version=1)
    daten.update(kwargs)
    return ZuordnungWechsel(**daten)


def test_endpunkt_schneidet_und_liefert_die_neue_zeile():
    from backend.api import mitglied_abteilungen as api
    db = _DB(_zuordnung())
    ergebnis = api.wechsel_zuordnung(5, 7, _wechsel(), _user(), db)
    assert db.wechsel_aufrufe == [(7, '2026-08-01', 'passiv', 1)]
    assert ergebnis['status'] == 'passiv' and ergebnis['von'] == '2026-08-01'


def test_endpunkt_weist_den_stichtag_mitten_im_monat_ab():
    from backend.api import mitglied_abteilungen as api
    db = _DB(_zuordnung())
    with pytest.raises(HTTPException) as e:
        api.wechsel_zuordnung(5, 7, _wechsel(ab='2026-08-15'), _user(), db)
    assert e.value.status_code == 422
    assert "Monatserster" in e.value.detail
    assert db.wechsel_aufrufe == []


def test_endpunkt_weist_eine_beendete_zuordnung_ab():
    """An einer abgelaufenen Zeile gibt es nichts zu schneiden – das ist ein
    Zustand, kein Eingabefehler, also 409 statt 422."""
    from backend.api import mitglied_abteilungen as api
    db = _DB(_zuordnung(bis=GESTERN))
    with pytest.raises(HTTPException) as e:
        api.wechsel_zuordnung(5, 7, _wechsel(), _user(), db)
    assert e.value.status_code == 409
    assert "neue Zuordnung" in e.value.detail
    assert db.wechsel_aufrufe == []


def test_endpunkt_meldet_den_versionskonflikt():
    from backend.api import mitglied_abteilungen as api
    db = _DB(_zuordnung(), wechsel_ergebnis=None)
    with pytest.raises(HTTPException) as e:
        api.wechsel_zuordnung(5, 7, _wechsel(), _user(), db)
    assert e.value.status_code == 409
    assert "Versionskonflikt" in e.value.detail


def test_endpunkt_prueft_den_status():
    from backend.api import mitglied_abteilungen as api
    db = _DB(_zuordnung())
    with pytest.raises(HTTPException) as e:
        api.wechsel_zuordnung(5, 7, _wechsel(status='erfunden'), _user(), db)
    assert e.value.status_code == 422


def test_endpunkt_findet_fremde_zuordnung_nicht():
    from backend.api import mitglied_abteilungen as api
    db = _DB(_zuordnung(mitglied_id=99))
    with pytest.raises(HTTPException) as e:
        api.wechsel_zuordnung(5, 7, _wechsel(), _user(), db)
    assert e.value.status_code == 404
