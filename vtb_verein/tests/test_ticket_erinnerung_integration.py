"""Welche Tickets gelten als unbeachtet (#179) – gegen echtes PostgreSQL.

Die Auswahl steckt in einer einzigen Abfrage (`TicketRepository.list_unbeachtet`), und
genau an ihr hängt alles: Wer als verantwortlich gilt, wessen Sicht zählt und wann ein
Ticket wieder aus der Liste fällt. Mit Fakes wäre davon nichts geprüft.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.ticket import Ticket, TicketBereich, TicketStatus  # noqa: E402
from app.services import notification_service as ns  # noqa: E402
from app.services import ticket_erinnerung_service as erin  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-ticket-erinnerung-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _kein_versand(monkeypatch):
    monkeypatch.setattr(ns.NotificationService, "send_notification_async",
                        staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ns.NotificationService, "send_notification",
                        staticmethod(lambda *a, **k: True))


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE ticket_zugriff_log, ticket_teilnehmer, ticket_teilnehmer_history, "
            "ticket_kommentare, ticket_kommentare_history, tickets, tickets_history, "
            "ticket_bereich_berechtigungen, ticket_bereich_berechtigungen_history, "
            "ticket_bereiche, ticket_bereiche_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM access_log WHERE event_type = %s", (erin.EVENT_ERINNERUNG,))
        cur.execute("DELETE FROM users WHERE username LIKE 'er_%'")
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
def szenario(db):
    melder = _mk_user(db, "er_melder")
    bearb = _mk_user(db, "er_bearb")
    fremd = _mk_user(db, "er_fremd")
    bereich = db.tickets.create_bereich(TicketBereich(name="ER-Bereich"), "test")
    db.ticket_bereich_berechtigungen.set_berechtigung(bereich.id, bearb, True, True, False, "test")
    ticket = db.tickets.create_ticket(
        Ticket(titel="Liegt herum", beschreibung="…", bereich_id=bereich.id,
               gemeldet_von=melder),
        created_by="er_melder", notify=False,
    )
    return dict(melder=melder, bearb=bearb, fremd=fremd, bereich=bereich, ticket=ticket)


def _unbeachtet(db):
    return [t.id for t in db.tickets.list_unbeachtet()]


class TestAuswahl:
    def test_frisches_ticket_ist_unbeachtet(self, db, szenario):
        assert _unbeachtet(db) == [szenario["ticket"].id]

    def test_sicht_des_melders_zaehlt_nicht(self, db, szenario):
        """Dass jemand sein eigenes Ticket ansieht, heißt nicht, dass sich wer kümmert."""
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["melder"], "er_melder")
        assert _unbeachtet(db) == [szenario["ticket"].id]

    def test_sicht_eines_unbeteiligten_zaehlt_nicht(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["fremd"], "er_fremd")
        assert _unbeachtet(db) == [szenario["ticket"].id]

    def test_sicht_des_bereichsbearbeiters_beendet_es(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        assert _unbeachtet(db) == []

    def test_sicht_des_zugewiesenen_beendet_es_auch_ohne_bereichsrecht(self, db, szenario):
        t = szenario["ticket"]
        t.zugewiesen_an = szenario["fremd"]
        assert db.tickets.update_ticket(t, updated_by="test") is True
        db.tickets.log_gesehen(t.id, szenario["fremd"], "er_fremd")
        assert _unbeachtet(db) == []

    def test_abgeschlossenes_ticket_faellt_heraus(self, db, szenario):
        t = db.tickets.get_ticket(szenario["ticket"].id)
        assert db.tickets.change_status(t, TicketStatus.ERLEDIGT, "er_bearb", t.version) is True
        assert _unbeachtet(db) == []

    def test_geloeschtes_ticket_faellt_heraus(self, db, szenario):
        assert db.tickets.mark_ticket_deleted(szenario["ticket"].id, "test") is True
        assert _unbeachtet(db) == []

    def test_ticket_ohne_bereich_bleibt_sichtbar(self, db, szenario):
        """Ohne Bereich gibt es keine Verantwortlichen – unbeachtet ist es trotzdem,
        gemahnt wird dann niemand (das entscheidet der Lauf, nicht die Abfrage)."""
        ohne = db.tickets.create_ticket(
            Ticket(titel="Ohne Bereich", beschreibung="…", gemeldet_von=szenario["melder"]),
            created_by="er_melder", notify=False)
        assert ohne.id in _unbeachtet(db)


class TestUngelesenAnzeige:
    """Der persönliche Gegenpol: „habe ICH das schon gelesen?" (#179)."""

    def _ungelesen(self, db, uid):
        return db.tickets.ids_ungelesen(db.get_user_by_id(uid))

    def test_bereichsbearbeiter_hat_es_ungelesen(self, db, szenario):
        assert self._ungelesen(db, szenario["bearb"]) == {szenario["ticket"].id}

    def test_nach_dem_oeffnen_ist_es_gelesen(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        assert self._ungelesen(db, szenario["bearb"]) == set()

    def test_die_sicht_eines_anderen_macht_es_nicht_gelesen(self, db, szenario):
        """Anders als bei der Erinnerung zählt hier nur die eigene Sicht."""
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["melder"], "er_melder")
        assert self._ungelesen(db, szenario["bearb"]) == {szenario["ticket"].id}

    def test_selbst_gemeldetes_zaehlt_nicht(self, db, szenario):
        """Der Melder hat sein Ticket geschrieben – es ihm als ungelesen zu zeigen,
        wäre eine Meldung über die eigene Eingabe."""
        eigenes = db.tickets.create_ticket(
            Ticket(titel="Von mir", beschreibung="…", bereich_id=szenario["bereich"].id,
                   gemeldet_von=szenario["bearb"]),
            created_by="er_bearb", notify=False)
        assert eigenes.id not in self._ungelesen(db, szenario["bearb"])

    def test_unbeteiligter_bekommt_nichts(self, db, szenario):
        assert self._ungelesen(db, szenario["fremd"]) == set()

    def test_zuweisung_reicht_ohne_bereichsrecht(self, db, szenario):
        t = szenario["ticket"]
        t.zugewiesen_an = szenario["fremd"]
        assert db.tickets.update_ticket(t, updated_by="test") is True
        assert self._ungelesen(db, szenario["fremd"]) == {t.id}

    def test_abgeschlossenes_faellt_heraus(self, db, szenario):
        t = db.tickets.get_ticket(szenario["ticket"].id)
        assert db.tickets.change_status(t, TicketStatus.ERLEDIGT, "er_bearb", t.version) is True
        assert self._ungelesen(db, szenario["bearb"]) == set()


