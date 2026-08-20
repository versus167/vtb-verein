"""Passive zahlen keinen Abteilungsbeitrag – jetzt über die Funktion (echtes PostgreSQL).

Seit Schema v105 ist „passiv" eine **Funktion** und kein Kennzeichen mehr an der
Abteilungs-Zuordnung. Der Gewinn: Sie hat einen Zeitraum. „Ab August passiv" wird
damit monatsgenau gerechnet, ohne dass man die Zuordnung aufteilen muss – das
Kennzeichen kannte kein Datum und wirkte deshalb immer rückwirkend auf die ganze
Laufzeit.

Ausgedrückt wird es über die Regel selbst: **Ausnahme** `passiv` (Normalfall) oder
**Bedingung** `passiv` (reduzierter Passiv-Beitrag). Die Wirkung ergibt sich aus dem
Abteilungsbezug – passiv für eine Abteilung trifft genau deren Beitrag, passiv ohne
Abteilung alle; der Vereinsbeitrag bleibt in beiden Fällen unberührt.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "passivtest"
STICHTAG = "2026-07-01"          # Q3 2026: Juli, August, September


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-passiv-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Eigene Zeilen entfernen, Blatt vor Wurzel. Kein TRUNCATE und kein
    RESTART IDENTITY: der Wegwerf-Postgres ist geteilt, und ein Sequenz-Reset
    lässt den Audit-Trigger fremder Module auf (id, version) kollidieren."""
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
    return _abteilung(db, "PT-Turnen")


def _abteilung(db, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", (name, MARKE, MARKE))
        return cur.fetchone()["id"]


def _mitglied(db, nachname):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="Pt", nachname=nachname, eintrittsdatum="2020-01-01",
                 zahlungsart="lastschrift"),
        created_by=MARKE)


def _zuordnen(db, mitglied_id, abteilung_id):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, von, "
            "created_by, updated_by) VALUES (%s, %s, '2020-01-01', %s, %s)",
            (mitglied_id, abteilung_id, MARKE, MARKE))


