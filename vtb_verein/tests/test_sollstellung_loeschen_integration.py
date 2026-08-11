"""Löschen von Sollstellungen nach der Fibu-Übergabe (#165, echtes PostgreSQL).

Storno und Löschen bedeuten in der App zwei verschiedene Dinge:

* **Storno** – aufheben und *diesmal nicht* abrechnen. Die Zeile bleibt und
  sperrt über `exists()` die Neu-Anlage.
* **Löschen** – für diesen Zeitraum wurde nichts abgerechnet. Die nächste
  Abrechnung legt die Sollstellung wieder an.

Bis #165 war Löschen gesperrt, sobald der Posten im Fibu-Export war. Geprüft wird
hier, dass es jetzt geht **und** dass die Buchhaltung dabei aufgeht: Der nächste
Export muss die Gegenbuchung enthalten, sonst bliebe in der Fibu eine Forderung
stehen, die es in der App nicht mehr gibt.

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


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-soll-uploads")
    yield d
    d.close()


@pytest.fixture
def regel_id(db):
    from app.models.beitrag import Beitragsregel
    r = db.beitragsregeln.create(
        Beitragsregel(id=None, name="Testregel #165", abteilung_id=None,
                      betrag_pro_monat=10.0, einzug_turnus='quartal',
                      gueltig_ab='2020-01-01'),
        created_by="tester")
    return r.id


@pytest.fixture
def mitglied_id(db):
    import uuid
    from app.models.mitglied import Mitglied
    m = db.create_mitglied(
        Mitglied(vorname="Soll", nachname=f"Test-{uuid.uuid4().hex[:6]}",
                 zahlungsart='sonstiges'),
        created_by="tester")
    return m.id


def _soll(db, mitglied_id, regel_id, zeitraum="2026-Q3"):
    from app.models.beitrag import BeitragSollstellung
    return db.sollstellungen.create(
        BeitragSollstellung(id=None, mitglied_id=mitglied_id, beitragsregel_id=regel_id,
                            zeitraum=zeitraum, betrag_soll=30.0,
                            faelligkeitsdatum='2026-07-01'),
        created_by="tester")


def _exportieren(db, soll_id) -> int:
    """Einen Fibu-Export-Lauf simulieren, der genau diesen Posten mitnimmt."""
    lauf = db.fibu_exporte.create_export(
        exportiert_von="tester", dateiname="test.csv", format="fbasc",
        anzahl_positionen=1, summe_cent=3000,
        neu_ids={'beitrag': [soll_id]}, storno_ids={})
    return lauf.id


def _gegenbuchen(db, soll_id) -> int:
    """Den Folge-Export simulieren, der die Gegenbuchung stempelt."""
    lauf = db.fibu_exporte.create_export(
        exportiert_von="tester", dateiname="test2.csv", format="fbasc",
        anzahl_positionen=1, summe_cent=-3000,
        neu_ids={}, storno_ids={'beitrag': [soll_id]})
    return lauf.id


def _ist_geloescht(db, soll_id) -> bool:
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM beitrag_sollstellung WHERE id=%s", (soll_id,))
        return cur.fetchone()['deleted_at'] is not None


# ------------------------------------------------------------------- Löschen

def test_loeschen_vor_dem_export_geht_weiterhin(db, mitglied_id, regel_id):
    s = _soll(db, mitglied_id, regel_id)
    assert db.sollstellungen.soft_delete(s.id, deleted_by="tester") is True


def test_loeschen_nach_dem_export_ist_erlaubt(db, mitglied_id, regel_id):
    """Der Kern von #165 – vorher scheiterte genau das."""
    s = _soll(db, mitglied_id, regel_id)
    _exportieren(db, s.id)
    assert db.sollstellungen.soft_delete(s.id, deleted_by="tester") is True
    assert _ist_geloescht(db, s.id)


