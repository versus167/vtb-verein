"""Interne Tickets (#178): sichtbar nur für Melder, Zuständige und Admins.

Bis Schema v107 durfte jeder angemeldete Benutzer jedes Ticket lesen — ``_can_read``
gab hart ``True`` zurück, und die Liste lieferte alles aus. Der Filter „Nur meine" im
Frontend war reine Kosmetik. Wer etwas Heikles zu melden hatte (Personen, Beschwerden,
Sicherheitslücken), konnte das nicht vertraulich tun.

Seit v108 trägt ein Ticket ein ``intern``-Kennzeichen. Offen bleibt der Normalfall;
ein internes Ticket sehen nur noch Melder, ein konkret Zugewiesener, wer am Bereich
berechtigt ist, und Admins.

Zwei Ebenen:
  * Rechte am API-Router – mit Fakes, ohne DB (Muster: test_ticket_wiedereroeffnen.py)
  * Spalte, History und Migration – gegen echtes PostgreSQL
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.ticket import Ticket, TicketBereich  # noqa: E402
from backend.api.tickets import (  # noqa: E402
    TicketWrite, _can_read, create_ticket, get_ticket, list_tickets,
)


# =========================================================== Rechte (ohne DB)

BEREICH = 7


class _FakeBerechtigungen:
    """Bereichs-ACL: ``mit_recht`` sind die User mit irgendeinem Recht am Bereich."""

    def __init__(self, mit_recht=()):
        self._mit_recht = set(mit_recht)

    def user_hat_bereichsrecht(self, bereich_id, user_id):
        return user_id in self._mit_recht

    def get_bereich_ids_mit_recht(self, user_id):
        return {BEREICH} if user_id in self._mit_recht else set()

    def list_berechtigungen_fuer_user(self, user_id):
        return [{"bereich_id": BEREICH, "darf_lesen": 1,
                 "darf_bearbeiten": 0, "darf_schliessen": 0}] if user_id in self._mit_recht else []


class _FakeTicketService:
    def __init__(self, tickets):
        self._tickets = list(tickets)
        self.angelegt = []

    def get_ticket(self, ticket_id):
        return next(t for t in self._tickets if t.id == ticket_id)

    def list_tickets_with_counts(self, nur_geloeschte=False):
        return list(self._tickets)

    def get_bereiche(self):
        return [TicketBereich(id=BEREICH, name="Bereich")]

    def get_bereich(self, bereich_id):
        return TicketBereich(id=BEREICH, name="Bereich")

    def create_ticket(self, ticket, created_by):
        ticket.id = 99
        self.angelegt.append(ticket)
        return ticket


class _FakeDB:
    def __init__(self, tickets, mit_recht=()):
        self.tickets = _FakeTicketService(tickets)
        self.ticket_bereich_berechtigungen = _FakeBerechtigungen(mit_recht)
        # UserService(db) im Listen-Endpunkt braucht diese beiden Repos.
        self.user_repository = SimpleNamespace(list_all=lambda: [])
        self.auth_token_repository = None

    def get_username(self, user_id):
        return f"u{user_id}"


def _user(uid, role="mitglied"):
    return SimpleNamespace(id=uid, username=f"u{uid}", role=role)


def _ticket(tid=1, *, intern=False, gemeldet_von=10, zugewiesen_an=None, bereich_id=BEREICH):
    return Ticket(id=tid, titel=f"Ticket {tid}", intern=intern, bereich_id=bereich_id,
                  gemeldet_von=gemeldet_von, zugewiesen_an=zugewiesen_an)


class TestCanRead:
    """Wer darf ein Ticket sehen?"""

    def test_offenes_ticket_darf_jeder_lesen(self):
        t = _ticket(intern=False)
        db = _FakeDB([t])
        assert _can_read(t, _user(999), db) is True

    def test_internes_ticket_bleibt_fremden_verborgen(self):
        t = _ticket(intern=True)
        db = _FakeDB([t])
        assert _can_read(t, _user(999), db) is False

    def test_melder_sieht_sein_internes_ticket(self):
        t = _ticket(intern=True, gemeldet_von=10)
        db = _FakeDB([t])
        assert _can_read(t, _user(10), db) is True

    def test_zugewiesener_sieht_internes_ticket(self):
        t = _ticket(intern=True, zugewiesen_an=42)
        db = _FakeDB([t])
        assert _can_read(t, _user(42), db) is True

    def test_bereichsberechtigter_sieht_internes_ticket(self):
        t = _ticket(intern=True)
        db = _FakeDB([t], mit_recht=[55])
        assert _can_read(t, _user(55), db) is True

    def test_admin_sieht_alles(self):
        t = _ticket(intern=True)
        db = _FakeDB([t])
        assert _can_read(t, _user(999, role="admin"), db) is True

    def test_internes_ticket_ohne_bereich_nur_fuer_melder_und_admin(self):
        """Über die API nicht erzeugbar (Bereich ist Pflicht) – Altbestand aber schon."""
        t = _ticket(intern=True, bereich_id=None, gemeldet_von=10)
        db = _FakeDB([t], mit_recht=[55])
        assert _can_read(t, _user(10), db) is True
        assert _can_read(t, _user(999, role="admin"), db) is True
        assert _can_read(t, _user(55), db) is False


class TestDetailEndpunkt:
    def test_fremder_bekommt_403(self):
        t = _ticket(intern=True)
        db = _FakeDB([t])
        with pytest.raises(HTTPException) as exc:
            get_ticket(t.id, _user(999), db)
        assert exc.value.status_code == 403

    def test_melder_bekommt_das_ticket(self):
        t = _ticket(intern=True, gemeldet_von=10)
        db = _FakeDB([t])
        assert get_ticket(t.id, _user(10), db)["id"] == t.id


class TestListe:
    """Der Filter muss im Backend sitzen – sonst gehen die Daten trotzdem raus."""

    def _ids(self, ergebnis):
        return [t["id"] for t in ergebnis]

    def test_internes_ticket_fehlt_bei_fremden(self):
        db = _FakeDB([_ticket(1, intern=False), _ticket(2, intern=True)])
        assert self._ids(list_tickets(_user(999), db)) == [1]

    def test_melder_sieht_sein_internes_ticket_in_der_liste(self):
        db = _FakeDB([_ticket(1, intern=False), _ticket(2, intern=True, gemeldet_von=10)])
        assert self._ids(list_tickets(_user(10), db)) == [1, 2]

    def test_zugewiesener_sieht_es_in_der_liste(self):
        db = _FakeDB([_ticket(2, intern=True, gemeldet_von=10, zugewiesen_an=42)])
        assert self._ids(list_tickets(_user(42), db)) == [2]

    def test_bereichsberechtigter_sieht_es_in_der_liste(self):
        db = _FakeDB([_ticket(2, intern=True)], mit_recht=[55])
        assert self._ids(list_tickets(_user(55), db)) == [2]

    def test_admin_sieht_alles(self):
        db = _FakeDB([_ticket(1), _ticket(2, intern=True)])
        assert self._ids(list_tickets(_user(999, role="admin"), db)) == [1, 2]


class TestAnlegen:
    def test_haken_kommt_am_ticket_an(self):
        db = _FakeDB([])
        create_ticket(TicketWrite(titel="Heikel", bereich_id=BEREICH, intern=True),
                      _user(10), db)
        assert db.tickets.angelegt[0].intern is True

    def test_ohne_angabe_bleibt_das_ticket_offen(self):
        db = _FakeDB([])
        create_ticket(TicketWrite(titel="Normal", bereich_id=BEREICH), _user(10), db)
        assert db.tickets.angelegt[0].intern is False


# ====================================================== Schema (mit Postgres)

_URL = os.getenv("VTB_TEST_DATABASE_URL")

pytest_integration = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_MARKE = 'TICKETINTERN'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-intern-uploads")
    yield d
    d.close()


@pytest.fixture()
def bestand(db):
    """Ein Melder und ein Bereich – nur die eigenen Spuren, die DB ist geteilt."""
    def aufraeumen():
        with db.cursor() as cur:
            cur.execute("DELETE FROM tickets_history WHERE titel LIKE %s", (f'{_MARKE}%',))
            cur.execute("DELETE FROM tickets WHERE titel LIKE %s", (f'{_MARKE}%',))
            cur.execute("DELETE FROM ticket_bereiche_history WHERE name LIKE %s", (f'{_MARKE}%',))
            cur.execute("DELETE FROM ticket_bereiche WHERE name LIKE %s", (f'{_MARKE}%',))
            cur.execute("DELETE FROM users_history WHERE username LIKE %s", (f'{_MARKE}%',))
            cur.execute("DELETE FROM users WHERE username LIKE %s", (f'{_MARKE}%',))

    aufraeumen()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES (%s,%s,'x','mitglied',1,'test','test') RETURNING id",
            (f'{_MARKE}melder', f'{_MARKE}@example.com'),
        )
        user_id = cur.fetchone()['id']
    bereich = db.ticket_bereiche.create(TicketBereich(name=f'{_MARKE}-Bereich'), 'test')
    yield SimpleNamespace(user_id=user_id, bereich_id=bereich.id)
    aufraeumen()


def _neues_ticket(db, bestand, *, intern):
    return db.tickets.create_ticket(
        Ticket(titel=f'{_MARKE}-Ticket', beschreibung='…', intern=intern,
               bereich_id=bestand.bereich_id, gemeldet_von=bestand.user_id),
        created_by='test', notify=False,
    )


@pytest_integration
class TestSpalte:
    def test_default_ist_offen(self, db, bestand):
        t = _neues_ticket(db, bestand, intern=False)
        assert db.tickets.get_ticket(t.id).intern is False

    def test_intern_ueberlebt_den_roundtrip(self, db, bestand):
        t = _neues_ticket(db, bestand, intern=True)
        assert db.tickets.get_ticket(t.id).intern is True

    def test_liste_liefert_das_kennzeichen_mit(self, db, bestand):
        t = _neues_ticket(db, bestand, intern=True)
        aus_liste = next(x for x in db.tickets.list_tickets_with_counts() if x.id == t.id)
        assert aus_liste.intern is True

    def test_statuswechsel_laesst_das_kennzeichen_stehen(self, db, bestand):
        """`change_status` schreibt das ganze Ticket zurück – intern darf dabei
        nicht verloren gehen."""
        t = _neues_ticket(db, bestand, intern=True)
        db.tickets.change_status(t, 'in_pruefung', changed_by='test', version=t.version)
        assert db.tickets.get_ticket(t.id).intern is True

    def test_history_schreibt_das_kennzeichen_mit(self, db, bestand):
        t = _neues_ticket(db, bestand, intern=False)
        t.intern = True
        assert db.tickets.update_ticket(t, updated_by='test')
        verlauf = db.tickets.get_ticket_history(t.id)
        assert [z['intern'] for z in verlauf] == [False, True]


@pytest_integration
class TestMigrationV108:
    def _auf_v107_zuruecksetzen(self, db):
        with db.cursor() as cur:
            cur.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS intern")
            cur.execute("ALTER TABLE tickets_history DROP COLUMN IF EXISTS intern")
            cur.execute("UPDATE schema_version SET version = 107 WHERE id = 1")

    def test_migration_ruestet_spalte_und_trigger_nach(self, db, bestand):
        self._auf_v107_zuruecksetzen(db)
        db._database._migrate_v107_to_v108()

        with db.cursor() as cur:
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            assert cur.fetchone()['version'] == 108

        # Spalte da, Bestand unverändert offen …
        t = _neues_ticket(db, bestand, intern=False)
        assert db.tickets.get_ticket(t.id).intern is False
        # … und der nachgezogene Trigger schreibt sie in die History.
        t.intern = True
        db.tickets.update_ticket(t, updated_by='test')
        assert [z['intern'] for z in db.tickets.get_ticket_history(t.id)] == [False, True]

    def test_migration_ist_wiederholbar(self, db, bestand):
        self._auf_v107_zuruecksetzen(db)
        db._database._migrate_v107_to_v108()
        db._database._migrate_v107_to_v108()   # darf nicht scheitern
        t = _neues_ticket(db, bestand, intern=True)
        assert db.tickets.get_ticket(t.id).intern is True
