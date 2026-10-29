"""Badge-Hinweis Fibu-Export: anzahl_offen() gegen echtes PostgreSQL.

Die Zählung für den Nav-Hinweis („Sonstiges" → Fibu-Export) muss zu der
Vorschau passen, die sich hinter der Kachel öffnet – hier gegen echte
Repository-Zeilen geprüft, inklusive der Abteilungs-Expansion auf ein
Soll/Haben-Paar und des Delta-Verhaltens (nach dem Export null, nach einem
Storno eine Gegenbuchung).

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
    d = VereinsDB(_URL, upload_path="/tmp/vtb-anzahl-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Eigene Zeilen entfernen (Blatt → Wurzel), s. test_fibu_belegnummer_integration."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM beitrag_sollstellung_history WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM beitrag_sollstellung WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM fibu_exporte_history WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM fibu_exporte WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM beitragsregel_history WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM beitragsregel WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM abteilung WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM mitglied_history WHERE created_by = 'anzahltest'")
        cur.execute("DELETE FROM mitglied WHERE created_by = 'anzahltest'")


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)


def _mitglied(db):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="Anzahl", nachname=f"Test-{uuid.uuid4().hex[:6]}",
                 zahlungsart='sonstiges'),
        created_by="anzahltest")


def _sollstellung(db, mitglied_id, *, zahler_typ='mitglied', abteilung_id=None):
    """Offene Sollstellung auf einer frischen Regel; liefert die Soll-ID."""
    from app.models.beitrag import Beitragsregel, BeitragSollstellung
    r = db.beitragsregeln.create(
        Beitragsregel(id=None, name=f"Anzahltest-{uuid.uuid4().hex[:6]}",
                      abteilung_id=abteilung_id, zahler_typ=zahler_typ,
                      betrag_pro_monat=10.0, einzug_turnus='quartal',
                      gueltig_ab='2020-01-01'),
        created_by="anzahltest")
    s = db.sollstellungen.create(
        BeitragSollstellung(id=None, mitglied_id=mitglied_id, beitragsregel_id=r.id,
                            zeitraum="2026-Q3", betrag_soll=30.0,
                            faelligkeitsdatum='2026-09-30'),
        created_by="anzahltest")
    return s.id


def _service(db):
    from app.services.fibu_export_service import FibuExportService
    return FibuExportService(db)


def _als_exportiert_stempeln(db, soll_id):
    """Wie test_fibu_belegnummer_integration._exportieren: Lauf anlegen + stempeln."""
    db.fibu_exporte.create_export(
        exportiert_von="anzahltest", dateiname="fbasc.hia", format="fbasc",
        anzahl_positionen=1, summe_cent=3000, neu_ids={'beitrag': [soll_id]}, storno_ids={})


def _stornieren(db, soll_id):
    with db.cursor() as cur:
        cur.execute("UPDATE beitrag_sollstellung SET status = 'storniert', version = version + 1 "
                    "WHERE id = %s", (soll_id,))


def test_anzahl_offen_stimmt_mit_vorschau_ueberein(db):
    """Ein offener Posten zählt eins – nach dem Export-Stempel wieder null."""
    soll_id = _sollstellung(db, _mitglied(db).id)

    svc = _service(db)
    v = svc.vorschau()
    assert svc.anzahl_offen() == len(v['forderungen']) + len(v['gegenbuchungen']) == 1

    _als_exportiert_stempeln(db, soll_id)
    assert svc.anzahl_offen() == 0


def test_stornierter_exportierter_posten_zaehlt_als_gegenbuchung(db):
    """Delta: exportiert + storniert → eine Haben-Gegenbuchung im nächsten Lauf."""
    soll_id = _sollstellung(db, _mitglied(db).id)
    _als_exportiert_stempeln(db, soll_id)
    _stornieren(db, soll_id)

    svc = _service(db)
    v = svc.vorschau()
    assert svc.anzahl_offen() == len(v['forderungen']) + len(v['gegenbuchungen']) == 1
    assert v['gegenbuchungen'] and not v['forderungen']


def test_abteilungs_beitrag_zaehlt_als_soll_haben_paar(db):
    """zahler_typ='abteilung' expandiert zu zwei Positionen (s. _positionen_fuer_row)."""
    from app.models.abteilung import Abteilung
    abt = db.create_abteilung(
        Abteilung(name=f"AnzAbt-{uuid.uuid4().hex[:6]}", kostenstelle=44),
        created_by="anzahltest")
    _sollstellung(db, _mitglied(db).id, zahler_typ='abteilung', abteilung_id=abt.id)

    svc = _service(db)
    v = svc.vorschau()
    assert svc.anzahl_offen() == len(v['forderungen']) + len(v['gegenbuchungen']) == 2


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
