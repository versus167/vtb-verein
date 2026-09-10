"""Tests für den Beleg-Scanner-PDF-Bauer (Ticket #197).

Prüft vor allem zwei Zusagen, die aus der Übernahme aus dem X1-ERP stammen:
die Seitengeometrie (lange Kante 297 mm, kurze nach Seitenverhältnis, randlos)
und dass die JPEG-Bytes unverändert ins PDF wandern.
"""
import io

import pytest
from PIL import Image
from reportlab.lib.units import mm

from app.services.scan_pdf_service import (
    LANGE_KANTE_MM,
    ScanFehlerError,
    ScanPdfService,
    zu_gross_meldung,
)


def jpeg(breite: int, hoehe: int, farbe=(200, 180, 160)) -> bytes:
    """Ein JPEG dieser Maße als Bytes."""
    puffer = io.BytesIO()
    Image.new("RGB", (breite, hoehe), farbe).save(puffer, format="JPEG", quality=86)
    return puffer.getvalue()


@pytest.fixture
def dienst():
    return ScanPdfService()


# --- Geometrie -------------------------------------------------------------

def test_hochformat_ergibt_hochformatige_seite(dienst):
    breite, hoehe = dienst.seitenmass_pt(1800, 2400)
    assert hoehe == pytest.approx(LANGE_KANTE_MM * mm)
    assert breite == pytest.approx(LANGE_KANTE_MM * mm * 1800 / 2400)
    assert breite < hoehe


def test_querformat_ergibt_querformatige_seite(dienst):
    breite, hoehe = dienst.seitenmass_pt(2400, 1800)
    assert breite == pytest.approx(LANGE_KANTE_MM * mm)
    assert hoehe == pytest.approx(LANGE_KANTE_MM * mm * 1800 / 2400)
    assert hoehe < breite


def test_kassenbon_wird_schmal_und_hoch(dienst):
    """Der Bon ist der Grund für die eigene Geometrie.

    Auf A4 mit Rand (``AnhangService.bild_zu_pdf``) läge er als Schnipsel
    mitten auf weißer Fläche; hier füllt er seine eigene schmale Seite.
    """
    breite, hoehe = dienst.seitenmass_pt(600, 2400)
    assert hoehe == pytest.approx(LANGE_KANTE_MM * mm)
    assert breite == pytest.approx(hoehe / 4)


def test_quadratisch_gilt_als_querformat(dienst):
    """Gleich lange Kanten: beide werden zur langen Kante, die Seite ist quadratisch."""
    breite, hoehe = dienst.seitenmass_pt(1000, 1000)
    assert breite == pytest.approx(LANGE_KANTE_MM * mm)
    assert hoehe == pytest.approx(LANGE_KANTE_MM * mm)


def test_lange_kante_ist_immer_gleich(dienst):
    """Egal welches Format — die lange Kante misst immer 297 mm."""
    for masse in [(1000, 4000), (4000, 1000), (2400, 2399), (10, 3000)]:
        seite = dienst.seitenmass_pt(*masse)
        assert max(seite) == pytest.approx(LANGE_KANTE_MM * mm)


def test_masslose_seite_wird_abgelehnt(dienst):
    with pytest.raises(ScanFehlerError):
        dienst.seitenmass_pt(0, 100)


# --- Prüfung ---------------------------------------------------------------

def test_ohne_seiten_kein_pdf(dienst):
    with pytest.raises(ScanFehlerError, match="Keine Seiten"):
        dienst.pruefe([])


def test_zu_viele_seiten(dienst):
    with pytest.raises(ScanFehlerError, match="20 Seiten"):
        dienst.pruefe([b"x"] * 21)


def test_leere_seite(dienst):
    with pytest.raises(ScanFehlerError, match="Seite 2 ist leer"):
        dienst.pruefe([b"x", b""])


def test_zu_grosse_seite():
    dienst = ScanPdfService(max_seite_bytes=1024)
    with pytest.raises(ScanFehlerError, match="Seite 1 ist größer"):
        dienst.pruefe([b"x" * 2048])


def test_kein_bild_wird_abgelehnt(dienst):
    with pytest.raises(ScanFehlerError, match="kein lesbares Bild"):
        dienst.baue([b"das ist kein Bild"])


# --- PDF-Aufbau ------------------------------------------------------------

def test_baut_ein_pdf_je_seite(dienst):
    pdf = dienst.baue([jpeg(1200, 1600), jpeg(1600, 1200)])
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert pdf.count(b"/Type /Page\n") == 2 or pdf.count(b"/Type /Page") >= 2


