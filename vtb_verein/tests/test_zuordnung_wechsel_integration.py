"""Wechsel statt Korrektur bei Abteilungs-Zuordnung und Funktion (echtes PostgreSQL).

Der Anlass in einem Satz: Wer eine laufende Zuordnung auf „passiv" *umschreibt*,
macht das Mitglied rückwirkend für die gesamte Laufzeit passiv – und der
Beitragslauf lässt das Quartal daraufhin komplett ausfallen, ohne einen Fehler zu
melden. Der Wechsel schneidet stattdessen: Die alte Zeile endet am Vortag, ab dem
Stichtag gilt die neue. Beide Fälle stehen unten nebeneinander.

Getestet wird außerdem, was der Schnitt für die Umgebung bedeutet: die
Transaktion (keine beendete Zeile ohne Nachfolger), die Sortierung der Listen und
die Auswertungen, die beendete Zuordnungen bisher mitzählten.

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
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", ("WT-Tischtennis", MARKE, MARKE))
        return cur.fetchone()["id"]


def _mitglied(db, nachname="Wechsler", eintritt="2020-01-01"):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="Wt", nachname=nachname, eintrittsdatum=eintritt,
                 zahlungsart="lastschrift"),
        created_by=MARKE).id


def _zuordnen(db, mitglied_id, abteilung_id, *, status='aktiv', von="2020-01-01", bis=None):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, status, von, bis, "
            "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (mitglied_id, abteilung_id, status, von, bis, MARKE, MARKE))
        return cur.fetchone()["id"]


def _zeilen(db, mitglied_id):
    return db.list_mitglied_abteilungen(mitglied_id)


# ------------------------------------------------------------------ Der Schnitt

def test_wechsel_erzeugt_zwei_zeilen_ohne_luecke_und_ohne_ueberlappung(db, abteilung):
    mid = _mitglied(db)
    alt_id = _zuordnen(db, mid, abteilung)

    neu = db.wechsel_mitglied_abteilung(alt_id, "2026-08-01", "passiv",
                                        updated_by=MARKE, expected_version=1)

    assert neu.status == "passiv" and neu.von == "2026-08-01" and neu.bis is None
    alt = db.get_mitglied_abteilung(alt_id)
    assert alt.bis == "2026-07-31"          # Vortag – kein Tag doppelt, keiner offen
    assert alt.status == "aktiv"            # die Vergangenheit bleibt, wie sie war
    assert alt.von == "2020-01-01"
    assert len(_zeilen(db, mid)) == 2


def test_wechsel_bei_falscher_version_aendert_nichts(db, abteilung):
    mid = _mitglied(db)
    alt_id = _zuordnen(db, mid, abteilung)

    assert db.wechsel_mitglied_abteilung(alt_id, "2026-08-01", "passiv",
                                         updated_by=MARKE, expected_version=99) is None
    assert db.get_mitglied_abteilung(alt_id).bis is None
    assert len(_zeilen(db, mid)) == 1


def test_abbruch_laesst_keine_beendete_zeile_ohne_nachfolger(db, abteilung, monkeypatch):
    """Der Grund, warum der Wechsel *ein* Endpunkt ist und nicht PUT+POST.

    Hier bricht der zweite Schritt weg. Ohne gemeinsame Transaktion stünde danach
    eine beendete Zuordnung ohne Nachfolger da – das Mitglied wäre lautlos aus der
    Abteilung verschwunden, und niemand hätte einen Fehler gesehen.
    """
    from contextlib import contextmanager

    mid = _mitglied(db)
    alt_id = _zuordnen(db, mid, abteilung)
    repo = db._mitglied_abteilung_repo
    echt = repo.cursor

    class _Sabotage:
        def __init__(self, cur):
            self._cur = cur

        def __getattr__(self, name):
            return getattr(self._cur, name)

        def execute(self, sql, params=None):
            if "INSERT INTO mitglied_abteilung" in sql:
                raise RuntimeError("Verbindung weg")
            return self._cur.execute(sql, params)

    @contextmanager
    def kaputt():
        with echt() as cur:
            yield _Sabotage(cur)

    monkeypatch.setattr(repo, "cursor", kaputt)
    with pytest.raises(RuntimeError):
        db.wechsel_mitglied_abteilung(alt_id, "2026-08-01", "passiv",
                                      updated_by=MARKE, expected_version=1)
    monkeypatch.undo()

    alt = db.get_mitglied_abteilung(alt_id)
    assert alt.bis is None and alt.version == 1     # zurückgerollt
    assert len(_zeilen(db, mid)) == 1


# --------------------------------------------------- Was der Beitragslauf daraus macht

def _abteilungsregel(db, abteilung_id):
    from app.models.beitrag import Beitragsregel
    return db.beitragsregeln.create(
        Beitragsregel(name="WT-Abteilungsbeitrag", abteilung_id=abteilung_id,
                      betrag_pro_monat=10.0, einzug_turnus="quartal",
                      gueltig_ab="2020-01-01"),
        created_by=MARKE)


def _q3_vorschau(db, mitglied_id):
    from app.services.beitrags_service import BeitragsService
    return [p for p in BeitragsService(db).vorschau("2026-07-01", mitglied_id)
            if p.mitglied_id == mitglied_id]


def test_beitragslauf_rechnet_ueber_den_wechselmonat_anteilig(db, abteilung):
    """Juli aktiv, ab August passiv → ein Monat von dreien im Quartal."""
    mid = _mitglied(db)
    alt_id = _zuordnen(db, mid, abteilung)
    _abteilungsregel(db, abteilung)

    db.wechsel_mitglied_abteilung(alt_id, "2026-08-01", "passiv",
                                  updated_by=MARKE, expected_version=1)

    positionen = _q3_vorschau(db, mid)
    assert len(positionen) == 1
    assert positionen[0].zeitraum == "2026-Q3"
    assert positionen[0].betrag == pytest.approx(10.0)
    assert (positionen[0].anzahl_monate, positionen[0].monate_im_zeitraum) == (1, 3)


def test_gegenprobe_ohne_schnitt_faellt_das_quartal_aus(db, abteilung):
    """Dasselbe fachliche Ereignis, nur in der bestehenden Zeile umgestellt: Das
    Mitglied gilt rückwirkend als seit 2020 passiv, und für Q3 entsteht gar keine
    Forderung. Kein Fehler, keine Warnung – nur eine fehlende Position."""
    mid = _mitglied(db)
    alt_id = _zuordnen(db, mid, abteilung)
    _abteilungsregel(db, abteilung)

    db.update_mitglied_abteilung(alt_id, "passiv", "2020-01-01", None,
                                 updated_by=MARKE, expected_version=1)

    assert _q3_vorschau(db, mid) == []


# ------------------------------------------------------------------- Funktionen

def _funktion_key(db):
    return db.funktionen.list_keys()[0]


def test_funktionswechsel_schneidet_genauso(db, abteilung):
    """„Bis Juli ÜL Tischtennis, ab August ÜL Volleyball" – auch hier darf die
    Vergangenheit nicht mitwandern, sonst greifen Beitragsregeln mit
    Funktions-Bedingung rückwirkend falsch."""
    mid = _mitglied(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", ("WT-Volleyball", MARKE, MARKE))
        zweite = cur.fetchone()["id"]
    key = _funktion_key(db)
    alt = db.create_mitglied_funktion(mid, abteilung, key, "2020-01-01", None,
                                      created_by=MARKE)

    neu = db.wechsel_mitglied_funktion(alt.id, "2026-08-01", zweite, key,
                                       updated_by=MARKE, expected_version=1)

    assert neu.abteilung_id == zweite and neu.von == "2026-08-01"
    vorher = db.get_mitglied_funktion(alt.id)
    assert vorher.bis == "2026-07-31" and vorher.abteilung_id == abteilung


# -------------------------------------------------------------- Listen und Zahlen

def test_listen_sortieren_nach_zeit_statt_nach_name(db, abteilung):
    """Laufend zuerst, dann künftig, dann beendet – eine 2024 beendete Zeile stand
    vorher zwischen den laufenden und sah aus wie eine."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) VALUES "
                    "(%s,%s,%s), (%s,%s,%s) RETURNING id",
                    ("WT-Aaa", MARKE, MARKE, "WT-Zzz", MARKE, MARKE))
        cur.execute("SELECT id, name FROM abteilung WHERE created_by = %s ORDER BY name",
                    (MARKE,))
        nach_name = {r["name"]: r["id"] for r in cur.fetchall()}
    mid = _mitglied(db)
    _zuordnen(db, mid, nach_name["WT-Aaa"], von=VORJAHR, bis=GESTERN)      # beendet
    _zuordnen(db, mid, nach_name["WT-Zzz"], von=VORJAHR)                   # laufend
    _zuordnen(db, mid, abteilung, von=MORGEN)                              # künftig

    assert [z.abteilung_name for z in _zeilen(db, mid)] == [
        "WT-Zzz", "WT-Tischtennis", "WT-Aaa"]


