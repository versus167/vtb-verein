#!/usr/bin/env python3
"""
Ticket-Erinnerungen (#179 + Nachgang) – für Sidecar/Cron (Default „einmal täglich").

Erinnert an offene Tickets, die liegen bleiben – in zwei Fällen:

  * unbeachtet: noch KEIN Verantwortlicher hat das Ticket geöffnet. Die Meldung
    ging unter; sobald einer aus dem Kreis hineinsieht, hört es von selbst auf.
  * Stillstand: jemand hat hingesehen, seither passiert aber nichts mehr – kein
    Kommentar, keine Statusänderung, kein Anhang. Hier beendet erst ein Schritt
    am Ticket die Erinnerung, nicht das bloße Draufschauen.

Die Fristen je Priorität stehen in der App (Tickets → Verwaltung → Erinnerungen),
nicht im Code: Wie lange „zu lange" ist, weiß, wer die Tickets bearbeitet.

Schreibt nur in die eigene DB (eine Protokollzeile je Erinnerung, damit dieselbe
Mahnung nicht bei jedem Lauf erneut rausgeht) und verschickt Benachrichtigungen
über den Kanal, den der Empfänger eingestellt hat.

Die DB kommt aus VTB_DATABASE_URL (Env/.env).

Beispiele:
  ./venv/bin/python tools/ticket_erinnerung_lauf.py
  ./venv/bin/python tools/ticket_erinnerung_lauf.py --trocken
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'vtb_verein'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except Exception:
    pass

from app.db.datastore import VereinsDB
from app.services import ticket_erinnerung_service as erinnerung


def _trockenlauf(db, log) -> None:
    """Zeigen, was fällig wäre – ohne Versand und ohne Protokollzeile."""
    einst = db.ticket_erinnerung_einstellungen.get()

    unbeachtet = db.tickets.list_unbeachtet()
    faellig = erinnerung.faellige_unbeachtete(
        unbeachtet,
        db.access_log_repository.letzte_je_detail(erinnerung.EVENT_ERINNERUNG),
        einst)
    log(f"✓ {len(unbeachtet)} unbeachtete(s) Ticket(s), {len(faellig)} fällig:")
    for ticket, tage in faellig:
        log(f"  #{ticket.id} [{ticket.prioritaet}] seit {tage} Tag(en): {ticket.titel}")

    stillstehend = db.tickets.list_stillstehend()
    faellig = erinnerung.faellige_stillstehende(
        stillstehend,
        db.access_log_repository.letzte_je_detail(erinnerung.EVENT_STILLSTAND),
        einst)
    log(f"✓ {len(stillstehend)} gesehene(s) offene(s) Ticket(s), {len(faellig)} still:")
    for ticket, tage in faellig:
        log(f"  #{ticket.id} [{ticket.prioritaet}] still seit {tage} Tag(en): {ticket.titel}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Erinnerung an liegen gebliebene Tickets")
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--trocken', action='store_true',
                    help='nur anzeigen, was fällig wäre – nichts verschicken')
    ap.add_argument('--quiet', action='store_true', help='nur Fehler ausgeben')
    args = ap.parse_args()

    if not args.database_url:
        print("FEHLER: VTB_DATABASE_URL fehlt (Env/.env oder --database-url).", file=sys.stderr)
        return 2

    db = VereinsDB(args.database_url)

    def log(msg):
        if not args.quiet:
            print(msg)

    try:
        if args.trocken:
            _trockenlauf(db, log)
            return 0
        res = erinnerung.erinnern(db)
        u, s = res['unbeachtet'], res['stillstand']
        log(f"✓ Unbeachtet: {u['erinnert']} von {u['offen']} Ticket(s) gemahnt, "
            f"{u['empfaenger']} Empfänger erreicht.")
        log(f"✓ Stillstand: {s['erinnert']} von {s['offen']} Ticket(s) gemahnt, "
            f"{s['empfaenger']} Empfänger erreicht.")
    except Exception as e:                      # noqa: BLE001 – Lauf soll sprechen, nicht crashen
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
