"""
Tests für die anteilige Beitragsberechnung (BeitragsService).

Fachregel (vom Anwender bestätigt):
- Monatsweise Abrechnung: jeder Kalendermonat im Turnus, in dem das Mitglied
  mindestens einen Tag aktiv war, zählt als voller `betrag_pro_monat`.
- Angefangener Monat zählt voll, der Austrittsmonat zählt mit.
"""
from datetime import date
from types import SimpleNamespace

from app.models.beitrag import Beitragsregel
from app.services.beitrags_service import (
    BeitragsService,
    VorschauPosition,
    zeitraum_monate,
    zeitraum_label,
    faelligkeitsdatum,
    parse_datum,
    aktive_monate_menge,
    _letzter_tag,
)

# Q4/2026 als durchgängiger Beispiel-Zeitraum: Okt, Nov, Dez 2026
Q4 = [(2026, 10), (2026, 11), (2026, 12)]


class TestZeitraumMonate:
    def test_quartal_q4(self):
        assert zeitraum_monate('quartal', date(2026, 10, 1)) == Q4
        # Stichtag irgendwo im Quartal liefert dieselben Monate
        assert zeitraum_monate('quartal', date(2026, 11, 23)) == Q4

    def test_quartal_q1(self):
        assert zeitraum_monate('quartal', date(2026, 2, 15)) == [(2026, 1), (2026, 2), (2026, 3)]

    def test_monat(self):
        assert zeitraum_monate('monat', date(2026, 7, 9)) == [(2026, 7)]

    def test_halbjahr(self):
        assert zeitraum_monate('halbjahr', date(2026, 3, 1)) == [(2026, m) for m in range(1, 7)]
        assert zeitraum_monate('halbjahr', date(2026, 9, 1)) == [(2026, m) for m in range(7, 13)]

    def test_jahr(self):
        assert zeitraum_monate('jahr', date(2026, 5, 5)) == [(2026, m) for m in range(1, 13)]

    def test_anzahl_passt_zum_einzug_faktor(self):
        # Voller Zeitraum = Faktor aus betrag_pro_einzug (monat=1, quartal=3, …)
        assert len(zeitraum_monate('monat', date(2026, 1, 1))) == 1
        assert len(zeitraum_monate('quartal', date(2026, 1, 1))) == 3
        assert len(zeitraum_monate('halbjahr', date(2026, 1, 1))) == 6
        assert len(zeitraum_monate('jahr', date(2026, 1, 1))) == 12


class TestParseDatum:
    def test_iso(self):
        assert parse_datum('2026-11-15') == date(2026, 11, 15)

    def test_mit_zeitanteil(self):
        assert parse_datum('2026-11-15T08:30:00') == date(2026, 11, 15)

    def test_leer_und_none(self):
        assert parse_datum('') is None
        assert parse_datum(None) is None

    def test_ungueltig(self):
        assert parse_datum('unbekannt') is None
        assert parse_datum('2026-13-40') is None


class TestLetzterTag:
    def test_normal(self):
        assert _letzter_tag(2026, 11) == date(2026, 11, 30)

    def test_dezember(self):
        assert _letzter_tag(2026, 12) == date(2026, 12, 31)

    def test_februar_schaltjahr(self):
        assert _letzter_tag(2024, 2) == date(2024, 2, 29)
        assert _letzter_tag(2026, 2) == date(2026, 2, 28)


