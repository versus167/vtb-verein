"""Erinnerung an liegen gebliebene Tickets (#179 + Nachgang) – die Entscheidungslogik.

Geprüft wird, wann gemahnt wird und wann nicht: die Staffelung nach Priorität, der
Rhythmus danach, dass eine Erinnerung nicht bei jedem Lauf erneut rausgeht – und für
den Stillstands-Zweig, dass er ab der letzten Aktivität rechnet und an die
Zuständigen geht. Alles reine Funktionen über Ticket-Objekte – ohne DB, ohne Versand.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.ticket import (  # noqa: E402
    TicketErinnerungEinstellungen, TicketPrioritaet, TicketStatus,
)
from app.services import ticket_erinnerung_service as erin  # noqa: E402

_JETZT = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


def _ticket(tage_alt=5, prioritaet=TicketPrioritaet.NORMAL, id=12, titel="Anmeldung hakt",
            still_seit_tagen=None, status=TicketStatus.OFFEN, zugewiesen_an=None):
    return SimpleNamespace(
        id=id, titel=titel, prioritaet=prioritaet, status=status,
        zugewiesen_an=zugewiesen_an, bereich_id=1,
        created_at=_JETZT - timedelta(days=tage_alt),
        stillstand_seit=(None if still_seit_tagen is None
                         else _JETZT - timedelta(days=still_seit_tagen)))


def _faellig_unbeachtet(ticket, zuletzt=None, einst=None):
    """Ein Ticket durch den Unbeachtet-Zweig schicken – „ist es fällig?"."""
    return bool(erin.faellige_unbeachtete([ticket], {str(ticket.id): zuletzt} if zuletzt
                                          else {}, einst, _JETZT))


def _faellig_still(ticket, zuletzt=None, einst=None):
    return bool(erin.faellige_stillstehende([ticket], {str(ticket.id): zuletzt} if zuletzt
                                            else {}, einst, _JETZT))


class TestStaffelung:
    def test_normal_mahnt_ab_drei_tagen(self):
        assert _faellig_unbeachtet(_ticket(tage_alt=2)) is False
        assert _faellig_unbeachtet(_ticket(tage_alt=3)) is True

    def test_sicherheit_mahnt_schon_am_naechsten_tag(self):
        assert _faellig_unbeachtet(_ticket(tage_alt=1,
                                           prioritaet=TicketPrioritaet.SICHERHEIT)) is True
        assert _faellig_unbeachtet(_ticket(tage_alt=1)) is False   # normal noch nicht

    def test_niedrig_bekommt_eine_woche_ruhe(self):
        assert _faellig_unbeachtet(_ticket(tage_alt=6,
                                           prioritaet=TicketPrioritaet.NIEDRIG)) is False
        assert _faellig_unbeachtet(_ticket(tage_alt=7,
                                           prioritaet=TicketPrioritaet.NIEDRIG)) is True

    def test_unbekannte_prioritaet_faellt_auf_normal_zurueck(self):
        assert _faellig_unbeachtet(_ticket(tage_alt=3, prioritaet='mittelmäßig')) is True


class TestEingestellteFristen:
    """Die Fristen kommen aus den Einstellungen, nicht mehr aus dem Code (#179-Nachgang)."""

    def test_eigene_frist_verschiebt_die_erste_mahnung(self):
        streng = TicketErinnerungEinstellungen(unbeachtet_tage_normal=1)
        assert _faellig_unbeachtet(_ticket(tage_alt=1), einst=streng) is True
        geduldig = TicketErinnerungEinstellungen(unbeachtet_tage_normal=30)
        assert _faellig_unbeachtet(_ticket(tage_alt=10), einst=geduldig) is False

    def test_frist_null_schaltet_eine_prioritaet_ab(self):
        ohne_niedrig = TicketErinnerungEinstellungen(stillstand_tage_niedrig=0)
        leise = _ticket(prioritaet=TicketPrioritaet.NIEDRIG, still_seit_tagen=400)
        assert _faellig_still(leise, einst=ohne_niedrig) is False
        # … die anderen Prioritäten bleiben unberührt
        assert _faellig_still(_ticket(still_seit_tagen=400), einst=ohne_niedrig) is True

    def test_schalter_legt_einen_ganzen_zweig_still(self):
        aus = TicketErinnerungEinstellungen(unbeachtet_aktiv=False, stillstand_aktiv=False)
        assert _faellig_unbeachtet(_ticket(tage_alt=99), einst=aus) is False
        assert _faellig_still(_ticket(still_seit_tagen=99), einst=aus) is False

    def test_eigener_wiederholungsabstand(self):
        taeglich = TicketErinnerungEinstellungen(stillstand_wiederholung_tage=1)
        gestern = _JETZT - timedelta(days=1)
        assert _faellig_still(_ticket(still_seit_tagen=60), gestern, taeglich) is True


