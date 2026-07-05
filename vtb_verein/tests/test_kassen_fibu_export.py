"""
Tests für den FBASC-Kassenexport (hmd):
- Formatter: Feld 39 (Dokument zur Erfassung)
- KassenbuchService.exportiere_fbasc: Positionen (Konto/Gegenkonto/S-H/Kost/Kostr),
  Feld-39-Belegreferenz, Zusatzbeleg- und Bericht-0,00-Zeilen, Zip-Struktur (flach)
- Validierung: fehlendes Sachkonto / Gegenkonto
- zuruecknehmen_export: nur jüngster Lauf, Stempel lösen + soft-delete
"""
import io
import zipfile
from types import SimpleNamespace

import pytest

from app.models.fibu import FibuEinstellungen, FibuExportPosition
from app.models.kasse import Kasse, KassenKategorie, KassenbuchExport, KassenbuchungAnhang
from app.services import fibu_formatter as ff
from app.services.kassenbuch_service import KassenbuchService, FibuKassenExportFehler


# ---------------------------------------------------------------------------
# Formatter – Feld 39
# ---------------------------------------------------------------------------

def test_formatter_feld39_dokument():
    f = ff.felder(FibuExportPosition(konto="1000", gegenkonto="4400", betrag=10.0,
                                     soll_haben="S", kontenart="S", dokument="B1.pdf"))
    assert f[39] == "B1.pdf"
    assert f[19] == "S"          # Kontenart Sachkonto
    assert f[0] == "1000"


def test_formatter_feld39_leer_wenn_kein_dokument():
    f = ff.felder(FibuExportPosition(konto="1000", gegenkonto="4400", betrag=10.0, soll_haben="S"))
    assert f[39] == ""


# ---------------------------------------------------------------------------
# Service-Setup mit Fake-Repos
# ---------------------------------------------------------------------------

def _buchung(id, datum, beleg, text, kategorie, einnahme=0, ausgabe=0):
    return dict(id=id, buchungsdatum=datum, belegnummer=beleg, buchungstext=text,
                kategorie=kategorie, einnahme_cent=einnahme, ausgabe_cent=ausgabe)


def _service(kasse, buchungen, kategorien, anhaenge_by_buchung, upload_path,
             *, abteilung_kostenstelle=None, kassendifferenz_gegenkonto=None, calls=None):
    calls = calls if calls is not None else {}

    def create_export(export, exported_by):
        export.id = 42
        calls["create_export"] = export
        return export

    export_repo = SimpleNamespace(
        get_nicht_exportierte_buchungen=lambda kid, bis: list(buchungen),
        get_buchungen_fuer_export=lambda eid: list(buchungen),
        create_export=create_export,
        update_dateiname=lambda eid, name: calls.__setitem__("dateiname", name),
        get_export=lambda eid: calls.get("export_obj"),
        is_latest_export=lambda eid: calls.get("is_latest", True),
        soft_delete=lambda eid, by: calls.__setitem__("soft_delete", (eid, by)) or True,
    )
    buchung_repo = SimpleNamespace(
        mark_buchungen_exportiert=lambda ids, eid: calls.__setitem__("mark", (ids, eid)) or len(ids),
        unmark_buchungen_exportiert=lambda eid: calls.__setitem__("unmark", eid) or 7,
    )
    kasse_repo = SimpleNamespace(get_kasse=lambda kid: kasse)
    kategorie_repo = SimpleNamespace(list_for_kasse=lambda kid: list(kategorien))
    anhang_repo = SimpleNamespace(list_by_buchung=lambda bid: list(anhaenge_by_buchung.get(bid, [])))
    anhang_service = SimpleNamespace(upload_path=upload_path)
    abteilung_repo = SimpleNamespace(
        get_abteilung=lambda aid: SimpleNamespace(kostenstelle=abteilung_kostenstelle))
    einst_repo = SimpleNamespace(
        get=lambda: FibuEinstellungen(verein_kostenstelle=12, default_kostentraeger=1,
                                      kassendifferenz_gegenkonto=kassendifferenz_gegenkonto))

    svc = KassenbuchService(
        kasse_repo=kasse_repo, buchung_repo=buchung_repo, export_repo=export_repo,
        berechtigung_repo=SimpleNamespace(), anhang_repo=anhang_repo,
        anhang_service=anhang_service, kategorie_repo=kategorie_repo,
        abteilung_repo=abteilung_repo, fibu_einstellungen_repo=einst_repo,
    )
    # Bericht-PDF nicht real rendern – hier nur den Zip-/Zeilen-Aufbau testen.
    svc._erzeuge_bericht_pdf = lambda k, von, bis, by: b"%PDF-bericht"
    return svc, calls


def _zeilen(fbasc_bytes):
    text = fbasc_bytes.decode("utf-8")
    return [z.split(";") for z in text.split("\r\n") if z]