class TestAktiveMonateMenge:
    def _anzahl(self, von, bis):
        return len(aktive_monate_menge(Q4, von, bis))

    def test_durchgehend_aktiv(self):
        # Eintritt lange vorher, kein Austritt → voller Zeitraum (3 Monate)
        assert aktive_monate_menge(Q4, date(2020, 1, 1), None) == set(Q4)
        # Komplett offenes Intervall
        assert aktive_monate_menge(Q4, None, None) == set(Q4)

    def test_eintritt_mitten_im_quartal(self):
        # Eintritt 15.11. → Nov + Dez = 2 (angefangener Monat zählt)
        assert aktive_monate_menge(Q4, date(2026, 11, 15), None) == {(2026, 11), (2026, 12)}
        assert self._anzahl(date(2026, 11, 15), None) == 2

    def test_austritt_mitten_im_quartal(self):
        # Austritt 10.11. → Okt + Nov = 2 (Austrittsmonat zählt mit)
        assert aktive_monate_menge(Q4, None, date(2026, 11, 10)) == {(2026, 10), (2026, 11)}
        assert self._anzahl(None, date(2026, 11, 10)) == 2

    def test_ein_und_austritt_im_selben_quartal(self):
        # 20.10. – 05.11. → Okt + Nov = 2
        assert self._anzahl(date(2026, 10, 20), date(2026, 11, 5)) == 2

    def test_nur_ein_monat(self):
        # Eintritt 01.12., kein Austritt → nur Dez
        assert aktive_monate_menge(Q4, date(2026, 12, 1), None) == {(2026, 12)}
        # Eintritt am letzten Tag des Monats → Monat zählt trotzdem voll
        assert aktive_monate_menge(Q4, date(2026, 12, 31), None) == {(2026, 12)}

    def test_eintritt_nach_zeitraum(self):
        # Eintritt erst im Folgejahr → keine Monate
        assert self._anzahl(date(2027, 1, 5), None) == 0

    def test_austritt_vor_zeitraum(self):
        # Austritt vor Quartalsbeginn → keine Monate
        assert self._anzahl(None, date(2026, 9, 30)) == 0

    def test_austritt_am_monatsersten_zaehlt(self):
        # bis = 01.11. → Austrittsmonat November zählt → Okt + Nov
        assert aktive_monate_menge(Q4, None, date(2026, 11, 1)) == {(2026, 10), (2026, 11)}

    def test_betrag_ist_vielfaches_des_monatsbeitrags(self):
        # betrag_pro_monat × Monate – keine krummen Cent-Beträge
        betrag_pro_monat = 12.50
        anzahl = self._anzahl(date(2026, 11, 15), None)   # 2 Monate
        assert round(betrag_pro_monat * anzahl, 2) == 25.00


