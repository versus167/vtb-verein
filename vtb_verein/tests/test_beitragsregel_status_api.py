"""Status-Bedingung einer Beitragsregel: Eingabeprüfung (backend/api/beitraege.py).

Die Bedingung entscheidet, wer den Abteilungsbeitrag zahlt. Ein Tippfehler ergäbe eine
Bedingung, auf die kein Mitglied passt – die Regel bliebe stumm, und auffallen würde das
erst, wenn die Beiträge eines Quartals fehlen. Darum lässt das Schema nur die bekannten
Status durch.
"""
import sys
from pathlib import Path

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from backend.api.beitraege import RegelCreate  # noqa: E402


def _regel(**kwargs):
    return RegelCreate(name="Abt", abteilung_id=5, betrag_pro_monat=6.0,
                       gueltig_ab="2026-01-01", **kwargs)


class TestStatusBedingung:

    def test_bekannte_status_bleiben_erhalten(self):
        assert _regel(bedingung_abteilung_status="aktiv,passiv"
                      ).bedingung_abteilung_status == "aktiv,passiv"

    def test_leerzeichen_werden_geraeumt(self):
        # Die Bedingung landet als Kommaliste in der DB und wird dort gesplittet –
        # ' passiv' träfe sonst nichts.
        assert _regel(bedingung_abteilung_status=" aktiv , passiv "
                      ).bedingung_abteilung_status == "aktiv,passiv"

    @pytest.mark.parametrize("wert", ["", "   ", ",,"])
    def test_leere_angabe_wird_zu_none(self, wert):
        # None = Grundregel „alle außer passiv"; ein leerer String wäre eine
        # Bedingung, die auf niemanden passt.
        assert _regel(bedingung_abteilung_status=wert).bedingung_abteilung_status is None

    def test_ohne_angabe_none(self):
        assert _regel().bedingung_abteilung_status is None

    # 'trainer' & Co. gehören seit v104 dazu: Rollen sind Funktionen, keine Status.
    @pytest.mark.parametrize("wert", ["aktive", "Passiv", "aktiv,trainer", "ehrenmitglied"])
    def test_unbekannter_status_wird_abgewiesen(self, wert):
        with pytest.raises(ValidationError, match="Unbekannter Abteilungs-Status"):
            _regel(bedingung_abteilung_status=wert)

    def test_passiv_ist_erlaubt(self):
        # Ausdrücklich genannt schlägt 'passiv' die Grundregel (Passiv-Beitrag).
        assert _regel(bedingung_abteilung_status="passiv"
                      ).bedingung_abteilung_status == "passiv"