# ---------------------------------------------------------------------------
# exportiere_fbasc – Happy Path
# ---------------------------------------------------------------------------

def test_export_zip_struktur_und_zeilen(tmp_path):
    # Belegdateien auf Platte ablegen
    (tmp_path / "kabu_000001.jpg").write_bytes(b"JPGDATA")
    (tmp_path / "kabu_000002.pdf").write_bytes(b"PDFDATA")

    kasse = Kasse(name="Handkasse Turnen", sachkonto="1000", abteilung_id=5, id=3)
    buchungen = [
        _buchung(1, "2026-06-05", "B1", "Startgelder Juni", "Startgelder", einnahme=1000),
        _buchung(2, "2026-06-20", "B2", "Hallenmiete", "Miete", ausgabe=500),
    ]
    kategorien = [
        KassenKategorie(name="Startgelder", gegenkonto="4400"),
        KassenKategorie(name="Miete", gegenkonto="4830"),
    ]
    anhaenge = {1: [
        KassenbuchungAnhang(id=1, buchung_id=1, original_name="foto.jpg", stored_name="kabu_000001.jpg"),
        KassenbuchungAnhang(id=2, buchung_id=1, original_name="rg.pdf", stored_name="kabu_000002.pdf"),
    ]}
    svc, calls = _service(kasse, buchungen, kategorien, anhaenge, tmp_path,
                          abteilung_kostenstelle=100)

    dateiname, zip_bytes = svc.exportiere_fbasc(3, "2026-06-30", "tester", user_id=None)

    assert dateiname == "handkasse-turnen-export-42.zip"
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    namen = set(zf.namelist())
    # flaches Zip: fbasc.hia + Belege + Bericht, alles im Root
    assert "fbasc.hia" in namen
    assert "B1.jpg" in namen and zf.read("B1.jpg") == b"JPGDATA"
    assert "B1-2.pdf" in namen and zf.read("B1-2.pdf") == b"PDFDATA"
    assert "bericht-2026-06-05-bis-2026-06-30.pdf" in namen
    assert not any("/" in n for n in namen)   # keine Unterordner

    zeilen = _zeilen(zf.read("fbasc.hia"))
    # 2 Buchungen + 1 Zusatzbeleg-Zeile + 1 Bericht-Zeile = 4
    assert len(zeilen) == 4

    b1, extra, b2, bericht = zeilen
    # Buchung 1: Einnahme → Kasse im Soll, Gegenkonto 4400, Beleg B1.jpg
    assert b1[0] == "1000" and b1[1] == "4400" and b1[2] == "10,00" and b1[3] == "S"
    assert b1[7] == "100" and b1[8] == "1"       # Kostenstelle (Abteilung) / Kostenträger
    assert b1[19] == "S" and b1[39] == "B1.jpg"
    # Zusatzbeleg-Zeile: 0,00 auf DENSELBEN Konten wie Buchung 1 (kein Selbstbuchungs-Split)
    assert extra[0] == "1000" and extra[1] == "4400" and extra[2] == "0,00" and extra[3] == "S"
    assert extra[39] == "B1-2.pdf"
    # Buchung 2: Ausgabe → Kasse im Haben, Gegenkonto 4830, ohne Beleg
    assert b2[0] == "1000" and b2[1] == "4830" and b2[2] == "5,00" and b2[3] == "H"
    assert b2[39] == ""
    # Bericht-Zeile: 0,00, erbt die Konten der LETZTEN Buchung (b2), trägt das Bericht-PDF
    assert bericht[0] == "1000" and bericht[1] == "4830" and bericht[2] == "0,00" and bericht[3] == "H"
    assert bericht[39] == "bericht-2026-06-05-bis-2026-06-30.pdf"

    # Buchungen wurden gesperrt
    assert calls["mark"] == ([1, 2], 42)
    assert calls["create_export"].format == "fbasc"


def test_kostentraeger_override_je_kategorie(tmp_path):
    # Kategorie mit eigenem Kostenträger (Feld 08) überschreibt den Default (1).
    kasse = Kasse(name="K", sachkonto="1000", id=1)
    buchungen = [
        _buchung(1, "2026-06-01", "B1", "Turnier", "Turnier", einnahme=500),
        _buchung(2, "2026-06-02", "B2", "Sonstiges", "Sonstiges", einnahme=100),
    ]
    kategorien = [
        KassenKategorie(name="Turnier", gegenkonto="4400", kostentraeger=7),
        KassenKategorie(name="Sonstiges", gegenkonto="4400"),  # kein Override -> Default
    ]
    svc, _ = _service(kasse, buchungen, kategorien, {}, tmp_path)
    _, zip_bytes = svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)
    zeilen = _zeilen(zipfile.ZipFile(io.BytesIO(zip_bytes)).read("fbasc.hia"))
    assert zeilen[0][8] == "7"   # Turnier -> Override
    assert zeilen[1][8] == "1"   # Sonstiges -> Default aus Fibu-Einstellungen


