"""Smoke-Tests für den Übungsleiter-Stundennachweis-Beleg (PDF).

Stellt sicher, dass der Beleg in beiden Layout-Varianten gebaut wird: kompakt
(ohne Angebot-Spalte) und mit Angebot-Spalte, sobald mindestens ein Termin einen
Angebot-Text trägt. Geprüft wird, dass gültige PDF-Bytes entstehen (kein Crash).
"""
from datetime import date, datetime, timezone

from reportlab.pdfbase.pdfmetrics import stringWidth

from app.services.ul_stundennachweis_pdf_service import (
    erstelle_stundennachweis_pdf, _fmt_datum, _fmt_datum_kurz_wt, _kuerzen,
    _verein_zeile, _verguetungs_rows,
)


_VEREIN = {'name': 'TV Musterstadt', 'strasse': 'Hauptstr. 1',
           'plz_ort': '12345 Musterstadt', 'registrier_nr': 'VR 42'}


def _pdf(termine, **extra):
    return erstelle_stundennachweis_pdf(
        verein=_VEREIN, ul_name='Max Mustermann', sportart='Fußball', iban='DE00…',
        trainerlizenz_nr=None, qualifikation=None, lizenz_klassifikation='ohne_lizenz',
        foerder_klassifikation=None, zeitraum_von='2026-06-01', zeitraum_bis='2026-06-30',
        termine=termine,
        summen={'summe_stunden': 4.0, 'verguetung_pro_stunde': 10.0, 'gesamtbetrag': 40.0,
                'monatssummen': {'2026-06': 4.0}, 'anzahl_termine': 2},
        **extra,
    )


def test_beleg_mit_angebot_spalte():
    termine = [
        {'datum': '2026-06-02', 'stunden': 2.0, 'wochentag': 2, 'angebot': 'Training'},
        {'datum': '2026-06-06', 'stunden': 2.0, 'wochentag': 6, 'angebot': 'Spiel'},
    ]
    pdf = _pdf(termine)
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_beleg_ohne_angebot_bleibt_kompakt():
    termine = [
        {'datum': '2026-06-02', 'stunden': 2.0, 'wochentag': 2, 'angebot': None},
        {'datum': '2026-06-09', 'stunden': 2.0, 'wochentag': 2, 'angebot': ''},
    ]
    pdf = _pdf(termine)
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_beleg_dichter_monat_bricht_um_statt_zu_crashen():
    """Ein Monat mit vielen Terminen wird höher als eine Seite. Die Monatstabelle muss
    über Seiten umbrechen (direkt in der Story, nicht verschachtelt) – sonst LayoutError."""
    termine = [{'datum': f'2026-06-{tag:02d}', 'stunden': 1.5} for tag in range(1, 31)]
    pdf = _pdf(termine)
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_beleg_mit_erfasser_und_bestaetiger_nachweis():
    """Erfasser/Bestätiger + Zeitstempel (#67) – timestamptz kommt als datetime,
    der Beleg muss damit umgehen (kein Crash)."""
    termine = [{'datum': '2026-06-02', 'stunden': 2.0, 'wochentag': 2}]
    pdf = _pdf(
        termine,
        eingereicht_von='Erika Erfasserin',
        eingereicht_am=datetime(2026, 7, 1, 10, 30, tzinfo=timezone.utc),
        bestaetigt_von='Bernd Bestätiger',
        bestaetigt_am=datetime(2026, 7, 3, 9, 15, tzinfo=timezone.utc),
    )
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000


def test_verein_zeile_ohne_registriernummer():
    """Ohne Nummer bleibt die Beschriftung weg statt leer zu enden — nicht jeder
    Verein hat eine, und eine frische Instanz hat sie noch nicht konfiguriert."""
    assert _verein_zeile(_VEREIN) == 'TV Musterstadt – Registrier-Nr. VR 42'
    assert _verein_zeile({'name': 'TV Musterstadt'}) == 'TV Musterstadt'
    assert _verein_zeile({'name': 'TV Musterstadt', 'registrier_nr': '  '}) == 'TV Musterstadt'


def test_fmt_datum_akzeptiert_datetime_date_und_iso():
    assert _fmt_datum(datetime(2026, 7, 1, 10, 30)) == '01.07.2026'
    assert _fmt_datum(date(2026, 7, 1)) == '01.07.2026'
    assert _fmt_datum('2026-07-01T10:30:00+00:00') == '01.07.2026'
    assert _fmt_datum('2026-07-01') == '01.07.2026'
    assert _fmt_datum(None) == ''


