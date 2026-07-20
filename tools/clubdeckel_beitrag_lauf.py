#!/usr/bin/env python3
"""
Teamtresor-Beitragslauf (#98) – für Sidecar/Cron (Default „einmal täglich").

Bucht für jeden aktiven Teamtresor mit konfiguriertem Monatsbeitrag den fälligen
Mannschaftsbeitrag nach – je aktivem Kader-Mitglied ohne Befreiung, datiert auf
den jeweiligen Monat. Idempotent: ein Monat wird nie doppelt gebucht, der Lauf
ist also gefahrlos beliebig oft wiederholbar (daher reicht ein täglicher Tick,
der den 1. sicher erwischt).

Die DB kommt aus VTB_DATABASE_URL (Env/.env). Schreibt nur in die eigene DB.

Beispiele:
  ./venv/bin/python tools/clubdeckel_beitrag_lauf.py
  ./venv/bin/python tools/clubdeckel_beitrag_lauf.py --quiet
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
from app.services.clubdeckel_beitrag_service import run_beitragslauf


def main() -> int:
    ap = argparse.ArgumentParser(description="Teamtresor-Beitragslauf (alle aktiven Deckel)")
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--quiet', action='store_true', help='nur Fehler ausgeben')
    args = ap.parse_args()

    if not args.database_url:
        print("FEHLER: VTB_DATABASE_URL fehlt (Env/.env oder --database-url).", file=sys.stderr)
        return 2

    db = VereinsDB(args.database_url)
    try:
        ergebnis = run_beitragslauf(db)
    finally:
        db.close()

    gesamt = sum(ergebnis.values())
    if not args.quiet:
        print(f"✓ Beitragslauf: {len(ergebnis)} aktive(r) Teamtresor(e) geprüft, "
              f"{gesamt} Beitragsbuchung(en) neu.")
        for deckel_id, n in ergebnis.items():
            if n:
                print(f"  · Deckel {deckel_id}: {n} neu gebucht")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
