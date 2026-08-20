"""Wechsel statt Korrektur bei Funktionszuordnungen (echtes PostgreSQL).

Der Anlass in einem Satz: Wer eine laufende Zuordnung *umschreibt*, ändert damit
rückwirkend ihre ganze Laufzeit – wer bis Juli ÜL Tischtennis war, wäre es dann nie
gewesen. Der Wechsel schneidet stattdessen: Die alte Zeile endet am Vortag, ab dem
Stichtag gilt die neue.

Seit v105 betrifft das nur noch Funktionen. Die Abteilungs-Zuordnung sagt nur, von
wann bis wann jemand dazugehört; ob er aktiv mitmacht, ist die Funktion `passiv` –
und die wechselt nach genau demselben Muster.

Getestet wird außerdem, was der Schnitt für die Umgebung bedeutet: die Transaktion
(keine beendete Zeile ohne Nachfolger), die Sortierung der Listen und die
Auswertungen, die beendete Zuordnungen bisher mitzählten.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "wechseltest"
GESTERN = (date.today() - timedelta(days=1)).isoformat()
MORGEN = (date.today() + timedelta(days=1)).isoformat()
VORJAHR = (date.today() - timedelta(days=400)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-wechsel-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Eigene Zeilen entfernen, Blatt vor Wurzel (geteilte Wegwerf-DB)."""
    with db.cursor() as cur:
        for tabelle in ('beitrag_sollstellung', 'beitrag_sollstellung_history',
                        'beitragsregel_history', 'beitragsregel',
                        'mitglied_funktion_history', 'mitglied_funktion',
                        'mitglied_abteilung_history', 'mitglied_abteilung',
                        'mitglied_history', 'mitglied',
                        'abteilung_history', 'abteilung'):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)


@pytest.fixture
def abteilung(db):
    return _abteilung(db, "WT-Tischtennis")


def _abteilung(db, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", (name, MARKE, MARKE))
        return cur.fetchone()["id"]


def _mitglied(db, nachname="Wechsler"):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="Wt", nachname=nachname, eintrittsdatum="2020-01-01",
                 zahlungsart="lastschrift"),
        created_by=MARKE).id


def _zuordnen(db, mitglied_id, abteilung_id, *, von="2020-01-01", bis=None):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, von, bis, "
            "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (mitglied_id, abteilung_id, von, bis, MARKE, MARKE))
        return cur.fetchone()["id"]


def _funktion(db, mitglied_id, abteilung_id, key='uebungsleiter', von="2020-01-01"):
    return db.create_mitglied_funktion(mitglied_id, abteilung_id, key, von, None,
                                       created_by=MARKE)


# ------------------------------------------------------------------ Der Schnitt

def test_wechsel_erzeugt_zwei_zeilen_ohne_luecke_und_ohne_ueberlappung(db, abteilung):
    zweite = _abteilung(db, "WT-Volleyball")
    mid = _mitglied(db)
    alt = _funktion(db, mid, abteilung)

    neu = db.wechsel_mitglied_funktion(alt.id, "2026-08-01", zweite, 'uebungsleiter',
                                       updated_by=MARKE, expected_version=1)

    assert neu.abteilung_id == zweite and neu.von == "2026-08-01" and neu.bis is None
    vorher = db.get_mitglied_funktion(alt.id)
    assert vorher.bis == "2026-07-31"           # Vortag – kein Tag doppelt, keiner offen
    assert vorher.abteilung_id == abteilung     # die Vergangenheit bleibt, wie sie war
    assert vorher.von == "2020-01-01"
    assert len(db.list_mitglied_funktionen(mid)) == 2


def test_wechsel_bei_falscher_version_aendert_nichts(db, abteilung):
    mid = _mitglied(db)
    alt = _funktion(db, mid, abteilung)

    assert db.wechsel_mitglied_funktion(alt.id, "2026-08-01", abteilung, 'passiv',
                                        updated_by=MARKE, expected_version=99) is None
    assert db.get_mitglied_funktion(alt.id).bis is None
    assert len(db.list_mitglied_funktionen(mid)) == 1


def test_abbruch_laesst_keine_beendete_zeile_ohne_nachfolger(db, abteilung, monkeypatch):
    """Der Grund, warum der Wechsel *ein* Endpunkt ist und nicht PUT+POST.

    Hier bricht der zweite Schritt weg. Ohne gemeinsame Transaktion stünde danach
    eine beendete Funktion ohne Nachfolger da – dem Betroffenen wären lautlos die
    daran hängenden Rechte entzogen, und niemand hätte einen Fehler gesehen.
    """
    from contextlib import contextmanager

    mid = _mitglied(db)
    alt = _funktion(db, mid, abteilung)
    repo = db._mitglied_funktion_repo
    echt = repo.cursor

    class _Sabotage:
        def __init__(self, cur):
            self._cur = cur

        def __getattr__(self, name):
            return getattr(self._cur, name)

        def execute(self, sql, params=None):
            if "INSERT INTO mitglied_funktion" in sql:
                raise RuntimeError("Verbindung weg")
            return self._cur.execute(sql, params)

    @contextmanager
    def kaputt():
        with echt() as cur:
            yield _Sabotage(cur)

    monkeypatch.setattr(repo, "cursor", kaputt)
    with pytest.raises(RuntimeError):
        db.wechsel_mitglied_funktion(alt.id, "2026-08-01", abteilung, 'passiv',
                                     updated_by=MARKE, expected_version=1)
    monkeypatch.undo()

    stand = db.get_mitglied_funktion(alt.id)
    assert stand.bis is None and stand.version == 1     # zurückgerollt
    assert len(db.list_mitglied_funktionen(mid)) == 1


