"""Tests für ULStundenService – Serien-/Wochenplan-Erfassung und Vorlage.

Fachregeln:
- add_serie erzeugt für jeden gewählten Wochentag (1=Mo … 7=So) einen Termin an
  jedem passenden Tag im Abrechnungszeitraum; bereits erfasste Tage werden
  übersprungen (idempotent) und nur Entwürfe sind bearbeitbar.
- letzte_vorlage gruppiert die Termine der jüngsten Vor-Abrechnung nach
  (Stunden, Angebot) und liefert je Gruppe die belegten Wochentage, dominantes
  Muster zuerst.
"""
from datetime import date

import pytest

from app.models.ul_stunden import (
    ULAbrechnung, ULStunde, STATUS_ENTWURF, STATUS_EINGEREICHT,
)
from app.services.ul_stunden_service import ULStundenService


def _abr(von='2026-06-01', bis='2026-06-30', status=STATUS_ENTWURF, id=1):
    return ULAbrechnung(id=id, mitglied_id=10, abteilung_id=5,
                        zeitraum_von=von, zeitraum_bis=bis, status=status)


def _stunde(datum, stunden=2.0, angebot=None):
    return ULStunde(datum=datum, stunden=stunden, angebot=angebot,
                    wochentag=date.fromisoformat(datum).isoweekday())


class _FakeRepo:
    """Minimaler Fake von db.ul_abrechnungen für die Service-Tests."""
    def __init__(self, *, stunden=(), vorlage_quelle=None, vorlage_termine=()):
        self._stunden = list(stunden)
        self.added = []
        self._vorlage_quelle = vorlage_quelle
        self._vorlage_termine = list(vorlage_termine)

    def list_stunden(self, abrechnung_id):
        if self._vorlage_quelle is not None and abrechnung_id == self._vorlage_quelle:
            return list(self._vorlage_termine)
        return list(self._stunden)

    def add_stunde(self, s, created_by):
        self._stunden.append(s)
        self.added.append(s)
        return s

    def letzte_vorlage_quelle_id(self, mitglied_id, abteilung_id, exclude_id=None):
        return self._vorlage_quelle


def _svc(repo):
    class _DB:
        ul_abrechnungen = repo
    return ULStundenService(_DB())


class TestAddSerie:
    def test_erzeugt_alle_passenden_wochentage(self):
        repo = _FakeRepo()
        # Juni 2026: 01 = Montag → Di = 2,9,16,23,30 ; Do = 4,11,18,25
        n = _svc(repo).add_serie(_abr(), wochentage=[2, 4], stunden=2.0,
                                 angebot='Fußball', bemerkung=None, erstellt_von='t')
        assert n == 9
        datums = sorted(s.datum for s in repo.added)
        assert datums == ['2026-06-02', '2026-06-04', '2026-06-09', '2026-06-11',
                          '2026-06-16', '2026-06-18', '2026-06-23', '2026-06-25', '2026-06-30']
        assert all(s.stunden == 2.0 and s.angebot == 'Fußball' for s in repo.added)
        assert {s.wochentag for s in repo.added} == {2, 4}

    def test_ueberspringt_bereits_erfasste_tage(self):
        repo = _FakeRepo(stunden=[_stunde('2026-06-09')])  # zweiter Dienstag schon da
        n = _svc(repo).add_serie(_abr(), wochentage=[2], stunden=2.0,
                                 angebot=None, bemerkung=None, erstellt_von='t')
        assert n == 4  # 5 Dienstage minus dem bereits erfassten
        assert '2026-06-09' not in [s.datum for s in repo.added]

    def test_nur_entwurf_bearbeitbar(self):
        repo = _FakeRepo()
        with pytest.raises(ValueError):
            _svc(repo).add_serie(_abr(status=STATUS_EINGEREICHT), wochentage=[2],
                                 stunden=2.0, angebot=None, bemerkung=None, erstellt_von='t')

    def test_leere_wochentage_fehler(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_serie(_abr(), wochentage=[], stunden=2.0,
                                        angebot=None, bemerkung=None, erstellt_von='t')

    def test_ungueltiger_wochentag_fehler(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_serie(_abr(), wochentage=[0, 8], stunden=2.0,
                                        angebot=None, bemerkung=None, erstellt_von='t')

    def test_stunden_muss_positiv_sein(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_serie(_abr(), wochentage=[2], stunden=0,
                                        angebot=None, bemerkung=None, erstellt_von='t')


class TestAddTage:
    def test_legt_gewaehlte_tage_an(self):
        repo = _FakeRepo()
        n = _svc(repo).add_tage(_abr(), datums=['2026-06-06', '2026-06-20'], stunden=2.0,
                                angebot='Spiel', bemerkung=None, erstellt_von='t')
        assert n == 2
        assert sorted(s.datum for s in repo.added) == ['2026-06-06', '2026-06-20']
        assert all(s.angebot == 'Spiel' for s in repo.added)
        # Wochentag wird aus dem Datum abgeleitet (06.06.2026 = Samstag = 6)
        assert repo.added[0].wochentag == 6

    def test_ausserhalb_zeitraum_und_duplikate_uebersprungen(self):
        repo = _FakeRepo(stunden=[_stunde('2026-06-10')])
        n = _svc(repo).add_tage(
            _abr(), datums=['2026-05-31',          # vor dem Zeitraum -> raus
                            '2026-07-01',          # nach dem Zeitraum -> raus
                            '2026-06-10',          # schon erfasst -> raus
                            '2026-06-15', '2026-06-15'],  # Duplikat -> nur einmal
            stunden=2.0, angebot=None, bemerkung=None, erstellt_von='t')
        assert n == 1
        assert [s.datum for s in repo.added] == ['2026-06-15']

    def test_leere_liste_fehler(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_tage(_abr(), datums=[], stunden=2.0,
                                       angebot=None, bemerkung=None, erstellt_von='t')

    def test_nur_entwurf_bearbeitbar(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_tage(_abr(status=STATUS_EINGEREICHT), datums=['2026-06-06'],
                                       stunden=2.0, angebot=None, bemerkung=None, erstellt_von='t')

    def test_stunden_muss_positiv_sein(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_tage(_abr(), datums=['2026-06-06'], stunden=0,
                                       angebot=None, bemerkung=None, erstellt_von='t')


class TestLetzteVorlage:
    def test_gruppiert_nach_stunden_und_angebot_dominant_zuerst(self):
        termine = [
            _stunde('2026-05-05', 2.0, 'Fußball'),   # Di
            _stunde('2026-05-12', 2.0, 'Fußball'),   # Di
            _stunde('2026-05-07', 1.5, 'Torwart'),   # Do
        ]
        repo = _FakeRepo(vorlage_quelle=99, vorlage_termine=termine)
        out = _svc(repo).letzte_vorlage(mitglied_id=10, abteilung_id=5, exclude_id=1)
        assert out == [
            {'wochentage': [2], 'stunden': 2.0, 'angebot': 'Fußball', 'anzahl': 2},
            {'wochentage': [4], 'stunden': 1.5, 'angebot': 'Torwart', 'anzahl': 1},
        ]

    def test_keine_quelle_liefert_leer(self):
        out = _svc(_FakeRepo(vorlage_quelle=None)).letzte_vorlage(
            mitglied_id=10, abteilung_id=5, exclude_id=1)
        assert out == []
