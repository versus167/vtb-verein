"""
Auswertung des Zutrittslogs (#161) – die Aufbereitung über den SQL-Aggregaten.

Geprüft wird, was der Service aus den rohen Zahlen macht: aufgefüllte Achsen (jede
Stunde, jeder Wochentag, jede Lücke im Verlauf), Anteile, Methoden-Labels, die
längste Serie und die Auszeichnungen – inklusive der Fälle, in denen es schlicht
nichts auszuzeichnen gibt.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services import zutritt_auswertung_service as service  # noqa: E402

HEUTE = datetime.now(service.ZEITZONE).date()


def _tag(vor_tagen: int) -> str:
    return (HEUTE - timedelta(days=vor_tagen)).isoformat()


def _roh(**kw):
    """Rohaggregate wie sie das Repository liefert – mit brauchbaren Vorgaben."""
    daten = {
        'kennzahlen': {'oeffnungen': 10, 'aktive_tage': 3, 'akteure': 2, 'schloesser': 2,
                       'erster_tag': _tag(4), 'letzter_tag': _tag(0),
                       'fehlversuche': 1, 'alarme': 0, 'ereignisse': 14},
        'schloesser': [{'schloss_id': 1, 'name': 'Küche', 'anzahl': 7, 'letzte': _tag(0) + 'T18:30'},
                       {'schloss_id': 2, 'name': 'Tor', 'anzahl': 3, 'letzte': _tag(1) + 'T09:00'}],
        'stunden': [{'stunde': 6, 'anzahl': 4}, {'stunde': 18, 'anzahl': 6}],
        'wochentage': [{'tag': 1, 'anzahl': 6}, {'tag': 6, 'anzahl': 4}],
        'methoden': [{'record_type': 7, 'methode': 'IC-Karte', 'anzahl': 8},
                     {'record_type': None, 'methode': 'Karte entsperren', 'anzahl': 2}],
        'personen': [{'wer': 'Marko Jakaric', 'anzahl': 6, 'schloesser': 2},
                     {'wer': 'karte1', 'anzahl': 4, 'schloesser': 1}],
        'tage': [{'datum': _tag(4), 'anzahl': 2}, {'datum': _tag(3), 'anzahl': 5},
                 {'datum': _tag(0), 'anzahl': 3}],
        'frueheste': {'wer': 'Marko Jakaric', 'schloss_name': 'Küche',
                      'zeitpunkt': _tag(3) + 'T05:12', 'uhrzeit': '05:12'},
        'spaeteste': {'wer': 'karte1', 'schloss_name': 'Tor',
                      'zeitpunkt': _tag(4) + 'T23:47', 'uhrzeit': '23:47'},
        'wochenende': {'wer': 'karte1', 'anzahl': 4},
        'nachtaktiv': {'wer': 'Marko Jakaric', 'anzahl': 2},
        'vielfalt': {'wer': 'Marko Jakaric', 'schloesser': 2, 'anzahl': 6},
    }
    daten.update(kw)
    return daten


def _db(roh=None, mitschrieb=None):
    def auswertung(*, schloss_ids=None, von=None):
        if mitschrieb is not None:
            mitschrieb.append({'schloss_ids': schloss_ids, 'von': von})
        return roh if roh is not None else _roh()
    return SimpleNamespace(tuer_zutritt_logs=SimpleNamespace(auswertung=auswertung))


def _auszeichnung(bericht, schluessel):
    return next((a for a in bericht['auszeichnungen'] if a['schluessel'] == schluessel), None)


# ------------------------------------------------------------------ Achsen
def test_stundenachse_ist_immer_vollstaendig():
    stunden = service.bericht(_db())['stunden']
    assert [s['stunde'] for s in stunden] == list(range(24))
    assert stunden[6]['anzahl'] == 4 and stunden[7]['anzahl'] == 0


def test_wochentagsachse_beginnt_montags_und_ist_vollstaendig():
    tage = service.bericht(_db())['wochentage']
    assert [t['label'] for t in tage] == ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    assert tage[0]['anzahl'] == 6 and tage[5]['anzahl'] == 4 and tage[6]['anzahl'] == 0


def test_verlauf_fuellt_tage_ohne_zutritt_mit_null():
    verlauf = service.bericht(_db())['verlauf']
    assert verlauf['granularitaet'] == 'tag'
    # 5 Tage Spanne, aber nur 3 Tage mit Daten → die beiden Lücken stehen als 0 drin
    assert [p['anzahl'] for p in verlauf['punkte']] == [2, 5, 0, 0, 3]


def test_langer_zeitraum_wird_zu_wochen_und_monaten_gebuendelt():
    """Am Handy sind 90 Tagesbalken unlesbar – ab 45 Tagen Woche, ab 200 Tagen Monat."""
    roh = _roh(kennzahlen={**_roh()['kennzahlen'], 'erster_tag': _tag(80), 'letzter_tag': _tag(0)},
               tage=[{'datum': _tag(80), 'anzahl': 1}, {'datum': _tag(0), 'anzahl': 2}])
    assert service.bericht(_db(roh), tage=90)['verlauf']['granularitaet'] == 'woche'

    roh = _roh(kennzahlen={**_roh()['kennzahlen'], 'erster_tag': _tag(300), 'letzter_tag': _tag(0)},
               tage=[{'datum': _tag(300), 'anzahl': 1}, {'datum': _tag(0), 'anzahl': 2}])
    verlauf = service.bericht(_db(roh), tage=365)['verlauf']
    assert verlauf['granularitaet'] == 'monat'
    assert sum(p['anzahl'] for p in verlauf['punkte']) == 3


def test_verlauf_beginnt_beim_ersten_zutritt_nicht_am_zeitraumanfang():
    """Sonst zeigt „365 Tage" bei einem Monat Daten elf leere Monate."""
    roh = _roh(kennzahlen={**_roh()['kennzahlen'], 'erster_tag': _tag(3), 'letzter_tag': _tag(0)},
               tage=[{'datum': _tag(3), 'anzahl': 1}])
    verlauf = service.bericht(_db(roh), tage=365)['verlauf']
    assert verlauf['granularitaet'] == 'tag' and len(verlauf['punkte']) == 4


