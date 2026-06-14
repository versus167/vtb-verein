"""
Tests für verwaltete Kassen-Kategorien.

Deckt ab:
- Model KassenKategorie (Geltungsbereich allgemein vs. kassenspezifisch)
- KassenbuchService._validate_kategorie (Backend-Validierung der Auswahl):
    * leer ist erlaubt (Pflicht erzwingt nur das Frontend)
    * ohne konfiguriertes Repo wird nicht validiert
    * gültige Kategorie (allgemein ∪ kassenspezifisch) ist erlaubt
    * unbekannte Kategorie wirft KategorieUngueltigError
    * unveränderter Legacy-Altwert beim Bearbeiten bleibt zulässig

Repository-SQL (effektive Liste, Namenskonflikt, partieller Unique-Index) wird
gegen eine echte Postgres geprüft (Wegwerf-Container), nicht hier.
"""
import pytest

from app.models.kasse import KassenKategorie
from app.services.kassenbuch_service import KassenbuchService, KategorieUngueltigError


class FakeKategorieRepo:
    """Minimaler Stub: gibt die effektive Auswahl je Kasse zurück."""

    def __init__(self, effektiv: dict[int, list[KassenKategorie]]):
        self._effektiv = effektiv

    def list_for_kasse(self, kasse_id: int) -> list[KassenKategorie]:
        return self._effektiv.get(kasse_id, [])


def _service(kategorie_repo) -> KassenbuchService:
    # Nur das kategorie_repo wird von _validate_kategorie benutzt; der Rest bleibt None.
    return KassenbuchService(
        kasse_repo=None,
        buchung_repo=None,
        export_repo=None,
        berechtigung_repo=None,
        kategorie_repo=kategorie_repo,
    )


class TestModel:
    def test_allgemein_wenn_kasse_id_none(self):
        assert KassenKategorie(name="Spende").ist_allgemein is True

    def test_kassenspezifisch_wenn_kasse_id_gesetzt(self):
        assert KassenKategorie(name="Trikot", kasse_id=1).ist_allgemein is False


class TestValidierung:
    def _repo(self):
        # Kasse 1: allgemeine "Spende" + kassenspezifisches "Trikot"
        return FakeKategorieRepo({
            1: [
                KassenKategorie(id=1, name="Spende", kasse_id=None),
                KassenKategorie(id=2, name="Trikot", kasse_id=1),
            ],
        })

    def test_leer_ist_erlaubt(self):
        svc = _service(self._repo())
        svc._validate_kategorie(1, "")        # kein Raise
        svc._validate_kategorie(1, "   ")     # nur Whitespace → wie leer

    def test_ohne_repo_keine_validierung(self):
        svc = _service(None)
        svc._validate_kategorie(1, "Beliebiger Freitext")  # kein Raise

    def test_allgemeine_kategorie_gueltig(self):
        svc = _service(self._repo())
        svc._validate_kategorie(1, "Spende")

    def test_kassenspezifische_kategorie_gueltig(self):
        svc = _service(self._repo())
        svc._validate_kategorie(1, "Trikot")

    def test_whitespace_wird_normalisiert(self):
        svc = _service(self._repo())
        svc._validate_kategorie(1, "  Spende  ")

    def test_unbekannte_kategorie_wirft(self):
        svc = _service(self._repo())
        with pytest.raises(KategorieUngueltigError):
            svc._validate_kategorie(1, "Gibt es nicht")

    def test_kassenfremde_kategorie_wirft(self):
        # "Trikot" gehört zu Kasse 1, ist bei Kasse 2 nicht wählbar.
        repo = FakeKategorieRepo({
            1: [KassenKategorie(id=2, name="Trikot", kasse_id=1)],
            2: [],
        })
        svc = _service(repo)
        with pytest.raises(KategorieUngueltigError):
            svc._validate_kategorie(2, "Trikot")

    def test_legacy_altwert_bleibt_beim_bearbeiten_zulaessig(self):
        svc = _service(self._repo())
        # Alter Freitext, nicht in den Stammdaten – beim Bearbeiten unverändert übernommen.
        svc._validate_kategorie(1, "Alter Freitext", vorheriger_wert="Alter Freitext")

    def test_aenderung_auf_ungueltig_wirft_trotz_altwert(self):
        svc = _service(self._repo())
        with pytest.raises(KategorieUngueltigError):
            svc._validate_kategorie(1, "Neu und ungültig", vorheriger_wert="Alter Freitext")