# --------------------------------------------- Was der Beitragslauf daraus macht

def test_beitragslauf_rechnet_ueber_den_wechselmonat_anteilig(db, abteilung):
    """ÜL-Beitrag für Tischtennis; zum 1.8. wechselt die Funktion nach Volleyball
    → im Quartal bleibt genau der Juli."""
    from app.models.beitrag import Beitragsregel
    from app.services.beitrags_service import BeitragsService

    zweite = _abteilung(db, "WT-Volleyball")
    mid = _mitglied(db)
    _zuordnen(db, mid, abteilung)
    alt = _funktion(db, mid, abteilung)
    regel = db.beitragsregeln.create(
        Beitragsregel(name="WT-UEL-Beitrag", abteilung_id=abteilung, betrag_pro_monat=10.0,
                      einzug_turnus="quartal", gueltig_ab="2020-01-01",
                      bedingung_funktionen=['uebungsleiter'],
                      bedingung_abteilung_ids=[abteilung]),
        created_by=MARKE)

    db.wechsel_mitglied_funktion(alt.id, "2026-08-01", zweite, 'uebungsleiter',
                                 updated_by=MARKE, expected_version=1)

    positionen = [p for p in BeitragsService(db).vorschau("2026-07-01", mid)
                  if p.beitragsregel_id == regel.id]
    assert len(positionen) == 1
    assert positionen[0].zeitraum == "2026-Q3"
    assert positionen[0].betrag == pytest.approx(10.0)
    assert (positionen[0].anzahl_monate, positionen[0].monate_im_zeitraum) == (1, 3)


# -------------------------------------------------------------- Listen und Zahlen

def test_listen_sortieren_nach_zeit_statt_nach_name(db, abteilung):
    """Laufend zuerst, dann künftig, dann beendet – eine 2024 beendete Zeile stand
    vorher zwischen den laufenden und sah aus wie eine."""
    a, z = _abteilung(db, "WT-Aaa"), _abteilung(db, "WT-Zzz")
    mid = _mitglied(db)
    db.create_mitglied_funktion(mid, a, 'uebungsleiter', VORJAHR, GESTERN, created_by=MARKE)
    db.create_mitglied_funktion(mid, z, 'uebungsleiter', VORJAHR, None, created_by=MARKE)
    db.create_mitglied_funktion(mid, abteilung, 'uebungsleiter', MORGEN, None, created_by=MARKE)

    assert [f.abteilung_name for f in db.list_mitglied_funktionen(mid)] == [
        "WT-Zzz", "WT-Tischtennis", "WT-Aaa"]


def test_wer_die_abteilung_verlassen_hat_kann_wieder_aufgenommen_werden(db, abteilung):
    """Vorher blockierte jede Zeile die Neuaufnahme, auch eine längst beendete."""
    mid = _mitglied(db)
    _zuordnen(db, mid, abteilung, von=VORJAHR, bis=GESTERN)
    assert db.mitglied_abteilung_exists_active(mid, abteilung) is False

    _zuordnen(db, mid, abteilung, von=date.today().isoformat())
    assert db.mitglied_abteilung_exists_active(mid, abteilung) is True


def test_abteilungsuebersicht_zaehlt_beendete_und_passive_nicht_mit(db, abteilung):
    """Zeitraum UND Passiv-Funktion: Beides fehlte, solange nur ein Status geprüft
    wurde, der kein Datum kannte."""
    _zuordnen(db, _mitglied(db, "Dabei"), abteilung, von=VORJAHR)
    _zuordnen(db, _mitglied(db, "Weg"), abteilung, von=VORJAHR, bis=GESTERN)
    _zuordnen(db, _mitglied(db, "Kuenftig"), abteilung, von=MORGEN)
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, passiv, abteilung, von=VORJAHR)
    db.create_mitglied_funktion(passiv, abteilung, 'passiv', VORJAHR, None, created_by=MARKE)

    zeile = next(z for z in db.statistik.abteilungsuebersicht()
                 if z["name"] == "WT-Tischtennis")
    assert zeile["anzahl"] == 1


def test_abteilungssicht_der_kpis_zaehlt_beendete_nicht_mit(db, abteilung):
    """Derselbe Fehler steckte im Abteilungs-Scope: `gesamt` zählte über den
    JOIN mit, `aktiv_in_abteilung` prüfte die Zeit – die beiden Zahlen liefen
    auseinander."""
    _zuordnen(db, _mitglied(db, "Dabei"), abteilung, von=VORJAHR)
    _zuordnen(db, _mitglied(db, "Weg"), abteilung, von=VORJAHR, bis=GESTERN)

    kpis = db.statistik.kpis(abteilung_id=abteilung)
    assert kpis["gesamt"] == kpis["aktiv_in_abteilung"] == 1
