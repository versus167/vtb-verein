"""
Tests für den Fibu-Delta-Export (Format hmd FBASC):
- Formatter (reine Zeilen-/Feldlogik)
- FibuExportService (Konten-Auflösung, Delta/Soll-Haben, Validierung, Export-Lauf)
"""
from types import SimpleNamespace

import pytest

from app.models.fibu import FibuEinstellungen, FibuExportPosition, FibuExport
from app.services import fibu_formatter as ff
from app.services.fibu_export_service import FibuExportService, FibuExportFehler


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def _pos(**kw):
    base = dict(konto=70005, gegenkonto='4000', betrag=10.0, soll_haben='S',
                belegnummer='B1', kostenstelle=12, kostentraeger=1,
                belegdatum='2026-12-31', faelligkeitsdatum='2026-12-31',
                buchungstext='Beitrag 2026-Q4', suchname='5', nachname='Müller',
                vorname='Anna', strasse='Weg 1', plz='12345', ort='Stadt', land='DE',
                iban='DE00', bic='XBIC', mandatsref='M1', mandatsdatum='2025-01-02',
                lastschrifteinzug=1, mailadresse='anna@example.org', kontoinhaber='Max Vormund')
    base.update(kw)
    return FibuExportPosition(**base)


class TestFormatterFelder:
    def test_feldanzahl_und_positionen(self):
        f = ff.felder(_pos())
        assert len(f) == 71
        assert f[0] == '70005'        # Kontonummer
        assert f[1] == '4000'         # Gegenkonto
        assert f[2] == '10,00'        # Betrag mit Komma
        assert f[3] == 'S'            # Soll/Haben
        assert f[4] == 'B1'           # Belegnummer
        assert f[7] == '12'           # Kostenstelle
        assert f[8] == '1'            # Kostenträger
        assert f[10] == '31.12.2026'  # Belegdatum TT.MM.JJJJ
        assert f[11] == '31.12.2026'  # Fälligkeitsdatum
        assert f[17] == 'E'           # Währung
        assert f[19] == 'D'           # Kontenart Debitor
        assert f[20] == '5'           # Suchname
        assert f[22] == 'Müller'      # Name
        assert f[40] == 'DE00'        # IBAN
        assert f[43] == 'Anna'        # Vorname
        assert f[47] == 'M1'          # Mandatsreferenz
        assert f[48] == '02.01.2025'  # Datum Mandatsreferenz
        assert f[59] == 'anna@example.org'  # Mailadresse
        assert f[70] == 'Max Vormund'       # abweichender Kontoinhaber

    def test_gesperrte_felder_52_bis_58_leer(self):
        f = ff.felder(_pos())
        assert all(f[i] == '' for i in range(52, 59))

    def test_betrag_immer_positiv(self):
        assert ff.felder(_pos(betrag=-7.5))[2] == '7,50'

    def test_kostentraeger_nur_mit_kostenstelle(self):
        f = ff.felder(_pos(kostenstelle=None, kostentraeger=1))
        assert f[7] == '' and f[8] == ''

    def test_lastschrift_leer_ohne_kennzeichen(self):
        assert ff.felder(_pos(lastschrifteinzug=None))[36] == ''
        assert ff.felder(_pos(lastschrifteinzug=1))[36] == '1'

    def test_land_fallback_de(self):
        assert ff.felder(_pos(land=None))[27] == 'DE'
        assert ff.felder(_pos(land='Deutschland'))[27] == 'DE'  # zu lang → Fallback

    def test_separator_wird_entschaerft(self):
        # Ein Semikolon im Namen darf die Spaltenzahl nicht sprengen.
        assert ';' not in ff.felder(_pos(nachname='A;B'))[22]


class TestFormatterRender:
    def test_zeile_mindestens_29_felder(self):
        assert len(ff.render_zeile(_pos()).split(';')) >= 29

    def test_render_crlf_und_utf8(self):
        data = ff.render([_pos(nachname='Groß'), _pos(belegnummer='B2')])
        assert isinstance(data, bytes)
        text = data.decode('utf-8')
        assert text.count('\r\n') == 2          # je Satz ein CRLF
        assert 'Groß' in text

    def test_dateiname(self):
        assert ff.FBASC_DATEINAME == 'fbasc.hia'


