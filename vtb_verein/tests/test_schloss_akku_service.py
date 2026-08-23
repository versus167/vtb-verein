"""Akku-Überwachung: Wann wird aus einem schwachen Akku ein Ticket – und wann nicht?

Die Entscheidung selbst ist reine Logik über Schwelle, Merker und Ladestand; sie wird
hier mit Attrappen geprüft (Muster wie test_zutritt_service). Dass die Merker-Spalte am
Schloss und die Konfigurationszeile im echten Schema stehen, prüft
test_schloss_akku_integration.
"""
from types import SimpleNamespace

from app.models.schliessanlage import SchliessanlageEinstellungen, TuerSchloss
from app.models.ticket import TicketPrioritaet
from app.services import schloss_akku_service as svc


class _SchlossRepo:
    def __init__(self, schloesser):
        self.schloesser = list(schloesser)
        self.merker = []                      # (schloss_id, ticket_id) je Aufruf

    def list_all(self, *, nur_aktive=False, nur_ttlock=False):
        return [s for s in self.schloesser if s.aktiv or not nur_aktive]

    def set_akku_ticket(self, schloss_id, ticket_id):
        self.merker.append((schloss_id, ticket_id))
        for s in self.schloesser:
            if s.id == schloss_id:
                s.akku_ticket_id = ticket_id


class _Tickets:
    def __init__(self, bereich=SimpleNamespace(id=7, name="Technik", deleted_at=None)):
        self._bereich = bereich
        self.erstellt = []

    def get_bereich(self, id):
        return self._bereich if self._bereich and self._bereich.id == id else None

    def create_ticket(self, ticket, created_by, notify=True):
        ticket.id = 100 + len(self.erstellt)
        self.erstellt.append((ticket, created_by))
        return ticket


class _DB:
    def __init__(self, schloesser, einst, tickets=None):
        self.tuer_schloesser = _SchlossRepo(schloesser)
        self.schliessanlage_einstellungen = SimpleNamespace(get=lambda: einst)
        self.tickets = tickets or _Tickets()


def _schloss(id=1, akku=15, ticket=None, aktiv=True, name="Vereinsheim"):
    return TuerSchloss(id=id, name=name, standort="Sportpark", akku_prozent=akku,
                       akku_stand_at="2026-08-20T08:00:00", aktiv=aktiv,
                       akku_ticket_id=ticket)


def _einst(bereich=7, schwelle=20, prio=TicketPrioritaet.NORMAL):
    return SchliessanlageEinstellungen(akku_ticket_bereich_id=bereich,
                                       akku_ticket_schwelle=schwelle,
                                       akku_ticket_prioritaet=prio)


def test_ohne_ticket_bereich_passiert_nichts():
    """Der Bereich ist der Ein-/Aus-Schalter – ohne ihn wird nichts angelegt."""
    db = _DB([_schloss(akku=3)], _einst(bereich=None))
    assert svc.pruefe_akkustaende(db) == {}
    assert db.tickets.erstellt == []
    assert db.tuer_schloesser.merker == []


def test_schwacher_akku_erzeugt_internes_ticket_im_bereich():
    db = _DB([_schloss(akku=15)], _einst(prio=TicketPrioritaet.HOCH))
    assert svc.pruefe_akkustaende(db) == {"akku_tickets": 1}
    ticket, wer = db.tickets.erstellt[0]
    assert ticket.bereich_id == 7 and ticket.intern is True
    assert ticket.prioritaet == TicketPrioritaet.HOCH and wer == "SYSTEM"
    assert "Vereinsheim" in ticket.titel and "15 %" in ticket.titel
    assert "20 %" in ticket.beschreibung          # die Schwelle steht im Text
    # Merker zeigt auf das erzeugte Ticket – daran hängt die Wiederholungssperre.
    assert db.tuer_schloesser.merker == [(1, ticket.id)]


def test_genau_auf_der_schwelle_zaehlt_schon_als_schwach():
    db = _DB([_schloss(akku=20)], _einst(schwelle=20))
    assert svc.pruefe_akkustaende(db) == {"akku_tickets": 1}


def test_kein_zweites_ticket_solange_der_merker_steht():
    """Der Sync läuft alle sechs Stunden – ohne Sperre stünden nach einer Woche 28
    gleichlautende Tickets im Bereich."""
    db = _DB([_schloss(akku=15)], _einst())
    svc.pruefe_akkustaende(db)
    db.tickets.erstellt.clear()
    assert svc.pruefe_akkustaende(db) == {}
    assert db.tickets.erstellt == []


def test_erst_der_batteriewechsel_macht_den_weg_frei():
    db = _DB([_schloss(akku=15)], _einst())
    svc.pruefe_akkustaende(db)                       # Ticket #100, Merker gesetzt
    db.tuer_schloesser.schloesser[0].akku_prozent = 100
    assert svc.pruefe_akkustaende(db) == {"akku_erholt": 1}
    assert db.tuer_schloesser.schloesser[0].akku_ticket_id is None
    db.tuer_schloesser.schloesser[0].akku_prozent = 12
    assert svc.pruefe_akkustaende(db) == {"akku_tickets": 1}
    assert len(db.tickets.erstellt) == 2


def test_pendeln_um_die_schwelle_loescht_den_merker_nicht():
    """Die Cloud liefert ganze Prozent; 20 → 21 → 20 ist kein Batteriewechsel."""
    db = _DB([_schloss(akku=20, ticket=100)], _einst(schwelle=20))
    for wert in (21, 25, 29):
        db.tuer_schloesser.schloesser[0].akku_prozent = wert
        assert svc.pruefe_akkustaende(db) == {}
    assert db.tuer_schloesser.schloesser[0].akku_ticket_id == 100


def test_ohne_akkuwert_und_stillgelegt_bleibt_alles_still():
    """Externe Schlösser melden keinen Ladestand, stillgelegte interessieren nicht."""
    db = _DB([_schloss(id=1, akku=None), _schloss(id=2, akku=5, aktiv=False)], _einst())
    assert svc.pruefe_akkustaende(db) == {}
    assert db.tickets.erstellt == []


def test_geloeschter_bereich_meldet_sich_statt_still_zu_scheitern():
    db = _DB([_schloss(akku=5)], _einst(bereich=7),
             tickets=_Tickets(bereich=SimpleNamespace(id=7, name="weg",
                                                      deleted_at="2026-08-01")))
    assert svc.pruefe_akkustaende(db) == {"akku_bereich_fehlt": True}
    assert db.tickets.erstellt == []


def test_unbekannte_prioritaet_faellt_auf_normal_zurueck():
    """Die Konfiguration ist älter als jede spätere Änderung der Prioritätsliste –
    ein unbekannter Wert darf die Meldung nicht verhindern."""
    db = _DB([_schloss(akku=5)], _einst(prio="dringend-dringend"))
    svc.pruefe_akkustaende(db)
    assert db.tickets.erstellt[0][0].prioritaet == TicketPrioritaet.NORMAL
