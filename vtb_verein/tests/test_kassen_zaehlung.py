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
from datetime import datetime, timedelta, timezone

import pytest

from app.models.kasse import (
    Kasse, Kassenbuchung, KassenbuchungAnhang, KassenKategorie, KassenZaehlung,
)
from app.services.kassenbuch_service import (
    KassenbuchService,
    ZaehlungUngueltigError,
    KategorieUngueltigError,
    KASSENDIFFERENZ_KATEGORIE,
    zaehlprotokoll_dateiname,
)

# So liefert psycopg eine TIMESTAMPTZ-Spalte: als datetime, nicht als Text.
DB_ZEITSTEMPEL = datetime(2026, 8, 22, 19, 5, 43, tzinfo=timezone(timedelta(hours=2)))


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
        for b in self.created:
            if b.id == buchung_id:
                return b
        raise KeyError(buchung_id)


class FakeExportRepo:
    def get_letztes_bis_datum(self, kasse_id): return None
    def ist_buchung_gesperrt(self, buchung_id): return False


class FakeZaehlungRepo:
    def __init__(self, created_at=DB_ZEITSTEMPEL):
        self.created = []
        self._created_at = created_at

    def create(self, zaehlung, created_by):
        zaehlung.id = 55
        zaehlung.created_by = created_by
        zaehlung.created_at = self._created_at
        self.created.append(zaehlung)
        return zaehlung

    def get(self, zaehlung_id):
        for z in self.created:
            if z.id == zaehlung_id:
                return z
        return None


class FakeAnhangRepo:
    """Hält die Anhänge im Speicher – reicht für Anlegen, Auflisten, Soft-Delete."""

    def __init__(self):
        self.anhaenge: list[KassenbuchungAnhang] = []
        self._next_id = 900

    def create(self, anhang: KassenbuchungAnhang) -> KassenbuchungAnhang:
        anhang.id = self._next_id
        anhang.stored_name = f"{anhang.id}.pdf"
        self._next_id += 1
        self.anhaenge.append(anhang)
        return anhang

    def list_by_buchung(self, buchung_id):
        return [a for a in self.anhaenge
                if a.buchung_id == buchung_id and a.deleted_at is None]

    def mark_deleted(self, anhang_id, deleted_by):
        for a in self.anhaenge:
            if a.id == anhang_id:
                a.deleted_at = "jetzt"
                a.deleted_by = deleted_by
                return True
        return False


class FakeAnhangService:
    """Schreibt „auf Platte" nur ins Dict; `schreib_fehler` erzwingt einen IOError."""

    def __init__(self, schreib_fehler: bool = False):
        self.dateien: dict[str, bytes] = {}
        self.schreib_fehler = schreib_fehler

    def validiere(self, mime_type, dateigroesse):
        assert mime_type == "application/pdf"

    def schreibe(self, stored_name, inhalt):
        if self.schreib_fehler:
            raise IOError("Platte voll")
        self.dateien[stored_name] = inhalt


class FakeKategorieRepo:
    """Gibt eine Auswahl ohne „Kassendifferenz" zurück – um zu prüfen, dass die
    Differenzbuchung die Kategorie-Validierung umgeht."""
    def list_for_kasse(self, kasse_id):
        return [KassenKategorie(id=1, name="Spende", kasse_id=None)]


def _service(bestand_cent, ausloeser=None, kategorie_repo=None,
             anhang_repo=None, anhang_service=None, created_at=DB_ZEITSTEMPEL):
    return KassenbuchService(
        kasse_repo=FakeKasseRepo(bestand_cent),
        buchung_repo=FakeBuchungRepo(ausloeser),
        export_repo=FakeExportRepo(),
        berechtigung_repo=None,
        anhang_repo=anhang_repo,
        anhang_service=anhang_service,
        kategorie_repo=kategorie_repo,
        zaehlung_repo=FakeZaehlungRepo(created_at),
    )


