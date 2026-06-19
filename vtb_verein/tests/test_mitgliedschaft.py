"""
Tests für pruefe_von_in_mitgliedschaft: der Beginn einer Zuordnung
(Abteilung/Funktion/Mannschaft) muss innerhalb der Vereinsmitgliedschaft liegen.
"""
import pytest

from app.services.mitgliedschaft import pruefe_von_in_mitgliedschaft


class TestVonInMitgliedschaft:
    EINTRITT = '2026-01-01'
    AUSTRITT = '2026-12-31'

    def test_von_vor_eintritt_wirft(self):
        with pytest.raises(ValueError, match='Vereinseintritt'):
            pruefe_von_in_mitgliedschaft(self.EINTRITT, None, '2025-12-31')

    def test_von_genau_eintritt_ok(self):
        pruefe_von_in_mitgliedschaft(self.EINTRITT, None, self.EINTRITT)

    def test_von_innerhalb_ok(self):
        pruefe_von_in_mitgliedschaft(self.EINTRITT, self.AUSTRITT, '2026-06-15')

    def test_von_genau_austritt_ok(self):
        pruefe_von_in_mitgliedschaft(self.EINTRITT, self.AUSTRITT, self.AUSTRITT)

    def test_von_nach_austritt_wirft(self):
        with pytest.raises(ValueError, match='Vereinsaustritt'):
            pruefe_von_in_mitgliedschaft(self.EINTRITT, self.AUSTRITT, '2027-01-01')

    def test_ohne_austritt_keine_obergrenze(self):
        pruefe_von_in_mitgliedschaft(self.EINTRITT, None, '2099-01-01')

    def test_ohne_von_nichts_zu_pruefen(self):
        pruefe_von_in_mitgliedschaft(self.EINTRITT, self.AUSTRITT, None)
        pruefe_von_in_mitgliedschaft(self.EINTRITT, self.AUSTRITT, '')

    def test_zeitanteil_wird_abgeschnitten(self):
        # von mit Uhrzeit wird auf das Datum reduziert (genau Eintritt → ok)
        pruefe_von_in_mitgliedschaft(self.EINTRITT, None, '2026-01-01T12:00:00')

    def test_ohne_eintritt_keine_untergrenze(self):
        pruefe_von_in_mitgliedschaft(None, None, '2000-01-01')
