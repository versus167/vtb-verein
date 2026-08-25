"""Welche Tickets gelten als unbeachtet (#179) bzw. als stillstehend (#179-Nachgang) –
gegen echtes PostgreSQL.

Die Auswahl steckt in je einer einzigen Abfrage (`TicketRepository.list_unbeachtet`
und `list_stillstehend`), und genau an ihr hängt alles: Wer als verantwortlich gilt,
wessen Sicht zählt, was als Aktivität durchgeht und wann ein Ticket wieder aus der
Liste fällt. Mit Fakes wäre davon nichts geprüft.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.ticket import (  # noqa: E402
    Ticket, TicketBereich, TicketKommentar, TicketStatus,
)
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
        cur.execute("DELETE FROM access_log WHERE event_type = ANY(%s)",
                    ([erin.EVENT_ERINNERUNG, erin.EVENT_STILLSTAND],))
        cur.execute("DELETE FROM users WHERE username LIKE 'er_%'")
        # Fristen auf die Vorgaben zurück – ein Test, der sie verstellt, darf den
        # nächsten nicht mitziehen.
        cur.execute("DELETE FROM ticket_erinnerung_einstellungen_history")
        cur.execute("DELETE FROM ticket_erinnerung_einstellungen")
        cur.execute("INSERT INTO ticket_erinnerung_einstellungen (id) VALUES (1)")
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

        res = erin.erinnern(db)["unbeachtet"]

        assert res["erinnert"] == 1 and res["empfaenger"] == 1
        assert db.access_log_repository.letzte_je_detail(erin.EVENT_ERINNERUNG).keys() == {
            str(szenario["ticket"].id)}

    def test_zweiter_lauf_am_selben_tag_schweigt(self, db, szenario):
        """Sonst käme dieselbe Mahnung bei jedem Tick erneut."""
        self._alt_machen(db, szenario["ticket"].id, 5)
        erin.erinnern(db)

        assert erin.erinnern(db)["unbeachtet"]["erinnert"] == 0

    def test_ohne_zustaendigen_wird_nichts_vermerkt(self, db, szenario):
        """Damit die Mahnung nachkommt, sobald jemand zuständig wird."""
        ohne = db.tickets.create_ticket(
            Ticket(titel="Ohne Bereich", beschreibung="…", gemeldet_von=szenario["melder"]),
            created_by="er_melder", notify=False)
        self._alt_machen(db, ohne.id, 5)
        db.tickets.mark_ticket_deleted(szenario["ticket"].id, "test")

        res = erin.erinnern(db)["unbeachtet"]

        assert res["offen"] == 1 and res["erinnert"] == 0
        assert db.access_log_repository.letzte_je_detail(erin.EVENT_ERINNERUNG) == {}

    def test_junges_ticket_wird_nicht_gemahnt(self, db, szenario):
        assert erin.erinnern(db)["unbeachtet"]["erinnert"] == 0


def _stillstehend(db):
    return {t.id: t.stillstand_seit for t in db.tickets.list_stillstehend()}


def _zurueckdatieren(db, ticket_id, tage):
    """Ticket UND alle Spuren daran altern lassen – Erstellung, letzte Änderung,
    Blicke, Kommentare. Nur zusammen ergibt das ein wirklich stillstehendes Ticket."""
    with db.cursor() as cur:
        cur.execute("UPDATE tickets SET created_at = now() - make_interval(days => %s), "
                    "updated_at = now() - make_interval(days => %s) WHERE id = %s",
                    (tage, tage, ticket_id))
        cur.execute("UPDATE ticket_zugriff_log SET created_at = now() - "
                    "make_interval(days => %s) WHERE ticket_id = %s", (tage, ticket_id))
        cur.execute("UPDATE ticket_kommentare SET created_at = now() - "
                    "make_interval(days => %s) WHERE ticket_id = %s", (tage, ticket_id))


class TestStillstandAuswahl:
    """Das Gegenstück zur Unbeachtet-Liste: gesehen – und dann liegen geblieben (#179-Nachgang)."""

    def test_unbeachtetes_ticket_ist_nicht_stillstehend(self, db, szenario):
        """Beide Listen schließen einander aus, sonst käme dasselbe Ticket doppelt."""
        assert _unbeachtet(db) == [szenario["ticket"].id]
        assert _stillstehend(db) == {}

    def test_nach_dem_blick_des_bearbeiters_steht_es_still(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        assert list(_stillstehend(db)) == [szenario["ticket"].id]
        assert _unbeachtet(db) == []

    def test_der_erste_blick_startet_die_uhr(self, db, szenario):
        """Ein lange unbeachtetes Ticket steht nicht in dem Moment still, in dem es
        endlich jemand öffnet – sonst käme die Mahnung sofort hinterher."""
        with db.cursor() as cur:
            cur.execute("UPDATE tickets SET created_at = now() - make_interval(days => 200), "
                        "updated_at = now() - make_interval(days => 200) WHERE id = %s",
                        (szenario["ticket"].id,))
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")

        seit = _stillstehend(db)[szenario["ticket"].id]
        assert erin.tage_seit(seit, datetime.now(timezone.utc)) == 0

    def test_erneutes_ansehen_verschiebt_nichts(self, db, szenario):
        """Draufschauen ist keine Bearbeitung – sonst ließe sich die Erinnerung
        beliebig vertagen, ohne dass am Ticket etwas geschieht."""
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        _zurueckdatieren(db, szenario["ticket"].id, 40)
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")

        seit = _stillstehend(db)[szenario["ticket"].id]
        assert erin.tage_seit(seit, datetime.now(timezone.utc)) == 40

    def test_kommentar_setzt_die_uhr_zurueck(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        _zurueckdatieren(db, szenario["ticket"].id, 40)
        db.tickets.add_kommentar(
            TicketKommentar(ticket_id=szenario["ticket"].id, autor_id=szenario["bearb"],
                            inhalt="Ich schaue es mir an."), created_by="er_bearb")

        seit = _stillstehend(db)[szenario["ticket"].id]
        assert erin.tage_seit(seit, datetime.now(timezone.utc)) == 0

    def test_statuswechsel_setzt_die_uhr_zurueck(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        _zurueckdatieren(db, szenario["ticket"].id, 40)
        t = db.tickets.get_ticket(szenario["ticket"].id)
        assert db.tickets.change_status(t, TicketStatus.IN_PRUEFUNG, "er_bearb",
                                        t.version) is True

        seit = _stillstehend(db)[szenario["ticket"].id]
        assert erin.tage_seit(seit, datetime.now(timezone.utc)) == 0

    def test_abgeschlossenes_faellt_heraus(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        t = db.tickets.get_ticket(szenario["ticket"].id)
        assert db.tickets.change_status(t, TicketStatus.ERLEDIGT, "er_bearb", t.version) is True
        assert _stillstehend(db) == {}

    def test_geloeschtes_faellt_heraus(self, db, szenario):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        assert db.tickets.mark_ticket_deleted(szenario["ticket"].id, "test") is True
        assert _stillstehend(db) == {}

    def test_blick_eines_unbeteiligten_zaehlt_nicht(self, db, szenario):
        """Wie bei der Unbeachtet-Liste: Nur der zuständige Kreis zählt."""
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["fremd"], "er_fremd")
        assert _stillstehend(db) == {}


class TestZustaendigeEmpfaenger:
    def test_ohne_zuweisung_der_ganze_bereichskreis(self, db, szenario):
        t = db.tickets.get_ticket(szenario["ticket"].id)
        assert db.tickets.zustaendige_empfaenger(t) == [szenario["bearb"]]

    def test_mit_zuweisung_nur_der_zugewiesene(self, db, szenario):
        """Sonst bekämen alle Bereichs-Bearbeiter eine Mahnung über eine Aufgabe,
        die jemand anderes übernommen hat."""
        t = db.tickets.get_ticket(szenario["ticket"].id)
        t.zugewiesen_an = szenario["fremd"]
        assert db.tickets.update_ticket(t, updated_by="test") is True
        assert db.tickets.zustaendige_empfaenger(
            db.tickets.get_ticket(t.id)) == [szenario["fremd"]]


class TestLaufStillstand:
    def _still_seit(self, db, szenario, tage):
        db.tickets.log_gesehen(szenario["ticket"].id, szenario["bearb"], "er_bearb")
        _zurueckdatieren(db, szenario["ticket"].id, tage)

    def test_liegen_gebliebenes_ticket_wird_gemahnt(self, db, szenario):
        self._still_seit(db, szenario, 30)          # normal: Frist 28 Tage

        res = erin.erinnern(db)["stillstand"]

        assert res == {"offen": 1, "erinnert": 1, "empfaenger": 1}
        assert db.access_log_repository.letzte_je_detail(erin.EVENT_STILLSTAND).keys() == {
            str(szenario["ticket"].id)}

    def test_frisch_bearbeitetes_ticket_bleibt_ungemahnt(self, db, szenario):
        self._still_seit(db, szenario, 3)

        res = erin.erinnern(db)["stillstand"]

        assert res == {"offen": 1, "erinnert": 0, "empfaenger": 0}

    def test_zweiter_lauf_schweigt(self, db, szenario):
        self._still_seit(db, szenario, 30)
        erin.erinnern(db)

        assert erin.erinnern(db)["stillstand"]["erinnert"] == 0

    def test_eingestellte_frist_entscheidet(self, db, szenario):
        """Der Verein stellt die Fristen selbst ein – der Lauf liest sie aus der DB."""
        self._still_seit(db, szenario, 5)
        assert erin.erinnern(db)["stillstand"]["erinnert"] == 0

        einst = db.ticket_erinnerung_einstellungen.get()
        einst.stillstand_tage_normal = 4
        db.ticket_erinnerung_einstellungen.update(einst, "test")

        assert erin.erinnern(db)["stillstand"]["erinnert"] == 1

    def test_abgeschalteter_zweig_schweigt(self, db, szenario):
        self._still_seit(db, szenario, 300)
        einst = db.ticket_erinnerung_einstellungen.get()
        einst.stillstand_aktiv = False
        db.ticket_erinnerung_einstellungen.update(einst, "test")

        assert erin.erinnern(db)["stillstand"]["erinnert"] == 0


class TestEinstellungen:
    def test_vorgaben_entsprechen_dem_bisherigen_verhalten(self, db):
        """Nach der Migration mahnt der Unbeachtet-Zweig unverändert weiter."""
        einst = db.ticket_erinnerung_einstellungen.get()
        assert (einst.unbeachtet_tage_sicherheit, einst.unbeachtet_tage_hoch,
                einst.unbeachtet_tage_normal, einst.unbeachtet_tage_niedrig,
                einst.unbeachtet_wiederholung_tage) == (1, 1, 3, 7, 7)
        assert einst.unbeachtet_aktiv and einst.stillstand_aktiv

    def test_aenderung_landet_in_der_history(self, db):
        einst = db.ticket_erinnerung_einstellungen.get()
        einst.stillstand_tage_hoch = 2
        neu = db.ticket_erinnerung_einstellungen.update(einst, "tester")

        assert neu.stillstand_tage_hoch == 2 and neu.version == einst.version + 1
        assert neu.updated_by == "tester"
        with db.cursor() as cur:
            cur.execute("SELECT version, stillstand_tage_hoch "
                        "FROM ticket_erinnerung_einstellungen_history ORDER BY version")
            zeilen = cur.fetchall()
        assert zeilen[-1]["version"] == neu.version
        assert zeilen[-1]["stillstand_tage_hoch"] == 2


class TestMigrationsPfad:
    """Fresh == Migriert: Eine v110-DB bekommt Tabelle, Vorgabezeile und Trigger."""

    def test_migration_legt_alles_an(self, db):
        with db.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS ticket_erinnerung_einstellungen_history")
            cur.execute("DROP TABLE IF EXISTS ticket_erinnerung_einstellungen")

        db._database._migrate_v110_to_v111()

        einst = db.ticket_erinnerung_einstellungen.get()
        assert einst.id == 1 and einst.unbeachtet_tage_normal == 3
        # Der Audit-Trigger muss mitgekommen sein, sonst bliebe die History leer.
        einst.stillstand_tage_normal = 21
        neu = db.ticket_erinnerung_einstellungen.update(einst, "test")
        with db.cursor() as cur:
            cur.execute("SELECT stillstand_tage_normal FROM "
                        "ticket_erinnerung_einstellungen_history WHERE version = %s",
                        (neu.version,))
            assert cur.fetchone()["stillstand_tage_normal"] == 21
