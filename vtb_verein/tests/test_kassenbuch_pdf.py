"""Smoke-Tests für den Kassenbuch-PDF-Bericht.

Stellt sicher, dass der Bericht mit den #78-Ergänzungen (Erfasser-Spalte +
gezeichnete Büroklammer als Anhang-Kennzeichen) gültige PDF-Bytes erzeugt und
die Hilfsfunktionen sich korrekt verhalten.
"""
from reportlab.graphics.shapes import Drawing

from app.services.kassenbuch_pdf_service import (
    erstelle_kassenbuch_pdf, _bueroklammer_flowable,
)


def _buchung(**over):
    b = dict(
        buchungsdatum='2026-06-05', belegnummer='2026-001',
        buchungstext='Startgeld Turnier', kategorie='Einnahme',
        einnahme_cent=5000, ausgabe_cent=0, notiz=None,
        exportiert_in_export_id=None, ist_storniert=False,
        anhang_count=0, created_by='kassenwart',
    )
    b.update(over)
    return b


def _pdf(buchungen, anfang=10000):
    return erstelle_kassenbuch_pdf(
        kasse_name='Hauptkasse', von_datum='2026-06-01', bis_datum='2026-06-30',
        buchungen=buchungen, anfangsbestand_cent=anfang, erstellt_von='admin',
    )


def test_pdf_mit_erfasser_und_anhang_baut():
    """Buchung mit Anhang (Büroklammer) + Erfasser darf nicht crashen."""
    buchungen = [
        _buchung(anhang_count=2, created_by='kassenwart'),
        _buchung(belegnummer='2026-002', buchungstext='Hallenmiete',
                 einnahme_cent=0, ausgabe_cent=3000, created_by='vorstand',
                 exportiert_in_export_id=7),
        _buchung(belegnummer='2026-003', buchungstext='Stornierte Buchung',
                 ist_storniert=True, anhang_count=1, created_by='kassenwart'),
    ]
    pdf = _pdf(buchungen)
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_pdf_leere_buchungsliste_baut():
    pdf = _pdf([])
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_pdf_ohne_created_by_baut():
    """Alt-Buchungen ohne created_by (None) müssen sauber durchlaufen."""
    pdf = _pdf([_buchung(created_by=None, anhang_count=0)])
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_pdf_langer_text_und_kategorie_bricht_um():
    """Lange Buchungstexte/Kategorien (auch ein langes Einzelwort) dürfen die
    Nachbarspalte nicht sprengen – sie werden als Paragraph umgebrochen."""
    buchungen = [
        _buchung(buchungstext='Sammelüberweisung Mitgliedsbeiträge Quartal inkl. Nachzahlungen',
                 kategorie='Kassendifferenzbereinigung', created_by='sehr.langer.benutzername',
                 anhang_count=1),
    ]
    pdf = _pdf(buchungen)
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_bueroklammer_ist_drawing():
    d = _bueroklammer_flowable()
    assert isinstance(d, Drawing)
    assert d.width > 0 and d.height > 0
