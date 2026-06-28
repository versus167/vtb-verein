"""Smoke-Tests für den Übungsleiter-Stundennachweis-Beleg (PDF).

Stellt sicher, dass der Beleg in beiden Layout-Varianten gebaut wird: kompakt
(ohne Angebot-Spalte) und mit Angebot-Spalte, sobald mindestens ein Termin einen
Angebot-Text trägt. Geprüft wird, dass gültige PDF-Bytes entstehen (kein Crash).
"""
from app.services.ul_stundennachweis_pdf_service import erstelle_stundennachweis_pdf


_VEREIN = {'name': 'TV Musterstadt', 'strasse': 'Hauptstr. 1',
           'plz_ort': '12345 Musterstadt', 'registrier_nr': 'VR 42'}


def _pdf(termine):
    return erstelle_stundennachweis_pdf(
        verein=_VEREIN, ul_name='Max Mustermann', sportart='Fußball', iban='DE00…',
        trainerlizenz_nr=None, qualifikation=None, lizenz_klassifikation='ohne_lizenz',
        foerder_klassifikation=None, zeitraum_von='2026-06-01', zeitraum_bis='2026-06-30',
        termine=termine,
        summen={'summe_stunden': 4.0, 'verguetung_pro_stunde': 10.0, 'gesamtbetrag': 40.0,
                'monatssummen': {'2026-06': 4.0}, 'anzahl_termine': 2},
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
