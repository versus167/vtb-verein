"""Verwerfen eines nie gespeicherten Ticket-Entwurfs (Ticket #136).

Beim Anlegen entsteht sofort ein Ticket mit Platzhalter-Titel, damit man ein
Foto direkt anhängen kann. Wer dann nicht speichert, will das Ticket nicht –
es wird verworfen, und zwar **samt Anhängen**. Blieben die Anhänge leben,
könnte der Prune das Ticket nie abräumen (Tor 4: keine Kind-Zeile mehr) und die
Datei läge für immer auf der Platte.

Abgegrenzt wird das hier gegen das „Verbergen" gespeicherter Tickets: dort
bleiben die Anhänge absichtlich stehen, weil Wiederherstellen sie zurückbringen
soll.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.ticket import Ticket, TicketBereich  # noqa: E402
from app.services import notification_service as ns  # noqa: E402
from backend.api.tickets import verwerfe_entwurf  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_UPLOADS = "/tmp/vtb-ticket-verwerfen-uploads"


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path=_UPLOADS)
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch):
    monkeypatch.setattr(
        ns.NotificationService, "send_notification_async",
        staticmethod(lambda *a, **k: None),
    )


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_zugriff_log, ticket_teilnehmer, ticket_teilnehmer_history, "
            "ticket_anhaenge, ticket_kommentare, ticket_kommentare_history, "
            "tickets, tickets_history, "
            "ticket_bereich_berechtigungen, ticket_bereich_berechtigungen_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username LIKE 've_%'")
    yield


def _mk_user(db, name):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES (%s,%s,'x','mitglied',1,'test','test') RETURNING id",
            (name, f"{name}@example.com"),
        )
        return cur.fetchone()["id"]


@pytest.fixture()
def entwurf(db):
    """Ein frisch angelegtes, noch nicht gespeichertes Ticket mit einem Foto."""
    melder = _mk_user(db, "ve_melder")
    fremd = _mk_user(db, "ve_fremd")
    bereich = db.tickets.create_bereich(TicketBereich(name="VE-Bereich"), "test")
    ticket = db.tickets.create_ticket(
        Ticket(titel="Neues Ticket", bereich_id=bereich.id, gemeldet_von=melder),
        created_by="ve_melder", notify=False,
    )
    anhang = db.tickets.add_anhang(
        ticket_id=ticket.id, kommentar_id=None, original_name="foto.jpg",
        mime_type="image/jpeg", inhalt=b"nicht wirklich ein jpeg",
        hochgeladen_von=melder, notify=False,
    )
    return dict(melder=melder, fremd=fremd, bereich=bereich, ticket=ticket, anhang=anhang)


def _lebende_anhaenge(db, ticket_id):
    return len(db.tickets.get_anhaenge(ticket_id))


def test_verwerfen_nimmt_die_anhaenge_mit(db, entwurf):
    tid = entwurf["ticket"].id
    assert _lebende_anhaenge(db, tid) == 1

    db.tickets.verwerfe_entwurf(tid, verworfen_von="ve_melder")

    assert db.tickets.get_ticket(tid).deleted_at is not None
    assert _lebende_anhaenge(db, tid) == 0
    # Sonst hinge der Prune fest: erst wenn keine Kind-Zeile mehr lebt, kann die
    # Anhang-Entität sie abräumen – und danach das Ticket.
    with db.cursor() as cur:
        cur.execute("SELECT deleted_by FROM ticket_anhaenge WHERE ticket_id = %s", (tid,))
        assert cur.fetchone()["deleted_by"] == "ve_melder"


def test_verwerfen_laesst_die_datei_liegen(db, entwurf):
    """Soft-Delete-Prinzip: die Datei räumt erst der Prune weg, nicht wir."""
    datei = Path(_UPLOADS) / entwurf["anhang"].stored_name
    assert datei.exists()

    db.tickets.verwerfe_entwurf(entwurf["ticket"].id, verworfen_von="ve_melder")

    assert datei.exists()


def test_verbergen_laesst_die_anhaenge_stehen(db, entwurf):
    """Abgrenzung: ein gespeichertes Ticket wird nur verborgen – Wiederherstellen
    soll es vollständig zurückbringen, also bleiben die Anhänge leben."""
    tid = entwurf["ticket"].id
    db.tickets.mark_ticket_deleted(tid, deleted_by="ve_melder")
    assert _lebende_anhaenge(db, tid) == 1

    db.tickets.restore_ticket(tid, restored_by="ve_melder")
    assert db.tickets.get_ticket(tid).deleted_at is None
    assert _lebende_anhaenge(db, tid) == 1


def test_fremder_darf_keinen_entwurf_verwerfen(db, entwurf):
    tid = entwurf["ticket"].id
    fremd = db.get_user_by_id(entwurf["fremd"])
    with pytest.raises(HTTPException) as exc:
        verwerfe_entwurf(tid, fremd, db)
    assert exc.value.status_code == 403
    assert _lebende_anhaenge(db, tid) == 1
    assert db.tickets.get_ticket(tid).deleted_at is None


def test_melder_darf_seinen_entwurf_verwerfen(db, entwurf):
    tid = entwurf["ticket"].id
    verwerfe_entwurf(tid, db.get_user_by_id(entwurf["melder"]), db)
    assert db.tickets.get_ticket(tid).deleted_at is not None
    assert _lebende_anhaenge(db, tid) == 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