# ---------------------------------------------------------------------------
# Service-Fixtures
# ---------------------------------------------------------------------------

def _row(**kw):
    base = dict(
        quelle_typ='beitrag', quelle_id=1, periode='2026-Q4', betrag_soll=30.0,
        belegdatum='2026-06-21', mitglied_id=10, mitgliedsnummer=5, vorname='Anna',
        nachname='Müller', strasse='Weg 1', plz='12345', ort='Stadt', land='DE',
        iban='DE00', bic='XBIC', zahlungsart='lastschrift', kontoinhaber=None,
        email='anna@example.org',
        sepa_mandatsref='M1', sepa_mandatsdatum='2025-01-02',
        eintrittsdatum='2024-03-15',
        quelle_name='Vereinsbeitrag', zahler_typ='mitglied', gegenkonto='4000',
        steuerschluessel=None, abteilung_id=None, abteilung_kostenstelle=None,
        quelle_kostenstelle=None, quelle_kostentraeger=None,
    )
    base.update(kw)
    return base


def _einst(**kw):
    base = dict(debitor_konto_basis=70000, default_gegenkonto='4999',
                default_steuerschluessel=None, verein_kostenstelle=12,
                default_kostentraeger=1)
    base.update(kw)
    return FibuEinstellungen(**base)


class _FibuExporteStub:
    def __init__(self, neu, gegen):
        self._neu, self._gegen = neu, gegen
        self.calls = []
        self.storno_calls = []
        self.un_export_calls = []
        self.exporte = {}          # id -> FibuExport (für get_export)
        self.latest_id = None      # is_latest()-Antwort
        self.storno_lauf = None    # find_storno_lauf()-Antwort

    def list_neue_positionen(self):
        return self._neu

    def list_gegenbuchungen(self):
        return self._gegen

    def get_positionen_fuer_export(self, export_id):
        return self._neu, self._gegen

    def create_export(self, **kw):
        self.calls.append(kw)
        return FibuExport(id=1, dateiname=kw['dateiname'],
                          anzahl_positionen=kw['anzahl_positionen'],
                          summe_cent=kw['summe_cent'])

    def get_export(self, export_id):
        if export_id in self.exporte:
            return self.exporte[export_id]
        raise KeyError(export_id)

    def is_latest(self, export_id):
        return export_id == self.latest_id

    def find_storno_lauf(self, original_id):
        return self.storno_lauf

    def un_export(self, export_id, *, benutzer):
        self.un_export_calls.append((export_id, benutzer))
        return 3

    def create_storno_lauf(self, **kw):
        self.storno_calls.append(kw)
        return FibuExport(id=99, dateiname=kw['dateiname'],
                          anzahl_positionen=kw['anzahl_positionen'],
                          summe_cent=kw['summe_cent'],
                          storno_von_export_id=kw['original_id'])


def _service(neu=None, gegen=None, einst=None):
    stub = _FibuExporteStub(neu or [], gegen or [])
    db = SimpleNamespace(
        fibu_einstellungen=SimpleNamespace(get=lambda: einst or _einst()),
        fibu_exporte=stub,
    )
    return FibuExportService(db), stub


# ---------------------------------------------------------------------------
# Konten-Auflösung
# ---------------------------------------------------------------------------

