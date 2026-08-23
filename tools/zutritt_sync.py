#!/usr/bin/env python3
"""
TTLock-Zutritts-Sync – für externen Cron/systemd-Timer (Default „paarmal am Tag").

Spiegelt Inventar (Schlösser/Gateways), am Schloss angelernte IC-Karten (Chips/
Berechtigungen), den read-only Credential-Mirror (Fingerprints/Passcodes/eKeys/IC) und holt
neue Zutrittslogs aus der TTLock-Cloud. Read-only gegenüber den Schlössern; schreibt nur in
die eigene DB. Idempotent (Dedupe über recordId/Kartennummer), daher gefahrlos wiederholbar.

Danach hält der Lauf das frische Ist gegen unser Soll (Soll-Ist-Abgleich der IC-Karten)
und meldet Admins, wenn ein gesperrter oder verlorener Chip am Schloss noch öffnet.
Der Abgleich selbst schreibt nichts an die Schlösser – er berichtet nur.

Ebenfalls am frischen Ist: Schlösser unter der eingestellten Akku-Schwelle bekommen ein
internes Ticket im dafür konfigurierten Bereich (Bereich Schließanlage → Einstellungen).

TTLock-Zugangsdaten kommen aus der Env/.env (TTLOCK_CLIENT_ID/SECRET/USERNAME/PASSWORD),
die DB aus VTB_DATABASE_URL.

Beispiele (Cron, z. B. alle 6 h):
  ./venv/bin/python tools/zutritt_sync.py                 # Inventar + Logs
  ./venv/bin/python tools/zutritt_sync.py --logs-only     # nur Logs
  ./venv/bin/python tools/zutritt_sync.py --backfill-days 7
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
from app.services.zutritt_service import (
    ZutrittService, ZutrittNichtKonfiguriertError, notify_alarme,
)
from app.services import zutritt_abgleich_service
from app.services import schloss_akku_service


def main() -> int:
    ap = argparse.ArgumentParser(description="TTLock-Zutritts-Sync (Inventar + Logs)")
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--inventar-only', action='store_true', help='nur Inventar spiegeln')
    ap.add_argument('--logs-only', action='store_true', help='nur Logs holen')
    ap.add_argument('--backfill-days', type=int, default=30,
                    help='Zeitfenster beim Erstlauf je Schloss (default 30)')
    ap.add_argument('--quiet', action='store_true', help='nur Fehler ausgeben')
    args = ap.parse_args()

    if not args.database_url:
        print("FEHLER: VTB_DATABASE_URL fehlt (Env/.env oder --database-url).", file=sys.stderr)
        return 2
    if not ZutrittService.is_configured():
        print("FEHLER: Kein vollständiges TTLock-Konto in der Env "
              "(TTLOCK_CLIENT_ID/CLIENT_SECRET/USERNAME/PASSWORD).", file=sys.stderr)
        return 2

    db = VereinsDB(args.database_url)
    svc = db.zutritt

    def log(msg):
        if not args.quiet:
            print(msg)

    try:
        if not args.logs_only:
            res = svc.inventar_sync()
            log(f"✓ Inventar-Sync: {res['schloesser']} Schloss/Schlösser gespiegelt.")
            res = svc.ic_cards_sync()
            log(f"✓ IC-Card-Import: {res['chips_neu']} Chips neu, "
                f"{res['berechtigungen_neu']} Berechtigungen neu, "
                f"{res['berechtigungen_akt']} aktualisiert.")
            res = svc.credentials_sync()
            log(f"✓ Credential-Mirror: {res['credentials']} Credentials gespiegelt "
                f"(Fingerprints/Passcodes/eKeys/IC).")
            # Das Ist ist jetzt frisch – erst hier ist der Soll-Ist-Vergleich eine Aussage.
            res = zutritt_abgleich_service.abgleich(db)
            log(f"✓ Abgleich: {len(res['befunde'])} Befund(e), "
                f"davon {res['kritisch']} sicherheitsrelevant.")
            gemeldet = zutritt_abgleich_service.melde_sperrluecken(db)
            if gemeldet:
                log(f"⚠ Gesperrte Chips öffnen weiter → {gemeldet} Admin(s) benachrichtigt.")
            # Akkustände sind mit dem Inventar frisch hereingekommen: Was unter der
            # eingestellten Schwelle liegt, meldet sich selbst als Ticket (einmal je
            # Entladung). Ohne hinterlegten Ticket-Bereich passiert hier nichts.
            akku = schloss_akku_service.pruefe_akkustaende(db)
            if akku.get("akku_tickets"):
                log(f"⚠ Akku schwach → {akku['akku_tickets']} Ticket(s) angelegt.")
            if akku.get("akku_erholt"):
                log(f"✓ {akku['akku_erholt']} Schloss/Schlösser wieder mit vollem Akku.")
        if not args.inventar_only:
            res = svc.logs_sync(backfill_days=args.backfill_days)
            log(f"✓ Log-Sync: {res['neu']} neue Zutrittslog-Einträge.")
            alarme = res.get("alarme", [])
            if alarme:
                erreicht = notify_alarme(db, alarme)
                log(f"⚠ {len(alarme)} Alarm-Ereignis(se) → {erreicht} Admin(s) benachrichtigt.")
    except ZutrittNichtKonfiguriertError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
