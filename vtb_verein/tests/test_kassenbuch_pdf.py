"""Smoke-Tests für den Kassenbuch-PDF-Bericht.

Stellt sicher, dass der Bericht mit den #78-Ergänzungen (Erfasser-Spalte +
gezeichnete Büroklammer als Anhang-Kennzeichen) gültige PDF-Bytes erzeugt und
die Hilfsfunktionen sich korrekt verhalten.
"""
from datetime import date, datetime, timedelta, timezone

from reportlab.graphics.shapes import Drawing

from app.services.kassenbuch_pdf_service import (
    erstelle_kassenbuch_pdf, erstelle_zaehlprotokoll_pdf, _bueroklammer_flowable,
    _fmt_datum, _fmt_zeitstempel,
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


# ---------------------------------------------------------------------------
# Datums-/Zeitstempel-Formatierer
#
# Die Audit-Spalten sind TIMESTAMPTZ, psycopg liefert dafür datetime-Objekte statt
# Text. `datetime.fromisoformat` wirft darauf TypeError (nicht ValueError) – genau
# daran ist das Zählprotokoll-PDF still gescheitert, weil der Aufrufer den Fehler
# nur wegloggt. Deshalb hier beide Eingabeformen festnageln.
# ---------------------------------------------------------------------------

def test_fmt_zeitstempel_nimmt_datetime_objekt():
    ts = datetime(2026, 8, 22, 19, 5, 43, 512, tzinfo=timezone(timedelta(hours=2)))
    assert _fmt_zeitstempel(ts) == '22.08.2026 19:05'


def test_fmt_zeitstempel_nimmt_iso_string():
    assert _fmt_zeitstempel('2026-06-17 14:32:11.123') == '17.06.2026 14:32'


def test_fmt_zeitstempel_leer_und_unlesbar():
    assert _fmt_zeitstempel('') == ''
    assert _fmt_zeitstempel(None) == ''
    assert _fmt_zeitstempel('irgendwas') == 'irgendwas'


def test_fmt_datum_nimmt_date_und_datetime():
    assert _fmt_datum(date(2026, 8, 22)) == '22.08.2026'
    assert _fmt_datum(datetime(2026, 8, 22, 19, 5)) == '22.08.2026'


def test_fmt_datum_nimmt_iso_string_und_zeitstempel():
    assert _fmt_datum('2026-08-22') == '22.08.2026'
    assert _fmt_datum('2026-08-22 19:05:43') == '22.08.2026'
    assert _fmt_datum('') == ''
    assert _fmt_datum('kein Datum') == 'kein Datum'


def test_zaehlprotokoll_pdf_mit_datetime_zeitstempel_baut():
    """Der Fall aus der Praxis: created_at kommt als datetime aus Postgres."""
    pdf = erstelle_zaehlprotokoll_pdf(
        kasse_name='Imbisskasse',
        stueckelung={'5000': 2, '200': 13},
        ist_cent=12600, soll_cent=12500, differenz_cent=100,
        gezaehlt_am=datetime(2026, 8, 22, 19, 5, tzinfo=timezone.utc),
        gezaehlt_von='marion.reichert', belegnummer='11', notiz='Vereinsfest',
    )
    assert pdf.startswith(b'%PDF')
