"""pain.008-Formatter und TARGET2-Kalender (Ticket #114).

Geprüft wird, was die Bank ablehnen würde: Zeichensatz, Betragsformat, Pflichtfelder,
Elementreihenfolge sowie die Summen/Zähler im Gruppen- und Zahlungs-Header.
"""
from datetime import date, datetime

import pytest

from app.models.sepa import SepaLauf, SepaPosition
from app.services import sepa_formatter as f

NS = {'p': f.NAMESPACE}


def _position(**kw) -> SepaPosition:
    basis = dict(quelle_typ='beitrag', quelle_id=7, mitglied_id=3, betrag_cent=4250,
                 end_to_end_id='B7', mandatsref='1234', mandatsdatum='2019-04-01',
                 iban='DE02120300000000202051', bic='BYLADEM1001',
                 kontoinhaber='Müller, Jürgen', verwendungszweck='Beitrag 2026-Q3')
    basis.update(kw)
    return SepaPosition(**basis)


def _lauf(positionen=None, **kw) -> SepaLauf:
    basis = dict(dateiname='sepa_2026-08-05.xml', message_id='VTB-20260730-120000',
                 ausfuehrungsdatum='2026-08-05', sequenztyp='RCUR',
                 glaeubiger_id='DE98ZZZ09999999999', glaeubiger_name='VTB Chemnitz e. V.',
                 glaeubiger_iban='DE02100500000054540402', glaeubiger_bic='BELADEBE')
    basis.update(kw)
    lauf = SepaLauf(**basis)
    lauf.positionen = positionen if positionen is not None else [_position()]
    return lauf


def _baum(lauf, **kw):
    from xml.etree import ElementTree as ET
    return ET.fromstring(f.render(lauf, **kw))


# --- Zeichensatz ------------------------------------------------------------

@pytest.mark.parametrize("roh, erwartet", [
    ('Müller', 'Mueller'),
    ('Weiß', 'Weiss'),
    ('Öl & Öl', 'Oel + Oel'),
    ('Beitrag "Q3"', "Beitrag 'Q3'"),
    ('Tab\tund\nUmbruch', 'Tab und Umbruch'),
    ('Ünnötig   viele    Leerzeichen', 'Uennoetig viele Leerzeichen'),
    ('', ''),
    (None, ''),
])
def test_sepa_text_transliteriert_und_saeubert(roh, erwartet):
    assert f.sepa_text(roh) == erwartet


def test_sepa_text_kuerzt_auf_maximallaenge():
    assert len(f.sepa_text('A' * 200, f.MAX_NAME)) == f.MAX_NAME


def test_sepa_text_entfernt_unerlaubte_zeichen():
    # * und # sind im SEPA-Zeichensatz nicht erlaubt.
    assert f.sepa_text('Beitrag *Q3* #1') == 'Beitrag Q3 1'


# --- Beträge ----------------------------------------------------------------

@pytest.mark.parametrize("cent, erwartet", [
    (4250, '42.50'), (5, '0.05'), (100, '1.00'), (123456, '1234.56'), (0, '0.00'),
])
def test_betragsformat_mit_punkt(cent, erwartet):
    assert f._betrag(cent) == erwartet


# --- TARGET2-Kalender -------------------------------------------------------

@pytest.mark.parametrize("tag, ist_geschaeftstag", [
    (date(2026, 7, 30), True),    # Donnerstag
    (date(2026, 8, 1), False),    # Samstag
    (date(2026, 8, 2), False),    # Sonntag
    (date(2026, 1, 1), False),    # Neujahr
    (date(2026, 4, 3), False),    # Karfreitag 2026
    (date(2026, 4, 6), False),    # Ostermontag 2026
    (date(2026, 5, 1), False),    # 1. Mai
    (date(2026, 12, 25), False),  # 1. Weihnachtsfeiertag
    (date(2027, 3, 26), False),   # Karfreitag 2027 (anderes Osterdatum)
])
def test_target2_tage(tag, ist_geschaeftstag):
    assert f.ist_target2_tag(tag) is ist_geschaeftstag


def test_ausfuehrungsdatum_ueberspringt_wochenende():
    # Freitag + 2 Bankarbeitstage → Dienstag
    assert f.ausfuehrungsdatum(date(2026, 7, 31), 2) == date(2026, 8, 4)


def test_ausfuehrungsdatum_ohne_vorlauf_ist_naechster_bankarbeitstag():
    assert f.ausfuehrungsdatum(date(2026, 8, 1), 0) == date(2026, 8, 3)


