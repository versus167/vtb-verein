"""Parser des DFBnet-Vereinsspielplans (#95, Etappe 2) – ohne Datenbank.

Die Testdatei wird hier synthetisch erzeugt: UTF-16LE mit BOM, tabgetrennt, mit
dem doppelten Spaltenkopf „Typ". Echte Exporte gehören nicht ins Repo, sie
enthalten Namen und Ausweisnummern von Schiedsrichtern.
"""
import pytest

from app.services import dfbnet_import_service as dfbnet

# Kopfzeile wie im Export – „Typ" steht zweimal drin (Platztyp und Spieltyp).
_KOPF = [
    'Saison', 'Verband', 'Spielgebiet', 'Mannschaftsart', 'Staffel', 'Spielstätte',
    'Spielstätten-Nr.', 'Straße/Hausnr.', 'PLZ', 'Ort', 'Platznummer', 'Typ', 'Größe',
    'Max. parallele Spiele', 'Max. Spiele/Tag', 'Max. Spiele/Wochenende',
    'Früheste Anstoßzeit', 'Späteste Anstoßzeit', 'Mittagspause', 'Wochentag',
    'Spieldatum', 'Uhrzeit', 'Sptg.', 'Spielkennung', 'Typ', 'Liga',
    'Heimmannschaft', 'Gastmannschaft', 'Spielleitung', 'Assistent 1', 'Assistent 2',
]


def _zeile(**kw):
    werte = {k: '' for k in _KOPF}
    werte.update({
        'Saison': '26/27', 'Mannschaftsart': 'Herren', 'Staffel': 'Kreisoberliga',
        'Spielstätte': 'Musterplatz', 'Spielstätten-Nr.': '1234567890',
        'Straße/Hausnr.': 'Musterweg 1', 'PLZ': '09111', 'Ort': 'Musterstadt',
        'Max. parallele Spiele': '2', 'Spieldatum': '15.08.2026', 'Uhrzeit': '15:00',
        'Sptg.': '1', 'Spielkennung': '111111111', 'Liga': 'Kreisoberliga',
        'Heimmannschaft': 'SV Beispiel', 'Gastmannschaft': 'Musterverein',
    })
    # Der Spieltyp sitzt in der ZWEITEN „Typ"-Spalte
    werte['__spieltyp'] = kw.pop('spieltyp', 'Meisterschaft')
    werte['__platztyp'] = kw.pop('platztyp', 'Rasenplatz')
    werte.update(kw)
    spalten = []
    typ_gesehen = 0
    for name in _KOPF:
        if name == 'Typ':
            typ_gesehen += 1
            spalten.append(werte['__platztyp'] if typ_gesehen == 1 else werte['__spieltyp'])
        else:
            spalten.append(werte[name])
    return '\t'.join(spalten)


def _datei(*zeilen) -> bytes:
    inhalt = '\r\n'.join(['\t'.join(_KOPF), *zeilen]) + '\r\n'
    return inhalt.encode('utf-16')      # erzeugt BOM + UTF-16LE wie der Export


def test_utf16_wird_erkannt():
    spiele, fehler = dfbnet.parse_spielplan(_datei(_zeile()))
    assert fehler == []
    assert len(spiele) == 1
    assert spiele[0].spielstaette == 'Musterplatz'


@pytest.mark.parametrize("kodierung", ['utf-8', 'utf-8-sig', 'cp1252'])
def test_andere_kodierungen_scheitern_nicht(kodierung):
    """Eine von Hand umgespeicherte Datei soll trotzdem lesbar sein."""
    text = '\r\n'.join(['\t'.join(_KOPF), _zeile()]) + '\r\n'
    spiele, fehler = dfbnet.parse_spielplan(text.encode(kodierung))
    assert fehler == []
    assert spiele[0].liga == 'Kreisoberliga'


def test_doppelter_spaltenkopf_typ_wird_aufgeloest():
    """Platztyp und Spieltyp heißen beide „Typ" – der Spieltyp muss ankommen."""
    spiele, _ = dfbnet.parse_spielplan(
        _datei(_zeile(platztyp='Kunstrasenplatz', spieltyp='Pokal')))
    assert spiele[0].spieltyp == 'Pokal'


def test_koepfe_werden_durchnummeriert():
    assert dfbnet._eindeutige_koepfe(['Typ', 'Liga', 'Typ']) == ['Typ', 'Liga', 'Typ#2']


def test_datum_und_uhrzeit_werden_wandzeit():
    spiele, _ = dfbnet.parse_spielplan(
        _datei(_zeile(**{'Spieldatum': '06.08.2026', 'Uhrzeit': '19:00'})))
    assert spiele[0].beginn == '2026-08-06T19:00'


def test_leerzeilen_werden_uebersprungen():
    leer = '\t'.join([''] * len(_KOPF))
    spiele, fehler = dfbnet.parse_spielplan(_datei(leer, _zeile(), leer))
    assert len(spiele) == 1 and fehler == []


def test_unlesbare_zeile_bricht_den_lauf_nicht_ab():
    kaputt = _zeile(**{'Spieldatum': '32.13.2026', 'Spielkennung': '999'})
    spiele, fehler = dfbnet.parse_spielplan(_datei(_zeile(), kaputt))
    assert len(spiele) == 1
    assert len(fehler) == 1 and 'unlesbar' in fehler[0]


def test_zeile_ohne_spielkennung_wird_gemeldet():
    ohne = _zeile(**{'Spielkennung': ''})
    spiele, fehler = dfbnet.parse_spielplan(_datei(ohne))
    assert spiele == []
    assert 'ohne Spielkennung' in fehler[0]


def test_fehlende_pflichtspalte_meldet_klartext():
    inhalt = '\r\n'.join(['Saison\tLiga', '26/27\tKreisoberliga']) + '\r\n'
    spiele, fehler = dfbnet.parse_spielplan(inhalt.encode('utf-16'))
    assert spiele == []
    assert 'Spalten fehlen' in fehler[0]


def test_ort_text_setzt_spielstaette_und_adresse_zusammen():
    spiele, _ = dfbnet.parse_spielplan(_datei(_zeile()))
    assert spiele[0].ort_text == 'Musterplatz, Musterweg 1, 09111 Musterstadt'


def test_leere_datei():
    spiele, fehler = dfbnet.parse_spielplan(''.encode('utf-16'))
    assert spiele == [] and fehler