class TestAufloesung:
    def test_debitor_konto_basis_plus_nummer(self):
        svc, _ = _service(neu=[_row(mitgliedsnummer=5)])
        p = svc.vorschau()['forderungen'][0]
        assert p.konto == 70005

    def test_soll_haben_und_belegnummer(self):
        svc, _ = _service(neu=[_row(quelle_typ='beitrag', quelle_id=7)],
                          gegen=[_row(quelle_typ='gebuehr', quelle_id=9, gegenkonto='4100')])
        v = svc.vorschau()
        assert v['forderungen'][0].soll_haben == 'S'
        assert v['forderungen'][0].belegnummer == 'B7'
        assert v['gegenbuchungen'][0].soll_haben == 'H'
        assert v['gegenbuchungen'][0].belegnummer == 'G9'

    def test_gegenkonto_fallback_auf_default(self):
        svc, _ = _service(neu=[_row(gegenkonto=None)])
        assert svc.vorschau()['forderungen'][0].gegenkonto == '4999'

    def test_kostenstelle_verein_default_ohne_abteilung(self):
        svc, _ = _service(neu=[_row(abteilung_id=None, abteilung_kostenstelle=None)])
        assert svc.vorschau()['forderungen'][0].kostenstelle == 12

    def test_kostenstelle_aus_abteilung(self):
        svc, _ = _service(neu=[_row(abteilung_id=3, abteilung_kostenstelle=44)])
        assert svc.vorschau()['forderungen'][0].kostenstelle == 44

    def test_kostenstelle_gebuehr_override_schlaegt_abteilung(self):
        svc, _ = _service(neu=[_row(quelle_typ='gebuehr', abteilung_id=3,
                                    abteilung_kostenstelle=44, quelle_kostenstelle=99)])
        assert svc.vorschau()['forderungen'][0].kostenstelle == 99

    def test_belegdatum_abrechnung_und_faelligkeit_plus_10(self):
        # Belegdatum = Abrechnungsdatum (hier created_at als Timestamp -> nur Datumsanteil),
        # Fälligkeit = Belegdatum + 10 Tage.
        svc, _ = _service(neu=[_row(belegdatum='2026-06-21 17:30:00.123+00')])
        p = svc.vorschau()['forderungen'][0]
        assert p.belegdatum == '2026-06-21'
        assert p.faelligkeitsdatum == '2026-07-01'

    def test_belegdatum_und_mandatsdatum_als_datetime_objekt(self):
        # Postgres liefert seit der TIMESTAMPTZ-/DATE-Umstellung (v51) datetime/date-Objekte
        # statt ISO-Strings. Diese müssen ebenso auf den reinen Datumsanteil normalisiert
        # werden (Regression: 'datetime.datetime' object is not subscriptable).
        from datetime import date, datetime, timezone
        svc, _ = _service(neu=[_row(
            belegdatum=datetime(2026, 6, 21, 17, 30, tzinfo=timezone.utc),
            sepa_mandatsdatum=date(2025, 1, 2),
        )])
        p = svc.vorschau()['forderungen'][0]
        assert p.belegdatum == '2026-06-21'
        assert p.faelligkeitsdatum == '2026-07-01'
        assert p.mandatsdatum == '2025-01-02'
        # Bis in die gerenderte FBASC-Zeile (Feld 48 = Mandatsdatum) durchformatiert.
        assert ff.render_zeile(p).split(';')[48] == '02.01.2025'

    def test_lastschrift_ohne_iban_leer(self):
        svc, _ = _service(neu=[_row(iban=None, sepa_mandatsref=None)])
        assert svc.vorschau()['forderungen'][0].lastschrifteinzug is None

    def test_mandatsref_gespeichert_hat_vorrang(self):
        svc, _ = _service(neu=[_row(sepa_mandatsref='ALT-9', sepa_mandatsdatum='2020-01-01')])
        p = svc.vorschau()['forderungen'][0]
        assert p.mandatsref == 'ALT-9' and p.mandatsdatum == '2020-01-01'

    def test_mandatsref_fallback_aus_mitgliedsnummer(self):
        # Neues Lastschrift-Mitglied ohne gespeichertes Mandat: Referenz = Mitgliedsnummer,
        # Datum = Eintrittsdatum, Lastschrift-Kennzeichen gesetzt (IBAN vorhanden).
        svc, _ = _service(neu=[_row(mitgliedsnummer=42, sepa_mandatsref=None,
                                    sepa_mandatsdatum=None, eintrittsdatum='2026-05-01')])
        p = svc.vorschau()['forderungen'][0]
        assert p.mandatsref == '42'
        assert p.mandatsdatum == '2026-05-01'
        assert p.lastschrifteinzug == 1

    def test_ueberweiser_ohne_lastschrift_und_ohne_mandatsfallback(self):
        # Überweiser mit IBAN: KEIN Lastschrift-Kennzeichen (Feld 36) und keine aus der
        # Mitgliedsnummer abgeleitete Mandatsreferenz.
        svc, _ = _service(neu=[_row(zahlungsart='ueberweisung', sepa_mandatsref=None,
                                    sepa_mandatsdatum=None)])
        p = svc.vorschau()['forderungen'][0]
        assert p.lastschrifteinzug is None
        assert p.mandatsref is None
        assert p.mandatsdatum is None

    def test_ueberweiser_behaelt_echtes_gespeichertes_mandat(self):
        # Ein real gespeichertes Mandat bleibt erhalten, aber ohne Lastschrift-Kennzeichen.
        svc, _ = _service(neu=[_row(zahlungsart='ueberweisung', sepa_mandatsref='ECHT-7')])
        p = svc.vorschau()['forderungen'][0]
        assert p.mandatsref == 'ECHT-7'
        assert p.lastschrifteinzug is None

    def test_mailadresse_wird_uebernommen(self):
        svc, _ = _service(neu=[_row(email='kontakt@example.org')])
        assert svc.vorschau()['forderungen'][0].mailadresse == 'kontakt@example.org'

    def test_abw_kontoinhaber_nur_wenn_abweichend(self):
        # Kontoinhaber gleich Mitgliedsname -> kein abweichender Kontoinhaber (Feld 70 leer).
        svc, _ = _service(neu=[_row(vorname='Anna', nachname='Müller', kontoinhaber='Anna Müller')])
        assert svc.vorschau()['forderungen'][0].kontoinhaber is None
        # Abweichender Name -> wird übernommen.
        svc, _ = _service(neu=[_row(vorname='Anna', nachname='Müller', kontoinhaber='Max Vormund')])
        assert svc.vorschau()['forderungen'][0].kontoinhaber == 'Max Vormund'


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