class TestLauf:
    def _alt_machen(self, db, ticket_id, tage):
        with db.cursor() as cur:
            cur.execute("UPDATE tickets SET created_at = now() - make_interval(days => %s) "
                        "WHERE id = %s", (tage, ticket_id))

    def test_erinnerung_geht_raus_und_wird_vermerkt(self, db, szenario):
        self._alt_machen(db, szenario["ticket"].id, 5)

        res = erin.erinnern(db)

        assert res["erinnert"] == 1 and res["empfaenger"] == 1
        assert db.access_log_repository.letzte_je_detail(erin.EVENT_ERINNERUNG).keys() == {
            str(szenario["ticket"].id)}

    def test_zweiter_lauf_am_selben_tag_schweigt(self, db, szenario):
        """Sonst käme dieselbe Mahnung bei jedem Tick erneut."""
        self._alt_machen(db, szenario["ticket"].id, 5)
        erin.erinnern(db)

        assert erin.erinnern(db)["erinnert"] == 0

    def test_ohne_zustaendigen_wird_nichts_vermerkt(self, db, szenario):
        """Damit die Mahnung nachkommt, sobald jemand zuständig wird."""
        ohne = db.tickets.create_ticket(
            Ticket(titel="Ohne Bereich", beschreibung="…", gemeldet_von=szenario["melder"]),
            created_by="er_melder", notify=False)
        self._alt_machen(db, ohne.id, 5)
        db.tickets.mark_ticket_deleted(szenario["ticket"].id, "test")

        res = erin.erinnern(db)

        assert res["unbeachtet"] == 1 and res["erinnert"] == 0
        assert db.access_log_repository.letzte_je_detail(erin.EVENT_ERINNERUNG) == {}

    def test_junges_ticket_wird_nicht_gemahnt(self, db, szenario):
        assert erin.erinnern(db)["erinnert"] == 0
