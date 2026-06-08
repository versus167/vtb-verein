#!/usr/bin/env python3
"""
Legt die Beitragsregeln und Aufnahmegebühren laut Gebührenordnung 2026
(VTB Chemnitz e.V., Stand 14.04.2026) in der Datenbank an.

STANDARD = Dry-Run (schreibt nichts). Erst mit --commit wird geschrieben.
Idempotent: Einträge werden anhand ihres Namens erkannt und beim erneuten Lauf
übersprungen (es wird nichts überschrieben oder dupliziert). Abteilungen werden
nur gematcht (vorher in der App anlegen), niemals angelegt.

Modell:
  * Vereinsbeitrag        9 €/Monat für alle Mitglieder (keine Altersbedingung)
  * Abteilungsbeitrag     je Abteilung, getrennt Erwachsene (Alter >= 18) /
                          Kinder (Alter <= 17). Wo es keinen Kinder-Satz gibt,
                          zahlen Kinder nur den Vereinsbeitrag (keine Kinder-Regel).
  * Aufnahmegebühr        einmalig Verein (Erw 12 / Kinder 6) + Zusatz je Abteilung.

Einzugs-Turnus: vierteljährlich (quartal). Gültig ab 2026-01-01, ohne 'bis'.

Hinweise / nicht abbildbar:
  * Die Altersgrenze 17/18 wird zum Abrechnungs-Stichtag ausgewertet. Laut Fußnote
    der Ordnung gilt der Erwachsenenbeitrag ab dem 01.01. des Jahres NACH dem
    18. Geburtstag (Jahrgangslogik) -> Stichtag der Abrechnung entsprechend auf
    den 01.01. legen, damit Alter == Jahrgangsalter ist.
  * Aerobic-Sonderfall ("Kinder, die vor 2022 im Verein waren, zahlen 16 €")
    braucht eine Eintrittsdatum-Bedingung und ist mit dem aktuellen Regelmodell
    NICHT abbildbar -> wird hier bewusst ausgelassen und muss manuell gepflegt werden.

Beispiele:
  ./venv/bin/python tools/setup_beitraege_2026.py --database-url postgresql://…
  ./venv/bin/python tools/setup_beitraege_2026.py --commit
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
from app.models.beitrag import Beitragsregel
from app.models.gebuehr import Gebuehr

# ---------------------------------------------------------------------------
# Stammdaten der Gebührenordnung 2026
# ---------------------------------------------------------------------------

GUELTIG_AB = '2026-01-01'
TURNUS = 'quartal'           # vierteljährlich
SETUP_BY = 'setup_beitraege_2026'

VEREINSBEITRAG_MONAT = 9.0
VEREIN_AUFNAHME = {'erwachsene': 12.0, 'kinder': 6.0}

# Beträge laut Tabelle. beitrag = Abteilungsbeitrag €/Monat,
# zusatz = einmalige Zusatz-Aufnahmegebühr. None = nicht vorhanden.
ABT_FEES = {
    'Aerobic':     {'beitrag': {'erwachsene': 11.0, 'kinder': 11.0},
                    'zusatz':  {'erwachsene': 18.0, 'kinder': 24.0}},
    'Badminton':   {'beitrag': {'erwachsene': 6.0,  'kinder': 1.0},
                    'zusatz':  {'erwachsene': 18.0, 'kinder': 24.0}},
    'Billard':     {'beitrag': {'erwachsene': 8.0,  'kinder': None},
                    'zusatz':  {'erwachsene': None, 'kinder': None}},
    'Fußball':     {'beitrag': {'erwachsene': 8.0,  'kinder': 6.0},
                    'zusatz':  {'erwachsene': 18.0, 'kinder': 10.0}},
    'Kraftsport':  {'beitrag': {'erwachsene': 6.0,  'kinder': 1.0},
                    'zusatz':  {'erwachsene': 18.0, 'kinder': 24.0}},
    'Volleyball':  {'beitrag': {'erwachsene': 5.0,  'kinder': None},
                    'zusatz':  {'erwachsene': None, 'kinder': None}},
    'Gymnastik':   {'beitrag': {'erwachsene': 5.0,  'kinder': None},
                    'zusatz':  {'erwachsene': None, 'kinder': None}},
    'Tischtennis': {'beitrag': {'erwachsene': 7.0,  'kinder': 7.0},
                    'zusatz':  {'erwachsene': None, 'kinder': 6.0}},
}

ALTER = {'erwachsene': ('alter_min', 18), 'kinder': ('alter_max', 17)}


def norm_abt(s):
    s = (s or '').lower().replace('ß', 'ss')
    return ''.join(c for c in s if c.isalnum())


def match_abteilung(fee_name, abteilungen):
    """Tolerant gegen Namens-Suffixe ('Aerobic' -> 'Aerobic/Fitness').
    Liefert (abteilung_or_None, status) mit status in matched|fehlt|mehrdeutig."""
    fn = norm_abt(fee_name)
    exact = [a for a in abteilungen if norm_abt(a.name) == fn]
    if exact:
        return exact[0], 'matched'
    partial = [a for a in abteilungen
               if norm_abt(a.name).startswith(fn) or fn.startswith(norm_abt(a.name))]
    if len(partial) == 1:
        return partial[0], 'matched'
    if len(partial) > 1:
        return None, 'mehrdeutig'
    return None, 'fehlt'


# ---------------------------------------------------------------------------
# Plan aufbauen
# ---------------------------------------------------------------------------

def build_plan(db):
    """Erzeugt (beitragsregeln, gebuehren, abgleich) – reine Objekte, kein Schreiben."""
    abteilungen = db.list_abteilungen()
    regeln, gebuehren, abgleich = [], [], []

    # 1) Vereinsbeitrag (für alle, keine Altersbedingung)
    regeln.append(Beitragsregel(
        name='Vereinsbeitrag', abteilung_id=None,
        betrag_pro_monat=VEREINSBEITRAG_MONAT, einzug_turnus=TURNUS,
        gueltig_ab=GUELTIG_AB, zahler_typ='mitglied',
    ))

    # 2) Aufnahmegebühr Verein (Erwachsene / Kinder)
    for grp, betrag in VEREIN_AUFNAHME.items():
        gebuehren.append(Gebuehr(
            name=f'Aufnahmegebühr Verein ({grp.capitalize()})', abteilung_id=None,
            betrag=betrag, anlass='aufnahme', gueltig_ab=GUELTIG_AB, zahler_typ='mitglied',
        ))

    # 3) je Abteilung: Abteilungsbeitrag + Zusatz-Aufnahmegebühr
    for fee_name, fees in ABT_FEES.items():
        abt, status = match_abteilung(fee_name, abteilungen)
        abgleich.append({'fee_name': fee_name, 'status': status,
                         'app_name': abt.name if abt else None})
        if abt is None:
            continue
        app_name = abt.name

        for grp, betrag in fees['beitrag'].items():
            if betrag is None:
                continue
            kind, wert = ALTER[grp]
            regeln.append(Beitragsregel(
                name=f'Abteilungsbeitrag {app_name} ({grp.capitalize()})',
                abteilung_id=abt.id, betrag_pro_monat=betrag, einzug_turnus=TURNUS,
                gueltig_ab=GUELTIG_AB, zahler_typ='mitglied',
                bedingung_alter_min=wert if kind == 'alter_min' else None,
                bedingung_alter_max=wert if kind == 'alter_max' else None,
            ))

        for grp, betrag in fees['zusatz'].items():
            if betrag is None:
                continue
            gebuehren.append(Gebuehr(
                name=f'Zusatz-Aufnahmegebühr {app_name} ({grp.capitalize()})',
                abteilung_id=abt.id, betrag=betrag, anlass='aufnahme',
                gueltig_ab=GUELTIG_AB, zahler_typ='mitglied',
            ))

    return regeln, gebuehren, abgleich


# ---------------------------------------------------------------------------
# Anwenden
# ---------------------------------------------------------------------------

def apply_plan(db, regeln, gebuehren, commit):
    existing_regeln = {r.name for r in db.beitragsregeln.list_all()}
    existing_gebuehren = {g.name for g in db.gebuehren.list_all()}

    report = {'regeln_neu': [], 'regeln_skip': [], 'gebuehren_neu': [], 'gebuehren_skip': []}

    for r in regeln:
        if r.name in existing_regeln:
            report['regeln_skip'].append(r)
            continue
        if commit:
            db.beitragsregeln.create(r, created_by=SETUP_BY)
        report['regeln_neu'].append(r)

    for g in gebuehren:
        if g.name in existing_gebuehren:
            report['gebuehren_skip'].append(g)
            continue
        if commit:
            db.gebuehren.create(g, created_by=SETUP_BY)
        report['gebuehren_neu'].append(g)

    return report


def _alter_text(r):
    if r.bedingung_alter_min is not None:
        return f"Alter >= {r.bedingung_alter_min}"
    if r.bedingung_alter_max is not None:
        return f"Alter <= {r.bedingung_alter_max}"
    return "alle"


def main():
    ap = argparse.ArgumentParser(description="Beitragsregeln & Aufnahmegebühren 2026 anlegen")
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--commit', action='store_true', help='tatsächlich schreiben (sonst Dry-Run)')
    args = ap.parse_args()

    if not args.database_url:
        sys.exit("Fehler: --database-url oder VTB_DATABASE_URL erforderlich")

    db = VereinsDB(args.database_url)  # migriert das Schema bei Bedarf hoch
    target = f"{db.conn.info.host}:{db.conn.info.port}/{db.conn.info.dbname}"

    regeln, gebuehren, abgleich = build_plan(db)
    report = apply_plan(db, regeln, gebuehren, commit=args.commit)
    db._database.close()

    print(f"Ziel-DB: {target}")
    print(f"Modus: {'COMMIT (schreibt)' if args.commit else 'DRY-RUN (schreibt nichts)'}\n")

    print("=== Abteilungs-Abgleich ===")
    for a in abgleich:
        if a['status'] == 'matched':
            print(f"  ✓        {a['fee_name']!r:14s} -> {a['app_name']}")
        elif a['status'] == 'mehrdeutig':
            print(f"  ? MEHRDEUTIG {a['fee_name']!r} – manuell prüfen")
        else:
            print(f"  ✗ FEHLT  {a['fee_name']!r} – Abteilung in der App anlegen (übersprungen)")
    print()

    print("=== Beitragsregeln ===")
    for r in report['regeln_neu']:
        abt = '(Verein)' if r.abteilung_id is None else f'Abt#{r.abteilung_id}'
        print(f"  + {r.name:42s} {r.betrag_pro_monat:6.2f} €/Mon  {_alter_text(r):11s} {r.einzug_turnus}  {abt}")
    for r in report['regeln_skip']:
        print(f"  = {r.name:42s} (existiert bereits – übersprungen)")
    print()

    print("=== Aufnahmegebühren ===")
    for g in report['gebuehren_neu']:
        abt = '(Verein)' if g.abteilung_id is None else f'Abt#{g.abteilung_id}'
        print(f"  + {g.name:46s} {g.betrag:6.2f} €  {g.anlass}  {abt}")
    for g in report['gebuehren_skip']:
        print(f"  = {g.name:46s} (existiert bereits – übersprungen)")
    print()

    print("=== Ergebnis ===")
    print(f"  Beitragsregeln neu:   {len(report['regeln_neu'])}  (übersprungen: {len(report['regeln_skip'])})")
    print(f"  Aufnahmegebühren neu: {len(report['gebuehren_neu'])}  (übersprungen: {len(report['gebuehren_skip'])})")
    fehlt = [a['fee_name'] for a in abgleich if a['status'] != 'matched']
    if fehlt:
        print(f"  !! nicht gematchte Abteilungen (übersprungen): {fehlt}")
    print("\n  Hinweis: Aerobic-Sonderfall (Kinder vor 2022 = 16 €) ist nicht abbildbar"
          " und wurde ausgelassen.")
    if not args.commit:
        print("\n(DRY-RUN – es wurde nichts geschrieben. Mit --commit ausführen.)")


if __name__ == '__main__':
    main()