class TestValidierung:
    def test_fehlende_mitgliedsnummer(self):
        svc, _ = _service(neu=[_row(mitgliedsnummer=None)])
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'Mitgliedsnummer' in fehler[0]['problem']

    def test_fehlendes_gegenkonto_ohne_default(self):
        svc, _ = _service(neu=[_row(gegenkonto=None)], einst=_einst(default_gegenkonto=None))
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'Gegenkonto' in fehler[0]['problem']

    def test_fehlende_konto_basis(self):
        svc, _ = _service(neu=[_row()], einst=_einst(debitor_konto_basis=None))
        fehler = svc.vorschau()['fehler']
        assert 'Debitor-Konto-Basis' in fehler[0]['problem']

    def test_alles_konfiguriert_keine_fehler(self):
        svc, _ = _service(neu=[_row()])
        assert svc.vorschau()['fehler'] == []


# ---------------------------------------------------------------------------
# Abteilungs-getragene Beiträge (zahler_typ='abteilung') – Kostenstellen-Umbuchung
# ---------------------------------------------------------------------------

def _abt_row(**kw):
    base = dict(zahler_typ='abteilung', abteilung_id=3, abteilung_kostenstelle=20, betrag_soll=30.0)
    base.update(kw)
    return _row(**base)


class TestAbteilungUmbuchung:
    def test_einbuchung_und_gegenbuchung_als_paar(self):
        svc, _ = _service(neu=[_abt_row(quelle_id=1)])
        f = svc.vorschau()['forderungen']
        assert len(f) == 2
        ein, gegen = f
        # Einbuchung: Soll, Kostenstelle Verein (12), kein Lastschrifteinzug (kein Geld fließt).
        assert ein.soll_haben == 'S' and ein.kostenstelle == 12
        assert ein.lastschrifteinzug is None
        # Gegenbuchung: Haben, Kostenstelle Abteilung (20).
        assert gegen.soll_haben == 'H' and gegen.kostenstelle == 20
        assert gegen.lastschrifteinzug is None
        # Gleiches Erlöskonto/Debitor/Betrag/Belegnummer → ausgleichendes OPOS-Paar.
        assert ein.konto == gegen.konto == 70005
        assert ein.gegenkonto == gegen.gegenkonto == '4000'
        assert ein.betrag == gegen.betrag == 30.0
        assert ein.belegnummer == gegen.belegnummer == 'B1'

    def test_export_rendert_zwei_zeilen_mit_getauschter_kostenstelle(self):
        svc, stub = _service(neu=[_abt_row(quelle_id=1)])
        export, content = svc.exportieren(erstellt_von='admin')
        zeilen = content.decode('utf-8').strip().split('\r\n')
        assert len(zeilen) == 2
        assert zeilen[0].split(';')[3] == 'S' and zeilen[0].split(';')[7] == '12'  # Einbuchung/Verein
        assert zeilen[1].split(';')[3] == 'H' and zeilen[1].split(';')[7] == '20'  # Gegenb./Abteilung
        # Netto fließt nichts; Quellzeile genau einmal gestempelt.
        assert stub.calls[0]['summe_cent'] == 0
        assert stub.calls[0]['anzahl_positionen'] == 2
        assert stub.calls[0]['neu_ids'] == {'beitrag': [1], 'gebuehr': []}

    def test_storno_dreht_beide_zeilen_um(self):
        # Stornierter/gelöschter Abteilungs-Posten → Gegenbuchungs-Paar mit invertiertem S/H.
        svc, _ = _service(gegen=[_abt_row(quelle_id=1)])
        g = svc.vorschau()['gegenbuchungen']
        assert len(g) == 2
        ein, gegen = g
        assert ein.soll_haben == 'H' and ein.kostenstelle == 12
        assert gegen.soll_haben == 'S' and gegen.kostenstelle == 20

    def test_fehler_ohne_abteilungskostenstelle(self):
        svc, _ = _service(neu=[_abt_row(abteilung_kostenstelle=None)])
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'Kostenstelle' in fehler[0]['problem']

    def test_fehler_ohne_abteilung(self):
        # Beitragsregel: weder eigene Abteilung noch über die Bedingung ableitbar.
        svc, _ = _service(neu=[_abt_row(abteilung_id=None, abteilung_kostenstelle=None)])
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'weder die Regel' in fehler[0]['problem']

    def test_abteilung_aus_bedingung_abgeleitet_bucht_paar(self):
        # Vereinsbeitrag ohne eigene Abteilung: das Repository hat die tragende Abteilung aus
        # der Bedingung aufgelöst (abteilung_id/-kostenstelle gesetzt) → Paar wie gewohnt,
        # keine Fehler.
        svc, _ = _service(neu=[_abt_row(abteilung_id=7, abteilung_kostenstelle=20)])
        v = svc.vorschau()
        assert v['fehler'] == []
        ein, gegen = v['forderungen']
        assert ein.kostenstelle == 12 and gegen.kostenstelle == 20

    def test_fehler_bei_mehrdeutiger_abteilung(self):
        # Bedingung nennt mehrere Abteilungen → nicht eindeutig zuordenbar (Repository-Flag).
        svc, _ = _service(neu=[_abt_row(abteilung_id=None, abteilung_kostenstelle=None,
                                        abteilung_mehrdeutig=True)])
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'mehrere' in fehler[0]['problem']

    def test_fehler_gebuehr_ohne_abteilung_nennt_gebuehr(self):
        # Gebühren haben keine Bedingung → eigene, gebührenspezifische Fehlermeldung.
        svc, _ = _service(neu=[_abt_row(quelle_typ='gebuehr', quelle_id=4,
                                        abteilung_id=None, abteilung_kostenstelle=None)])
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'Gebühr' in fehler[0]['problem']

    def test_konto_fehler_nicht_doppelt_gemeldet(self):
        # Beide Positionen teilen denselben Konto-Fehler → darf nur einmal erscheinen.
        svc, _ = _service(neu=[_abt_row(mitgliedsnummer=None)])
        fehler = svc.vorschau()['fehler']
        assert len(fehler) == 1 and 'Mitgliedsnummer' in fehler[0]['problem']


