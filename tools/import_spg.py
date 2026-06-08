#!/usr/bin/env python3
"""
CLI für den SPG-Verein CSV-Import. Die eigentliche Logik liegt in
app.services.spg_import_service (wird auch vom Admin-Upload genutzt).

STANDARD = Dry-Run (schreibt nichts). Erst mit --commit wird geschrieben.
Abteilungen werden nur gematcht (vorher in der App anlegen).

Beispiele:
  ./venv/bin/python tools/import_spg.py export.csv --database-url postgresql://… --limit 5
  ./venv/bin/python tools/import_spg.py export.csv --commit
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

from app.db.database import Database
from app.services.spg_import_service import run_import


def main():
    ap = argparse.ArgumentParser(description="SPG-Verein CSV-Import")
    ap.add_argument('csv_path')
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--commit', action='store_true', help='tatsächlich schreiben (sonst Dry-Run)')
    ap.add_argument('--update', action='store_true', help='bestehende Mitglieder aktualisieren')
    ap.add_argument('--allow-unmatched-abteilung', action='store_true',
                    help='nicht gematchte Abteilungen überspringen statt abzubrechen')
    ap.add_argument('--limit', type=int, default=0, help='nur die ersten N Zeilen')
    args = ap.parse_args()

    if not args.database_url:
        sys.exit("Fehler: --database-url oder VTB_DATABASE_URL erforderlich")

    with open(args.csv_path, 'rb') as fh:
        data = fh.read()

    db = Database(args.database_url)  # migriert das Schema bei Bedarf hoch
    r = run_import(db.conn, data, commit=args.commit, update=args.update,
                   allow_unmatched=args.allow_unmatched_abteilung, limit=args.limit)
    db.close()

    print(f"Gelesen: {r.rows} Datenzeilen aus {os.path.basename(args.csv_path)}")
    print(f"Modus: {'COMMIT (schreibt)' if r.committed else 'DRY-RUN (schreibt nichts)'}"
          f"{' +update' if r.update else ''}\n")
    print("=== Abteilungs-Abgleich ===")
    for a in r.abteilungs_abgleich:
        print(f"  {'✓' if a['matched'] else '✗ FEHLT':8s} {a['name']!r}  ({a['count']} Mitglieder)")
    if r.ehrenmitglieder_count:
        print(f"  (Funktion)   {r.ehrenmitglieder_count}x 'Ehrenmitglieder' -> Funktion 'ehrenmitglied'")
    print()
    if r.mannschaften_uebersicht:
        print("=== Mannschaften (Sonstiges_1) ===")
        for t in r.mannschaften_uebersicht:
            mark = '✓' if t['matched'] else '✗ Abt. fehlt'
            print(f"  {mark:12s} {t['name']!r} -> {t['abteilung']} ({t['count']})")
        print()

    if r.aborted:
        print("ABBRUCH:", r.abort_reason)
        sys.exit(1)

    print("=== Ergebnis ===")
    print(f"  Mitglieder neu:             {r.neu}")
    print(f"  Mitglieder aktualisiert:    {r.aktualisiert}")
    print(f"  übersprungen (existiert):   {r.skip_exist}")
    print(f"  übersprungen (kein Name):   {r.skip_noname}")
    print(f"  übersprungen (keine Nr):    {r.skip_nonr}")
    print(f"  davon Ehrenmitglied:        {r.ehrenmitglied} (als Funktion)")
    print(f"  Kontakte:                   {r.kontakte}")
    print(f"  Abteilungs-Zuordnungen:     {r.abteilungen}")
    print(f"  Funktions-Zuordnungen:      {r.funktionen} (inkl. Ehrenmitglied)")
    print(f"  Kader-Zuordnungen:          {r.kader}")
    print(f"  neue Funktions-Katalog:     {len(r.neue_funktionen)} {r.neue_funktionen if r.neue_funktionen else ''}")
    print(f"  neue Mannschaften:          {len(r.neue_mannschaften)} {r.neue_mannschaften if r.neue_mannschaften else ''}")
    if r.unmatched_abteilungen:
        print(f"  !! nicht gematchte Abteilungen: {r.unmatched_abteilungen}")
        print(f"     -> übersprungene Zuordnungen: {r.abt_unmatched_zuordnungen}")
    if not r.committed:
        print("\n(DRY-RUN – es wurde nichts geschrieben. Mit --commit ausführen.)")


if __name__ == '__main__':
    main()
