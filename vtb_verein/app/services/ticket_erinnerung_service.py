"""Erinnerung an Tickets, die noch niemand angesehen hat (#179).

Angelegt, zugewiesen, kommentiert — für jeden dieser Vorgänge geht bereits eine
Benachrichtigung raus. Was danach kommt, sieht niemand: Ein Ticket wird einmal
gemeldet, die Nachricht geht in der Post unter, und es liegt. Genau diese Lücke
schließt der Lauf hier — nicht „ungelesene Änderungen", sondern der eine Fall, für
den es sonst kein Signal gibt: **kein Verantwortlicher hat es je geöffnet**.

Verantwortlich ist der Zugewiesene und, über die Bereichs-Berechtigung, wer dort
bearbeiten oder schließen darf (`TicketRepository.list_unbeachtet` setzt das durch;
dass der Melder sein eigenes Ticket ansieht, zählt nicht). Öffnet einer von ihnen
das Ticket, hört die Erinnerung von selbst auf — es gibt nichts abzuhaken.

Gemahnt wird nach Priorität gestaffelt und danach wöchentlich, damit ein
Sicherheitsticket nicht dieselbe Woche Ruhe bekommt wie eine Idee für später. Das
Gedächtnis ist das Zugriffsprotokoll (eine Zeile je Erinnerung): Ohne das käme bei
jedem Lauf dieselbe Nachricht erneut.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.ticket import TicketPrioritaet

logger = logging.getLogger(__name__)

# Ab wann ein unbeachtetes Ticket das erste Mal mahnt – je dringender, desto früher.
ERINNERUNG_NACH_TAGEN: dict[str, int] = {
    TicketPrioritaet.SICHERHEIT: 1,
    TicketPrioritaet.HOCH: 1,
    TicketPrioritaet.NORMAL: 3,
    TicketPrioritaet.NIEDRIG: 7,
}
_STANDARD_TAGE = ERINNERUNG_NACH_TAGEN[TicketPrioritaet.NORMAL]

# Danach im Wochenrhythmus, bis es jemand öffnet. Öfter wäre Druck, nicht Information.
WIEDERHOLUNG_TAGE = 7

EVENT_ERINNERUNG = 'ticket_erinnerung'
_KATEGORIE = 'ticket'


def _als_datetime(wert) -> Optional[datetime]:
    """DB-Zeitstempel → aware datetime. TIMESTAMPTZ liefert bereits datetime,
    ältere Zeilen können als ISO-Text ankommen."""
    if wert is None or isinstance(wert, datetime):
        return wert
    try:
        return datetime.fromisoformat(str(wert).replace('Z', '+00:00'))
    except ValueError:
        return None


def wartetage(ticket, jetzt: datetime) -> Optional[int]:
    """Wie viele Tage liegt das Ticket schon? None, wenn kein Datum lesbar ist."""
    erstellt = _als_datetime(ticket.created_at)
    if erstellt is None:
        return None
    if erstellt.tzinfo is None:
        erstellt = erstellt.replace(tzinfo=timezone.utc)
    return (jetzt - erstellt).days


def ist_faellig(ticket, zuletzt_erinnert: Optional[datetime],
                jetzt: Optional[datetime] = None) -> bool:
    """Ist für dieses Ticket jetzt eine Erinnerung dran?

    Zwei Schwellen: die erste Mahnung nach der Priorität, jede weitere im
    Wochenabstand zur letzten. Beides zählt ab einem festen Zeitpunkt (Erstellung
    bzw. letzte Erinnerung), der Lauf ist damit unabhängig von seinem Takt — ein
    ausgefallener Lauf holt die Mahnung nach, ein doppelter schickt sie nicht zweimal.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    tage = wartetage(ticket, jetzt)
    if tage is None:
        return False
    if tage < ERINNERUNG_NACH_TAGEN.get(ticket.prioritaet, _STANDARD_TAGE):
        return False
    zuletzt = _als_datetime(zuletzt_erinnert)
    if zuletzt is None:
        return True
    if zuletzt.tzinfo is None:
        zuletzt = zuletzt.replace(tzinfo=timezone.utc)
    return jetzt - zuletzt >= timedelta(days=WIEDERHOLUNG_TAGE)