# ---------------------------------------------------------------------------
# Export-Lauf
# ---------------------------------------------------------------------------

class TestExportieren:
    def test_partitioniert_neu_und_storno_ids(self):
        svc, stub = _service(
            neu=[_row(quelle_typ='beitrag', quelle_id=1),
                 _row(quelle_typ='gebuehr', quelle_id=2, gegenkonto='4100')],
            gegen=[_row(quelle_typ='beitrag', quelle_id=3)],
        )
        export, content = svc.exportieren(erstellt_von='admin')
        assert isinstance(content, bytes) and content
        kw = stub.calls[0]
        assert kw['neu_ids'] == {'beitrag': [1], 'gebuehr': [2]}
        assert kw['storno_ids'] == {'beitrag': [3], 'gebuehr': []}
        assert kw['anzahl_positionen'] == 3

    def test_summe_cent_netto(self):
        svc, stub = _service(
            neu=[_row(quelle_id=1, betrag_soll=30.0)],
            gegen=[_row(quelle_id=2, betrag_soll=10.0)],
        )
        svc.exportieren(erstellt_von='admin')
        assert stub.calls[0]['summe_cent'] == 3000 - 1000

    def test_abbruch_bei_validierungsfehler(self):
        svc, stub = _service(neu=[_row(mitgliedsnummer=None)])
        with pytest.raises(FibuExportFehler):
            svc.exportieren(erstellt_von='admin')
        assert stub.calls == []  # kein Lauf angelegt

    def test_abbruch_wenn_nichts_zu_exportieren(self):
        svc, _ = _service(neu=[], gegen=[])
        with pytest.raises(ValueError):
            svc.exportieren(erstellt_von='admin')