def test_fmt_datum_kurz_wt_kompakt_mit_wochentag():
    # 06.01.2025 ist ein Montag, 11.01.2025 ein Samstag
    assert _fmt_datum_kurz_wt(date(2025, 1, 6)) == '06.01.25,Mo'
    assert _fmt_datum_kurz_wt(datetime(2025, 1, 6, 8, 0)) == '06.01.25,Mo'
    assert _fmt_datum_kurz_wt('2025-01-11') == '11.01.25,Sa'


def test_kuerzen_haelt_spaltenbreite_ein():
    # kurzer Text bleibt unverändert
    assert _kuerzen('Turnen', 200) == 'Turnen'
    assert _kuerzen('', 200) == '' and _kuerzen(None, 200) == ''
    # langer Text wird mit '…' auf die Breite gekürzt und bleibt darunter
    lang = 'Kinderturnen Gruppe A (Halle 2), Aufwärmen + Geräte'
    max_pt = 90
    gek = _kuerzen(lang, max_pt)
    assert gek.endswith('…') and len(gek) < len(lang)
    assert stringWidth(gek, 'Helvetica', 8) <= max_pt


# ---------------------------------------------------------------------------
# Vergütungsblock je Vergütungsart (#84)
# ---------------------------------------------------------------------------

def test_verguetungsblock_stundensatz_bleibt_wie_bisher():
    rows = _verguetungs_rows({'verguetungsart': 'stundensatz',
                              'verguetung_pro_stunde': 10.0, 'gesamtbetrag': 40.0})
    assert [r[0] for r in rows] == ['Vergütung / h', 'Gesamtbetrag']
    assert rows[1][1] == '40,00 €'


def test_verguetungsblock_ohne_art_faellt_auf_stundensatz_zurueck():
    # Altbestand/Belege ohne die neue Angabe dürfen sich nicht verändern.
    rows = _verguetungs_rows({'verguetung_pro_stunde': 10.0, 'gesamtbetrag': 40.0})
    assert [r[0] for r in rows] == ['Vergütung / h', 'Gesamtbetrag']


def test_verguetungsblock_monatspauschale_weist_die_monate_aus():
    rows = _verguetungs_rows({'verguetungsart': 'monatspauschale',
                              'verguetung_pro_stunde': 150.0, 'anzahl_monate': 3,
                              'monate_im_zeitraum': 3, 'gesamtbetrag': 450.0})
    assert [r[0] for r in rows] == ['Monatspauschale', 'Vergütete Monate', 'Gesamtbetrag']
    assert rows[1][1] == '3' and rows[2][1] == '450,00 €'


def test_verguetungsblock_nennt_den_schon_verguteten_monat():
    """Ein Monat läuft über eine frühere Abrechnung – der Beleg muss zeigen, warum
    hier nur einer bezahlt wird, sonst sieht die Zahl nach einem Fehler aus."""
    rows = _verguetungs_rows({'verguetungsart': 'monatspauschale',
                              'verguetung_pro_stunde': 150.0, 'anzahl_monate': 1,
                              'monate_im_zeitraum': 2, 'gesamtbetrag': 150.0})
    assert rows[1] == ['Vergütete Monate', '1 von 2 im Zeitraum']


def test_verguetungsblock_ohne_verguetung_nennt_keinen_betrag():
    # Eine 0,00-€-Zeile würde behaupten, der ÜL bekomme nichts – er bekommt es nur
    # nicht über die App.
    rows = _verguetungs_rows({'verguetungsart': 'ohne_verguetung',
                              'verguetung_pro_stunde': 0.0, 'gesamtbetrag': None})
    assert rows == [['Vergütung', 'nach gesonderter Vereinbarung']]


def test_beleg_ohne_verguetung_baut_trotzdem_den_stundennachweis():
    termine = [{'datum': '2026-06-02', 'stunden': 2.0, 'wochentag': 2, 'angebot': None}]
    pdf = erstelle_stundennachweis_pdf(
        verein=_VEREIN, ul_name='Max Mustermann', sportart='Fußball', iban=None,
        trainerlizenz_nr=None, qualifikation=None, lizenz_klassifikation='ohne_lizenz',
        foerder_klassifikation=None, zeitraum_von='2026-06-01', zeitraum_bis='2026-06-30',
        termine=termine,
        summen={'summe_stunden': 2.0, 'verguetungsart': 'ohne_verguetung',
                'verguetung_pro_stunde': 0.0, 'gesamtbetrag': None, 'anzahl_monate': 1,
                'monatssummen': {'2026-06': 2.0}, 'anzahl_termine': 1},
    )
    assert pdf[:4] == b'%PDF' and len(pdf) > 1000
