"""Integrationstest für bereichsspezifische Ticket-Berechtigungen gegen echtes PostgreSQL.

Regression: Ein User, der schon einmal für einen Bereich berechtigt und dann per
Soft-Delete wieder entfernt wurde, muss erneut hinzugefügt werden können. Weil
``UNIQUE (bereich_id, user_id)`` auch für soft-gelöschte Zeilen gilt, darf ``set_berechtigung``
nicht blind ein INSERT absetzen, sondern muss den vorhandenen (gelöschten) Eintrag
reaktivieren.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt – VereinsDB legt
das Schema beim Connect an.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

from app.models.ticket import TicketBereich  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-berecht-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_bereich_berechtigungen, ticket_bereich_berechtigungen_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username='berechttester'")
    yield


@pytest.fixture()
def user_id(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES ('berechttester','berecht@example.com','x','mitglied',1,'test','test') "
            "RETURNING id"
        )
        return cur.fetchone()['id']


@pytest.fixture()
def bereich_id(db):
    b = db.ticket_bereiche.create(TicketBereich(name='Regressionsbereich'), 'test')
    return b.id


def test_reaktivierung_nach_soft_delete(db, bereich_id, user_id):
    repo = db.ticket_bereich_berechtigungen

    # 1) Anlegen
    repo.set_berechtigung(bereich_id, user_id, True, False, False, 'test')
    b = repo.get_berechtigung(bereich_id, user_id)
    assert b is not None
    assert b['darf_lesen'] == 1

    # 2) Entfernen (alle Flags False -> Soft-Delete)
    repo.set_berechtigung(bereich_id, user_id, False, False, False, 'test')
    assert repo.get_berechtigung(bereich_id, user_id) is None

    # 3) Erneut hinzufügen -> darf keine UniqueViolation werfen, sondern reaktivieren
    repo.set_berechtigung(bereich_id, user_id, True, True, False, 'test')
    b = repo.get_berechtigung(bereich_id, user_id)
    assert b is not None
    assert b['darf_lesen'] == 1
    assert b['darf_bearbeiten'] == 1

    # Es darf weiterhin genau eine Zeile geben (reaktiviert, nicht dupliziert)
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM ticket_bereich_berechtigungen "
            "WHERE bereich_id=%s AND user_id=%s",
            (bereich_id, user_id),
        )
        assert cur.fetchone()['n'] == 1
