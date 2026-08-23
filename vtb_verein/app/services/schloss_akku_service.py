"""Akku-Überwachung der Schlösser: Aus einem schwachen Akku wird ein Ticket.

Der Inventar-Sync bringt den Ladestand jedes Cloud-Schlosses mit (`electricQuantity`);
sichtbar war er bisher nur auf der Seite. Wer nicht hinschaut, merkt vom leeren Akku
erst, wenn die Tür nicht mehr aufgeht. Diese Prüfung schließt die Lücke: Unterhalb der
eingestellten Schwelle legt sie ein internes Ticket im konfigurierten Bereich an, über
den regulären TicketService – inklusive Benachrichtigung an die im Bereich Zuständigen.

Zwei Dinge entscheiden, ob überhaupt etwas passiert:

  * **Ein Ticket je Entladung, nicht je Lauf.** Der Sync läuft alle sechs Stunden; ohne
    Gedächtnis stünden nach einer Woche 28 gleichlautende Tickets im Bereich. Deshalb
    merkt sich das Schloss die Nummer seiner offenen Meldung (`akku_ticket_id`), und
    erst wenn der Akku wieder deutlich über der Schwelle liegt – also nach einem
    Batteriewechsel –, ist der Merker frei für die nächste Meldung. Bewusst nicht am
    Ticket-Status festgemacht: Ein zu früh geschlossenes Ticket würde sonst sechs
    Stunden später als neues wieder auftauchen.
  * **Ohne Ticket-Bereich passiert nichts.** Der Bereich ist der Ein-/Aus-Schalter der
    Funktion (Bereich Schließanlage → Einstellungen).

Läuft am Ende des Syncs, wenn die Akkustände frisch sind – aus dem Cron-Lauf
(`tools/zutritt_sync.py`) wie aus dem On-demand-Sync der Seite.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.models.ticket import Ticket, TicketPrioritaet

logger = logging.getLogger(__name__)

# Wieviel Prozentpunkte über der Schwelle gelten als „Akku gewechselt"? Ein frischer
# Satz Batterien meldet um die 100 %, insofern reicht jeder Abstand. Er ist trotzdem
# nötig: Die Cloud liefert ganze Prozent, und ein Wert, der um die Schwelle herum
# pendelt (20 → 21 → 20), erzeugte sonst bei jedem Ausschlag ein neues Ticket.
ERHOLUNG_PROZENTPUNKTE = 10


def _prozent(wert: Optional[int]) -> str:
    return "unbekannt" if wert is None else f"{wert} %"


def ticket_text(schloss, schwelle: int) -> tuple[str, str]:
    """Titel und Beschreibung der automatischen Meldung (ohne DB, damit testbar)."""
    ort = f" ({schloss.standort})" if schloss.standort else ""
    titel = f"Akku schwach: {schloss.name}{ort} – {_prozent(schloss.akku_prozent)}"
    zeilen = [
        f"Das Schloss „{schloss.name}“ meldet einen Akkustand von "
        f"{_prozent(schloss.akku_prozent)} und liegt damit auf oder unter der "
        f"eingestellten Schwelle von {schwelle} %.",
        "",
        f"Standort: {schloss.standort or '–'}",
        f"Stand der Messung: {schloss.akku_stand_at or 'unbekannt'}",
        "",
        "Bitte die Batterien wechseln. Dieses Ticket hat die Schließanlage selbst "
        "erstellt; ein weiteres kommt für dieses Schloss erst wieder, wenn der Akku "
        "zwischendurch aufgefüllt war.",
    ]
    return titel, "\n".join(zeilen)


def pruefe_akkustaende(db, *, by: str = "SYSTEM") -> dict:
    """Akkustände gegen die eingestellte Schwelle halten; Tickets anlegen bzw. Merker
    zurücksetzen. Gibt eine kleine Bilanz für das Sync-Ergebnis zurück (leer, wenn die
    Funktion nicht eingerichtet ist)."""
    e = db.schliessanlage_einstellungen.get()
    if not e.akku_ticket_bereich_id:
        return {}
    bereich = db.tickets.get_bereich(e.akku_ticket_bereich_id)
    if bereich is None or bereich.deleted_at:
        logger.warning(
            "Akku-Überwachung: eingestellter Ticket-Bereich %s existiert nicht (mehr) – "
            "es wird kein Ticket erzeugt.", e.akku_ticket_bereich_id)
        return {"akku_bereich_fehlt": True}

    schwelle = e.akku_ticket_schwelle
    prioritaet = (e.akku_ticket_prioritaet if e.akku_ticket_prioritaet in TicketPrioritaet.ALL
                  else TicketPrioritaet.NORMAL)
    erstellt, zurueckgesetzt = 0, 0
    for s in db.tuer_schloesser.list_all(nur_aktive=True):
        if s.akku_prozent is None:
            continue                       # externes Schloss oder noch nie gemeldet
        if s.akku_ticket_id is None and s.akku_prozent <= schwelle:
            titel, text = ticket_text(s, schwelle)
            neu = db.tickets.create_ticket(
                Ticket(titel=titel, beschreibung=text, intern=True,
                       prioritaet=prioritaet, bereich_id=bereich.id),
                created_by=by,
            )
            db.tuer_schloesser.set_akku_ticket(s.id, neu.id)
            erstellt += 1
            logger.info("Akku-Ticket #%s für Schloss %s (%s %%) angelegt.",
                        neu.id, s.name, s.akku_prozent)
        elif s.akku_ticket_id is not None and s.akku_prozent >= schwelle + ERHOLUNG_PROZENTPUNKTE:
            db.tuer_schloesser.set_akku_ticket(s.id, None)
            zurueckgesetzt += 1
            logger.info("Schloss %s wieder bei %s %% – Akku-Merker gelöscht.",
                        s.name, s.akku_prozent)

    ergebnis = {}
    if erstellt:
        ergebnis["akku_tickets"] = erstellt
    if zurueckgesetzt:
        ergebnis["akku_erholt"] = zurueckgesetzt
    return ergebnis
