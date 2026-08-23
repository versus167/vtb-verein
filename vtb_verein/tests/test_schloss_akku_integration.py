"""Akku-Überwachung gegen echtes PostgreSQL: Konfiguration, Merker, Ticket.

Die Logik selbst prüft test_schloss_akku_service mit Attrappen. Hier geht es um das,
was nur das reale Schema zeigen kann: die Single-Row-Konfiguration samt History-Trigger,
der Merker `tuer_schloss.akku_ticket_id` (der einen Sync-Lauf überlebt, ohne eine
History-Zeile zu erzeugen) und das tatsächlich im Bereich angelegte Ticket.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt. Beispiel:
    docker run -d --name vtb-pg-akkutest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=akkutest -p 55444:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55444/akkutest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_schloss_akku_integration.py
"""
import os

import pytest

from app.models.schliessanlage import SchliessanlageEinstellungen
from app.models.ticket import TicketBereich, TicketPrioritaet
from app.services import schloss_akku_service as svc

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-akku-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute("TRUNCATE tuer_schloss, tuer_schloss_status_log RESTART IDENTITY CASCADE")
        cur.execute("TRUNCATE tuer_schloss_history RESTART IDENTITY")
        cur.execute("TRUNCATE tickets, ticket_bereiche RESTART IDENTITY CASCADE")
        cur.execute("TRUNCATE tickets_history, ticket_bereiche_history RESTART IDENTITY")
        cur.execute("UPDATE schliessanlage_einstellungen "
                    "SET akku_ticket_bereich_id = NULL, akku_ticket_schwelle = 20, "
                    "    akku_ticket_prioritaet = 'normal' WHERE id = 1")
    yield


def _schloss(db, akku):
    return db.tuer_schloesser.upsert_inventory(
        ttlock_lock_id=4711, name="Vereinsheim", lock_mac="AA",
        ttlock_gateway_id=1, gateway_online=True, akku_prozent=akku,
        akku_stand_at="2026-08-20T08:00:00")


def _einrichten(db, *, schwelle=20, prio=TicketPrioritaet.HOCH):
    bereich = db.tickets.create_bereich(TicketBereich(name="Technik"), created_by="t")
    db.schliessanlage_einstellungen.update(
        SchliessanlageEinstellungen(akku_ticket_bereich_id=bereich.id,
                                    akku_ticket_schwelle=schwelle,
                                    akku_ticket_prioritaet=prio),
        updated_by="t")
    return bereich


def test_einstellungen_sind_eine_zeile_mit_historie(db):
    e = db.schliessanlage_einstellungen.get()
    assert e.id == 1 and e.akku_ticket_bereich_id is None and e.akku_ticket_schwelle == 20
    bereich = _einrichten(db, schwelle=30)
    e = db.schliessanlage_einstellungen.get()
    assert (e.akku_ticket_bereich_id, e.akku_ticket_schwelle) == (bereich.id, 30)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM schliessanlage_einstellungen_history")
        assert cur.fetchone()['n'] >= 1


def test_ticket_landet_im_bereich_und_wiederholt_sich_nicht(db):
    bereich = _einrichten(db)
    sid = _schloss(db, 12)

    assert svc.pruefe_akkustaende(db) == {"akku_tickets": 1}
    tickets = db.tickets.list_tickets()
    assert len(tickets) == 1
    t = tickets[0]
    assert t.bereich_id == bereich.id and t.intern is True
    assert t.prioritaet == TicketPrioritaet.HOCH and "Vereinsheim" in t.titel
    assert db.tuer_schloesser.get(sid).akku_ticket_id == t.id

    # Zweiter Lauf mit unverändertem Akku: kein weiteres Ticket.
    assert svc.pruefe_akkustaende(db) == {}
    assert len(db.tickets.list_tickets()) == 1


def test_merker_ueberlebt_den_naechsten_inventar_sync(db):
    """Der Sync schreibt nur cloud-abgeleitete Felder – der Merker gehört nicht dazu."""
    _einrichten(db)
    sid = _schloss(db, 12)
    svc.pruefe_akkustaende(db)
    _schloss(db, 11)                       # nächster Inventar-Lauf, Akku sinkt weiter
    assert db.tuer_schloesser.get(sid).akku_ticket_id is not None
    assert svc.pruefe_akkustaende(db) == {}


def test_merker_erzeugt_keine_history_zeile(db):
    """Maschinenzustand ohne Versions-Bump: sonst stünde je Meldung ein detailloses
    „Schloss geändert" im Verlauf."""
    _einrichten(db)
    sid = _schloss(db, 12)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM tuer_schloss_history WHERE id = %s", (sid,))
        vorher = cur.fetchone()['n']
    svc.pruefe_akkustaende(db)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM tuer_schloss_history WHERE id = %s", (sid,))
        assert cur.fetchone()['n'] == vorher
        # Die Spalte gibt es trotzdem in der History (Fresh == Migriert).
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tuer_schloss_history' AND column_name = 'akku_ticket_id'")
        assert cur.fetchone() is not None


def test_nach_batteriewechsel_gibt_es_wieder_ein_ticket(db):
    _einrichten(db)
    sid = _schloss(db, 12)
    svc.pruefe_akkustaende(db)
    _schloss(db, 100)                      # neue Batterien
    assert svc.pruefe_akkustaende(db) == {"akku_erholt": 1}
    assert db.tuer_schloesser.get(sid).akku_ticket_id is None
    _schloss(db, 9)
    assert svc.pruefe_akkustaende(db) == {"akku_tickets": 1}
    assert len(db.tickets.list_tickets()) == 2