class TestVorschauAnteilig:
    """Orchestrierung von vorschau() mit anteiliger Berechnung (Fake-DB)."""

    def _service(self, regel, rows):
        db = SimpleNamespace(
            beitragsregeln=SimpleNamespace(list_aktive=lambda s: [regel]),
            sollstellungen=SimpleNamespace(exists=lambda mid, rid, z: False),
        )
        svc = BeitragsService(db)
        # DB-abhängige Helfer durch die vorbereiteten Daten ersetzen.
        svc._betroffene_mitglieder = lambda r, s, ps, pe: rows
        svc._mitglied_abteilungen = lambda ids: {}
        return svc

    def test_anteilige_betraege_pro_mitglied(self):
        regel = Beitragsregel(id=1, name='Verein', abteilung_id=None,
                              betrag_pro_monat=10.0, einzug_turnus='quartal')
        rows = [
            # durchgehend aktiv → 3 Monate → 30 €
            {'id': 1, 'vorname': 'A', 'nachname': 'Voll', 'iban': None,
             'aktiv_von': '2020-01-01', 'aktiv_bis': None},
            # Eintritt 15.11. → Nov+Dez → 20 €
            {'id': 2, 'vorname': 'B', 'nachname': 'Neu', 'iban': None,
             'aktiv_von': '2026-11-15', 'aktiv_bis': None},
            # Austritt 10.11. → Okt+Nov → 20 €
            {'id': 3, 'vorname': 'C', 'nachname': 'Weg', 'iban': None,
             'aktiv_von': '2019-01-01', 'aktiv_bis': '2026-11-10'},
            # Eintritt erst 2027 → 0 Monate → keine Position
            {'id': 4, 'vorname': 'D', 'nachname': 'Spaeter', 'iban': None,
             'aktiv_von': '2027-01-05', 'aktiv_bis': None},
        ]
        positionen = self._service(regel, rows).vorschau('2026-10-01')

        by_id = {p.mitglied_id: p for p in positionen}
        assert set(by_id) == {1, 2, 3}            # Mitglied 4 fällt raus
        assert (by_id[1].betrag, by_id[1].anzahl_monate) == (30.0, 3)
        assert (by_id[2].betrag, by_id[2].anzahl_monate) == (20.0, 2)
        assert (by_id[3].betrag, by_id[3].anzahl_monate) == (20.0, 2)
        assert all(p.monate_im_zeitraum == 3 for p in positionen)
        assert by_id[2].zeitraum == '2026-Q4'

    def test_vereinsaustritt_deckelt_abteilungsbeitrag(self):
        # Ticket #18 Nachtrag: Austritt aus dem Verein (30.06.) beendet implizit
        # die Abteilungsmitgliedschaft – auch wenn dort kein bis-Datum steht.
        regel = Beitragsregel(id=9, name='Abt', abteilung_id=5,
                              betrag_pro_monat=11.0, einzug_turnus='quartal')
        rows = [
            {'id': 1, 'vorname': 'Ben', 'nachname': 'M', 'iban': None,
             'aktiv_von': '2014-11-01', 'aktiv_bis': None,
             'verein_bis': '2026-06-30'},
        ]
        # Q3 (Jul–Sep): nach dem Vereinsaustritt → keine Position mehr
        assert self._service(regel, rows).vorschau('2026-07-01') == []
        # Q2 (Apr–Jun): noch voll aktiv → 3 Monate
        positionen = self._service(regel, rows).vorschau('2026-04-01')
        assert len(positionen) == 1
        assert (positionen[0].anzahl_monate, positionen[0].betrag) == (3, 33.0)

    def test_vereinsaustritt_im_quartal_zaehlt_anteilig(self):
        # Austritt 10.08. → Austrittsmonat zählt mit: Jul+Aug = 2 Monate
        regel = Beitragsregel(id=9, name='Abt', abteilung_id=5,
                              betrag_pro_monat=11.0, einzug_turnus='quartal')
        rows = [
            {'id': 1, 'vorname': 'Ben', 'nachname': 'M', 'iban': None,
             'aktiv_von': '2014-11-01', 'aktiv_bis': None,
             'verein_bis': '2026-08-10'},
        ]
        positionen = self._service(regel, rows).vorschau('2026-07-01')
        assert (positionen[0].anzahl_monate, positionen[0].betrag) == (2, 22.0)

    def test_frueheres_abteilungsende_hat_vorrang(self):
        # bis (31.07.) liegt vor dem Vereinsaustritt (30.09.) → bis gewinnt: Jul = 1 Monat
        regel = Beitragsregel(id=9, name='Abt', abteilung_id=5,
                              betrag_pro_monat=11.0, einzug_turnus='quartal')
        rows = [
            {'id': 1, 'vorname': 'Ben', 'nachname': 'M', 'iban': None,
             'aktiv_von': '2014-11-01', 'aktiv_bis': '2026-07-31',
             'verein_bis': '2026-09-30'},
        ]
        positionen = self._service(regel, rows).vorschau('2026-07-01')
        assert (positionen[0].anzahl_monate, positionen[0].betrag) == (1, 11.0)

    def test_mehrere_intervalle_werden_vereinigt(self):
        # Zwei Mitgliedschafts-Zeilen desselben Mitglieds: Monate vereinigen,
        # nicht summieren. Okt (aus Zeile 1) + Dez (aus Zeile 2) = 2 Monate.
        regel = Beitragsregel(id=7, name='Abt', abteilung_id=5,
                              betrag_pro_monat=10.0, einzug_turnus='quartal')
        rows = [
            {'id': 1, 'vorname': 'A', 'nachname': 'X', 'iban': None,
             'aktiv_von': '2026-10-01', 'aktiv_bis': '2026-10-31'},
            {'id': 1, 'vorname': 'A', 'nachname': 'X', 'iban': None,
             'aktiv_von': '2026-12-01', 'aktiv_bis': '2026-12-31'},
        ]
        positionen = self._service(regel, rows).vorschau('2026-10-01')
        assert len(positionen) == 1
        assert positionen[0].anzahl_monate == 2
        assert positionen[0].betrag == 20.0