def test_ausfuehrungsdatum_ueberspringt_feiertag():
    # Do 30.04.2026 + 1 Bankarbeitstag: 01.05. ist TARGET2-Feiertag, 02./03.05. Wochenende
    assert f.ausfuehrungsdatum(date(2026, 4, 30), 1) == date(2026, 5, 4)


# --- XML --------------------------------------------------------------------

def test_grundstruktur_und_namespace():
    xml = f.render(_lauf())
    assert xml.startswith(b"<?xml")
    baum = _baum(_lauf())
    assert baum.tag == f"{{{f.NAMESPACE}}}Document"
    assert baum.find('p:CstmrDrctDbtInitn/p:GrpHdr', NS) is not None


def test_gruppenheader_zaehlt_lastschriften_und_summiert():
    lauf = _lauf([_position(betrag_cent=4250),
                  _position(quelle_id=8, betrag_cent=1750, end_to_end_id='5678-20260805',
                            mandatsref='5678', iban='DE02100500000054540402')])
    kopf = _baum(lauf).find('p:CstmrDrctDbtInitn/p:GrpHdr', NS)
    assert kopf.findtext('p:NbOfTxs', namespaces=NS) == '2'
    assert kopf.findtext('p:CtrlSum', namespaces=NS) == '60.00'


def test_zahlungsblock_traegt_glaeubiger_und_sequenztyp():
    zahlung = _baum(_lauf()).find('p:CstmrDrctDbtInitn/p:PmtInf', NS)
    assert zahlung.findtext('p:PmtMtd', namespaces=NS) == 'DD'
    assert zahlung.findtext('p:PmtTpInf/p:SvcLvl/p:Cd', namespaces=NS) == 'SEPA'
    assert zahlung.findtext('p:PmtTpInf/p:LclInstrm/p:Cd', namespaces=NS) == 'CORE'
    assert zahlung.findtext('p:PmtTpInf/p:SeqTp', namespaces=NS) == 'RCUR'
    assert zahlung.findtext('p:ReqdColltnDt', namespaces=NS) == '2026-08-05'
    assert zahlung.findtext('p:ChrgBr', namespaces=NS) == 'SLEV'
    assert zahlung.findtext('p:CdtrAcct/p:Id/p:IBAN', namespaces=NS) == 'DE02100500000054540402'
    assert zahlung.findtext('p:CdtrSchmeId/p:Id/p:PrvtId/p:Othr/p:Id',
                            namespaces=NS) == 'DE98ZZZ09999999999'
    assert zahlung.findtext('p:CdtrSchmeId/p:Id/p:PrvtId/p:Othr/p:SchmeNm/p:Prtry',
                            namespaces=NS) == 'SEPA'