def test_export_ohne_abteilung_nutzt_verein_kostenstelle(tmp_path):
    kasse = Kasse(name="Vereinskasse", sachkonto="1000", abteilung_id=None, id=1)
    buchungen = [_buchung(9, "2026-06-01", "B9", "Spende", "Spenden", einnahme=200)]
    kategorien = [KassenKategorie(name="Spenden", gegenkonto="4200")]
    svc, _ = _service(kasse, buchungen, kategorien, {}, tmp_path)

    _, zip_bytes = svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    b9 = _zeilen(zf.read("fbasc.hia"))[0]
    assert b9[7] == "12"        # Verein-Kostenstelle aus FibuEinstellungen


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

def test_export_fehlt_sachkonto(tmp_path):
    kasse = Kasse(name="Ohne Konto", sachkonto=None, id=1)
    buchungen = [_buchung(1, "2026-06-01", "B1", "x", "Startgelder", einnahme=100)]
    kategorien = [KassenKategorie(name="Startgelder", gegenkonto="4400")]
    svc, _ = _service(kasse, buchungen, kategorien, {}, tmp_path)
    with pytest.raises(FibuKassenExportFehler) as ei:
        svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)
    assert any("Sachkonto" in f for f in ei.value.fehler)


def test_export_fehlt_gegenkonto(tmp_path):
    kasse = Kasse(name="K", sachkonto="1000", id=1)
    buchungen = [_buchung(1, "2026-06-01", "B1", "x", "Unbekannt", einnahme=100)]
    kategorien = [KassenKategorie(name="Startgelder", gegenkonto="4400")]
    svc, _ = _service(kasse, buchungen, kategorien, {}, tmp_path)
    with pytest.raises(FibuKassenExportFehler) as ei:
        svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)
    assert any("Gegenkonto" in f and "Unbekannt" in f for f in ei.value.fehler)


def test_kassendifferenz_gegenkonto_aus_einstellungen(tmp_path):
    # System-Kategorie „Kassendifferenz" ist keine verwaltete Kategorie → Gegenkonto
    # kommt aus den Fibu-Einstellungen.
    kasse = Kasse(name="K", sachkonto="1000", id=1)
    buchungen = [_buchung(1, "2026-06-30", "Z1", "Kassensturz", "Kassendifferenz", ausgabe=37)]
    svc, _ = _service(kasse, buchungen, [], {}, tmp_path, kassendifferenz_gegenkonto="6970")
    _, zip_bytes = svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)
    z = _zeilen(zipfile.ZipFile(io.BytesIO(zip_bytes)).read("fbasc.hia"))[0]
    assert z[0] == "1000" and z[1] == "6970" and z[3] == "H"


def test_kassendifferenz_ohne_gegenkonto_meldet_einstellungen(tmp_path):
    kasse = Kasse(name="K", sachkonto="1000", id=1)
    buchungen = [_buchung(1, "2026-06-30", "Z1", "Kassensturz", "Kassendifferenz", ausgabe=37)]
    svc, _ = _service(kasse, buchungen, [], {}, tmp_path, kassendifferenz_gegenkonto=None)
    with pytest.raises(FibuKassenExportFehler) as ei:
        svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)
    assert any("Fibu-Einstellungen" in f and "Kassendifferenz" in f for f in ei.value.fehler)


def test_export_keine_buchungen(tmp_path):
    kasse = Kasse(name="K", sachkonto="1000", id=1)
    svc, _ = _service(kasse, [], [], {}, tmp_path)
    with pytest.raises(ValueError):
        svc.exportiere_fbasc(1, "2026-06-30", "tester", user_id=None)


# ---------------------------------------------------------------------------
# Un-Export
# ---------------------------------------------------------------------------

def test_zuruecknehmen_nur_juengster(tmp_path):
    kasse = Kasse(name="K", sachkonto="1000", id=1)
    export = KassenbuchExport(kasse_id=1, zeitraum_von="2026-06-01", zeitraum_bis="2026-06-30",
                              dateiname="k-export-5.zip", anzahl_buchungen=3, id=5, format="fbasc")
    svc, calls = _service(kasse, [], [], {}, tmp_path)
    calls["export_obj"] = export

    # Nicht der jüngste → abgelehnt
    calls["is_latest"] = False
    with pytest.raises(ValueError):
        svc.zuruecknehmen_export(5, "tester", user_id=None)
    assert "unmark" not in calls and "soft_delete" not in calls

    # Jüngster → Stempel lösen + soft-delete
    calls["is_latest"] = True
    res = svc.zuruecknehmen_export(5, "tester", user_id=None)
    assert res == {"zurueckgenommen": 5, "buchungen_wieder_offen": 7}
    assert calls["unmark"] == 5
    assert calls["soft_delete"] == (5, "tester")