# ---------------------------------------------------------------------------
# Lauf-Storno: Un-Export (Rücknahme) und Gegenbuchungs-Lauf
# ---------------------------------------------------------------------------

class TestZuruecknehmen:
    def test_un_export_des_juengsten_laufs(self):
        svc, stub = _service(neu=[_row()])
        stub.exporte = {5: FibuExport(id=5)}
        stub.latest_id = 5
        result = svc.zuruecknehmen(5, benutzer='admin')
        assert result == {'zurueckgenommen': 5, 'positionen_wieder_offen': 3}
        assert stub.un_export_calls == [(5, 'admin')]

    def test_nicht_juengster_lauf_abgelehnt(self):
        svc, stub = _service(neu=[_row()])
        stub.exporte = {5: FibuExport(id=5)}
        stub.latest_id = 7  # 5 ist nicht der jüngste
        with pytest.raises(ValueError):
            svc.zuruecknehmen(5, benutzer='admin')
        assert stub.un_export_calls == []

    def test_unbekannter_lauf(self):
        svc, stub = _service(neu=[_row()])
        with pytest.raises(KeyError):
            svc.zuruecknehmen(123, benutzer='admin')


class TestGegenbuchungsLauf:
    def test_storno_tauscht_soll_haben_und_summe(self):
        # Original: eine Forderung (S) über 30 € → Gegenbuchung (H), Netto-Summe negativ.
        svc, stub = _service(neu=[_row(quelle_typ='beitrag', quelle_id=1, betrag_soll=30.0)])
        stub.exporte = {5: FibuExport(id=5)}
        export, content = svc.stornieren(5, benutzer='admin')
        assert export.storno_von_export_id == 5
        assert stub.storno_calls[0]['original_id'] == 5
        assert stub.storno_calls[0]['summe_cent'] == -3000
        # Erste Buchungszeile muss Haben sein (Feld 03), Original war Soll.
        assert content.decode('utf-8').split('\r\n')[0].split(';')[3] == 'H'

    def test_re_download_storno_lauf_rekonstruiert_aus_original(self):
        svc, stub = _service(neu=[_row(quelle_typ='beitrag', quelle_id=1)])
        stub.exporte = {99: FibuExport(id=99, storno_von_export_id=5)}
        content = svc.re_download(99)
        assert content.decode('utf-8').split('\r\n')[0].split(';')[3] == 'H'

    def test_doppel_storno_abgelehnt(self):
        svc, stub = _service(neu=[_row()])
        stub.exporte = {5: FibuExport(id=5)}
        stub.storno_lauf = FibuExport(id=99, storno_von_export_id=5)  # schon storniert
        with pytest.raises(ValueError):
            svc.stornieren(5, benutzer='admin')
        assert stub.storno_calls == []

    def test_storno_eines_storno_laufs_abgelehnt(self):
        svc, stub = _service(neu=[_row()])
        stub.exporte = {9: FibuExport(id=9, storno_von_export_id=5)}  # selbst ein Storno-Lauf
        with pytest.raises(ValueError):
            svc.stornieren(9, benutzer='admin')

    def test_storno_ohne_positionen_abgelehnt(self):
        svc, stub = _service(neu=[], gegen=[])
        stub.exporte = {5: FibuExport(id=5)}
        with pytest.raises(ValueError):
            svc.stornieren(5, benutzer='admin')