def faellige_tickets(tickets: list, letzte_erinnerungen: dict,
                     jetzt: Optional[datetime] = None) -> list:
    """Aus den unbeachteten Tickets die heute fälligen heraussuchen (reine Funktion)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    return [t for t in tickets
            if ist_faellig(t, letzte_erinnerungen.get(str(t.id)), jetzt)]


def build_erinnerung(ticket, tage: int) -> tuple[str, str]:
    """Titel und Text der Erinnerung. Der Text sagt, warum sie kommt — sonst liest
    sie sich wie die dritte Kopie der ursprünglichen Meldung."""
    dringend = ticket.prioritaet in (TicketPrioritaet.SICHERHEIT, TicketPrioritaet.HOCH)
    titel = (f"{'🔴' if dringend else '🎫'} Ticket #{ticket.id} wartet seit "
             f"{tage} {'Tag' if tage == 1 else 'Tagen'}")
    text = (f"\"{ticket.titel}\"\n\n"
            f"Priorität: {TicketPrioritaet.LABELS.get(ticket.prioritaet, ticket.prioritaet)}\n\n"
            "Noch niemand aus dem zuständigen Kreis hat dieses Ticket geöffnet. "
            "Ein Blick genügt – danach kommt keine Erinnerung mehr.")
    return titel, text


def erinnern(db, *, jetzt: Optional[datetime] = None) -> dict:
    """Fällige Erinnerungen verschicken. Gibt Zahl der Tickets und Empfänger zurück.

    Der Versand läuft bewusst synchron: Der Lauf ist ein kurzlebiger Prozess, der
    einen Hintergrund-Pool beim Beenden mitrisse.
    """
    from app.services.notification_service import NotificationService
    jetzt = jetzt or datetime.now(timezone.utc)
    unbeachtet = db.tickets.list_unbeachtet()
    letzte = db.access_log_repository.letzte_je_detail(EVENT_ERINNERUNG)
    faellig = faellige_tickets(unbeachtet, letzte, jetzt)

    tickets = empfaenger_gesamt = 0
    for ticket in faellig:
        # `verantwortlich_ungesehen` ist hier der ganze Kreis (gesehen hat es keiner)
        # und filtert bereits auf aktive Konten.
        empfaenger = db.tickets.get_gesehen(ticket)['verantwortlich_ungesehen']
        if not empfaenger:
            continue          # niemand zuständig – dann mahnt hier auch niemanden etwas
        titel, text = build_erinnerung(ticket, wartetage(ticket, jetzt))
        url = f"/tickets?ticket={ticket.id}"
        erreicht = 0
        for eintrag in empfaenger:
            user = db.user_repository.get_by_id(eintrag['user_id'])
            if not (user and user.active):
                continue
            try:
                if NotificationService.send_notification(user, titel, text,
                                                         push_service=db.push, url=url):
                    erreicht += 1
            except Exception:
                logger.exception("Ticket-Erinnerung an %s fehlgeschlagen.", user.username)
        db.access_log_repository.log(EVENT_ERINNERUNG, category=_KATEGORIE,
                                     detail=str(ticket.id))
        tickets += 1
        empfaenger_gesamt += erreicht
    if tickets:
        logger.info("Ticket-Erinnerungen: %d Ticket(s), %d Empfänger erreicht "
                    "(%d unbeachtet insgesamt).", tickets, empfaenger_gesamt, len(unbeachtet))
    return {"unbeachtet": len(unbeachtet), "erinnert": tickets,
            "empfaenger": empfaenger_gesamt}
