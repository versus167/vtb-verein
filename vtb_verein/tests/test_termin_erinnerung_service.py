"""Erinnerung an fehlende Termin-Meldungen (#95-Nachgang) – die Entscheidungslogik.

Geprüft wird, wann erinnert wird und wann nicht: welche Stufe bei welchem Vorlauf
greift, dass ein ausgefallener Lauf seine Stufe nachholt, dass ein kurzfristig
angelegter Termin NICHT beide Stufen auf einmal auslöst und dass eine verschickte
Stufe nicht bei jedem Lauf erneut rausgeht. Alles reine Funktionen über
Termin-Objekte – ohne DB, ohne Versand.
"""
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.termin import TerminErinnerungEinstellungen  # noqa: E402
from app.services import termin_erinnerung_service as erin  # noqa: E402

_HEUTE = date(2026, 8, 26)


@pytest.fixture(autouse=True)
def _standard_kuerzel(monkeypatch):
    """Platzhalter-Default („Beispiel") prüfen, unabhängig von der Env des Rechners."""
    monkeypatch.delenv('VTB_VEREIN_KURZ', raising=False)


def _termin(in_tagen=3, id=7, typ='spiel', gegner='SV Beispiel',
            heim_auswaerts='heim', mannschaft_name='AH'):
    tag = _HEUTE + timedelta(days=in_tagen)
    return SimpleNamespace(
        id=id, mannschaft_id=1, mannschaft_name=mannschaft_name, typ=typ,
        beginn=f"{tag.isoformat()}T18:30", ende=None, ort='Sportplatz',
        treffpunkt=None, treffpunkt_zeit=None, beschreibung=None,
        gegner=gegner, heim_auswaerts=heim_auswaerts, status='geplant')


def _faellig(termin, bereits=None, einst=None):
    """Einen Termin durch den Lauf schicken – „welche Stufe ist dran?" (None = keine)."""
    treffer = erin.faellige([termin], bereits or {}, einst, _HEUTE)
    return treffer[0][1] if treffer else None


class TestStufen:
    def test_drei_tage_vorher_greift_die_erste_stufe(self):
        assert _faellig(_termin(in_tagen=3)) == 3

    def test_am_vortag_greift_die_zweite_stufe(self):
        assert _faellig(_termin(in_tagen=1)) == 1

    def test_ausserhalb_des_vorlaufs_passiert_nichts(self):
        assert _faellig(_termin(in_tagen=4)) is None

    def test_am_termintag_ist_erinnern_zu_spaet(self):
        assert _faellig(_termin(in_tagen=0)) is None
        assert _faellig(_termin(in_tagen=-1)) is None

    def test_ausgefallener_lauf_holt_die_stufe_nach(self):
        """Vorlauf 2 bei den Stufen 3/1: Die 3er-Stufe kommt verspätet nach, statt
        ersatzlos auszufallen."""
        assert _faellig(_termin(in_tagen=2)) == 3

    def test_kurzfristiger_termin_loest_nur_eine_stufe_aus(self):
        """Heute für morgen angelegt: nur die 1er-Stufe, nicht beide auf einmal."""
        termin = _termin(in_tagen=1)
        assert _faellig(termin) == 1
        # Und nachdem sie raus ist, folgt nichts mehr.
        bereits = {erin.schluessel(termin.id, 1): 'egal'}
        assert _faellig(termin, bereits) is None

    def test_verschickte_stufe_geht_nicht_erneut_raus(self):
        termin = _termin(in_tagen=3)
        assert _faellig(termin, {erin.schluessel(termin.id, 3): 'egal'}) is None

    def test_erste_stufe_blockiert_die_zweite_nicht(self):
        termin = _termin(in_tagen=1)
        assert _faellig(termin, {erin.schluessel(termin.id, 3): 'egal'}) == 1


class TestEinstellungen:
    def test_abgeschaltet_erinnert_gar_nicht(self):
        einst = TerminErinnerungEinstellungen(aktiv=False)
        assert _faellig(_termin(in_tagen=1), einst=einst) is None

    def test_stufe_null_schaltet_die_einzelne_stufe_ab(self):
        einst = TerminErinnerungEinstellungen(zweite_stufe_tage=0)
        assert erin.stufen(einst) == (3,)
        # Der Vortag fällt jetzt unter die 3er-Stufe – die ist aber längst raus.
        termin = _termin(in_tagen=1)
        assert _faellig(termin, {erin.schluessel(termin.id, 3): 'egal'}, einst) is None

    def test_eigene_vorlaeufe_werden_sortiert(self):
        einst = TerminErinnerungEinstellungen(erste_stufe_tage=2, zweite_stufe_tage=7)
        assert erin.stufen(einst) == (7, 2)
        assert _faellig(_termin(in_tagen=7), einst=einst) == 7
        assert _faellig(_termin(in_tagen=2), einst=einst) == 2

    def test_doppelter_vorlauf_bleibt_eine_stufe(self):
        einst = TerminErinnerungEinstellungen(erste_stufe_tage=2, zweite_stufe_tage=2)
        assert erin.stufen(einst) == (2,)

    def test_beide_stufen_null_heisst_kein_lauf(self):
        einst = TerminErinnerungEinstellungen(erste_stufe_tage=0, zweite_stufe_tage=0)
        assert erin.stufen(einst) == ()
        assert _faellig(_termin(in_tagen=1), einst=einst) is None


class TestNachricht:
    def test_titel_nennt_die_mannschaft(self):
        titel, _ = erin.build_erinnerung(_termin(), vorlauf=3)
        assert titel == "Rückmeldung fehlt – AH"

    def test_text_nennt_termin_und_zeitpunkt(self):
        _, text = erin.build_erinnerung(_termin(in_tagen=3), vorlauf=3)
        assert "Spiel (H) Beispiel AH - SV Beispiel" in text
        assert "Sa., 29.08.2026 18:30" in text
        assert "in 3 Tagen" in text
        assert "zu- oder absagen" in text

    def test_text_sagt_morgen_statt_in_einem_tag(self):
        _, text = erin.build_erinnerung(_termin(in_tagen=1), vorlauf=1)
        assert "der Termin ist morgen." in text

    def test_uebermorgen_hat_ein_eigenes_wort(self):
        assert erin.wann_text(2) == 'übermorgen'
        assert erin.wann_text(5) == 'in 5 Tagen'

    def test_ohne_mannschaftsnamen_bleibt_die_nummer(self):
        termin = _termin(mannschaft_name=None)
        titel, _ = erin.build_erinnerung(termin, vorlauf=1)
        assert titel == "Rückmeldung fehlt – Mannschaft 1"


class TestUnlesbareDaten:
    def test_kaputter_beginn_wird_uebersprungen(self):
        termin = _termin()
        termin.beginn = 'demnächst'
        assert erin.vorlauf_tage(termin.beginn, _HEUTE) is None
        assert _faellig(termin) is None