class TestWiederholung:
    def test_frisch_gemahnt_wird_nicht_erneut(self):
        gestern = _JETZT - timedelta(days=1)
        assert _faellig_unbeachtet(_ticket(tage_alt=10), gestern) is False

    def test_nach_einer_woche_wieder(self):
        vor_woche = _JETZT - timedelta(days=7)
        assert _faellig_unbeachtet(_ticket(tage_alt=30), vor_woche) is True

    def test_ausgefallener_lauf_holt_die_mahnung_nach(self):
        """Gerechnet wird ab festen Zeitpunkten, nicht ab dem letzten Lauf."""
        vor_drei_wochen = _JETZT - timedelta(days=21)
        assert _faellig_unbeachtet(_ticket(tage_alt=60), vor_drei_wochen) is True

    def test_zeitstempel_als_text_wird_verstanden(self):
        """Ältere Protokollzeilen können als ISO-Text ankommen."""
        gestern = (_JETZT - timedelta(days=1)).isoformat()
        assert _faellig_unbeachtet(_ticket(tage_alt=30), gestern) is False

    def test_naive_zeitstempel_gelten_als_utc(self):
        naiv = (_JETZT - timedelta(days=1)).replace(tzinfo=None)
        assert _faellig_unbeachtet(_ticket(tage_alt=30), naiv) is False


class TestStillstand:
    def test_stillstand_rechnet_ab_der_letzten_aktivitaet(self):
        """Nicht ab Erstellung: Ein altes Ticket, an dem gestern jemand gearbeitet
        hat, steht nicht still."""
        alt_aber_frisch = _ticket(tage_alt=400, still_seit_tagen=1)
        assert _faellig_still(alt_aber_frisch) is False
        assert _faellig_still(_ticket(tage_alt=400, still_seit_tagen=28)) is True

    def test_hohe_prioritaet_wird_frueher_gemahnt(self):
        assert _faellig_still(_ticket(still_seit_tagen=7,
                                      prioritaet=TicketPrioritaet.HOCH)) is True
        assert _faellig_still(_ticket(still_seit_tagen=7)) is False   # normal: 4 Wochen

    def test_ohne_stillstandszeitpunkt_wird_nicht_gemahnt(self):
        """Lieber keine Erinnerung als eine mit erfundenem Alter."""
        assert _faellig_still(_ticket(still_seit_tagen=None)) is False


class TestAuswahl:
    def test_faellige_werden_je_ticket_getrennt_beurteilt(self):
        tickets = [
            _ticket(id=1, tage_alt=10),                                    # nie gemahnt
            _ticket(id=2, tage_alt=10),                                    # gestern gemahnt
            _ticket(id=3, tage_alt=1),                                     # zu jung
            _ticket(id=4, tage_alt=1, prioritaet=TicketPrioritaet.HOCH),   # dringend
        ]
        letzte = {'2': _JETZT - timedelta(days=1)}
        faellig = erin.faellige_unbeachtete(tickets, letzte, None, _JETZT)
        assert [t.id for t, _ in faellig] == [1, 4]

    def test_alter_wird_mitgeliefert(self):
        """Der Text braucht die Tage – zweimal rechnen wäre zweimal Gelegenheit,
        etwas anderes zu rechnen."""
        [(_, tage)] = erin.faellige_unbeachtete([_ticket(tage_alt=9)], {}, None, _JETZT)
        assert tage == 9

    def test_ohne_erstellungsdatum_wird_nicht_gemahnt(self):
        ohne = SimpleNamespace(id=9, titel='?', prioritaet=TicketPrioritaet.NORMAL,
                               created_at=None)
        assert erin.faellige_unbeachtete([ohne], {}, None, _JETZT) == []


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

    def test_stillstands_text_nennt_status_und_ausweg(self):
        still = _ticket(still_seit_tagen=30, status=TicketStatus.IN_PRUEFUNG)
        titel, text = erin.build_stillstand(still, 30)
        assert '#12' in titel and 'still' in titel
        assert 'In Prüfung' in text
        assert 'nichts mehr passiert' in text and 'Statuswechsel' in text


class FakeLog:
    def __init__(self, letzte=None):
        self.letzte = letzte or {}
        self.geschrieben = []

    def letzte_je_detail(self, event_type):
        return dict(self.letzte.get(event_type, {}))

    def log(self, event_type, *, category=None, detail=None, **kw):
        self.geschrieben.append((event_type, category, detail))


class FakeTickets:
    def __init__(self, unbeachtet, empfaenger, stillstehend=None, zustaendige=None):
        self._unbeachtet = unbeachtet
        self._stillstehend = stillstehend or []
        self._empfaenger = empfaenger
        self._zustaendige = zustaendige or {}

    def list_unbeachtet(self):
        return list(self._unbeachtet)

    def list_stillstehend(self):
        return list(self._stillstehend)

    def get_gesehen(self, ticket):
        return {'gesehen': [], 'verantwortlich_ungesehen': self._empfaenger.get(ticket.id, [])}

    def zustaendige_empfaenger(self, ticket):
        return self._zustaendige.get(ticket.id, [])


