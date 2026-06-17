"""
Tests für Kassenzählungen (Zählprotokoll / Stückelung).

Deckt ab:
- KassenbuchService._normalisiere_stueckelung (Ist-Berechnung + Validierung)
- KassenbuchService.erstelle_zaehlung:
    * Überschuss (Ist > Soll) → Einnahme-Differenzbuchung
    * Fehlbetrag (Ist < Soll) → Ausgabe-Differenzbuchung
    * Differenz 0 → 0-€-Buchung
    * Soll wird aus dem aktuellen Buchbestand eingefroren
    * ohne Auslöser → Systemkategorie „Kassendifferenz"
    * mit auslösender Buchung → deren Kategorie wird verbucht (Trigger)
    * Differenzbuchung umgeht die Kategorie-Validierung (skip)

Repository-SQL (JSONB-Persistenz, History-Trigger) wird gegen eine echte Postgres
geprüft, nicht hier.
"""
import pytest

from app.models.kasse import Kasse, Kassenbuchung, KassenKategorie
from app.services.kassenbuch_service import (
    KassenbuchService,
    ZaehlungUngueltigError,
    KategorieUngueltigError,
    KASSENDIFFERENZ_KATEGORIE,
)


class FakeKasseRepo:
    def __init__(self, bestand_cent: int, name: str = "Barkasse"):
        self._bestand = bestand_cent
        self._name = name

    def get_bestand_cent(self, kasse_id): return self._bestand
    def get_bestand_zum_datum_cent(self, kasse_id, datum): return self._bestand
    def get_kasse(self, kasse_id): return Kasse(id=kasse_id, name=self._name)


class FakeBuchungRepo:
    def __init__(self, ausloeser: dict[int, Kassenbuchung] | None = None):
        self.created: list[Kassenbuchung] = []
        self._ausloeser = ausloeser or {}
        self._next_id = 100

    def get_naechste_belegnummer(self, kasse_id): return "7"

    def create_kassenbuchung(self, buchung, created_by):
        buchung.id = self._next_id
        self._next_id += 1
        buchung.created_by = created_by
        self.created.append(buchung)
        return buchung

    def get_kassenbuchung(self, buchung_id):
        if buchung_id in self._ausloeser:
            return self._ausloeser[buchung_id]
        raise KeyError(buchung_id)


class FakeExportRepo:
    def get_letztes_bis_datum(self, kasse_id): return None
    def ist_buchung_gesperrt(self, buchung_id): return False


class FakeZaehlungRepo:
    def __init__(self):
        self.created = []

    def create(self, zaehlung, created_by):
        zaehlung.id = 55
        zaehlung.created_by = created_by
        zaehlung.created_at = "2026-06-17 14:32:00"
        self.created.append(zaehlung)
        return zaehlung


class FakeKategorieRepo:
    """Gibt eine Auswahl ohne „Kassendifferenz" zurück – um zu prüfen, dass die
    Differenzbuchung die Kategorie-Validierung umgeht."""
    def list_for_kasse(self, kasse_id):
        return [KassenKategorie(id=1, name="Spende", kasse_id=None)]


def _service(bestand_cent, ausloeser=None, kategorie_repo=None):
    return KassenbuchService(
        kasse_repo=FakeKasseRepo(bestand_cent),
        buchung_repo=FakeBuchungRepo(ausloeser),
        export_repo=FakeExportRepo(),
        berechtigung_repo=None,
        kategorie_repo=kategorie_repo,
        zaehlung_repo=FakeZaehlungRepo(),
    )


class TestNormalisierung:
    def test_summe_und_drop_nullen(self):
        svc = _service(0)
        norm, ist = svc._normalisiere_stueckelung({"5000": 2, "200": 13, "1": 0})
        assert ist == 2 * 5000 + 13 * 200
        assert norm == {"5000": 2, "200": 13}

    def test_unbekannter_wert_wirft(self):
        svc = _service(0)
        with pytest.raises(ZaehlungUngueltigError):
            svc._normalisiere_stueckelung({"333": 1})

    def test_negative_anzahl_wirft(self):
        svc = _service(0)
        with pytest.raises(ZaehlungUngueltigError):
            svc._normalisiere_stueckelung({"500": -2})

    def test_leere_stueckelung_ist_null(self):
        svc = _service(0)
        norm, ist = svc._normalisiere_stueckelung({})
        assert (norm, ist) == ({}, 0)


class TestErstelleZaehlung:
    def test_ueberschuss_erzeugt_einnahme(self):
        svc = _service(bestand_cent=12500)
        z = svc.erstelle_zaehlung(1, {"5000": 2, "200": 13}, created_by="vsuess")  # ist 12600
        assert z.ist_cent == 12600
        assert z.soll_cent == 12500          # eingefroren aus get_bestand_cent
        assert z.differenz_cent == 100
        b = svc._buchung.created[0]
        assert b.einnahme_cent == 100 and b.ausgabe_cent == 0
        assert b.kategorie == KASSENDIFFERENZ_KATEGORIE
        assert b.buchungstext == "Kassenzählung"
        assert z.buchung_id == b.id

    def test_fehlbetrag_erzeugt_ausgabe(self):
        svc = _service(bestand_cent=12700)
        z = svc.erstelle_zaehlung(1, {"5000": 2, "200": 13}, created_by="vsuess")  # ist 12600
        assert z.differenz_cent == -100
        b = svc._buchung.created[0]
        assert b.ausgabe_cent == 100 and b.einnahme_cent == 0

    def test_differenz_null_erzeugt_nullbuchung(self):
        svc = _service(bestand_cent=12600)
        z = svc.erstelle_zaehlung(1, {"5000": 2, "200": 13}, created_by="vsuess")  # ist 12600
        assert z.differenz_cent == 0
        b = svc._buchung.created[0]
        assert b.einnahme_cent == 0 and b.ausgabe_cent == 0

    def test_ausloesende_kategorie_wird_verbucht(self):
        ausloeser = {42: Kassenbuchung(
            id=42, kasse_id=1, buchungsdatum="2026-06-17",
            buchungstext="Sommerfest", kategorie="Sommerfest", einnahme_cent=5000,
        )}
        svc = _service(bestand_cent=5000, ausloeser=ausloeser)
        z = svc.erstelle_zaehlung(1, {"5000": 1}, created_by="vsuess", ausloesende_buchung_id=42)
        b = svc._buchung.created[0]
        assert b.kategorie == "Sommerfest"
        assert z.ausloesende_buchung_id == 42

    def test_differenzbuchung_umgeht_kategorie_validierung(self):
        # Kassendifferenz ist NICHT in der erlaubten Auswahl – darf trotzdem gebucht werden.
        svc = _service(bestand_cent=10000, kategorie_repo=FakeKategorieRepo())
        z = svc.erstelle_zaehlung(1, {"5000": 3}, created_by="vsuess")  # ist 15000, diff +5000
        assert z.differenz_cent == 5000
        assert svc._buchung.created[0].kategorie == KASSENDIFFERENZ_KATEGORIE

    def test_ungueltige_stueckelung_legt_nichts_an(self):
        svc = _service(bestand_cent=0)
        with pytest.raises(ZaehlungUngueltigError):
            svc.erstelle_zaehlung(1, {"999": 1}, created_by="vsuess")
        assert svc._buchung.created == []
        assert svc._zaehlung.created == []