# --------------------------------------------------------------- Kennzahlen
def test_anteile_und_schnitt():
    b = service.bericht(_db())
    assert b['kennzahlen']['oeffnungen'] == 10
    assert b['kennzahlen']['pro_tag'] == 2.0            # 10 Öffnungen auf 5 Tage Spanne
    assert b['kennzahlen']['spitze_pro_tag'] == 5
    assert b['schloesser'][0]['anteil'] == 0.7
    assert b['personen'][0]['anteil'] == 0.6


def test_methoden_bekommen_lesbare_labels():
    methoden = service.bericht(_db())['methoden']
    assert methoden[0]['label'] == 'IC-Karte'
    # Fremdanlage ohne erkannten Typ: der Originaltext des Exports bleibt stehen
    assert methoden[1]['label'] == 'Karte entsperren'


def test_zeitraum_wird_als_utc_grenze_weitergereicht():
    mitschrieb = []
    service.bericht(_db(mitschrieb=mitschrieb), tage=30)
    von = datetime.fromisoformat(mitschrieb[0]['von'])
    assert 29 <= (datetime.now(von.tzinfo) - von).days <= 30
    assert mitschrieb[0]['schloss_ids'] is None


def test_zeitraum_null_heisst_seit_jeher():
    mitschrieb = []
    service.bericht(_db(mitschrieb=mitschrieb), tage=0)
    assert mitschrieb[0]['von'] is None


def test_abteilungs_scope_wird_durchgereicht():
    mitschrieb = []
    service.bericht(_db(mitschrieb=mitschrieb), schloss_ids={2, 1})
    assert mitschrieb[0]['schloss_ids'] == [1, 2]


# ------------------------------------------------------------- Auszeichnungen
def test_frueheste_und_spaeteste_oeffnung():
    b = service.bericht(_db())
    frueh = _auszeichnung(b, 'frueheste')
    assert frueh['wer'] == 'Marko Jakaric' and frueh['wert'] == '05:12 Uhr'
    assert frueh['detail'].startswith(date.fromisoformat(_tag(3)).strftime('%d.%m.%Y'))
    assert _auszeichnung(b, 'spaeteste')['wert'] == '23:47 Uhr'


def test_stammgast_tuer_und_rekordtag():
    b = service.bericht(_db())
    assert _auszeichnung(b, 'stammgast')['wer'] == 'Marko Jakaric'
    assert _auszeichnung(b, 'tuer')['wer'] == 'Küche'
    rekord = _auszeichnung(b, 'rekordtag')
    assert rekord['wert'] == '5×'
    assert rekord['detail'] == date.fromisoformat(_tag(3)).strftime('%d.%m.%Y')


def test_laengste_serie_zaehlt_nur_aufeinanderfolgende_tage():
    roh = _roh(tage=[{'datum': _tag(9), 'anzahl': 1}, {'datum': _tag(8), 'anzahl': 1},
                     {'datum': _tag(7), 'anzahl': 1}, {'datum': _tag(2), 'anzahl': 1}],
               kennzahlen={**_roh()['kennzahlen'], 'erster_tag': _tag(9), 'letzter_tag': _tag(2)})
    serie = _auszeichnung(service.bericht(_db(roh)), 'serie')
    assert serie['wert'] == '3 Tage'
    assert serie['detail'].startswith(date.fromisoformat(_tag(9)).strftime('%d.%m.%Y'))


def test_einzelner_tag_ist_keine_serie():
    roh = _roh(tage=[{'datum': _tag(1), 'anzahl': 3}])
    assert _auszeichnung(service.bericht(_db(roh)), 'serie') is None


def test_schluesselbund_nur_bei_mehreren_tueren():
    roh = _roh(vielfalt={'wer': 'karte1', 'schloesser': 1, 'anzahl': 4})
    assert _auszeichnung(service.bericht(_db(roh)), 'vielfalt') is None


def test_nachtschicht_nur_wenn_es_sie_gab():
    roh = _roh(nachtaktiv=None, wochenende={'wer': 'karte1', 'anzahl': 0})
    b = service.bericht(_db(roh))
    assert _auszeichnung(b, 'nacht') is None
    assert _auszeichnung(b, 'wochenende') is None


def test_ohne_daten_bleibt_der_bericht_leer_aber_vollstaendig():
    """Ein frisch aufgesetzter Verein darf keine kaputte Seite bekommen."""
    leer = {'kennzahlen': {'oeffnungen': 0, 'aktive_tage': 0, 'akteure': 0, 'schloesser': 0,
                           'erster_tag': None, 'letzter_tag': None,
                           'fehlversuche': 0, 'alarme': 0, 'ereignisse': 0},
            'schloesser': [], 'stunden': [], 'wochentage': [], 'methoden': [],
            'personen': [], 'tage': [], 'frueheste': None, 'spaeteste': None,
            'wochenende': None, 'nachtaktiv': None, 'vielfalt': None}
    b = service.bericht(_db(leer))
    assert b['auszeichnungen'] == []
    assert b['kennzahlen']['pro_tag'] == 0.0
    assert len(b['stunden']) == 24 and len(b['wochentage']) == 7
    assert b['verlauf']['punkte'] == [{'label': HEUTE.strftime('%d.%m.'),
                                       'datum': HEUTE.isoformat(), 'anzahl': 0}]
