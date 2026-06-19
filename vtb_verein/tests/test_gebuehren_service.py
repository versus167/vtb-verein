"""
Tests für GebuehrenService.vorschlag_aufnahmegebuehren (Ticket #42).

Fachregel:
- Vorgeschlagen werden nur Gebühren mit anlass='aufnahme', die am Stichtag gültig sind
  (das übernimmt list_aktive), deren Abteilungs-Scope passt (None = Verein) und für die
  das Mitglied noch keine (nicht stornierte) Forderung hat.
"""
from types import SimpleNamespace

from app.models.gebuehr import Gebuehr
from app.services.gebuehren_service import GebuehrenService, _alter_am


def _gebuehr(id, anlass='aufnahme', abteilung_id=None, betrag=25.0,
             alter_min=None, alter_max=None):
    return Gebuehr(id=id, name=f'G{id}', anlass=anlass, abteilung_id=abteilung_id, betrag=betrag,
                   bedingung_alter_min=alter_min, bedingung_alter_max=alter_max)


def _fake_db(aktive, vorhandene_forderungen=(), geburtsdatum=None):
    """vorhandene_forderungen: Menge von (mitglied_id, gebuehr_id)-Tupeln."""
    return SimpleNamespace(
        gebuehren=SimpleNamespace(list_aktive=lambda datum: list(aktive)),
        gebuehr_forderung_exists=lambda mid, gid: (mid, gid) in set(vorhandene_forderungen),
        get_mitglied=lambda mid: SimpleNamespace(geburtsdatum=geburtsdatum),
    )


class TestVorschlagAufnahmegebuehren:
    def test_verein_scope_nimmt_nur_aufnahme_ohne_abteilung(self):
        db = _fake_db([
            _gebuehr(1, anlass='aufnahme', abteilung_id=None),
            _gebuehr(2, anlass='aufnahme', abteilung_id=5),    # andere Abteilung -> raus
            _gebuehr(3, anlass='sonstiges', abteilung_id=None),  # falscher Anlass -> raus
        ])
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(mitglied_id=10, abteilung_id=None, datum='2026-06-19')
        assert [g.id for g in res] == [1]

    def test_abteilung_scope_nimmt_nur_diese_abteilung(self):
        db = _fake_db([
            _gebuehr(1, abteilung_id=None),
            _gebuehr(2, abteilung_id=5),
            _gebuehr(3, abteilung_id=7),
        ])
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(mitglied_id=10, abteilung_id=5, datum='2026-06-19')
        assert [g.id for g in res] == [2]

    def test_bestehende_forderung_wird_uebersprungen(self):
        db = _fake_db(
            [_gebuehr(1, abteilung_id=None), _gebuehr(2, abteilung_id=None)],
            vorhandene_forderungen=[(10, 1)],
        )
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(mitglied_id=10, abteilung_id=None, datum='2026-06-19')
        assert [g.id for g in res] == [2]

    def test_keine_passende_gebuehr_liefert_leer(self):
        db = _fake_db([_gebuehr(1, anlass='aufnahme', abteilung_id=5)])
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(mitglied_id=10, abteilung_id=None, datum='2026-06-19')
        assert res == []


class TestAltersbedingung:
    KINDER = 1   # alter_max=17
    ERWACHSENE = 2  # alter_min=18

    def _db(self, geburtsdatum):
        return _fake_db(
            [_gebuehr(self.KINDER, alter_max=17), _gebuehr(self.ERWACHSENE, alter_min=18)],
            geburtsdatum=geburtsdatum,
        )

    def test_kind_bekommt_nur_kindergebuehr(self):
        db = self._db('2015-01-01')  # 11 Jahre am Stichtag
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(10, None, '2026-06-19')
        assert [g.id for g in res] == [self.KINDER]

    def test_erwachsener_bekommt_nur_erwachsenengebuehr(self):
        db = self._db('1990-01-01')  # 36 Jahre
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(10, None, '2026-06-19')
        assert [g.id for g in res] == [self.ERWACHSENE]

    def test_grenze_18_zaehlt_als_erwachsen(self):
        db = self._db('2008-06-19')  # wird am Stichtag genau 18
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(10, None, '2026-06-19')
        assert [g.id for g in res] == [self.ERWACHSENE]

    def test_ohne_geburtsdatum_kein_altersabhaengiger_vorschlag(self):
        db = self._db(None)
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(10, None, '2026-06-19')
        assert res == []

    def test_gebuehr_ohne_altersbedingung_gilt_immer(self):
        db = _fake_db([_gebuehr(1)], geburtsdatum=None)
        res = GebuehrenService(db).vorschlag_aufnahmegebuehren(10, None, '2026-06-19')
        assert [g.id for g in res] == [1]


class TestAlterAm:
    def test_geburtstag_noch_nicht_erreicht(self):
        assert _alter_am('2008-12-31', '2026-06-19') == 17

    def test_geburtstag_genau_am_stichtag(self):
        assert _alter_am('2008-06-19', '2026-06-19') == 18

    def test_ungueltiges_datum(self):
        assert _alter_am('', '2026-06-19') is None
        assert _alter_am(None, '2026-06-19') is None
