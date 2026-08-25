"""Erinnerung an liegen gebliebene Tickets (#179 + Nachgang).

Angelegt, zugewiesen, kommentiert — für jeden dieser Vorgänge geht bereits eine
Benachrichtigung raus. Was danach kommt, sieht niemand. Für die zwei Arten, wie ein
Ticket danach liegen bleibt, gibt es hier je einen Zweig:

* **unbeachtet** (#179) — noch KEIN Verantwortlicher hat es geöffnet. Die Meldung
  ging in der Post unter; gezählt wird ab Erstellung. Öffnet einer aus dem Kreis das
  Ticket, hört die Erinnerung von selbst auf: Es gibt nichts abzuhaken.
* **stillstand** (#179-Nachgang) — jemand hat hingesehen, vielleicht auch etwas getan, und
  seither passiert nichts mehr: kein Kommentar, keine Statusänderung, kein Anhang.
  Gezählt wird ab der letzten Aktivität (`stillstand_seit`, s. Repository). Hier hört
  die Erinnerung erst auf, wenn tatsächlich etwas geschieht — Wegklicken genügt nicht.

Beide Listen schließen einander aus, kein Ticket wird also doppelt gemahnt.

Verantwortlich ist der Zugewiesene und, über die Bereichs-Berechtigung, wer dort
bearbeiten oder schließen darf; dass der Melder sein eigenes Ticket ansieht, zählt
nicht. Wer die Mahnung bekommt, unterscheidet sich zwischen den Zweigen: Solange
niemand hingesehen hat, ist auch nichts verteilt — dann geht sie an den ganzen Kreis.
Beim Stillstand gilt die Vorrang-Regel aus `TicketService.zustaendige_empfaenger`:
Ist jemand zugewiesen, trifft es nur ihn.

Die Fristen sind KEINE Konstanten mehr, sondern stehen in
`ticket_erinnerung_einstellungen` (#179-Nachgang) — wie lange „zu lange" ist, weiß nicht der
Code, sondern wer die Tickets bearbeitet. Frist 0 schaltet eine einzelne Priorität ab.

Das Gedächtnis ist das Zugriffsprotokoll (eine Zeile je Erinnerung, je Zweig ein
eigener Ereignistyp): Ohne das käme bei jedem Lauf dieselbe Nachricht erneut.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.ticket import (
    TicketErinnerungEinstellungen, TicketPrioritaet, TicketStatus,
)

logger = logging.getLogger(__name__)

EVENT_ERINNERUNG = 'ticket_erinnerung'
EVENT_STILLSTAND = 'ticket_stillstand_erinnerung'
_KATEGORIE = 'ticket'

# Vorgabe, solange keine Einstellungen vorliegen (Tests, ganz frische DB): die
# Standardwerte der Dataclass – also genau die Werte, die auch in der Tabelle stehen.
STANDARD_EINSTELLUNGEN = TicketErinnerungEinstellungen()


def _als_datetime(wert) -> Optional[datetime]:
    """DB-Zeitstempel → aware datetime. TIMESTAMPTZ liefert bereits datetime,
    ältere Zeilen können als ISO-Text ankommen."""
    if wert is None:
        return None
    if not isinstance(wert, datetime):
        try:
            wert = datetime.fromisoformat(str(wert).replace('Z', '+00:00'))
        except ValueError:
            return None
    return wert if wert.tzinfo else wert.replace(tzinfo=timezone.utc)


def tage_seit(zeitpunkt, jetzt: datetime) -> Optional[int]:
    """Wie viele volle Tage liegt der Zeitpunkt zurück? None, wenn nicht lesbar."""
    wert = _als_datetime(zeitpunkt)
    return None if wert is None else (jetzt - wert).days


def ist_faellig(seit, zuletzt_erinnert, frist_tage: int, wiederholung_tage: int,
                jetzt: datetime) -> bool:
    """Ist jetzt eine Erinnerung dran?

    Zwei Schwellen: die erste Mahnung nach `frist_tage`, jede weitere im Abstand
    `wiederholung_tage` zur letzten. Beides zählt ab einem festen Zeitpunkt (`seit`
    bzw. letzte Erinnerung), der Lauf ist damit unabhängig von seinem Takt — ein
    ausgefallener Lauf holt die Mahnung nach, ein doppelter schickt sie nicht zweimal.

    `frist_tage <= 0` heißt „diese Priorität nicht mahnen".
    """
    if frist_tage <= 0:
        return False
    tage = tage_seit(seit, jetzt)
    if tage is None or tage < frist_tage:
        return False
    zuletzt = _als_datetime(zuletzt_erinnert)
    if zuletzt is None:
        return True
    # Ohne Untergrenze würde eine Wiederholung von 0 Tagen bei jedem Lauf mahnen.
    return jetzt - zuletzt >= timedelta(days=max(wiederholung_tage, 1))


def faellige_unbeachtete(tickets: list, letzte_erinnerungen: dict,
                         einstellungen: Optional[TicketErinnerungEinstellungen] = None,
                         jetzt: Optional[datetime] = None) -> list[tuple]:
    """Aus den unbeachteten Tickets die fälligen heraussuchen – (Ticket, Tage)."""
    einst = einstellungen or STANDARD_EINSTELLUNGEN
    jetzt = jetzt or datetime.now(timezone.utc)
    if not einst.unbeachtet_aktiv:
        return []
    faellig = []
    for t in tickets:
        if ist_faellig(t.created_at, letzte_erinnerungen.get(str(t.id)),
                       einst.unbeachtet_tage(t.prioritaet),
                       einst.unbeachtet_wiederholung_tage, jetzt):
            faellig.append((t, tage_seit(t.created_at, jetzt)))
    return faellig


def faellige_stillstehende(tickets: list, letzte_erinnerungen: dict,
                           einstellungen: Optional[TicketErinnerungEinstellungen] = None,
                           jetzt: Optional[datetime] = None) -> list[tuple]:
    """Aus den gesehenen Tickets die stillstehenden und fälligen – (Ticket, Tage)."""
    einst = einstellungen or STANDARD_EINSTELLUNGEN
    jetzt = jetzt or datetime.now(timezone.utc)
    if not einst.stillstand_aktiv:
        return []
    faellig = []
    for t in tickets:
        if ist_faellig(t.stillstand_seit, letzte_erinnerungen.get(str(t.id)),
                       einst.stillstand_tage(t.prioritaet),
                       einst.stillstand_wiederholung_tage, jetzt):
            faellig.append((t, tage_seit(t.stillstand_seit, jetzt)))
    return faellig


def _dringend(ticket) -> bool:
    return ticket.prioritaet in (TicketPrioritaet.SICHERHEIT, TicketPrioritaet.HOCH)


def _tage_text(tage: int) -> str:
    return f"{tage} {'Tag' if tage == 1 else 'Tagen'}"


def _prioritaet_text(ticket) -> str:
    return TicketPrioritaet.LABELS.get(ticket.prioritaet, ticket.prioritaet)


def build_erinnerung(ticket, tage: int) -> tuple[str, str]:
    """Titel und Text der Erinnerung an ein unbeachtetes Ticket. Der Text sagt, warum
    sie kommt — sonst liest sie sich wie die dritte Kopie der ursprünglichen Meldung."""
    titel = (f"{'🔴' if _dringend(ticket) else '🎫'} Ticket #{ticket.id} wartet seit "
             f"{_tage_text(tage)}")
    text = (f"\"{ticket.titel}\"\n\n"
            f"Priorität: {_prioritaet_text(ticket)}\n\n"
            "Noch niemand aus dem zuständigen Kreis hat dieses Ticket geöffnet. "
            "Ein Blick genügt – danach kommt keine Erinnerung mehr.")
    return titel, text


def build_stillstand(ticket, tage: int) -> tuple[str, str]:
    """Titel und Text der Erinnerung an ein liegen gebliebenes Ticket (#179-Nachgang).

    Anders als bei der unbeachteten Meldung reicht Hinsehen hier nicht: Der Text sagt
    deshalb, was das Ticket aus der Erinnerung nimmt – ein Schritt daran."""
    titel = (f"{'🔴' if _dringend(ticket) else '⏳'} Ticket #{ticket.id} liegt seit "
             f"{_tage_text(tage)} still")
    text = (f"\"{ticket.titel}\"\n\n"
            f"Priorität: {_prioritaet_text(ticket)}\n"
            f"Status: {TicketStatus.LABELS.get(ticket.status, ticket.status)}\n\n"
            f"Seit {_tage_text(tage)} ist an diesem Ticket nichts mehr passiert – "
            "kein Kommentar, keine Statusänderung. Ein Kommentar, ein Statuswechsel "
            "oder das Schließen beendet die Erinnerung.")
    return titel, text


def _empfaenger_ids(eintraege) -> list[int]:
    """Empfängerlisten der beiden Zweige auf User-IDs bringen (dicts oder IDs)."""
    return [e['user_id'] if isinstance(e, dict) else e for e in eintraege]


def _versenden(db, user_ids: list[int], titel: str, text: str, url: str) -> int:
    """An die aktiven Konten aus `user_ids` schicken; gibt die Zahl der Erreichten
    zurück. Ein Fehler bei einem Empfänger stoppt den Lauf nicht."""
    from app.services.notification_service import NotificationService
    erreicht = 0
    for user_id in user_ids:
        user = db.user_repository.get_by_id(user_id)
        if not (user and user.active):
            continue
        try:
            if NotificationService.send_notification(user, titel, text,
                                                     push_service=db.push, url=url):
                erreicht += 1
        except Exception:
            logger.exception("Ticket-Erinnerung an %s fehlgeschlagen.", user.username)
    return erreicht


def _einstellungen(db) -> TicketErinnerungEinstellungen:
    """Fristen aus der DB; fällt auf die Vorgaben zurück, wenn es sie (noch) nicht gibt."""
    repo = getattr(db, 'ticket_erinnerung_einstellungen', None)
    if repo is None:
        return STANDARD_EINSTELLUNGEN
    return repo.get()


def _lauf(db, *, faellig: list[tuple], event: str, empfaenger_je_ticket,
          text_je_ticket) -> dict:
    """Gemeinsamer Versandlauf beider Zweige.

    Ein Ticket ohne jeden Zuständigen wird übersprungen und NICHT vermerkt, damit die
    Mahnung nachkommt, sobald jemand zuständig wird. Der Versand läuft bewusst synchron:
    Der Lauf ist ein kurzlebiger Prozess, der einen Hintergrund-Pool beim Beenden mitrisse.
    """
    tickets = empfaenger_gesamt = 0
    for ticket, tage in faellig:
        empfaenger = _empfaenger_ids(empfaenger_je_ticket(ticket))
        if not empfaenger:
            continue          # niemand zuständig – dann mahnt hier auch niemanden etwas
        titel, text = text_je_ticket(ticket, tage)
        erreicht = _versenden(db, empfaenger, titel, text,
                              f"/tickets?ticket={ticket.id}")
        db.access_log_repository.log(event, category=_KATEGORIE, detail=str(ticket.id))
        tickets += 1
        empfaenger_gesamt += erreicht
    return {"erinnert": tickets, "empfaenger": empfaenger_gesamt}


def erinnern(db, *, jetzt: Optional[datetime] = None) -> dict:
    """Fällige Erinnerungen beider Zweige verschicken.

    Gibt je Zweig zurück, wie viele Tickets in Frage kamen (`offen`), wie viele gemahnt
    wurden und wie viele Empfänger erreicht wurden.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    einst = _einstellungen(db)

    unbeachtet = db.tickets.list_unbeachtet()
    faellig_u = faellige_unbeachtete(
        unbeachtet, db.access_log_repository.letzte_je_detail(EVENT_ERINNERUNG),
        einst, jetzt)
    ergebnis_u = _lauf(
        db, faellig=faellig_u, event=EVENT_ERINNERUNG,
        # `verantwortlich_ungesehen` ist hier der ganze Kreis (gesehen hat es keiner)
        # und filtert bereits auf aktive Konten.
        empfaenger_je_ticket=lambda t: db.tickets.get_gesehen(t)['verantwortlich_ungesehen'],
        text_je_ticket=build_erinnerung)

    stillstehend = db.tickets.list_stillstehend()
    faellig_s = faellige_stillstehende(
        stillstehend, db.access_log_repository.letzte_je_detail(EVENT_STILLSTAND),
        einst, jetzt)
    ergebnis_s = _lauf(
        db, faellig=faellig_s, event=EVENT_STILLSTAND,
        empfaenger_je_ticket=db.tickets.zustaendige_empfaenger,
        text_je_ticket=build_stillstand)

    if ergebnis_u['erinnert'] or ergebnis_s['erinnert']:
        logger.info("Ticket-Erinnerungen: %d unbeachtete(s) und %d liegen gebliebene(s) "
                    "Ticket(s) gemahnt, %d Empfänger erreicht.",
                    ergebnis_u['erinnert'], ergebnis_s['erinnert'],
                    ergebnis_u['empfaenger'] + ergebnis_s['empfaenger'])
    return {
        "unbeachtet": {"offen": len(unbeachtet), **ergebnis_u},
        "stillstand": {"offen": len(stillstehend), **ergebnis_s},
    }