class FakeDB:
    def __init__(self, tickets, empfaenger, letzte=None, konten=None,
                 stillstehend=None, zustaendige=None, einstellungen=None):
        self.tickets = FakeTickets(tickets, empfaenger, stillstehend, zustaendige)
        self.access_log_repository = FakeLog(letzte)
        self.push = None
        konten = konten or {}
        self.user_repository = SimpleNamespace(get_by_id=lambda uid: konten.get(uid))
        self.ticket_erinnerung_einstellungen = SimpleNamespace(
            get=lambda: einstellungen or TicketErinnerungEinstellungen())


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

        assert res['unbeachtet'] == {'offen': 1, 'erinnert': 1, 'empfaenger': 2}
        assert [g[0] for g in gesendet] == ['a', 'b']
        assert db.access_log_repository.geschrieben == [
            (erin.EVENT_ERINNERUNG, 'ticket', '5')]

    def test_stillgelegtes_konto_bekommt_nichts(self, monkeypatch):
        gesendet = self._versand(monkeypatch)
        t = _ticket(id=5, tage_alt=4)
        db = FakeDB([t], {5: [{'user_id': 1, 'username': 'ruhend'}]},
                    konten={1: _konto(1, 'ruhend', aktiv=False)})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert gesendet == [] and res['unbeachtet']['empfaenger'] == 0
        # Trotzdem vermerkt: Sonst liefe der Versuch bei jedem Lauf erneut.
        assert db.access_log_repository.geschrieben

    def test_ticket_ohne_zustaendigen_bleibt_unvermerkt(self, monkeypatch):
        """Niemand zuständig heißt: niemanden mahnen – und nichts abhaken, damit die
        Zuweisung nachträglich noch eine Erinnerung auslöst."""
        gesendet = self._versand(monkeypatch)
        db = FakeDB([_ticket(id=5, tage_alt=4)], {5: []})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert gesendet == [] and res['unbeachtet']['erinnert'] == 0
        assert db.access_log_repository.geschrieben == []

    def test_noch_nicht_faelliges_ticket_wird_uebergangen(self, monkeypatch):
        gesendet = self._versand(monkeypatch)
        db = FakeDB([_ticket(id=5, tage_alt=1)], {5: [{'user_id': 1, 'username': 'a'}]},
                    konten={1: _konto(1, 'a')})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert gesendet == []
        assert res['unbeachtet'] == {'offen': 1, 'erinnert': 0, 'empfaenger': 0}

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

        assert res['unbeachtet']['empfaenger'] == 1   # der zweite kommt trotzdem durch


class TestVersandStillstand:
    def test_stillstehendes_ticket_geht_an_die_zustaendigen(self, monkeypatch):
        gesendet = []
        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, 'send_notification',
                            staticmethod(lambda u, titel, text, **kw:
                                         gesendet.append((u.username, titel)) or True))
        still = _ticket(id=7, tage_alt=90, still_seit_tagen=30, zugewiesen_an=2)
        db = FakeDB([], {}, stillstehend=[still], zustaendige={7: [2]},
                    konten={2: _konto(2, 'bea')})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert res['stillstand'] == {'offen': 1, 'erinnert': 1, 'empfaenger': 1}
        assert [g[0] for g in gesendet] == ['bea']
        assert 'still' in gesendet[0][1]
        assert db.access_log_repository.geschrieben == [
            (erin.EVENT_STILLSTAND, 'ticket', '7')]

    def test_eigenes_gedaechtnis_je_zweig(self, monkeypatch):
        """Eine Unbeachtet-Mahnung von gestern darf die Stillstands-Mahnung nicht
        unterdrücken – die Zweige zählen getrennt."""
        monkeypatch.setattr(
            'app.services.notification_service.NotificationService.send_notification',
            staticmethod(lambda u, titel, text, **kw: True))
        still = _ticket(id=7, tage_alt=90, still_seit_tagen=30)
        db = FakeDB([], {}, stillstehend=[still], zustaendige={7: [2]},
                    konten={2: _konto(2, 'bea')},
                    letzte={erin.EVENT_ERINNERUNG: {'7': _JETZT - timedelta(days=1)}})

        assert erin.erinnern(db, jetzt=_JETZT)['stillstand']['erinnert'] == 1

    def test_beide_zweige_laufen_im_selben_durchgang(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.notification_service.NotificationService.send_notification',
            staticmethod(lambda u, titel, text, **kw: True))
        db = FakeDB([_ticket(id=5, tage_alt=4)], {5: [{'user_id': 1, 'username': 'a'}]},
                    stillstehend=[_ticket(id=7, tage_alt=90, still_seit_tagen=30)],
                    zustaendige={7: [2]},
                    konten={1: _konto(1, 'a'), 2: _konto(2, 'bea')})

        res = erin.erinnern(db, jetzt=_JETZT)

        assert res['unbeachtet']['erinnert'] == 1 and res['stillstand']['erinnert'] == 1
