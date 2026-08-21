"""Tests für ULStundenService – Serien-/Wochenplan-Erfassung und Vorlage.

Fachregeln:
- add_serie erzeugt für jeden gewählten Wochentag (1=Mo … 7=So) einen Termin an
  jedem passenden Tag im Abrechnungszeitraum; bereits erfasste Tage werden
  übersprungen (idempotent) und nur Entwürfe sind bearbeitbar.
- letzte_vorlage gruppiert die Termine der jüngsten Vor-Abrechnung nach
  (Stunden, Angebot) und liefert je Gruppe die belegten Wochentage, dominantes
  Muster zuerst.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.models.ul_stunden import (
    ULAbrechnung, ULStunde, ULSatz, STATUS_ENTWURF, STATUS_EINGEREICHT, STATUS_BESTAETIGT,
    VERGUETUNG_STUNDENSATZ, VERGUETUNG_MONATSPAUSCHALE, VERGUETUNG_OHNE,
)
from app.services.ul_stunden_service import (
    ULStundenService, berechne_betrag, monate_im_zeitraum, monatsschluessel,
)


def _abr(von='2026-06-01', bis='2026-06-30', status=STATUS_ENTWURF, id=1):
    return ULAbrechnung(id=id, mitglied_id=10, abteilung_id=5,
                        zeitraum_von=von, zeitraum_bis=bis, status=status)


def _satz(wert, art=VERGUETUNG_STUNDENSATZ):
    """Vereinbarung, wie ul_saetze.resolve() sie liefert."""
    return ULSatz(id=1, satz=wert, verguetungsart=art)


def _stunde(datum, stunden=2.0, angebot=None):
    return ULStunde(datum=datum, stunden=stunden, angebot=angebot,
                    wochentag=date.fromisoformat(datum).isoweekday())


class _FakeRepo:
    """Minimaler Fake von db.ul_abrechnungen für die Service-Tests."""
    def __init__(self, *, stunden=(), vorlage_quelle=None, vorlage_termine=(),
                 pauschal_zeitraeume=()):
        self._stunden = list(stunden)
        self.added = []
        self._vorlage_quelle = vorlage_quelle
        self._vorlage_termine = list(vorlage_termine)
        # (von, bis) bereits eingereichter/bestätigter Monatspauschal-Abrechnungen
        self._pauschal_zeitraeume = list(pauschal_zeitraeume)

    def monatspauschal_zeitraeume(self, mitglied_id, abteilung_id, exclude_id=None):
        return list(self._pauschal_zeitraeume)

    def list_stunden(self, abrechnung_id):
        if self._vorlage_quelle is not None and abrechnung_id == self._vorlage_quelle:
            return list(self._vorlage_termine)
        return list(self._stunden)

    def add_stunde(self, s, created_by):
        self._stunden.append(s)
        self.added.append(s)
        return s

    def letzte_vorlage_quelle_id(self, mitglied_id, abteilung_id, exclude_id=None):
        return self._vorlage_quelle


def _svc(repo):
    class _DB:
        ul_abrechnungen = repo
    return ULStundenService(_DB())


class TestAddSerie:
    def test_erzeugt_alle_passenden_wochentage(self):
        repo = _FakeRepo()
        # Juni 2026: 01 = Montag → Di = 2,9,16,23,30 ; Do = 4,11,18,25
        n = _svc(repo).add_serie(_abr(), wochentage=[2, 4], stunden=2.0,
                                 angebot='Fußball', bemerkung=None, erstellt_von='t')
        assert n == 9
        datums = sorted(s.datum for s in repo.added)
        assert datums == ['2026-06-02', '2026-06-04', '2026-06-09', '2026-06-11',
                          '2026-06-16', '2026-06-18', '2026-06-23', '2026-06-25', '2026-06-30']
        assert all(s.stunden == 2.0 and s.angebot == 'Fußball' for s in repo.added)
        assert {s.wochentag for s in repo.added} == {2, 4}

    def test_ueberspringt_bereits_erfasste_tage(self):
        repo = _FakeRepo(stunden=[_stunde('2026-06-09')])  # zweiter Dienstag schon da
        n = _svc(repo).add_serie(_abr(), wochentage=[2], stunden=2.0,
                                 angebot=None, bemerkung=None, erstellt_von='t')
        assert n == 4  # 5 Dienstage minus dem bereits erfassten
        assert '2026-06-09' not in [s.datum for s in repo.added]

    def test_nur_entwurf_bearbeitbar(self):
        repo = _FakeRepo()
        with pytest.raises(ValueError):
            _svc(repo).add_serie(_abr(status=STATUS_EINGEREICHT), wochentage=[2],
                                 stunden=2.0, angebot=None, bemerkung=None, erstellt_von='t')

    def test_leere_wochentage_fehler(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_serie(_abr(), wochentage=[], stunden=2.0,
                                        angebot=None, bemerkung=None, erstellt_von='t')

    def test_ungueltiger_wochentag_fehler(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_serie(_abr(), wochentage=[0, 8], stunden=2.0,
                                        angebot=None, bemerkung=None, erstellt_von='t')

    def test_stunden_muss_positiv_sein(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_serie(_abr(), wochentage=[2], stunden=0,
                                        angebot=None, bemerkung=None, erstellt_von='t')


class TestAddTage:
    def test_legt_gewaehlte_tage_an(self):
        repo = _FakeRepo()
        n = _svc(repo).add_tage(_abr(), datums=['2026-06-06', '2026-06-20'], stunden=2.0,
                                angebot='Spiel', bemerkung=None, erstellt_von='t')
        assert n == 2
        assert sorted(s.datum for s in repo.added) == ['2026-06-06', '2026-06-20']
        assert all(s.angebot == 'Spiel' for s in repo.added)
        # Wochentag wird aus dem Datum abgeleitet (06.06.2026 = Samstag = 6)
        assert repo.added[0].wochentag == 6

    def test_ausserhalb_zeitraum_und_duplikate_uebersprungen(self):
        repo = _FakeRepo(stunden=[_stunde('2026-06-10')])
        n = _svc(repo).add_tage(
            _abr(), datums=['2026-05-31',          # vor dem Zeitraum -> raus
                            '2026-07-01',          # nach dem Zeitraum -> raus
                            '2026-06-10',          # schon erfasst -> raus
                            '2026-06-15', '2026-06-15'],  # Duplikat -> nur einmal
            stunden=2.0, angebot=None, bemerkung=None, erstellt_von='t')
        assert n == 1
        assert [s.datum for s in repo.added] == ['2026-06-15']

    def test_leere_liste_fehler(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_tage(_abr(), datums=[], stunden=2.0,
                                       angebot=None, bemerkung=None, erstellt_von='t')

    def test_nur_entwurf_bearbeitbar(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_tage(_abr(status=STATUS_EINGEREICHT), datums=['2026-06-06'],
                                       stunden=2.0, angebot=None, bemerkung=None, erstellt_von='t')

    def test_stunden_muss_positiv_sein(self):
        with pytest.raises(ValueError):
            _svc(_FakeRepo()).add_tage(_abr(), datums=['2026-06-06'], stunden=0,
                                       angebot=None, bemerkung=None, erstellt_von='t')


class TestLizenzAbleitung:
    """mit_lizenz, wenn das Zeitraum-Ende (bis) im Lizenzfenster [von, bis] liegt (#63)."""
    def _svc(self, gueltig_bis, gueltig_von='2020-01-01'):
        m = SimpleNamespace(trainerlizenz_gueltig_von=gueltig_von,
                            trainerlizenz_gueltig_bis=gueltig_bis)
        return ULStundenService(SimpleNamespace(get_mitglied=lambda mid: m))

    def test_gueltige_lizenz_ist_mit_lizenz(self):
        assert self._svc('2026-12-31').lizenz_fuer(1, '2026-06-30') == 'mit_lizenz'

    def test_genau_am_periodenende_ist_mit_lizenz(self):
        assert self._svc('2026-06-30').lizenz_fuer(1, '2026-06-30') == 'mit_lizenz'

    def test_abgelaufene_lizenz_ist_ohne_lizenz(self):
        assert self._svc('2026-05-31').lizenz_fuer(1, '2026-06-30') == 'ohne_lizenz'

    def test_periodenende_vor_lizenzbeginn_ist_ohne_lizenz(self):
        # Lizenz beginnt erst NACH dem Abrechnungs-Ende → ohne (Startdatum greift, #63).
        assert self._svc('2026-12-31', gueltig_von='2026-07-01') \
            .lizenz_fuer(1, '2026-06-30') == 'ohne_lizenz'

    def test_genau_am_lizenzbeginn_ist_mit_lizenz(self):
        assert self._svc('2026-12-31', gueltig_von='2026-06-30') \
            .lizenz_fuer(1, '2026-06-30') == 'mit_lizenz'

    def test_kein_bis_ist_ohne_lizenz(self):
        assert self._svc(None).lizenz_fuer(1, '2026-06-30') == 'ohne_lizenz'

    def test_kein_von_ist_ohne_lizenz(self):
        # Defensiv: fehlt das Startdatum (legacy-Daten vor #63), zählt es als ohne Lizenz.
        assert self._svc('2026-12-31', gueltig_von=None).lizenz_fuer(1, '2026-06-30') == 'ohne_lizenz'

    def test_unbekanntes_mitglied_ist_ohne_lizenz(self):
        def boom(mid):
            raise KeyError(mid)
        svc = ULStundenService(SimpleNamespace(get_mitglied=boom))
        assert svc.lizenz_fuer(99, '2026-06-30') == 'ohne_lizenz'


class TestEinreichenSnapshot:
    """Beim Einreichen werden Satz UND die Lizenz-Beleg-Stammdaten (Nr./Qualifikation)
    eingefroren, damit ein eingereichter Beleg nicht rückwirkend kippt (#63)."""
    def test_friert_lizenz_nr_und_qualifikation_ein(self):
        erfasst = {}

        class _Repo:
            def list_stunden(self, _id):
                return [_stunde('2026-06-10')]
            def max_gesperrt_bis(self, mid, aid):
                return None
            def monatspauschal_zeitraeume(self, mid, aid, exclude_id=None):
                return []
            def einreichen(self, _id, *, verguetungsart, verguetung_pro_stunde,
                           verguetung_monate, eingereicht_von,
                           trainerlizenz_nr=None, qualifikation=None):
                erfasst.update(satz=verguetung_pro_stunde, art=verguetungsart,
                               nr=trainerlizenz_nr, qual=qualifikation)
                return True
            def get(self, _id):
                return _abr(status=STATUS_EINGEREICHT)

        m = SimpleNamespace(trainerlizenz_nr='TL-123', qualifikation='ÜL-B Prävention')

        class _DB:
            ul_abrechnungen = _Repo()
            ul_saetze = SimpleNamespace(resolve=lambda mid, aid, kl: _satz(17.5))
            get_mitglied = staticmethod(lambda mid: m)

        ULStundenService(_DB()).einreichen(_abr(), eingereicht_von='admin')
        assert erfasst == {'satz': 17.5, 'art': VERGUETUNG_STUNDENSATZ,
                           'nr': 'TL-123', 'qual': 'ÜL-B Prävention'}


class TestSummenVorschau:
    """Im Entwurf ist noch kein Satz eingefroren. summen() liefert dann eine
    Vorschau aus dem aktuell gültigen Satz, ohne den Snapshot zu setzen;
    ab dem Einreichen zählt allein der eingefrorene verguetung_pro_stunde."""

    @staticmethod
    def _svc(stunden, resolve):
        repo = _FakeRepo(stunden=stunden)

        class _DB:
            ul_abrechnungen = repo
            ul_saetze = SimpleNamespace(resolve=resolve)

        return ULStundenService(_DB())

    def test_entwurf_zeigt_vorschau_ohne_snapshot(self):
        svc = self._svc([_stunde('2026-06-02'), _stunde('2026-06-09')],
                        lambda mid, aid, kl: _satz(10.0))
        s = svc.summen(_abr())                      # Entwurf, verguetung_pro_stunde=None
        assert s['verguetung_pro_stunde'] is None and s['gesamtbetrag'] is None
        assert s['vorschau_pro_stunde'] == 10.0
        assert s['vorschau_gesamtbetrag'] == 40.0   # 2×2,0 Std. × 10 €

    def test_eingereicht_nutzt_snapshot_ohne_vorschau(self):
        abr = _abr(status=STATUS_EINGEREICHT)
        abr.verguetung_pro_stunde = 12.0
        svc = self._svc([_stunde('2026-06-02'), _stunde('2026-06-09')],
                        lambda mid, aid, kl: _satz(99.0))  # darf nicht herangezogen werden
        s = svc.summen(abr)
        assert s['verguetung_pro_stunde'] == 12.0 and s['gesamtbetrag'] == 48.0
        assert s['vorschau_pro_stunde'] is None and s['vorschau_gesamtbetrag'] is None

    def test_entwurf_ohne_satz_liefert_keine_vorschau(self):
        svc = self._svc([_stunde('2026-06-02')], lambda mid, aid, kl: None)
        s = svc.summen(_abr())
        assert s['vorschau_pro_stunde'] is None and s['vorschau_gesamtbetrag'] is None


class TestLetzteVorlage:
    def test_gruppiert_nach_stunden_und_angebot_dominant_zuerst(self):
        termine = [
            _stunde('2026-05-05', 2.0, 'Fußball'),   # Di
            _stunde('2026-05-12', 2.0, 'Fußball'),   # Di
            _stunde('2026-05-07', 1.5, 'Torwart'),   # Do
        ]
        repo = _FakeRepo(vorlage_quelle=99, vorlage_termine=termine)
        out = _svc(repo).letzte_vorlage(mitglied_id=10, abteilung_id=5, exclude_id=1)
        assert out == [
            {'wochentage': [2], 'stunden': 2.0, 'angebot': 'Fußball', 'anzahl': 2},
            {'wochentage': [4], 'stunden': 1.5, 'angebot': 'Torwart', 'anzahl': 1},
        ]

    def test_keine_quelle_liefert_leer(self):
        out = _svc(_FakeRepo(vorlage_quelle=None)).letzte_vorlage(
            mitglied_id=10, abteilung_id=5, exclude_id=1)
        assert out == []


class TestBelegPdf:
    """Der Stundennachweis wird an zwei Stellen gebraucht – Einzeldownload in der App
    und Beleg-Beilage im Fibu-Export – und deshalb im Service gebaut."""

    @staticmethod
    def _svc_mit(abrechnung, mitglied=None, users=None):
        repo = _FakeRepo(stunden=[_stunde('2026-06-02')])
        db = SimpleNamespace(
            ul_abrechnungen=repo,
            ul_saetze=SimpleNamespace(resolve=lambda *a, **k: None),
            get_mitglied=lambda mid: mitglied,
            get_user_by_username=lambda name: (users or {}).get(name),
            get_mitglied_by_user_id=lambda uid: mitglied,
        )
        return ULStundenService(db)

    @staticmethod
    def _abgefangen(monkeypatch):
        """Fängt den Aufruf des PDF-Bauers ab – geprüft wird, was er zu sehen bekommt."""
        gesehen = {}

        def _fake(**kw):
            gesehen.update(kw)
            return b'%PDF-fake'

        monkeypatch.setattr('app.services.ul_stunden_service.erstelle_stundennachweis_pdf',
                            _fake)
        return gesehen

    def test_bestaetigter_beleg_nutzt_den_eingefrorenen_lizenz_snapshot(self, monkeypatch):
        """Eine später am Mitglied geänderte Lizenz darf den fertigen Beleg nicht
        rückwirkend verändern (#63)."""
        gesehen = self._abgefangen(monkeypatch)
        a = _abr(status=STATUS_BESTAETIGT)
        a.trainerlizenz_nr, a.qualifikation = 'ALT-1', 'B-Lizenz'
        mitglied = SimpleNamespace(trainerlizenz_nr='NEU-9', qualifikation='C-Lizenz')
        self._svc_mit(a, mitglied).beleg_pdf(a, verein={'name': 'TV'})
        assert gesehen['trainerlizenz_nr'] == 'ALT-1'
        assert gesehen['qualifikation'] == 'B-Lizenz'

    def test_entwurf_zieht_die_lizenz_live_vom_mitglied(self, monkeypatch):
        gesehen = self._abgefangen(monkeypatch)
        a = _abr(status=STATUS_ENTWURF)
        mitglied = SimpleNamespace(trainerlizenz_nr='NEU-9', qualifikation='C-Lizenz')
        self._svc_mit(a, mitglied).beleg_pdf(a, verein={'name': 'TV'})
        assert gesehen['trainerlizenz_nr'] == 'NEU-9'

    def test_erfasser_erscheint_mit_klarnamen(self, monkeypatch):
        gesehen = self._abgefangen(monkeypatch)
        a = _abr(status=STATUS_BESTAETIGT)
        a.eingereicht_von = 'awagner'
        mitglied = SimpleNamespace(vorname='Annett', nachname='Wagner',
                                   trainerlizenz_nr=None, qualifikation=None)
        svc = self._svc_mit(a, mitglied, users={'awagner': SimpleNamespace(id=3)})
        svc.beleg_pdf(a, verein={'name': 'TV'})
        assert gesehen['eingereicht_von'] == 'Annett Wagner'

    def test_ohne_mitglied_bleibt_der_beleg_baubar(self, monkeypatch):
        """Ein fehlendes Mitglied darf den Beleg nicht sprengen – im Fibu-Export
        hinge sonst der ganze Lauf am Stammdatensatz."""
        gesehen = self._abgefangen(monkeypatch)
        a = _abr(status=STATUS_ENTWURF)
        self._svc_mit(a, mitglied=None).beleg_pdf(a, verein={'name': 'TV'})
        assert gesehen['trainerlizenz_nr'] is None


class TestMonateImZeitraum:
    """Bemessungsgrundlage der Monatspauschale: angebrochene Kalendermonate."""

    def test_ein_monat(self):
        assert monate_im_zeitraum('2026-06-01', '2026-06-30') == 1

    def test_angebrochene_monate_zaehlen_voll(self):
        # 30.06.–01.08. berührt Juni, Juli und August.
        assert monate_im_zeitraum('2026-06-30', '2026-08-01') == 3

    def test_ueber_den_jahreswechsel(self):
        assert monate_im_zeitraum('2026-11-15', '2027-02-03') == 4

    def test_bis_vor_von_ist_null(self):
        # Defensiv: die Zeitraum-Validierung fängt das vorher ab.
        assert monate_im_zeitraum('2026-06-30', '2026-06-01') == 0


class TestBerechneBetrag:
    """Die eine Stelle, an der die Vergütungsart zu Geld wird (#84)."""

    def test_stundensatz_multipliziert_stunden(self):
        assert berechne_betrag(VERGUETUNG_STUNDENSATZ, 12.5, 8.0, 3) == 100.0

    def test_monatspauschale_ignoriert_die_stunden(self):
        # 3 Monate × 200 € – die 8 geleisteten Stunden ändern nichts daran.
        assert berechne_betrag(VERGUETUNG_MONATSPAUSCHALE, 200.0, 8.0, 3) == 600.0

    def test_ohne_verguetung_liefert_keinen_betrag(self):
        assert berechne_betrag(VERGUETUNG_OHNE, 200.0, 8.0, 3) is None

    def test_ohne_vereinbarung_liefert_keinen_betrag(self):
        assert berechne_betrag(VERGUETUNG_STUNDENSATZ, None, 8.0, 3) is None


class TestSummenVerguetungsarten:
    """summen() rechnet je Art unterschiedlich – die Stundenerfassung bleibt gleich."""

    @staticmethod
    def _svc(stunden, resolve, pauschal_zeitraeume=()):
        repo = _FakeRepo(stunden=stunden, pauschal_zeitraeume=pauschal_zeitraeume)

        class _DB:
            ul_abrechnungen = repo
            ul_saetze = SimpleNamespace(resolve=resolve)

        return ULStundenService(_DB())

    def test_entwurf_zeigt_monatspauschale_als_vorschau(self):
        # Juni–August = 3 Monate × 150 €, unabhängig von den erfassten Stunden.
        svc = self._svc([_stunde('2026-06-02'), _stunde('2026-07-07')],
                        lambda mid, aid, kl: _satz(150.0, VERGUETUNG_MONATSPAUSCHALE))
        s = svc.summen(_abr(von='2026-06-01', bis='2026-08-31'))
        assert s['anzahl_monate'] == 3
        assert s['vorschau_verguetungsart'] == VERGUETUNG_MONATSPAUSCHALE
        assert s['vorschau_gesamtbetrag'] == 450.0
        assert s['summe_stunden'] == 4.0          # Nachweis bleibt vollständig

    def test_eingereichte_monatspauschale_nutzt_den_snapshot(self):
        abr = _abr(von='2026-06-01', bis='2026-07-31', status=STATUS_EINGEREICHT)
        abr.verguetungsart = VERGUETUNG_MONATSPAUSCHALE
        abr.verguetung_pro_stunde = 150.0
        abr.verguetung_monate = 2
        svc = self._svc([_stunde('2026-06-02')],
                        lambda mid, aid, kl: _satz(999.0))   # darf nicht greifen
        s = svc.summen(abr)
        assert s['verguetungsart'] == VERGUETUNG_MONATSPAUSCHALE
        assert s['gesamtbetrag'] == 300.0                    # 2 Monate × 150 €
        assert s['vorschau_gesamtbetrag'] is None

    def test_ohne_verguetung_zaehlt_stunden_ohne_betrag(self):
        svc = self._svc([_stunde('2026-06-02'), _stunde('2026-06-09')],
                        lambda mid, aid, kl: _satz(0.0, VERGUETUNG_OHNE))
        s = svc.summen(_abr())
        assert s['summe_stunden'] == 4.0
        assert s['vorschau_verguetungsart'] == VERGUETUNG_OHNE
        assert s['vorschau_gesamtbetrag'] is None

    def test_eingereicht_ohne_verguetung_bleibt_ohne_betrag(self):
        # Der Statuswechsel darf nicht in die Vorschau zurückfallen, nur weil kein
        # Satzwert im Snapshot steht – sonst erschiene plötzlich ein fremder Betrag.
        abr = _abr(status=STATUS_EINGEREICHT)
        abr.verguetungsart = VERGUETUNG_OHNE
        abr.verguetung_pro_stunde = 0.0
        svc = self._svc([_stunde('2026-06-02')], lambda mid, aid, kl: _satz(50.0))
        s = svc.summen(abr)
        assert s['gesamtbetrag'] is None
        assert s['vorschau_pro_stunde'] is None


class TestEinreichenFriertArtEin:
    """Nicht nur der Satzwert, auch die Art gehört zum Snapshot: Wird die
    Vereinbarung später umgestellt, darf eine bestätigte Abrechnung nicht kippen."""

    def test_uebernimmt_art_der_vereinbarung(self):
        erfasst = {}

        class _Repo:
            def list_stunden(self, _id):
                return [_stunde('2026-06-10')]
            def max_gesperrt_bis(self, mid, aid):
                return None
            def monatspauschal_zeitraeume(self, mid, aid, exclude_id=None):
                return []
            def einreichen(self, _id, *, verguetungsart, verguetung_pro_stunde,
                           verguetung_monate, eingereicht_von,
                           trainerlizenz_nr=None, qualifikation=None):
                erfasst.update(art=verguetungsart, satz=verguetung_pro_stunde,
                               monate=verguetung_monate)
                return True
            def get(self, _id):
                return _abr(status=STATUS_EINGEREICHT)

        class _DB:
            ul_abrechnungen = _Repo()
            ul_saetze = SimpleNamespace(
                resolve=lambda mid, aid, kl: _satz(180.0, VERGUETUNG_MONATSPAUSCHALE))
            get_mitglied = staticmethod(lambda mid: None)

        ULStundenService(_DB()).einreichen(_abr(), eingereicht_von='admin')
        # Juni allein = 1 Monat; nichts davon ist anderweitig vergütet.
        assert erfasst == {'art': VERGUETUNG_MONATSPAUSCHALE, 'satz': 180.0, 'monate': 1}

    def test_ohne_vereinbarung_bleibt_stundensatz(self):
        erfasst = {}

        class _Repo:
            def list_stunden(self, _id):
                return [_stunde('2026-06-10')]
            def max_gesperrt_bis(self, mid, aid):
                return None
            def monatspauschal_zeitraeume(self, mid, aid, exclude_id=None):
                return []
            def einreichen(self, _id, *, verguetungsart, verguetung_pro_stunde,
                           verguetung_monate, eingereicht_von,
                           trainerlizenz_nr=None, qualifikation=None):
                erfasst.update(art=verguetungsart, satz=verguetung_pro_stunde,
                               monate=verguetung_monate)
                return True
            def get(self, _id):
                return _abr(status=STATUS_EINGEREICHT)

        class _DB:
            ul_abrechnungen = _Repo()
            ul_saetze = SimpleNamespace(resolve=lambda mid, aid, kl: None)
            get_mitglied = staticmethod(lambda mid: None)

        ULStundenService(_DB()).einreichen(_abr(), eingereicht_von='admin')
        # Kein Monatswert beim Stundensatz – die Spalte bliebe sonst irreführend gefüllt.
        assert erfasst == {'art': VERGUETUNG_STUNDENSATZ, 'satz': None, 'monate': None}


class TestMonatsAbgrenzung:
    """Ein Kalendermonat wird höchstens einmal als Pauschale vergütet – auch wenn
    zwei aufeinanderfolgende Abrechnungen in ihn hineinragen. Das Sperr-Wasserzeichen
    verhindert das nicht: Es rechnet tagegenau und lässt 16.06. direkt nach 15.06. zu."""

    @staticmethod
    def _svc(pauschal_zeitraeume=()):
        repo = _FakeRepo(pauschal_zeitraeume=pauschal_zeitraeume)

        class _DB:
            ul_abrechnungen = repo

        return ULStundenService(_DB())

    def test_geteilter_monat_wird_nur_einmal_verguetet(self):
        """Der Fall aus dem Ticket: 15.05.–15.06. und 16.06.–10.07. sind drei
        Pauschalen (Mai, Juni, Juli), nicht vier."""
        erste = self._svc().verguetungs_monate(_abr(von='2026-05-15', bis='2026-06-15'))
        assert erste == ['2026-05', '2026-06']

        zweite = self._svc([('2026-05-15', '2026-06-15')]).verguetungs_monate(
            _abr(von='2026-06-16', bis='2026-07-10', id=2))
        assert zweite == ['2026-07'], "Juni wurde ein zweites Mal vergütet"

    def test_vollstaendig_abgedeckter_zeitraum_bekommt_nichts(self):
        # Nachtrag innerhalb eines schon vergüteten Monats: Stunden ja, Pauschale nein.
        svc = self._svc([('2026-06-01', '2026-06-15')])
        assert svc.verguetungs_monate(_abr(von='2026-06-16', bis='2026-06-30', id=2)) == []

    def test_luecke_zwischen_abrechnungen_verschenkt_keinen_monat(self):
        # Mai vergütet, Juni gar nicht abgerechnet: Die Juli-Abrechnung holt Juni mit.
        svc = self._svc([('2026-05-01', '2026-05-31')])
        assert svc.verguetungs_monate(_abr(von='2026-06-20', bis='2026-07-31', id=2)) \
            == ['2026-06', '2026-07']

    def test_ohne_nachbarn_zaehlen_alle_monate(self):
        svc = self._svc()
        assert svc.verguetungs_monate(_abr(von='2026-06-01', bis='2026-08-31')) \
            == ['2026-06', '2026-07', '2026-08']

    def test_vorschau_zeigt_den_gekuerzten_betrag(self):
        """Der ÜL darf in der Erfassung nicht 300 € sehen und dann 150 € bekommen."""
        repo = _FakeRepo(stunden=[_stunde('2026-06-20')],
                         pauschal_zeitraeume=[('2026-05-15', '2026-06-15')])

        class _DB:
            ul_abrechnungen = repo
            ul_saetze = SimpleNamespace(
                resolve=lambda mid, aid, kl: _satz(150.0, VERGUETUNG_MONATSPAUSCHALE))

        s = ULStundenService(_DB()).summen(_abr(von='2026-06-16', bis='2026-07-10', id=2))
        assert s['monate_im_zeitraum'] == 2      # Juni + Juli berührt
        assert s['anzahl_monate'] == 1           # nur Juli offen
        assert s['vorschau_gesamtbetrag'] == 150.0


class TestMonatsschluessel:
    def test_liefert_die_beruehrten_monate(self):
        assert monatsschluessel('2026-06-30', '2026-08-01') == \
            ['2026-06', '2026-07', '2026-08']

    def test_ueber_den_jahreswechsel(self):
        assert monatsschluessel('2026-12-20', '2027-01-05') == ['2026-12', '2027-01']

    def test_bis_vor_von_ist_leer(self):
        assert monatsschluessel('2026-06-30', '2026-06-01') == []