def _passiv(db, mitglied_id, abteilung_id=None, von="2020-01-01", bis=None):
    """Funktion `passiv` – ohne Abteilung heißt „im ganzen Verein passiv"."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_funktion (mitglied_id, abteilung_id, funktion, von, bis, "
            "created_by, updated_by) VALUES (%s, %s, 'passiv', %s, %s, %s, %s)",
            (mitglied_id, abteilung_id, von, bis, MARKE, MARKE))


def _abteilungsregel(db, abteilung_id, *, passiv='ausnahme'):
    """Abteilungsbeitrag 6 €/Monat. `passiv`: 'ausnahme' (Normalfall),
    'bedingung' (reduzierter Passiv-Beitrag) oder None (trifft alle)."""
    from app.models.beitrag import Beitragsregel
    felder = {}
    if passiv == 'ausnahme':
        felder = dict(ausnahme_funktionen=['passiv'], ausnahme_abteilung_ids=[abteilung_id])
    elif passiv == 'bedingung':
        felder = dict(bedingung_funktionen=['passiv'], bedingung_abteilung_ids=[abteilung_id])
    return db.beitragsregeln.create(
        Beitragsregel(name=f"PT-Abteilungsbeitrag {abteilung_id}", abteilung_id=abteilung_id,
                      betrag_pro_monat=6.0, einzug_turnus="quartal",
                      gueltig_ab="2020-01-01", **felder),
        created_by=MARKE)


def _monate(db, mitglied_id, regel_id=None):
    """Berechnete Monate je Regel für dieses Mitglied im Quartal des Stichtags."""
    from app.services.beitrags_service import BeitragsService
    treffer = {p.beitragsregel_id: p.anzahl_monate
               for p in BeitragsService(db).vorschau(STICHTAG, mitglied_id)}
    return treffer if regel_id is None else treffer.get(regel_id, 0)


# --------------------------------------------------------------- Grundregel

def test_passives_mitglied_zahlt_keinen_abteilungsbeitrag(db, abteilung):
    aktiv, passiv = _mitglied(db, "Aktiv"), _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung)
    _zuordnen(db, passiv.id, abteilung)
    _passiv(db, passiv.id, abteilung)
    regel = _abteilungsregel(db, abteilung)

    assert _monate(db, aktiv.id, regel.id) == 3
    assert _monate(db, passiv.id, regel.id) == 0


def test_ab_august_passiv_kostet_nur_den_juli(db, abteilung):
    """Der eigentliche Gewinn: Die Funktion hat einen Zeitraum, also rechnet der
    Lauf den Monatswechsel anteilig – ohne dass die Zuordnung geteilt werden muss."""
    mid = _mitglied(db, "AbAugust")
    _zuordnen(db, mid.id, abteilung)
    _passiv(db, mid.id, abteilung, von="2026-08-01")
    regel = _abteilungsregel(db, abteilung)

    assert _monate(db, mid.id, regel.id) == 1


def test_passiv_endet_wieder(db, abteilung):
    """Und rückwärts genauso: Wer im September wieder mitmacht, zahlt den September."""
    mid = _mitglied(db, "Rueckkehr")
    _zuordnen(db, mid.id, abteilung)
    _passiv(db, mid.id, abteilung, von="2026-07-01", bis="2026-08-31")
    regel = _abteilungsregel(db, abteilung)

    assert _monate(db, mid.id, regel.id) == 1


# ------------------------------------------------------- Wirkung je Abteilung

def test_passiv_in_einer_abteilung_laesst_die_andere_zahlen(db, abteilung):
    """Der Fall, an dem die alte Paarung scheiterte: Die Abteilung der
    Funktions-Zeile entscheidet, nicht die Mitgliedschaft."""
    zweite = _abteilung(db, "PT-Volleyball")
    mid = _mitglied(db, "Beides")
    _zuordnen(db, mid.id, abteilung)
    _zuordnen(db, mid.id, zweite)
    _passiv(db, mid.id, abteilung)
    eine, andere = _abteilungsregel(db, abteilung), _abteilungsregel(db, zweite)

    monate = _monate(db, mid.id)
    assert monate.get(eine.id, 0) == 0
    assert monate.get(andere.id, 0) == 3


def test_passiv_ohne_abteilung_trifft_alle_abteilungsbeitraege(db, abteilung):
    zweite = _abteilung(db, "PT-Volleyball")
    mid = _mitglied(db, "Ganz")
    _zuordnen(db, mid.id, abteilung)
    _zuordnen(db, mid.id, zweite)
    _passiv(db, mid.id, abteilung_id=None)
    eine, andere = _abteilungsregel(db, abteilung), _abteilungsregel(db, zweite)

    monate = _monate(db, mid.id)
    assert monate.get(eine.id, 0) == 0
    assert monate.get(andere.id, 0) == 0


def test_vereinsbeitrag_gilt_auch_fuer_passive(db, abteilung):
    """Passiv in der Abteilung heißt nicht passiv im Verein – und auch ein
    vereinsweites „passiv" nimmt nur die Abteilungsbeiträge, nicht den
    Vereinsbeitrag: Ausgeschlossen wird nur, was einen Abteilungsbezug hat."""
    from app.models.beitrag import Beitragsregel
    mid = _mitglied(db, "Passiv")
    _zuordnen(db, mid.id, abteilung)
    _passiv(db, mid.id, abteilung_id=None)
    vereinsregel = db.beitragsregeln.create(
        Beitragsregel(name="PT-Vereinsbeitrag", abteilung_id=None, betrag_pro_monat=9.0,
                      einzug_turnus="quartal", gueltig_ab="2020-01-01"),
        created_by=MARKE)

    assert _monate(db, mid.id, vereinsregel.id) == 3


# --------------------------------------------- ausdrücklich genannt = Passiv-Beitrag

def test_bedingung_passiv_rechnet_genau_die_passiven_ab(db, abteilung):
    """Reduzierter Passiv-Beitrag: ohne diesen Weg wären Passive nie abrechenbar."""
    aktiv, passiv = _mitglied(db, "Aktiv"), _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung)
    _zuordnen(db, passiv.id, abteilung)
    _passiv(db, passiv.id, abteilung)
    regel = _abteilungsregel(db, abteilung, passiv='bedingung')

    assert _monate(db, passiv.id, regel.id) == 3
    assert _monate(db, aktiv.id, regel.id) == 0


def test_ohne_bedingung_und_ohne_ausnahme_zahlen_alle(db, abteilung):
    """Nichts gesetzt heißt: Die Regel trifft alle – auch die Passiven. Genau davor
    warnt die Oberfläche, wenn ein Abteilungsbeitrag `passiv` nirgends nennt."""
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, passiv.id, abteilung)
    _passiv(db, passiv.id, abteilung)
    regel = _abteilungsregel(db, abteilung, passiv=None)

    assert _monate(db, passiv.id, regel.id) == 3


# ------------------------------------------------------------ ganze Abrechnung

def test_abrechnung_erzeugt_keine_sollstellung_fuer_passive(db, abteilung):
    """Ende zu Ende: nicht nur die Auswahl, auch die erzeugte Forderung fehlt."""
    from app.services.beitrags_service import BeitragsService
    aktiv, passiv = _mitglied(db, "Aktiv"), _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung)
    _zuordnen(db, passiv.id, abteilung)
    _passiv(db, passiv.id, abteilung)
    regel = _abteilungsregel(db, abteilung)

    BeitragsService(db).abrechnen(STICHTAG, erstellt_von=MARKE, quartale_rueckschau=0)

    with db.cursor() as cur:
        cur.execute("SELECT mitglied_id FROM beitrag_sollstellung "
                    "WHERE beitragsregel_id = %s AND deleted_at IS NULL", (regel.id,))
        assert [r["mitglied_id"] for r in cur.fetchall()] == [aktiv.id]
