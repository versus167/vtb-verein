"""Integrationstest für Ticket-Zuweisung, Änderungsverlauf und „Gesehen"-Log (#130-Nachgang).

Deckt gegen echtes PostgreSQL ab:
  * Zuweisung (zugewiesen_an) + Verantwortlichen-Kreis (Bereich ∪ Zugewiesener),
  * wählbare Verantwortliche = Bereichs-Bearbeiter/Schließer,
  * append-only Gesehen-Log mit Throttle + Aggregation (list_seen / get_gesehen),
  * Änderungsverlauf mit updated_by (wer/was/wann),
  * zeitbasierter Prune des Gesehen-Logs.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB); VereinsDB legt das Schema an.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.ticket import Ticket, TicketBereich  # noqa: E402
from app.services import notification_service as ns  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-gesehen-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch):
    # Kein echter Mail-/Push-Versand im Test.
    monkeypatch.setattr(
        ns.NotificationService, "send_notification_async",
        staticmethod(lambda *a, **k: None),
    )


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_zugriff_log, ticket_teilnehmer, ticket_teilnehmer_history, "
            "ticket_kommentare, ticket_kommentare_history, tickets, tickets_history, "
            "ticket_bereich_berechtigungen, ticket_bereich_berechtigungen_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM users WHERE username LIKE 'gv_%'")
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
def scenario(db):
    melder = _mk_user(db, "gv_melder")
    bearb = _mk_user(db, "gv_bearb")
    schliesser = _mk_user(db, "gv_schliesser")
    fremd = _mk_user(db, "gv_fremd")
    bereich = db.tickets.create_bereich(TicketBereich(name="GV-Bereich"), "test")
    db.ticket_bereich_berechtigungen.set_berechtigung(bereich.id, bearb, True, True, False, "test")
    db.ticket_bereich_berechtigungen.set_berechtigung(bereich.id, schliesser, True, False, True, "test")
    ticket = db.tickets.create_ticket(
        Ticket(titel="Testticket", beschreibung="Erst", bereich_id=bereich.id, gemeldet_von=melder),
        created_by="gv_melder", notify=False,
    )
    return dict(melder=melder, bearb=bearb, schliesser=schliesser, fremd=fremd,
               bereich=bereich, ticket=ticket)


def test_moegliche_verantwortliche_sind_bereichsverantwortliche(db, scenario):
    t = scenario["ticket"]
    ids = {v["user_id"] for v in db.tickets.get_moegliche_verantwortliche(t)}
    assert ids == {scenario["bearb"], scenario["schliesser"]}
    assert scenario["melder"] not in ids and scenario["fremd"] not in ids


def test_zuweisung_setzt_verantwortlichen(db, scenario):
    t = scenario["ticket"]
    t.zugewiesen_an = scenario["bearb"]
    t.version = t.version
    assert db.tickets.update_ticket(t, updated_by="gv_bearb") is True
    reload = db.tickets.get_ticket(t.id)
    assert reload.zugewiesen_an == scenario["bearb"]
    # Verantwortlichen-Kreis = Bereich (bearb, schliesser) ∪ Zugewiesener
    assert db.tickets._verantwortliche_ids(reload) == {scenario["bearb"], scenario["schliesser"]}


def test_gesehen_log_throttle_und_aggregation(db, scenario):
    t = scenario["ticket"]
    assert db.tickets.log_gesehen(t.id, scenario["bearb"], "gv_bearb") is True
    # zweite Sicht sofort → gethrottlet, keine neue Zeile
    assert db.tickets.log_gesehen(t.id, scenario["bearb"], "gv_bearb") is False
    seen = db.ticket_zugriff_log.list_seen(t.id)
    assert len(seen) == 1
    assert seen[0]["user_id"] == scenario["bearb"]
    assert seen[0]["anzahl"] == 1


def test_get_gesehen_markiert_verantwortliche_und_ungesehen(db, scenario):
    t = db.tickets.get_ticket(scenario["ticket"].id)
    db.tickets.log_gesehen(t.id, scenario["bearb"], "gv_bearb")
    db.tickets.log_gesehen(t.id, scenario["fremd"], "gv_fremd")
    result = db.tickets.get_gesehen(t)

    by_id = {g["user_id"]: g for g in result["gesehen"]}
    assert by_id[scenario["bearb"]]["verantwortlich"] is True
    assert by_id[scenario["fremd"]]["verantwortlich"] is False
    # schliesser ist verantwortlich, hat aber nicht gesehen → ungesehen
    ungesehen_ids = {u["user_id"] for u in result["verantwortlich_ungesehen"]}
    assert scenario["schliesser"] in ungesehen_ids
    assert scenario["bearb"] not in ungesehen_ids


def test_verlauf_enthaelt_wer_was_wann(db, scenario):
    t = db.tickets.get_ticket(scenario["ticket"].id)
    t.zugewiesen_an = scenario["bearb"]
    db.tickets.update_ticket(t, updated_by="gv_bearb")

    hist = db.tickets.get_ticket_history(t.id)
    assert len(hist) >= 2                       # Anlage + Zuweisung
    assert hist[0]["version"] == 1
    letzte = hist[-1]
    assert letzte["updated_by"] == "gv_bearb"   # „wer"
    assert letzte["zugewiesen_an"] == scenario["bearb"]
    assert "beschreibung" in letzte             # für „Beschreibung bearbeitet"-Diff


def _backdate_close(db, ticket_id, days):
    with db.cursor() as cur:
        cur.execute(
            "UPDATE tickets SET geschlossen_am = (now() - make_interval(days => %s))::text, "
            "updated_at = now() - make_interval(days => %s) WHERE id = %s",
            (days, days, ticket_id),
        )


def test_abgeschlossenes_altes_ticket_wird_mit_kindern_archiviert(db, scenario):
    from app.services.prune_service import PruneService, TICKET_ABGESCHLOSSEN_ALTER

    t = db.tickets.get_ticket(scenario["ticket"].id)
    # Kinder anlegen: Kommentar, Teilnehmer, Anhang (Anhang direkt, ohne Datei-IO)
    from app.models.ticket import TicketKommentar
    db.tickets.add_kommentar(TicketKommentar(ticket_id=t.id, autor_id=scenario["melder"], inhalt="x"), "gv_melder")
    db.tickets.add_teilnehmer(t.id, scenario["fremd"], scenario["bearb"], "gv_bearb")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO ticket_anhaenge (ticket_id, original_name, stored_name, mime_type, "
            "dateigroesse, hochgeladen_von) VALUES (%s,'a.pdf','s1','application/pdf',1,%s)",
            (t.id, scenario["melder"]),
        )
    # Abschließen + auf >5 Jahre zurückdatieren
    assert db.tickets.change_status(t, "erledigt", "gv_bearb", t.version) is True
    _backdate_close(db, t.id, 6 * 365)

    rep = {e["name"]: e for e in PruneService(db).report()["entities"]}
    assert rep[TICKET_ABGESCHLOSSEN_ALTER]["archivierbar"] == 1

    PruneService(db).prune(dry_run=False)

    # Ticket + alle Kinder sind jetzt im Papierkorb (soft-deleted)
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM tickets WHERE id=%s", (t.id,))
        assert cur.fetchone()["deleted_at"] is not None
        cur.execute("SELECT COUNT(*) AS n FROM ticket_kommentare WHERE ticket_id=%s AND deleted_at IS NULL", (t.id,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT COUNT(*) AS n FROM ticket_teilnehmer WHERE ticket_id=%s AND deleted_at IS NULL", (t.id,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT COUNT(*) AS n FROM ticket_anhaenge WHERE ticket_id=%s AND deleted_at IS NULL", (t.id,))
        assert cur.fetchone()["n"] == 0


def test_offenes_altes_ticket_wird_nicht_archiviert(db, scenario):
    from app.services.prune_service import PruneService, TICKET_ABGESCHLOSSEN_ALTER

    # Ticket bleibt offen, aber weit zurückdatiert
    with db.cursor() as cur:
        cur.execute(
            "UPDATE tickets SET updated_at = now() - make_interval(days => %s), "
            "created_at = now() - make_interval(days => %s) WHERE id = %s",
            (6 * 365, 6 * 365, scenario["ticket"].id),
        )
    rep = {e["name"]: e for e in PruneService(db).report()["entities"]}
    assert rep[TICKET_ABGESCHLOSSEN_ALTER]["archivierbar"] == 0


def test_frisch_abgeschlossenes_ticket_ist_noch_nicht_faellig(db, scenario):
    from app.services.prune_service import PruneService, TICKET_ABGESCHLOSSEN_ALTER

    t = db.tickets.get_ticket(scenario["ticket"].id)
    db.tickets.change_status(t, "abgelehnt", "gv_bearb", t.version)   # schließt + setzt geschlossen_am
    reload = db.tickets.get_ticket(t.id)
    assert reload.geschlossen_am is not None                          # auch bei 'abgelehnt' gesetzt
    rep = {e["name"]: e for e in PruneService(db).report()["entities"]}
    assert rep[TICKET_ABGESCHLOSSEN_ALTER]["archivierbar"] == 0       # heute geschlossen → nicht fällig


def test_termin_default_ist_fuenf_jahre():
    from app.services.prune_service import DEFAULT_TERMIN_ALTER_RETENTION_DAYS
    assert DEFAULT_TERMIN_ALTER_RETENTION_DAYS == 5 * 365


def test_prune_report_und_cleanup_des_gesehen_logs(db, scenario):
    from app.services.prune_service import PruneService, TICKET_ZUGRIFF_LOG

    t = scenario["ticket"]
    db.tickets.log_gesehen(t.id, scenario["bearb"], "gv_bearb")

    rep = {e["name"]: e for e in PruneService(db).report()["entities"]}
    assert TICKET_ZUGRIFF_LOG in rep
    assert rep[TICKET_ZUGRIFF_LOG]["eintraege"] == 1
    assert rep[TICKET_ZUGRIFF_LOG]["loeschbar"] == 0   # frisch → nicht alt genug

    # Zeile künstlich altern → jetzt löschbar
    with db.cursor() as cur:
        cur.execute("UPDATE ticket_zugriff_log SET created_at = now() - interval '400 days'")
    assert db.ticket_zugriff_log.count_older_than(180) == 1
    assert db.ticket_zugriff_log.cleanup_older_than(180) == 1
    assert db.ticket_zugriff_log.count() == 0