def test_geloeschter_posten_erscheint_als_gegenbuchung(db, mitglied_id, regel_id):
    """Ohne diesen Schritt bliebe in der Fibu eine Forderung stehen, die es in
    der App nicht mehr gibt."""
    s = _soll(db, mitglied_id, regel_id)
    _exportieren(db, s.id)
    db.sollstellungen.soft_delete(s.id, deleted_by="tester")
    ids = [g['quelle_id'] for g in db.fibu_exporte.list_gegenbuchungen()
           if g['quelle_typ'] == 'beitrag']
    assert s.id in ids


def test_geloeschter_posten_wird_nicht_erneut_als_forderung_exportiert(db, mitglied_id, regel_id):
    s = _soll(db, mitglied_id, regel_id)
    _exportieren(db, s.id)
    db.sollstellungen.soft_delete(s.id, deleted_by="tester")
    assert s.id not in [n['quelle_id'] for n in db.fibu_exporte.list_neue_positionen()
                        if n['quelle_typ'] == 'beitrag']


def test_bezahlte_bleiben_gesperrt(db, mitglied_id, regel_id):
    """Bezahltes wird nicht neu abgerechnet – die Sperre bleibt bestehen."""
    s = _soll(db, mitglied_id, regel_id)
    db.sollstellungen.mark_bezahlt(s.id, '2026-07-15', updated_by="tester")
    assert db.sollstellungen.soft_delete(s.id, deleted_by="tester") is False


def test_geloeschtes_quartal_wird_neu_abgerechnet(db, mitglied_id, regel_id):
    """Der eigentliche Zweck: `exists()` darf den gelöschten Posten nicht mehr
    als vorhanden zählen, sonst bliebe die Neu-Abrechnung aus."""
    s = _soll(db, mitglied_id, regel_id)
    _exportieren(db, s.id)
    db.sollstellungen.soft_delete(s.id, deleted_by="tester")
    assert db.sollstellungen.exists(mitglied_id, regel_id, "2026-Q3") is False


def test_storno_zaehlt_weiter_als_vorhanden(db, mitglied_id, regel_id):
    """Gegenprobe: Storno heißt „diesmal nicht abrechnen" – die Neu-Anlage bleibt
    gesperrt. Sonst holte der nächste Routinelauf jedes Storno zurück."""
    s = _soll(db, mitglied_id, regel_id)
    db.sollstellungen.mark_storniert(s.id, updated_by="tester")
    assert db.sollstellungen.exists(mitglied_id, regel_id, "2026-Q3") is True


# ----------------------------------------------------------- Wiederherstellen

def test_wiederherstellen_geht_solange_nicht_gegengebucht(db, mitglied_id, regel_id):
    """Gelöscht, aber der Export war noch nicht: Dann ist nichts passiert, was
    sich nicht zurücknehmen ließe."""
    s = _soll(db, mitglied_id, regel_id)
    _exportieren(db, s.id)
    db.sollstellungen.soft_delete(s.id, deleted_by="tester")
    assert db.sollstellungen.restore(s.id, restored_by="tester") is True


def test_wiederherstellen_gesperrt_nach_der_gegenbuchung(db, mitglied_id, regel_id):
    """Sonst stünde die Forderung ohne Buchung da: Der Export bucht sie nicht
    erneut, weil exportiert_in_export_id längst gesetzt ist."""
    s = _soll(db, mitglied_id, regel_id)
    _exportieren(db, s.id)
    db.sollstellungen.soft_delete(s.id, deleted_by="tester")
    _gegenbuchen(db, s.id)
    assert db.sollstellungen.restore(s.id, restored_by="tester") is False
    assert _ist_geloescht(db, s.id)


def test_wiederherstellen_gesperrt_bei_bestehendem_duplikat(db, mitglied_id, regel_id):
    """Unverändert: Wurde der Zeitraum zwischenzeitlich neu abgerechnet, darf der
    alte Posten nicht daneben zurückkehren."""
    s = _soll(db, mitglied_id, regel_id)
    db.sollstellungen.soft_delete(s.id, deleted_by="tester")
    _soll(db, mitglied_id, regel_id)          # neue Abrechnung desselben Zeitraums
    assert db.sollstellungen.restore(s.id, restored_by="tester") is False
