"""
Tests für die Sichtbarkeit von Abteilungen/Funktionen in der Personenliste (Ticket #91).

Erwartetes Verhalten:
- Erst künftig beginnende Zuordnungen (Beginndatum in der Zukunft) bleiben sichtbar und
  behalten ``von``/``bis`` in der Antwort (das Frontend kennzeichnet sie mit „ab …").
- Bereits abgelaufene Zuordnungen (``bis`` in der Vergangenheit) werden ausgeblendet.
- Aktuell laufende Zuordnungen bleiben unverändert sichtbar.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.api.personen import _aktiv_oder_kuenftig, _person_row  # noqa: E402


def _iso(delta_days: int) -> str:
    return (date.today() + timedelta(days=delta_days)).isoformat()


class _Zuordnung:
    """Stub einer Abteilungs-/Funktions-Zuordnung – nur die von ``_person_row`` genutzten Felder."""

    def __init__(self, von=None, bis=None, **extra):
        self.id = extra.get("id", 1)
        self.von = von
        self.bis = bis
        self.abteilung_id = extra.get("abteilung_id")
        self.abteilung_name = extra.get("abteilung_name")
        self.abteilung_kuerzel = extra.get("abteilung_kuerzel")
        self.status = extra.get("status", "aktiv")
        self.funktion = extra.get("funktion", "trainer")


class TestAktivOderKuenftig:
    def test_ohne_datum_sichtbar(self):
        assert _aktiv_oder_kuenftig(None, None) is True

    def test_laufend_sichtbar(self):
        assert _aktiv_oder_kuenftig(_iso(-10), _iso(10)) is True

    def test_kuenftiger_beginn_bleibt_sichtbar(self):
        # Früher (nur "gültig heute") wäre das ausgeblendet worden.
        assert _aktiv_oder_kuenftig(_iso(30), None) is True
        assert _aktiv_oder_kuenftig(_iso(30), _iso(400)) is True

    def test_abgelaufen_ausgeblendet(self):
        assert _aktiv_oder_kuenftig(_iso(-100), _iso(-1)) is False


class TestPersonRowSichtbarkeit:
    def test_kuenftige_abteilung_bleibt_mit_von(self):
        ab = _Zuordnung(von=_iso(20), abteilung_id=3, abteilung_name="Fußball", abteilung_kuerzel="FB")
        row = _person_row(None, None, [ab], [])
        assert len(row["abteilungen"]) == 1
        assert row["abteilungen"][0]["von"] == _iso(20)

    def test_kuenftige_funktion_bleibt_mit_von(self):
        f = _Zuordnung(von=_iso(15), funktion="uebungsleiter", abteilung_id=3, abteilung_name="Fußball")
        row = _person_row(None, None, [], [f])
        assert len(row["funktionen"]) == 1
        assert row["funktionen"][0]["von"] == _iso(15)

    def test_abgelaufene_zuordnung_faellt_weg(self):
        ab_alt = _Zuordnung(von=_iso(-400), bis=_iso(-1), abteilung_id=3)
        f_alt = _Zuordnung(von=_iso(-40), bis=_iso(-1), funktion="trainer")
        row = _person_row(None, None, [ab_alt], [f_alt])
        assert row["abteilungen"] == []
        assert row["funktionen"] == []