def test_lastschrift_enthaelt_mandat_betrag_und_debitor():
    posten = _baum(_lauf()).find('p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    assert posten.findtext('p:PmtId/p:EndToEndId', namespaces=NS) == 'B7'
    betrag = posten.find('p:InstdAmt', NS)
    assert (betrag.text, betrag.get('Ccy')) == ('42.50', 'EUR')
    mandat = posten.find('p:DrctDbtTx/p:MndtRltdInf', NS)
    assert mandat.findtext('p:MndtId', namespaces=NS) == '1234'
    assert mandat.findtext('p:DtOfSgntr', namespaces=NS) == '2019-04-01'
    assert posten.findtext('p:DbtrAgt/p:FinInstnId/p:BICFI', namespaces=NS) == 'BYLADEM1001'
    # Umlaut im Namen ist transliteriert
    assert posten.findtext('p:Dbtr/p:Nm', namespaces=NS) == 'Mueller, Juergen'
    assert posten.findtext('p:DbtrAcct/p:Id/p:IBAN', namespaces=NS) == 'DE02120300000000202051'
    assert posten.findtext('p:RmtInf/p:Ustrd', namespaces=NS) == 'Beitrag 2026-Q3'


def test_elementreihenfolge_der_lastschrift_ist_schemakonform():
    posten = _baum(_lauf()).find('p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    tags = [kind.tag.split('}')[1] for kind in posten]
    assert tags == ['PmtId', 'InstdAmt', 'DrctDbtTx', 'DbtrAgt', 'Dbtr', 'DbtrAcct', 'RmtInf']


def test_ohne_bic_wird_notprovided_gesetzt():
    posten = _baum(_lauf([_position(bic=None)])).find(
        'p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    assert posten.findtext('p:DbtrAgt/p:FinInstnId/p:Othr/p:Id', namespaces=NS) == 'NOTPROVIDED'
    assert posten.find('p:DbtrAgt/p:FinInstnId/p:BICFI', NS) is None


def test_ohne_verwendungszweck_kein_leeres_rmtinf():
    posten = _baum(_lauf([_position(verwendungszweck=None)])).find(
        'p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    assert posten.find('p:RmtInf', NS) is None


def test_erstellzeitpunkt_wird_uebernommen():
    kopf = _baum(_lauf(), erzeugt_am=datetime(2026, 7, 30, 14, 30, 5)).find(
        'p:CstmrDrctDbtInitn/p:GrpHdr', NS)
    assert kopf.findtext('p:CreDtTm', namespaces=NS) == '2026-07-30T14:30:05'


def test_lauf_ohne_positionen_ist_ein_fehler():
    with pytest.raises(ValueError, match="ohne Positionen"):
        f.render(_lauf(positionen=[]))


def test_end_to_end_id_je_mandat_und_lauf():
    assert f.end_to_end_id('303926', '2026-08-05') == '303926-20260805'


def test_end_to_end_id_kuerzt_lange_mandatsreferenz_und_behaelt_das_datum():
    e2e = f.end_to_end_id('M' * 60, '2026-08-05')
    assert len(e2e) <= f.MAX_ID
    assert e2e.endswith('-20260805')


# --- Bündelung (mehrere Posten eines Mandats = eine Lastschrift) -------------

def _gebuendelt():
    """Zwei Posten desselben Mandats – wie zwei Beiträge eines Mitglieds."""
    return _lauf([_position(betrag_cent=1200, verwendungszweck='Abteilungsbeitrag 2026-Q2'),
                  _position(quelle_id=8, betrag_cent=1800,
                            verwendungszweck='Vereinsbeitrag 2026-Q2')])


def test_gleiches_mandat_wird_zu_einer_lastschrift():
    zahlung = _baum(_gebuendelt()).find('p:CstmrDrctDbtInitn/p:PmtInf', NS)
    posten = zahlung.findall('p:DrctDbtTxInf', NS)
    assert len(posten) == 1
    assert posten[0].findtext('p:InstdAmt', namespaces=NS) == '30.00'
    assert zahlung.findtext('p:NbOfTxs', namespaces=NS) == '1'
    assert zahlung.findtext('p:CtrlSum', namespaces=NS) == '30.00'


def test_gebuendelte_lastschrift_nennt_beide_verwendungszwecke():
    posten = _baum(_gebuendelt()).find('p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    assert posten.findtext('p:RmtInf/p:Ustrd', namespaces=NS) == \
        'Abteilungsbeitrag 2026-Q2, Vereinsbeitrag 2026-Q2'


@pytest.mark.parametrize("abweichung", [
    {'mandatsref': '9999', 'end_to_end_id': '9999-20260805'},   # anderes Mandat
    {'iban': 'DE02100500000054540402'},                          # anderes Konto
])
def test_ueber_mandate_und_konten_hinweg_wird_nicht_gebuendelt(abweichung):
    lauf = _lauf([_position(), _position(quelle_id=8, **abweichung)])
    posten = _baum(lauf).findall('p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    assert len(posten) == 2


def test_zu_langer_verwendungszweck_wird_angedeutet_statt_abgeschnitten():
    positionen = [_position(quelle_id=i, verwendungszweck=f'Beitragsposten Nummer {i} ' + 'X' * 30)
                  for i in range(1, 8)]
    zweck = _baum(_lauf(positionen)).findtext(
        'p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf/p:RmtInf/p:Ustrd', namespaces=NS)
    assert len(zweck) <= f.MAX_VERWENDUNGSZWECK
    assert zweck.endswith(' u.w.')
    assert 'Beitragsposten Nummer 1' in zweck


def test_alter_lauf_mit_belegnummern_bleibt_einzeln():
    """Läufe aus Etappe 1 tragen je Posten eine eigene EndToEndId – Re-Download stabil."""
    lauf = _lauf([_position(end_to_end_id='B7'), _position(quelle_id=8, end_to_end_id='B8')])
    posten = _baum(lauf).findall('p:CstmrDrctDbtInitn/p:PmtInf/p:DrctDbtTxInf', NS)
    assert [p.findtext('p:PmtId/p:EndToEndId', namespaces=NS) for p in posten] == ['B7', 'B8']


def test_message_id_bleibt_im_laengenlimit():
    mid = f.message_id(datetime(2026, 7, 30, 14, 30, 5), lauf_id=12)
    assert mid == 'VTB-20260730-143005-12'
    assert len(mid) <= f.MAX_ID
