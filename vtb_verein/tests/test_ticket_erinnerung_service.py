"""Erinnerung an unbeachtete Tickets (#179) – die Entscheidungslogik.

Geprüft wird, wann gemahnt wird und wann nicht: die Staffelung nach Priorität, der
Wochenrhythmus danach, und dass eine Erinnerung nicht bei jedem Lauf erneut rausgeht.
Alles reine Funktionen über Ticket-Objekte – ohne DB, ohne Versand.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.ticket import TicketPrioritaet  # noqa: E402
from app.services import ticket_erinnerung_service as erin  # noqa: E402

_JETZT = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


def _ticket(tage_alt=5, prioritaet=TicketPrioritaet.NORMAL, id=12, titel="Anmeldung hakt"):
    return SimpleNamespace(id=id, titel=titel, prioritaet=prioritaet,
                           created_at=_JETZT - timedelta(days=tage_alt))


class TestStaffelung:
    def test_normal_mahnt_ab_drei_tagen(self):
        assert erin.ist_faellig(_ticket(tage_alt=2), None, _JETZT) is False
        assert erin.ist_faellig(_ticket(tage_alt=3), None, _JETZT) is True

    def test_sicherheit_mahnt_schon_am_naechsten_tag(self):
        heikel = _ticket(tage_alt=1, prioritaet=TicketPrioritaet.SICHERHEIT)
        assert erin.ist_faellig(heikel, None, _JETZT) is True
        assert erin.ist_faellig(_ticket(tage_alt=1), None, _JETZT) is False   # normal noch nicht

    def test_niedrig_bekommt_eine_woche_ruhe(self):
        leise = _ticket(prioritaet=TicketPrioritaet.NIEDRIG)
        assert erin.ist_faellig(_ticket(tage_alt=6, prioritaet=TicketPrioritaet.NIEDRIG),
                                None, _JETZT) is False
        assert erin.ist_faellig(_ticket(tage_alt=7, prioritaet=TicketPrioritaet.NIEDRIG),
                                None, _JETZT) is True
        assert leise.prioritaet == TicketPrioritaet.NIEDRIG

    def test_unbekannte_prioritaet_faellt_auf_normal_zurueck(self):
        assert erin.ist_faellig(_ticket(tage_alt=3, prioritaet='mittelmäßig'),
                                None, _JETZT) is True


class TestWiederholung:
    def test_frisch_gemahnt_wird_nicht_erneut(self):
        gestern = _JETZT - timedelta(days=1)
        assert erin.ist_faellig(_ticket(tage_alt=10), gestern, _JETZT) is False

    def test_nach_einer_woche_wieder(self):
        vor_woche = _JETZT - timedelta(days=7)
        assert erin.ist_faellig(_ticket(tage_alt=30), vor_woche, _JETZT) is True

    def test_ausgefallener_lauf_holt_die_mahnung_nach(self):
        """Gerechnet wird ab festen Zeitpunkten, nicht ab dem letzten Lauf."""
        vor_drei_wochen = _JETZT - timedelta(days=21)
        assert erin.ist_faellig(_ticket(tage_alt=60), vor_drei_wochen, _JETZT) is True

    def test_zeitstempel_als_text_wird_verstanden(self):
        """Ältere Protokollzeilen können als ISO-Text ankommen."""
        assert erin.ist_faellig(_ticket(tage_alt=30),
                                (_JETZT - timedelta(days=1)).isoformat(), _JETZT) is False

    def test_naive_zeitstempel_gelten_als_utc(self):
        naiv = (_JETZT - timedelta(days=1)).replace(tzinfo=None)
        assert erin.ist_faellig(_ticket(tage_alt=30), naiv, _JETZT) is False


class TestAuswahl:
    def test_faellige_werden_je_ticket_getrennt_beurteilt(self):
        tickets = [
            _ticket(id=1, tage_alt=10),                                    # nie gemahnt
            _ticket(id=2, tage_alt=10),                                    # gestern gemahnt
            _ticket(id=3, tage_alt=1),                                     # zu jung
            _ticket(id=4, tage_alt=1, prioritaet=TicketPrioritaet.HOCH),   # dringend
        ]
        letzte = {'2': _JETZT - timedelta(days=1)}
        assert [t.id for t in erin.faellige_tickets(tickets, letzte, _JETZT)] == [1, 4]

    def test_ohne_erstellungsdatum_wird_nicht_gemahnt(self):
        """Lieber keine Erinnerung als eine mit erfundenem Alter."""
        ohne = SimpleNamespace(id=9, titel='?', prioritaet=TicketPrioritaet.NORMAL,
                               created_at=None)
        assert erin.faellige_tickets([ohne], {}, _JETZT) == []


class TestText:
    def test_text_sagt_warum_die_nachricht_kommt(self):
        titel, text = erin.build_erinnerung(_ticket(tage_alt=5), 5)
        assert '#12' in titel and '5 Tagen' in titel
        assert 'Anmeldung hakt' in text
        assert 'Noch niemand' in text and 'keine Erinnerung mehr' in text

    def test_ein_tag_wird_nicht_gebeugt(self):
        titel, _ = erin.build_erinnerung(_ticket(tage_alt=1), 1)
        assert 'seit 1 Tag' in titel

    def test_dringendes_ticket_ist_am_titel_zu_erkennen(self):
        heikel = _ticket(prioritaet=TicketPrioritaet.SICHERHEIT)
        titel, text = erin.build_erinnerung(heikel, 2)
        assert titel.startswith('🔴')
        assert 'Sicherheit' in text


class FakeLog:
    def __init__(self, letzte=None):
        self.letzte = letzte or {}
        self.geschrieben = []

    def letzte_je_detail(self, event_type):
        return dict(self.letzte)

    def log(self, event_type, *, category=None, detail=None, **kw):
        self.geschrieben.append((event_type, category, detail))


class FakeTickets:
    def __init__(self, tickets, empfaenger):
        self._tickets = tickets
        self._empfaenger = empfaenger

    def list_unbeachtet(self):
        return list(self._tickets)

    def get_gesehen(self, ticket):
        return {'gesehen': [], 'verantwortlich_ungesehen': self._empfaenger.get(ticket.id, [])}


class FakeDB:
    def __init__(self, tickets, empfaenger, letzte=None, konten=None):
        self.tickets = FakeTickets(tickets, empfaenger)
        self.access_log_repository = FakeLog(letzte)
        self.push = None
        konten = konten or {}
        self.user_repository = SimpleNamespace(get_by_id=lambda uid: konten.get(uid))


def _konto(uid, name, aktiv=True):
    return SimpleNamespace(id=uid, username=name, active=aktiv)


class TestVersand:
    def _versand(self, monkeypatch):
        gesendet = []
        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, 'send_notification',
                            staticmethod(lambda u, titel, text, **kw:
                                         gesendet.append((u.username, titel)) or True))
        return gesendet

    def test_alle_verantwortlichen_werden_erreicht(self, monkeypatch):
        gesendet = self._versand(monkeypatch)
        t = _ticket(id=5, tage_alt=4)
        db = FakeDB([t], {5: [{'user_id': 1, 'username': 'a'},
                              {'user_id': 2, 'username': 'b'}]},
                    konten={1: _konto(1, 'a'), 2: _konto(2, 'b')})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert res == {'unbeachtet': 1, 'erinnert': 1, 'empfaenger': 2}
        assert [g[0] for g in gesendet] == ['a', 'b']
        assert db.access_log_repository.geschrieben == [
            (erin.EVENT_ERINNERUNG, 'ticket', '5')]

    def test_stillgelegtes_konto_bekommt_nichts(self, monkeypatch):
        gesendet = self._versand(monkeypatch)
        t = _ticket(id=5, tage_alt=4)
        db = FakeDB([t], {5: [{'user_id': 1, 'username': 'ruhend'}]},
                    konten={1: _konto(1, 'ruhend', aktiv=False)})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert gesendet == [] and res['empfaenger'] == 0
        # Trotzdem vermerkt: Sonst liefe der Versuch bei jedem Lauf erneut.
        assert db.access_log_repository.geschrieben

    def test_ticket_ohne_zustaendigen_bleibt_unvermerkt(self, monkeypatch):
        """Niemand zuständig heißt: niemanden mahnen – und nichts abhaken, damit die
        Zuweisung nachträglich noch eine Erinnerung auslöst."""
        gesendet = self._versand(monkeypatch)
        db = FakeDB([_ticket(id=5, tage_alt=4)], {5: []})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert gesendet == [] and res['erinnert'] == 0
        assert db.access_log_repository.geschrieben == []

    def test_noch_nicht_faelliges_ticket_wird_uebergangen(self, monkeypatch):
        gesendet = self._versand(monkeypatch)
        db = FakeDB([_ticket(id=5, tage_alt=1)], {5: [{'user_id': 1, 'username': 'a'}]},
                    konten={1: _konto(1, 'a')})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert gesendet == [] and res == {'unbeachtet': 1, 'erinnert': 0, 'empfaenger': 0}

    def test_versandfehler_stoppt_den_lauf_nicht(self, monkeypatch):
        from app.services.notification_service import NotificationService

        def kaputt(user, *a, **kw):
            if user.username == 'a':
                raise RuntimeError("Mailserver weg")
            return True

        monkeypatch.setattr(NotificationService, 'send_notification', staticmethod(kaputt))
        db = FakeDB([_ticket(id=5, tage_alt=4)],
                    {5: [{'user_id': 1, 'username': 'a'}, {'user_id': 2, 'username': 'b'}]},
                    konten={1: _konto(1, 'a'), 2: _konto(2, 'b')})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert res['empfaenger'] == 1          # der zweite kommt trotzdem durch