def _service_mit_anhaengen(bestand_cent, schreib_fehler=False, **kw):
    """Service mit Anhang-Ablage – nur so läuft der Protokoll-PDF-Pfad überhaupt."""
    return _service(
        bestand_cent,
        anhang_repo=FakeAnhangRepo(),
        anhang_service=FakeAnhangService(schreib_fehler),
        **kw,
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


class TestKategorieGetriebeneZaehlung:
    """Ticket #38: Wählt man eine „mit Zählung"-Kategorie, IST die Zählung die Buchung
    dieser Kategorie – Betrag = Zählung (Ist) − Altbestand (Soll)."""

    def test_zaehlung_bucht_unter_gewaehlter_kategorie(self):
        svc = _service(bestand_cent=10000, kategorie_repo=FakeKategorieRepo())  # Altbestand 100 €
        z = svc.erstelle_zaehlung(
            1, {"5000": 3}, created_by="vsuess",          # Ist 150 €
            kategorie="Spende", buchungstext="Imbiss Tageseinnahmen",
        )
        assert z.ist_cent == 15000
        assert z.soll_cent == 10000           # Altbestand eingefroren
        assert z.differenz_cent == 5000       # = Tageseinnahmen
        b = svc._buchung.created[0]
        assert b.kategorie == "Spende"
        assert b.buchungstext == "Imbiss Tageseinnahmen"
        assert b.einnahme_cent == 5000 and b.ausgabe_cent == 0

    def test_negative_differenz_wird_ausgabe(self):
        svc = _service(bestand_cent=15000, kategorie_repo=FakeKategorieRepo())  # Altbestand 150 €
        z = svc.erstelle_zaehlung(
            1, {"5000": 2}, created_by="vsuess",          # Ist 100 €
            kategorie="Spende", buchungstext="Korrektur",
        )
        assert z.differenz_cent == -5000
        b = svc._buchung.created[0]
        assert b.ausgabe_cent == 5000 and b.einnahme_cent == 0

    def test_unzulaessige_kategorie_wirft_und_legt_nichts_an(self):
        svc = _service(bestand_cent=10000, kategorie_repo=FakeKategorieRepo())
        with pytest.raises(KategorieUngueltigError):
            svc.erstelle_zaehlung(
                1, {"5000": 3}, created_by="vsuess",
                kategorie="Imbiss",            # nicht in der erlaubten Auswahl (nur „Spende")
                buchungstext="x",
            )
        assert svc._buchung.created == []
        assert svc._zaehlung.created == []


class TestZaehlprotokollAnhang:
    """Das Zählprotokoll-PDF muss an der Zähl-Buchung hängen.

    Regression: Seit die Audit-Spalten TIMESTAMPTZ sind, kommt `created_at` als
    datetime aus der DB. Der PDF-Bau ist daran mit TypeError gescheitert – und weil
    das Anhängen best-effort ist, wurde der Fehler nur geloggt: Die Zählung war
    gebucht, das Protokoll fehlte still an der Buchung.
    """

    def test_protokoll_haengt_an_der_buchung(self):
        svc = _service_mit_anhaengen(bestand_cent=12500)
        z = svc.erstelle_zaehlung(1, {"5000": 2, "200": 13}, created_by="vsuess", user_id=7, is_admin=True)

        anhang = svc.protokoll_anhang(z)
        assert anhang is not None
        assert anhang.original_name == zaehlprotokoll_dateiname(z.id)
        assert anhang.mime_type == "application/pdf"
        assert anhang.buchung_id == svc._buchung.created[0].id
        assert anhang.hochgeladen_von == 7
        assert svc._anhang_service.dateien[anhang.stored_name].startswith(b"%PDF")

    def test_protokoll_haengt_auch_bei_text_zeitstempel(self):
        """Ältere Bestände/SQLite-Reste liefern den Zeitstempel als Text."""
        svc = _service_mit_anhaengen(bestand_cent=12500, created_at="2026-06-17 14:32:00")
        z = svc.erstelle_zaehlung(1, {"5000": 2}, created_by="vsuess", user_id=7, is_admin=True)
        assert svc.protokoll_anhang(z) is not None

    def test_ohne_user_id_kein_protokoll(self):
        """Interne Aufrufe ohne Benutzer (Skripte/Tests) buchen, hängen aber nichts an."""
        svc = _service_mit_anhaengen(bestand_cent=12500)
        z = svc.erstelle_zaehlung(1, {"5000": 2}, created_by="system")
        assert svc.protokoll_anhang(z) is None

    def test_schreibfehler_haelt_die_zaehlung_nicht_auf(self):
        svc = _service_mit_anhaengen(bestand_cent=12500, schreib_fehler=True)
        z = svc.erstelle_zaehlung(1, {"5000": 2}, created_by="vsuess", user_id=7, is_admin=True)
        assert z.id == 55                      # Zählung + Buchung sind da …
        assert svc._buchung.created            # …
        assert svc.protokoll_anhang(z) is None  # … nur das Protokoll fehlt

    def test_fremder_beleg_gilt_nicht_als_protokoll(self):
        """Ein hochgeladenes Foto an derselben Buchung ist kein Zählprotokoll."""
        svc = _service_mit_anhaengen(bestand_cent=12500)
        z = svc.erstelle_zaehlung(1, {"5000": 2}, created_by="vsuess")
        svc._anhang_repo.create(KassenbuchungAnhang(
            buchung_id=z.buchung_id, original_name="kassenzettel.pdf",
            mime_type="application/pdf",
        ))
        assert svc.protokoll_anhang(z) is None

    def test_protokoll_ohne_buchung_ist_none(self):
        svc = _service_mit_anhaengen(bestand_cent=0)
        zaehlung = KassenZaehlung(kasse_id=1, ist_cent=0, soll_cent=0, differenz_cent=0,
                                 id=1, buchung_id=None)
        assert svc.protokoll_anhang(zaehlung) is None


class TestProtokollNachtragen:
    """Fehlt das Protokoll (alter Bestand oder Fehlschlag), lässt es sich nachtragen."""

    def _zaehlung_ohne_protokoll(self, bestand_cent=12500):
        svc = _service_mit_anhaengen(bestand_cent, schreib_fehler=True)
        z = svc.erstelle_zaehlung(1, {"5000": 2}, created_by="marion.reichert", user_id=7, is_admin=True)
        svc._anhang_service.schreib_fehler = False   # Ablage ist wieder in Ordnung
        return svc, z

    def test_nachtragen_haengt_das_protokoll_an(self):
        svc, z = self._zaehlung_ohne_protokoll()
        assert svc.protokoll_anhang(z) is None

        anhang = svc.protokoll_nachtragen(1, z.id, user_id=3, is_admin=True)
        assert anhang.original_name == zaehlprotokoll_dateiname(z.id)
        assert anhang.hochgeladen_von == 3            # nachgetragen hat ein anderer …
        assert svc.protokoll_anhang(z).id == anhang.id
        assert svc._anhang_service.dateien[anhang.stored_name].startswith(b"%PDF")

    def test_nachtragen_ist_idempotent(self):
        svc, z = self._zaehlung_ohne_protokoll()
        erst = svc.protokoll_nachtragen(1, z.id, user_id=3, is_admin=True)
        nochmal = svc.protokoll_nachtragen(1, z.id, user_id=3, is_admin=True)
        assert nochmal.id == erst.id
        assert len(svc._anhang_repo.list_by_buchung(z.buchung_id)) == 1

    def test_nachtragen_prueft_die_kasse(self):
        svc, z = self._zaehlung_ohne_protokoll()
        with pytest.raises(KeyError):
            svc.protokoll_nachtragen(2, z.id, user_id=3, is_admin=True)

    def test_nachtragen_unbekannte_zaehlung_wirft(self):
        svc, _ = self._zaehlung_ohne_protokoll()
        with pytest.raises(KeyError):
            svc.protokoll_nachtragen(1, 999, user_id=3, is_admin=True)
