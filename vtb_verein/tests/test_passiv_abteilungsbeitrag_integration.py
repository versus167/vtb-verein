"""Passive Abteilungsmitglieder zahlen keinen Abteilungsbeitrag (echtes PostgreSQL).

Grundregel: Wer in einer Abteilung den Status ``passiv`` hat, gehört ihr an, trainiert
aber nicht mit – ein Abteilungsbeitrag entsteht nicht. Die Regel greift ohne Zutun, also
auch für alle Bestandsregeln, die zur Status-Bedingung nichts sagen.

Ausdrücklich genannte Status schlagen die Grundregel: Eine Regel, die ``passiv`` nennt,
rechnet Passive ab (reduzierter Passiv-Beitrag). Sonst gäbe es keinen Weg, sie je
abzurechnen.

Der Vereinsbeitrag bleibt unberührt – der kennt den Abteilungs-Status nicht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "passivtest"
Q3_START, Q3_ENDE = date(2026, 7, 1), date(2026, 9, 30)
STICHTAG = "2026-07-01"


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
        cur.execute("DELETE FROM beitrag_sollstellung WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM beitrag_sollstellung_history WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM beitragsregel_history WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM beitragsregel WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM mitglied_abteilung_history WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM mitglied_abteilung WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM mitglied_history WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM mitglied WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM abteilung_history WHERE created_by = %s", (MARKE,))
        cur.execute("DELETE FROM abteilung WHERE created_by = %s", (MARKE,))


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)


@pytest.fixture
def abteilung(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    ("PT-Turnen", MARKE, MARKE))
        return cur.fetchone()["id"]


def _mitglied(db, nachname):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="Pt", nachname=nachname, eintrittsdatum="2020-01-01",
                 zahlungsart="lastschrift"),
        created_by=MARKE)


def _zuordnen(db, mitglied_id, abteilung_id, status):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, status, von, "
            "created_by, updated_by) VALUES (%s, %s, %s, '2020-01-01', %s, %s)",
            (mitglied_id, abteilung_id, status, MARKE, MARKE))


def _betroffene(db, regel):
    from app.services.beitrags_service import BeitragsService
    return {m["id"] for m in BeitragsService(db)._betroffene_mitglieder(
        regel, STICHTAG, Q3_START, Q3_ENDE)}


def _abteilungsregel(abteilung_id, **kwargs):
    from app.models.beitrag import Beitragsregel
    return Beitragsregel(name="PT-Abteilungsbeitrag", abteilung_id=abteilung_id,
                         betrag_pro_monat=6.0, einzug_turnus="quartal",
                         gueltig_ab="2020-01-01", **kwargs)


# --------------------------------------------------------------- Grundregel

def test_passives_mitglied_zahlt_keinen_abteilungsbeitrag(db, abteilung):
    aktiv = _mitglied(db, "Aktiv")
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung, "aktiv")
    _zuordnen(db, passiv.id, abteilung, "passiv")

    betroffen = _betroffene(db, _abteilungsregel(abteilung))
    assert aktiv.id in betroffen
    assert passiv.id not in betroffen


def test_uebrige_status_zahlen_weiter(db, abteilung):
    """Die Grundregel schließt genau einen Status aus – nicht alle außer 'aktiv'."""
    ids = {}
    for status in ("aktiv", "trainer", "vorstand", "ehrenmitglied", "passiv"):
        m = _mitglied(db, f"Status-{status}")
        _zuordnen(db, m.id, abteilung, status)
        ids[status] = m.id

    betroffen = _betroffene(db, _abteilungsregel(abteilung))
    assert {s for s, i in ids.items() if i in betroffen} == {
        "aktiv", "trainer", "vorstand", "ehrenmitglied"}


def test_vereinsbeitrag_gilt_auch_fuer_passive(db, abteilung):
    """Passiv in der Abteilung heißt nicht passiv im Verein – der Vereinsbeitrag bleibt."""
    from app.models.beitrag import Beitragsregel
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, passiv.id, abteilung, "passiv")

    vereinsregel = Beitragsregel(name="PT-Vereinsbeitrag", abteilung_id=None,
                                 betrag_pro_monat=9.0, gueltig_ab="2020-01-01")
    assert passiv.id in _betroffene(db, vereinsregel)


# ------------------------------------------------- ausdrückliche Status-Angabe

def test_genannte_status_schlagen_die_grundregel(db, abteilung):
    """Reduzierter Passiv-Beitrag: ohne diesen Weg wären Passive nie abrechenbar."""
    aktiv = _mitglied(db, "Aktiv")
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung, "aktiv")
    _zuordnen(db, passiv.id, abteilung, "passiv")

    regel = _abteilungsregel(abteilung, bedingung_abteilung_status="passiv")
    betroffen = _betroffene(db, regel)
    assert passiv.id in betroffen
    assert aktiv.id not in betroffen


def test_auswahl_gilt_woertlich(db, abteilung):
    aktiv = _mitglied(db, "Aktiv")
    trainer = _mitglied(db, "Trainer")
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung, "aktiv")
    _zuordnen(db, trainer.id, abteilung, "trainer")
    _zuordnen(db, passiv.id, abteilung, "passiv")

    regel = _abteilungsregel(abteilung, bedingung_abteilung_status="aktiv,trainer")
    assert _betroffene(db, regel) == {aktiv.id, trainer.id}


# ------------------------------------------------------------ ganze Abrechnung

def test_abrechnung_erzeugt_keine_sollstellung_fuer_passive(db, abteilung):
    """Ende zu Ende: nicht nur die Auswahl, auch die erzeugte Forderung fehlt."""
    from app.services.beitrags_service import BeitragsService
    aktiv = _mitglied(db, "Aktiv")
    passiv = _mitglied(db, "Passiv")
    _zuordnen(db, aktiv.id, abteilung, "aktiv")
    _zuordnen(db, passiv.id, abteilung, "passiv")
    regel = db.beitragsregeln.create(_abteilungsregel(abteilung), created_by=MARKE)

    positionen = [p for p in BeitragsService(db).vorschau("2026-07-01")
                  if p.beitragsregel_id == regel.id]
    assert {p.mitglied_id for p in positionen} == {aktiv.id}
    assert positionen[0].betrag == 18.0          # 3 Monate à 6 €


def test_wechsel_auf_passiv_beendet_kuenftige_forderungen(db, abteilung):
    """Der Status wirkt ab dem nächsten Lauf; bereits erzeugte Sollstellungen
    bleiben stehen (stornieren/löschen ist eine eigene Entscheidung)."""
    from app.services.beitrags_service import BeitragsService
    m = _mitglied(db, "Wechsler")
    _zuordnen(db, m.id, abteilung, "aktiv")
    regel = db.beitragsregeln.create(_abteilungsregel(abteilung), created_by=MARKE)
    assert m.id in _betroffene(db, regel)

    with db.cursor() as cur:
        cur.execute("UPDATE mitglied_abteilung SET status = 'passiv', version = version + 1, "
                    "updated_by = %s WHERE mitglied_id = %s", (MARKE, m.id))

    assert m.id not in _betroffene(db, regel)
    assert [p for p in BeitragsService(db).vorschau("2026-07-01")
            if p.beitragsregel_id == regel.id] == []