def test_jpeg_wandert_unveraendert_ins_pdf(dienst):
    """Kein Neukodieren: ReportLab bettet JPEG als DCTDecode-Strom ein.

    Das ist der eigentliche Zweck des Endpunkts — die 2400 px des Scanners
    sollen erhalten bleiben und nicht auf 1800 px / Q80 heruntergerechnet
    werden wie bei einem normalen Bild-Upload.
    """
    seite = jpeg(1200, 1600)
    pdf = dienst.baue([seite])
    assert b"/DCTDecode" in pdf
    # Die kompletten JPEG-Bytes stecken unverändert im PDF.
    assert seite in pdf


def test_ohne_ascii85_armierung(dienst):
    """Bildströme roh statt ASCII85 — sonst wäre das PDF ein Viertel größer.

    ReportLab kodiert Bildströme standardmäßig mit ASCII85. Der Inhalt bliebe
    derselbe, das PDF würde aber deutlich schwerer — und es geht zum Handy
    zurück und von dort wieder hoch.
    """
    pdf = dienst.baue([jpeg(1200, 1600)])
    assert b"ASCII85" not in pdf


def test_globaler_ascii85_schalter_wird_zurueckgesetzt(dienst):
    """Der Bau legt einen globalen ReportLab-Schalter um und wieder zurück."""
    import reportlab.rl_config as rl_config

    vorher = rl_config.useA85
    dienst.baue([jpeg(400, 500)])
    assert rl_config.useA85 == vorher

    # Auch wenn der Bau mittendrin scheitert.
    with pytest.raises(ScanFehlerError):
        dienst.baue([jpeg(400, 500), b"kaputt"])
    assert rl_config.useA85 == vorher


def test_seitenreihenfolge_bleibt(dienst):
    """Reihenfolge der Übergabe = Seitenreihenfolge im PDF."""
    erste = jpeg(600, 2400, (10, 20, 30))
    zweite = jpeg(2400, 600, (240, 235, 230))
    pdf = dienst.baue([erste, zweite])
    assert pdf.index(erste) < pdf.index(zweite)


def test_gleiche_bilddaten_werden_einmal_abgelegt(dienst):
    """ReportLab legt bildgleiche Seiten nur einmal ab — hier gepinnt.

    Der Cache-Schlüssel ist der *dekodierte* Pixelstrom ohne die Bildmaße
    (``Canvas.drawImage``). Zwei Seiten mit identischen Pixeln teilen sich
    deshalb ein XObject; das spart Platz und ist richtig, solange die Maße
    übereinstimmen.

    Für den Scanner ist der Sonderfall „gleiche Pixel, andere Maße" nicht
    erreichbar: Er normiert die lange Kante immer auf 2400 px, gleiche
    Pixelzahl bei vertauschten Kanten gäbe es also nur bei quadratischen
    Seiten — und dann sind die Maße wieder gleich.
    """
    seite = jpeg(800, 1000, (128, 128, 128))
    eins = dienst.baue([seite])
    zwei = dienst.baue([seite, seite])
    # Die zweite Seite kostet nur den Seiteneintrag, nicht das Bild.
    assert len(zwei) - len(eins) < len(seite) // 2


def test_seitenmasse_stehen_im_pdf(dienst):
    """Die MediaBox der Seite trägt die berechnete Größe, randlos."""
    pdf = dienst.baue([jpeg(1200, 1600)])
    breite, hoehe = dienst.seitenmass_pt(1200, 1600)
    erwartet = f"/MediaBox [ 0 0 {breite:.4f} {hoehe:.4f} ]".encode()
    assert erwartet in pdf


def test_png_geht_auch(dienst):
    """Der Scanner liefert JPEG, PNG bleibt als zweites Format erlaubt."""
    puffer = io.BytesIO()
    Image.new("RGB", (800, 1000), (10, 20, 30)).save(puffer, format="PNG")
    pdf = dienst.baue([puffer.getvalue()])
    assert pdf.startswith(b"%PDF-")


# --- Formatprüfung ---------------------------------------------------------
#
# Der Scanner selbst kann nur JPEG (oder, als Spec-Fallback, PNG) liefern: Er
# fasst nie eine Datei an, sondern kodiert Canvas-Pixel mit
# `toBlob(…, 'image/jpeg', 0.86)`. Der Endpunkt nimmt aber entgegen, was ihm
# geschickt wird — deshalb prüft der Dienst nach, statt es zu glauben.

