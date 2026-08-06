"""Parser und Feld-Mapping des LINEAR-Imports (ohne Datenbank).

Alle Beispieldaten sind **erfunden** — der echte Muster-Export enthält Namen,
Adressen und Bankverbindungen realer Personen und gehört nicht ins Repo.

Schwerpunkte: die drei Stellen, an denen das Format vom SPG-Export abweicht
(Kodierung, Datum mit Uhrzeit, Abteilungen als Kreuz-Spalten) und die
Entscheidungen aus LINEAR_IMPORT_PLAN.md.
"""
from app.services import linear_import_service as linear
from app.services.import_common import decode_csv, to_iso

KOPF = ('"MITGLNR";"Anrede";"Nachname";"Vorname";"Geburtsdatum";"Strasse";"PLZ";'
        '"Ort";"IBAN1";"BIC1";"Status";"Eintritt";"Austritt";"Telefon";'
        '"Geschlecht";"Staatsangehörigkeit";"Mobiltelefon";'
        '"Allgemeine Sportgruppe";"Kegeln";"Kegeln o. LFV"')
LEERZEILE = ';;;;;;;;;;;;;;;;;;;'


def csv_bytes(*zeilen, kodierung='utf-8'):
    return ('\n'.join([KOPF, LEERZEILE, LEERZEILE, *zeilen])).encode(kodierung)


def zeile(nr='0999', nachname='Mustermann', vorname='Max', geburt='01.01.2000 00:00',
          strasse='Musterweg 1', plz='09111', ort='Musterstadt , Sachs',
          iban='DE02120300000000202051', bic='BYLADEM1001', status='Aktiv',
          eintritt='01.01.2020 00:00', austritt='', telefon='', geschlecht='MÄNNLICH',
          staat='DE', mobil='01700000000', abt1='X', abt2='', abt3=''):
    return (f'"{nr}";"Herr";"{nachname}";"{vorname}";{geburt};"{strasse}";"{plz}";'
            f'"{ort}";"{iban}";"{bic}";"{status}";{eintritt};{austritt};"{telefon}";'
            f'"{geschlecht}";"{staat}";"{mobil}";"{abt1}";"{abt2}";"{abt3}"')


# --- Kodierung ---------------------------------------------------------------

def test_utf8_wird_richtig_gelesen():
    """Beim falschen Griff stünde „StaatsangehÃ¶rigkeit" dauerhaft in der DB."""
    rows, spalten = linear.parse_csv_bytes(csv_bytes(zeile(nachname='Müller')))
    assert rows[0]['Nachname'] == 'Müller'
    assert 'Staatsangehörigkeit' not in spalten     # gehört zu den Stammdaten


def test_cp1252_wird_als_rueckfall_gelesen():
    rows, _ = linear.parse_csv_bytes(csv_bytes(zeile(nachname='Müller'), kodierung='cp1252'))
    assert rows[0]['Nachname'] == 'Müller'


def test_bom_klebt_nicht_am_ersten_spaltennamen():
    rows, _ = linear.parse_csv_bytes(csv_bytes(zeile(), kodierung='utf-8-sig'))
    assert rows[0]['MITGLNR'] == '0999'


def test_unlesbare_datei_meldet_sich():
    """Lieber ein Formatfehler als kaputte Umlaute in der Datenbank."""
    import pytest
    with pytest.raises(UnicodeDecodeError):
        decode_csv(b'\xff\xfe\x00\x81\x8d', kodierungen=('utf-8',))


# --- Struktur ----------------------------------------------------------------

def test_leerzeilen_unter_dem_header_werden_uebersprungen():
    rows, _ = linear.parse_csv_bytes(csv_bytes(zeile()))
    assert len(rows) == 1


def test_abteilungsspalten_werden_hinter_den_stammdaten_erkannt():
    """Die Spaltenliste ist vereinsspezifisch und darf nicht fest verdrahtet sein."""
    _, spalten = linear.parse_csv_bytes(csv_bytes(zeile()))
    assert spalten == ['Allgemeine Sportgruppe', 'Kegeln', 'Kegeln o. LFV']


