#!/usr/bin/env python3
"""
Ticket-Erinnerungen (#179) – für Sidecar/Cron (Default „einmal täglich").

Erinnert an offene Tickets, die noch KEIN Verantwortlicher geöffnet hat. Anlegen,
Zuweisen und Kommentare melden sich bereits von selbst; hier geht es um den Fall
danach: Die Meldung ging unter, und das Ticket liegt. Gemahnt wird nach Priorität
gestaffelt (Sicherheit/Hoch ab 1 Tag, Normal ab 3, Niedrig ab 7) und danach
wöchentlich, bis es jemand öffnet – dann hört es von selbst auf.

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
from app.services import ticket_erinnerung_service


def main() -> int:
    ap = argparse.ArgumentParser(description="Erinnerung an unbeachtete Tickets")
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
            unbeachtet = db.tickets.list_unbeachtet()
            letzte = db.access_log_repository.letzte_je_detail(
                ticket_erinnerung_service.EVENT_ERINNERUNG)
            faellig = ticket_erinnerung_service.faellige_tickets(unbeachtet, letzte)
            log(f"✓ {len(unbeachtet)} unbeachtete(s) Ticket(s), {len(faellig)} fällig:")
            for t in faellig:
                log(f"  #{t.id} [{t.prioritaet}] {t.titel}")
            return 0
        res = ticket_erinnerung_service.erinnern(db)
        log(f"✓ Ticket-Erinnerungen: {res['erinnert']} von {res['unbeachtet']} "
            f"unbeachteten Ticket(s) gemahnt, {res['empfaenger']} Empfänger erreicht.")
    except Exception as e:                      # noqa: BLE001 – Lauf soll sprechen, nicht crashen
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