@pytest.mark.parametrize("format_name", ["GIF", "TIFF", "BMP", "WEBP"])
def test_fremde_bildformate_werden_abgelehnt(dienst, format_name):
    """Lesbar heißt nicht erlaubt.

    Pillow öffnet all das anstandslos, und ohne Prüfung landete es im PDF —
    aber nicht so, wie der Docstring es zusagt: ReportLab dekodiert diese
    Formate und kodiert sie neu, statt die Bytes durchzureichen.
    """
    puffer = io.BytesIO()
    Image.new("RGB", (800, 1000), (90, 90, 90)).save(puffer, format=format_name)
    with pytest.raises(ScanFehlerError) as e:
        dienst.baue([puffer.getvalue()])
    assert format_name in str(e.value)


def test_meldung_nennt_die_betroffene_seite(dienst):
    """Bei mehreren Seiten muss klar sein, welche klemmt."""
    puffer = io.BytesIO()
    Image.new("RGB", (800, 1000), (90, 90, 90)).save(puffer, format="GIF")
    with pytest.raises(ScanFehlerError) as e:
        dienst.baue([jpeg(800, 1000), jpeg(800, 1000), puffer.getvalue()])
    assert "Seite 3" in str(e.value)


def test_heic_kann_gar_nicht_erst_ankommen():
    """Dokumentiert, warum iPhone-HEIC hier kein Thema ist.

    Nicht der Dienst hält HEIC ab, sondern die Bauweise des Scanners: Er liest
    keine Dateien, sondern kodiert Canvas-Pixel selbst. Das Kamerarollen-Format
    des Geräts spielt deshalb keine Rolle. Dieser Test hält die Voraussetzung
    dafür fest — gäbe es je einen Datei-Auswähler im Scanner, käme HEIC durch
    die Tür und diese Annahme wäre still falsch.
    """
    from pathlib import Path
    wurzel = Path(__file__).resolve().parents[2]
    scanner = (wurzel / "frontend/public/beleg-scanner.html").read_text(encoding="utf-8")
    js = (wurzel / "frontend/public/vendor/beleg-scan.js").read_text(encoding="utf-8")
    assert 'type="file"' not in scanner
    assert "FileReader" not in js
    assert "toBlob(res, 'image/jpeg'" in js


# --- Anhang-Grenze ---------------------------------------------------------
#
# Der Endpunkt gibt nur das PDF zurück; abgelegt wird es erst beim Speichern
# der Rechnung. Reißt es dort VTB_MAX_UPLOAD_MB, war alles umsonst — deshalb
# fällt die Entscheidung vorher. Geprüft wird sie hier als reine Funktion, ohne
# HTTP und Anmeldung (gleiche Bauart wie test_spa_fallback_404.py).

MB = 1024 * 1024


def test_passendes_pdf_meldet_nichts():
    assert zu_gross_meldung(19 * MB, 20 * MB) is None


def test_genau_auf_der_grenze_geht_noch_durch():
    """`größer als` heißt größer, nicht `größer oder gleich` — sonst scheiterte
    ausgerechnet der Beleg, der exakt passt."""
    assert zu_gross_meldung(20 * MB, 20 * MB) is None


def test_zu_grosses_pdf_wird_gemeldet():
    meldung = zu_gross_meldung(21 * MB, 20 * MB)
    assert meldung is not None
    assert "21.0 MB" in meldung
    assert "20 MB" in meldung


def test_meldung_nennt_den_ausweg():
    """Eine Grenze ohne Handlungsanweisung hilft niemandem auf dem Handy.

    Der Filter ist der wirksamste Hebel: „Dokument" wiegt rund ein Fünftel von
    „Farbe" — damit passt selbst ein voller 20-Seiten-Scan bequem.
    """
    meldung = zu_gross_meldung(30 * MB, 20 * MB)
    assert "Dokument" in meldung and "Farbe" in meldung
    assert "Weniger Seiten" in meldung


def test_bezeichnung_laesst_sich_setzen():
    """Vor dem Bau wiegt der Endpunkt die Seiten, danach das fertige PDF —
    die Meldung soll sagen, welches von beidem klemmt."""
    assert zu_gross_meldung(30 * MB, 20 * MB).startswith("Der Beleg")
    assert zu_gross_meldung(30 * MB, 20 * MB, was="Das fertige PDF").startswith(
        "Das fertige PDF")