def test_wer_die_abteilung_verlassen_hat_kann_wieder_aufgenommen_werden(db, abteilung):
    """Vorher blockierte jede Zeile die Neuaufnahme, auch eine längst beendete –
    und seit es den Wechsel gibt, sind beendete Zeilen der Normalfall."""
    mid = _mitglied(db)
    beendet = _zuordnen(db, mid, abteilung, von=VORJAHR, bis=GESTERN)
    assert db.mitglied_abteilung_exists_active(mid, abteilung) is False

    _zuordnen(db, mid, abteilung, von=date.today().isoformat())
    assert db.mitglied_abteilung_exists_active(mid, abteilung) is True
    assert beendet  # die alte Zeile bleibt als Historie stehen


def test_abteilungsuebersicht_zaehlt_beendete_zuordnungen_nicht_mehr(db, abteilung):
    """Der Status bleibt beim Beenden auf 'aktiv' stehen – gezählt wird deshalb
    über von/bis, nicht über den Status allein."""
    _zuordnen(db, _mitglied(db, "Dabei"), abteilung, von=VORJAHR)
    _zuordnen(db, _mitglied(db, "Weg"), abteilung, von=VORJAHR, bis=GESTERN)
    _zuordnen(db, _mitglied(db, "Kuenftig"), abteilung, von=MORGEN)

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