def test_kreuz_spalten_ergeben_die_zugehoerigkeit():
    rows, spalten = linear.parse_csv_bytes(csv_bytes(zeile(abt1='X', abt2='', abt3='x')))
    assert linear.row_abteilungen(rows[0], spalten) == ['Allgemeine Sportgruppe',
                                                        'Kegeln o. LFV']


def test_o_lfv_bleibt_eine_eigene_abteilung():
    """Entscheidung 1: „Kegeln o. LFV" wird nicht mit „Kegeln" verschmolzen."""
    _, spalten = linear.parse_csv_bytes(csv_bytes(zeile()))
    assert 'Kegeln' in spalten and 'Kegeln o. LFV' in spalten


def test_kurze_zeile_fuellt_fehlende_spalten_leer():
    kurz = '"0001";"Herr";"Kurz";"Karl"'
    rows, _ = linear.parse_csv_bytes(csv_bytes(kurz))
    assert rows[0]['Nachname'] == 'Kurz'
    assert rows[0]['Mobiltelefon'] == ''


# --- Datum -------------------------------------------------------------------

def test_datum_mit_uhrzeit():
    """LINEAR hängt an jedes Datum eine Uhrzeit — SPG kannte das Format nicht."""
    assert to_iso('13.01.2005 00:00') == '2005-01-13'


def test_datum_ohne_uhrzeit_weiter_moeglich():
    assert to_iso('13.01.2005') == '2005-01-13'


def test_leeres_und_unsinniges_datum_ergibt_none():
    assert to_iso('') is None
    assert to_iso('irgendwas') is None


# --- Feld-Mapping ------------------------------------------------------------

def test_ort_zusatz_wird_abgeschnitten():
    """Entscheidung 4: „Chemnitz , Sachs" → „Chemnitz"."""
    assert linear.ort_ohne_zusatz('Musterstadt , Sachs') == 'Musterstadt'
    assert linear.ort_ohne_zusatz('Musterstadt') == 'Musterstadt'
    assert linear.ort_ohne_zusatz('') == ''


def test_kontakte_telefon_und_mobil_sind_je_primaer():
    rows, _ = linear.parse_csv_bytes(csv_bytes(zeile(telefon='037112345', mobil='01700000000')))
    assert linear.build_contacts(rows[0]) == [
        ('telefon', '037112345', None, True),
        ('mobil', '01700000000', None, True),
    ]


def test_fehlende_kontaktspalte_erzeugt_keine_leere_zeile():
    rows, _ = linear.parse_csv_bytes(csv_bytes(zeile(telefon='', mobil='')))
    assert linear.build_contacts(rows[0]) == []


def test_geschlecht_wird_uebersetzt():
    assert linear.GESCHLECHT['MÄNNLICH'] == 'm'
    assert linear.GESCHLECHT['WEIBLICH'] == 'w'
    assert linear.GESCHLECHT.get('UNBEKANNT') is None      # wird nicht geraten


def test_staatsangehoerigkeit_ist_keine_abteilung():
    """Sie wird gar nicht übernommen — sie darf aber auch nicht als Abteilung
    missverstanden werden, weil sie vor der Grenzspalte steht."""
    _, spalten = linear.parse_csv_bytes(csv_bytes(zeile()))
    assert 'Staatsangehörigkeit' not in spalten


def test_grenzspalte_fehlt_ergibt_keine_falschen_abteilungen():
    """Ohne „Mobiltelefon" im Header darf der Parser nicht raten."""
    kopf_ohne = KOPF.replace(';"Mobiltelefon"', '')
    daten = (kopf_ohne + '\n' + ';;;;;;;;;;;;;;;;;;'
             + '\n"0002";"Herr";"Ohne";"Otto";;;;;;;;;;;;;"X";"";""')
    rows, spalten = linear.parse_csv_bytes(daten.encode('utf-8'))
    assert spalten == ['Allgemeine Sportgruppe', 'Kegeln', 'Kegeln o. LFV']
    assert rows[0]['Nachname'] == 'Ohne'
