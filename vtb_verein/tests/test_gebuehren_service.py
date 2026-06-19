"""
Tests für GebuehrenService.vorschlag_aufnahmegebuehren (Ticket #42).

Fachregel:
- Vorgeschlagen werden nur Gebühren mit anlass='aufnahme', die am Stichtag gültig sind
  (das übernimmt list_aktive), deren Abteilungs-Scope passt (None = Verein) und für die
  das Mitglied noch keine (nicht stornierte) Forderung hat.
"""
from types import SimpleNamespace

from app.models.gebuehr import Gebuehr
from app.services.gebuehren_service import GebuehrenService


def _gebuehr(id, anlass='aufnahme', abteilung_id=None, betrag=25.0):
    return Gebuehr(id=id, name=f'G{id}', anlass=anlass, abteilung_id=abteilung_id, betrag=betrag)


def _fake_db(aktive, vorhandene_forderungen=()):
    """vorhandene_forderungen: Menge von (mitglied_id, gebuehr_id)-Tupeln."""
    return SimpleNamespace(
        gebuehren=SimpleNamespace(list_aktive=lambda datum: list(aktive)),
        gebuehr_forderung_exists=lambda mid, gid: (mid, gid) in set(vorhandene_forderungen),
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
