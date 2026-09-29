"""Sprechende Fibu-Belegnummern (Schema v124) gegen echtes PostgreSQL.

Feld 04 geht seit v124 als „Beitrag-26Q3"/„Gebuehr-260926" hinaus. Welche Nummer
eine Gegenbuchung trägt, entscheidet der Lauf, mit dem ihre Forderung exportiert
wurde (`fibu_exporte.belegnummer_schema`) – nur so gleicht sie in der Fibu aus.
Geprüft werden beide Schema-Pfade: Frischaufbau (Default 'sprechend') und die
Migration (Bestandsläufe → 'id', neue Läufe → 'sprechend').

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-beleg-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Eigene Zeilen entfernen (Blatt → Wurzel), s. test_sollstellung_loeschen_integration."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM beitrag_sollstellung_history WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM beitrag_sollstellung WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM fibu_exporte_history WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM fibu_exporte WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM beitragsregel_history WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM beitragsregel WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM mitglied_history WHERE created_by = 'belegtest'")
        cur.execute("DELETE FROM mitglied WHERE created_by = 'belegtest'")


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)


@pytest.fixture
def soll_id(db):
    from app.models.beitrag import Beitragsregel, BeitragSollstellung
    from app.models.mitglied import Mitglied
    r = db.beitragsregeln.create(
        Beitragsregel(id=None, name="Belegtest", abteilung_id=None, betrag_pro_monat=10.0,
                      einzug_turnus='quartal', gueltig_ab='2020-01-01'),
        created_by="belegtest")
    m = db.create_mitglied(
        Mitglied(vorname="Beleg", nachname=f"Test-{uuid.uuid4().hex[:6]}",
                 zahlungsart='sonstiges'),
        created_by="belegtest")
    s = db.sollstellungen.create(
        BeitragSollstellung(id=None, mitglied_id=m.id, beitragsregel_id=r.id,
                            zeitraum="2026-Q3", betrag_soll=30.0,
                            faelligkeitsdatum='2026-09-30'),
        created_by="belegtest")
    return s.id


def _exportieren(db, soll_id):
    return db.fibu_exporte.create_export(
        exportiert_von="belegtest", dateiname="fbasc.hia", format="fbasc",
        anzahl_positionen=1, summe_cent=3000, neu_ids={'beitrag': [soll_id]}, storno_ids={})


def _gegenbuchung(db, soll_id):
    with db.cursor() as cur:
        cur.execute("UPDATE beitrag_sollstellung SET status = 'storniert', version = version + 1 "
                    "WHERE id = %s", (soll_id,))
    return next(r for r in db.fibu_exporte.list_gegenbuchungen() if r['quelle_id'] == soll_id)


def test_neuer_lauf_vergibt_sprechende_nummern(db, soll_id):
    from app.services.fibu_export_service import belegnummer
    neu = next(r for r in db.fibu_exporte.list_neue_positionen() if r['quelle_id'] == soll_id)
    assert belegnummer(neu) == ('Beitrag-26Q3', f'B{soll_id}')

    lauf = _exportieren(db, soll_id)
    assert lauf.belegnummer_schema == 'sprechend'
    # Die Gegenbuchung folgt dem Lauf ihrer Forderung.
    assert belegnummer(_gegenbuchung(db, soll_id))[0] == 'Beitrag-26Q3'


def test_gegenbuchung_zu_altem_lauf_behaelt_b_id(db, soll_id):
    from app.services.fibu_export_service import belegnummer
    lauf = _exportieren(db, soll_id)
    with db.cursor() as cur:
        cur.execute("UPDATE fibu_exporte SET belegnummer_schema = 'id' WHERE id = %s", (lauf.id,))
    assert belegnummer(_gegenbuchung(db, soll_id))[0] == f'B{soll_id}'


def test_migration_markiert_bestandslaeufe_als_alt(db, soll_id):
    """Zustand vor v124 herstellen (Spalte fort), migrieren: Bestand → 'id',
    der nächste Lauf → 'sprechend', und die History schreibt die Spalte mit."""
    alt = _exportieren(db, soll_id)
    with db.cursor() as cur:
        cur.execute("ALTER TABLE fibu_exporte DROP COLUMN belegnummer_schema")
        cur.execute("ALTER TABLE fibu_exporte_history DROP COLUMN belegnummer_schema")
    db._database._migrate_v123_to_v124()

    assert db.fibu_exporte.get_export(alt.id).belegnummer_schema == 'id'
    neu = db.fibu_exporte.create_export(
        exportiert_von="belegtest", dateiname="fbasc.hia", format="fbasc",
        anzahl_positionen=0, summe_cent=0, neu_ids={}, storno_ids={})
    assert neu.belegnummer_schema == 'sprechend'
    with db.cursor() as cur:
        cur.execute("SELECT belegnummer_schema FROM fibu_exporte_history WHERE id = %s",
                    (neu.id,))
        assert cur.fetchone()['belegnummer_schema'] == 'sprechend'