class _FakeCursor:
    """Minimaler Cursor, der die letzte SQL/Parameter festhält und [] liefert."""
    def __init__(self):
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class TestBetroffeneMitgliederSQL:
    """
    Regressionsschutz für den NULL-Datums-Bug (Tickets #18/#19): offene
    Mitgliedschaften (bis/austritt IS NULL) bzw. fehlende Eintritts-/von-Daten
    dürfen vom Vorfilter NICHT ausgeschlossen werden. Ohne echte DB wird die
    generierte WHERE-Klausel geprüft.
    """
    def _sql_fuer(self, regel):
        cur = _FakeCursor()
        db = SimpleNamespace(conn=SimpleNamespace(cursor=lambda: cur))
        BeitragsService(db)._betroffene_mitglieder(
            regel, '2026-04-15', date(2026, 4, 1), date(2026, 6, 30))
        return cur.sql

    def test_abteilung_schliesst_offene_mitgliedschaften_nicht_aus(self):
        sql = self._sql_fuer(Beitragsregel(id=1, abteilung_id=5, einzug_turnus='quartal'))
        assert 'ma.bis IS NULL' in sql
        assert 'ma.von IS NULL' in sql
        # Das fehlerhafte NOT(... AND ...)-Muster darf nicht zurückkommen.
        assert 'NOT (ma.bis' not in sql
        assert 'NOT (ma.von' not in sql

    def test_abteilung_beruecksichtigt_vereinsaustritt(self):
        # Vereinsaustritt beendet implizit die Abteilungsmitgliedschaft:
        # austrittsdatum muss selektiert und vorgefiltert werden.
        sql = self._sql_fuer(Beitragsregel(id=1, abteilung_id=5, einzug_turnus='quartal'))
        assert 'm.austrittsdatum AS verein_bis' in sql
        assert 'm.austrittsdatum IS NULL' in sql

    def test_verein_schliesst_aktive_mitglieder_nicht_aus(self):
        sql = self._sql_fuer(Beitragsregel(id=2, abteilung_id=None, einzug_turnus='quartal'))
        assert 'm.austrittsdatum IS NULL' in sql
        assert 'm.eintrittsdatum IS NULL' in sql
        assert 'NOT (m.austrittsdatum' not in sql


class TestDashboardAggregation:
    """Aggregation der Projektion zu Summen/Zahlern je Bereich (Fake-vorschau)."""

    def _pos(self, mid, abt_id, abt_name, betrag):
        return VorschauPosition(
            mitglied_id=mid, mitglied_vorname='', mitglied_nachname='',
            mitglied_iban=None, beitragsregel_id=1, beitragsregel_name='',
            beitragsregel_abteilung_id=abt_id, beitragsregel_abteilung_name=abt_name,
            betrag=betrag, zahler_typ='mitglied', zeitraum='2026-Q4',
            faelligkeitsdatum='2026-12-31', bereits_vorhanden=False)

    def _dashboard(self, positionen):
        svc = BeitragsService(SimpleNamespace())
        svc.vorschau = lambda s: positionen
        return svc.dashboard('2026-10-01')

    def test_summen_und_distinct_zahler(self):
        positionen = [
            self._pos(1, None, None, 30.0),     # Vereinsbeitrag
            self._pos(2, None, None, 20.0),
            self._pos(1, 5, 'Turnen', 15.0),    # Mitglied 1 zusätzlich in Abteilung 5
            self._pos(3, 5, 'Turnen', 15.0),
        ]
        erg = self._dashboard(positionen)

        assert erg.zeitraum == '2026-Q4'
        assert erg.gesamt_summe == 80.0
        assert erg.gesamt_zahler == 3            # Mitglieder 1, 2, 3 – distinct
        assert erg.gesamt_positionen == 4

        # Vereinsbeitrag steht vorn und bekommt einen Ersatznamen.
        verein = erg.gruppen[0]
        assert verein.abteilung_id is None
        assert verein.abteilung_name == 'Vereinsbeitrag'
        assert (verein.summe, verein.anzahl_zahler, verein.anzahl_positionen) == (50.0, 2, 2)

        turnen = erg.gruppen[1]
        assert turnen.abteilung_id == 5
        assert (turnen.summe, turnen.anzahl_zahler) == (30.0, 2)

    def test_leer(self):
        erg = self._dashboard([])
        assert erg.gruppen == []
        assert (erg.gesamt_summe, erg.gesamt_zahler, erg.gesamt_positionen) == (0, 0, 0)


class TestZeitraumLabelUndFaelligkeit:
    def test_label(self):
        assert zeitraum_label('quartal', date(2026, 11, 1)) == '2026-Q4'
        assert zeitraum_label('monat', date(2026, 1, 9)) == '2026-01'

    def test_faelligkeit_quartal(self):
        # Letzter Tag des Quartals
        assert faelligkeitsdatum('quartal', date(2026, 11, 1)) == '2026-12-31'

    def test_faelligkeit_jahr(self):
        assert faelligkeitsdatum('jahr', date(2026, 5, 1)) == '2026-12-31'
