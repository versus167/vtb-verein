"""SepaService: Vorschau, Ausschlussgründe, Lauf-Erzeugung (Ticket #114).

Stub-basiert nach dem Muster von test_mein_mitglied_kontakte_api: SimpleNamespace-DB,
keine echte Datenbank. Die SQL-Auswahl der Kandidaten (offen, fällig, nicht eingezogen)
deckt der Integrationstest ab; hier geht es um die Entscheidung „einziehbar oder nicht"
und darum, was in den Positions-Snapshot wandert.
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from app.models.fibu import FibuEinstellungen  # noqa: E402
from app.services.sepa_service import SepaFehler, SepaService  # noqa: E402

_HEUTE = date(2026, 7, 30)   # Donnerstag


def _einstellungen(**kw) -> FibuEinstellungen:
    basis = dict(sepa_glaeubiger_id='DE98ZZZ09999999999',
                 sepa_glaeubiger_name='VTB Chemnitz e. V.',
                 sepa_iban='DE02100500000054540402',
                 sepa_bic='BELADEBE', sepa_vorlauftage=2)
    basis.update(kw)
    return FibuEinstellungen(**basis)


def _row(**kw) -> dict:
    basis = dict(quelle_typ='beitrag', quelle_id=7, betrag_soll=42.5,
                 periode='2026-Q3', faelligkeitsdatum='2026-07-01',
                 quelle_name='Beitrag Erwachsene', mitglied_id=3, mitgliedsnummer=1234,
                 vorname='Jürgen', nachname='Müller',
                 iban='DE02120300000000202051', bic='BYLADEM1001', kontoinhaber='',
                 zahlungsart='lastschrift', sepa_mandatsref=None, sepa_mandatsdatum=None,
                 eintrittsdatum='2019-04-01')
    basis.update(kw)
    return basis


class _SepaRepoStub:
    def __init__(self, rows):
        self.rows = rows
        self.angelegt = []

    def list_kandidaten(self, bis_datum):
        self.bis_datum = bis_datum
        return list(self.rows)

    def create_lauf(self, lauf, positionen, erstellt_von):
        self.angelegt.append((lauf, positionen, erstellt_von))
        lauf.id = 1
        lauf.positionen = positionen
        lauf.created_at = '2026-07-30T12:00:00'
        return lauf


def _db(rows=None, einst=None):
    repo = _SepaRepoStub(rows if rows is not None else [_row()])
    return SimpleNamespace(
        sepa=repo,
        fibu_einstellungen=SimpleNamespace(get=lambda: einst or _einstellungen()),
    )


# --- Ausführungsdatum -------------------------------------------------------

def test_vorschau_nimmt_fruehestes_ausfuehrungsdatum():
    # Do 30.07. + 2 Bankarbeitstage → Mo 03.08.2026
    v = SepaService(_db()).vorschau(heute=_HEUTE)
    assert v['ausfuehrungsdatum'] == '2026-08-03'


def test_vorlauftage_aus_den_einstellungen_wirken():
    db = _db(einst=_einstellungen(sepa_vorlauftage=5))
    assert SepaService(db).vorschau(heute=_HEUTE)['ausfuehrungsdatum'] == '2026-08-06'


def test_faelligkeitsgrenze_ist_das_ausfuehrungsdatum():
    db = _db()
    SepaService(db).vorschau(heute=_HEUTE)
    assert db.sepa.bis_datum == '2026-08-03'


# --- Einziehbarkeit ---------------------------------------------------------

def test_posten_mit_haken_iban_und_mandat_ist_einziehbar():
    v = SepaService(_db()).vorschau(heute=_HEUTE)
    assert v['anzahl'] == 1 and not v['nicht_einziehbar']
    k = v['einziehbar'][0]
    assert (k.betrag_cent, k.mandatsref, k.mandatsdatum) == (4250, '1234', '2019-04-01')
    # Mandats-Fallback: Referenz aus der Mitgliedsnummer, Datum aus dem Eintritt
    assert k.bezeichnung == 'Beitrag Erwachsene 2026-Q3'


def test_gepflegtes_mandat_hat_vorrang_vor_dem_fallback():
    db = _db([_row(sepa_mandatsref='M-42', sepa_mandatsdatum='2021-06-15')])
    k = SepaService(db).vorschau(heute=_HEUTE)['einziehbar'][0]
    assert (k.mandatsref, k.mandatsdatum) == ('M-42', '2021-06-15')


@pytest.mark.parametrize("aenderung, grund", [
    (dict(zahlungsart='ueberweisung'), 'kein Einzugs-Haken'),
    (dict(iban=None), 'keine IBAN hinterlegt'),
    (dict(iban='DE00120300000000202051'), 'IBAN ungültig'),
    (dict(betrag_soll=0), 'Betrag ist 0'),
    (dict(mitgliedsnummer=None), 'keine Mandatsreferenz'),
    (dict(eintrittsdatum=None), 'kein Mandatsdatum'),
])
def test_ausschlussgruende_werden_benannt(aenderung, grund):
    v = SepaService(_db([_row(**aenderung)])).vorschau(heute=_HEUTE)
    assert v['anzahl'] == 0
    assert grund in v['nicht_einziehbar'][0].ausschluss


def test_summe_zaehlt_nur_einziehbare():
    db = _db([_row(betrag_soll=42.5),
              _row(quelle_id=8, betrag_soll=10, iban=None),
              _row(quelle_typ='gebuehr', quelle_id=9, betrag_soll=7.5)])
    v = SepaService(db).vorschau(heute=_HEUTE)
    assert (v['anzahl'], v['summe_cent']) == (2, 5000)
    assert len(v['nicht_einziehbar']) == 1


def test_kontoinhaber_faellt_auf_den_mitgliedsnamen_zurueck():
    einziehbar = SepaService(_db()).vorschau(heute=_HEUTE)['einziehbar'][0]
    assert einziehbar.kontoinhaber == 'Jürgen Müller'


def test_abweichender_kontoinhaber_wird_uebernommen():
    db = _db([_row(kontoinhaber='Erika Müller')])
    assert SepaService(db).vorschau(heute=_HEUTE)['einziehbar'][0].kontoinhaber == 'Erika Müller'


# --- Konfiguration ----------------------------------------------------------

@pytest.mark.parametrize("aenderung, meldung", [
    (dict(sepa_glaeubiger_id=None), 'Gläubiger-ID'),
    (dict(sepa_glaeubiger_name=None), 'Gläubiger-Name'),
    (dict(sepa_iban=None), 'IBAN des Vereinskontos nicht gesetzt'),
    (dict(sepa_iban='DE00100500000054540402'), 'IBAN des Vereinskontos ist ungültig'),
])
def test_fehlende_glaeubiger_konfiguration_wird_gemeldet(aenderung, meldung):
    db = _db(einst=_einstellungen(**aenderung))
    v = SepaService(db).vorschau(heute=_HEUTE)
    assert any(meldung in f for f in v['konfiguration_fehler'])
    with pytest.raises(SepaFehler):
        SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)


# --- Lauf erzeugen ----------------------------------------------------------

def test_erzeugen_legt_lauf_mit_snapshot_an_und_rendert_xml():
    db = _db()
    lauf, xml = SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)
    assert lauf.ausfuehrungsdatum == '2026-08-03'
    assert lauf.dateiname == 'sepa_2026-08-03.xml'
    assert lauf.glaeubiger_id == 'DE98ZZZ09999999999'
    gespeicherte = db.sepa.angelegt[0][1]
    assert len(gespeicherte) == 1
    p = gespeicherte[0]
    # Snapshot: Betrag, IBAN und EndToEndId (Mandat + Lauftermin) liegen fest in der Position
    assert (p.betrag_cent, p.iban, p.end_to_end_id) == (4250, 'DE02120300000000202051',
                                                        '1234-20260803')
    assert b'<InstdAmt Ccy="EUR">42.50</InstdAmt>' in xml
    assert b'Mueller' in xml and 'Müller'.encode() not in xml


def test_erzeugen_ueberspringt_nicht_einziehbare_posten():
    db = _db([_row(), _row(quelle_id=8, iban=None)])
    lauf, _ = SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)
    assert [p.quelle_id for p in db.sepa.angelegt[0][1]] == [7]


def test_erzeugen_ohne_einziehbare_posten_ist_ein_fehler():
    db = _db([_row(iban=None)])
    with pytest.raises(SepaFehler, match="Keine einziehbaren Posten"):
        SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)


def test_end_to_end_id_kommt_aus_mandat_und_termin():
    db = _db([_row(quelle_typ='gebuehr', quelle_id=99, periode=None)])
    SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)
    assert db.sepa.angelegt[0][1][0].end_to_end_id == '1234-20260803'


# --- Bündelung --------------------------------------------------------------

def test_posten_desselben_mitglieds_teilen_sich_eine_end_to_end_id():
    db = _db([_row(quelle_id=7, betrag_soll=12), _row(quelle_id=8, betrag_soll=18)])
    SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)
    positionen = db.sepa.angelegt[0][1]
    # Zwei Positionen (je Posten eine), aber nur EINE Lastschrift in der Datei
    assert len(positionen) == 2
    assert {p.end_to_end_id for p in positionen} == {'1234-20260803'}


def test_verschiedene_mandate_bekommen_verschiedene_end_to_end_ids():
    db = _db([_row(quelle_id=7), _row(quelle_id=8, mitgliedsnummer=5678, mitglied_id=4,
                                      iban='DE02100500000054540402')])
    SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)
    assert [p.end_to_end_id for p in db.sepa.angelegt[0][1]] == ['1234-20260803', '5678-20260803']


def test_gleiche_mandatsreferenz_bei_verschiedenen_konten_bleibt_eindeutig():
    """Fehlerhafte Stammdaten: gleiche Referenz, anderes Konto → keine Sammel-Lastschrift."""
    db = _db([_row(quelle_id=7), _row(quelle_id=8, mitglied_id=4,
                                      iban='DE02100500000054540402')])
    SepaService(db).erzeugen(erstellt_von='kasse', heute=_HEUTE)
    e2e = [p.end_to_end_id for p in db.sepa.angelegt[0][1]]
    assert e2e == ['1234-20260803', '1234-20260803-2']


def test_vorschau_zaehlt_lastschriften_und_posten_getrennt():
    db = _db([_row(quelle_id=7, betrag_soll=12), _row(quelle_id=8, betrag_soll=18),
              _row(quelle_id=9, mitgliedsnummer=5678, mitglied_id=4, betrag_soll=15)])
    v = SepaService(db).vorschau(heute=_HEUTE)
    assert (v['anzahl'], v['anzahl_lastschriften']) == (3, 2)
    assert v['summe_cent'] == 4500
