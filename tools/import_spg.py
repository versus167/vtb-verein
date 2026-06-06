#!/usr/bin/env python3
"""
Import von Mitgliederdaten aus einem SPG-Verein-CSV-Export in das vtb_verein-Datenmodell.

- Encoding cp1252, Trennzeichen ';', Felder zusätzlich in einfachen Anführungszeichen gequotet.
- Idempotent über die Mitglieds_Nr: bestehende Mitglieder werden standardmäßig übersprungen
  (mit --update aktualisiert und ihre Unterzuordnungen neu synchronisiert).
- STANDARD = Dry-Run (schreibt nichts, zeigt nur eine Zusammenfassung). Erst mit --commit
  wird geschrieben.

Bewusst NICHT importiert (separate Entscheidung): Beiträge/Beitragsarten, Einmalbeträge,
Ehrungen, Zusatzfelder.

Beispiele:
  ./venv/bin/python tools/import_spg.py export.csv --database-url postgresql://… --limit 5
  ./venv/bin/python tools/import_spg.py export.csv --commit
"""
import argparse
import csv
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'vtb_verein'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except Exception:
    pass

from app.db.database import Database
from app.db.mitglied_repository import MitgliedRepository
from app.db.mitglied_kontakt_repository import MitgliedKontaktRepository
from app.db.abteilung_repository import AbteilungRepository
from app.db.mitglied_abteilung_repository import MitgliedAbteilungRepository
from app.db.funktion_repository import FunktionRepository
from app.db.mitglied_funktion_repository import MitgliedFunktionRepository
from app.models.mitglied import Mitglied
from app.models.abteilung import Abteilung

ACTOR = 'spg-import'

# SPG-Funktionsbezeichnung -> (key, Anzeigename)
FUNKTION_MAP = {
    'Übungsleiter mit Lizenz': ('uebungsleiter_lizenz', 'Übungsleiter mit Lizenz'),
    'Übungsleiter':            ('uebungsleiter',         'Übungsleiter'),
    'Abteilungsleiter':        ('abteilungsleiter',      'Abteilungsleiter'),
    'Vorstand':                ('vorstand',              'Vorstand'),
    'Kampfrichter':            ('kampfrichter',          'Kampfrichter'),
    'Kassenprüfer':            ('kassenpruefer',         'Kassenprüfer'),
    'Mitarbeiter':             ('mitarbeiter',           'Mitarbeiter'),
}
ZAHLART = {'s': 'lastschrift', 'b': 'ueberweisung'}
ABT_STATUS = {'a': 'aktiv', 'p': 'passiv'}

# Kontaktfelder in Reihenfolge: (CSV-Spalte, Typ, Label)
CONTACT_FIELDS = [
    ('Email',              'email',   None),
    ('Telefon_Privat',     'telefon', 'privat'),
    ('Telefon_Dienstlich', 'telefon', 'dienstlich'),
    ('Handy_1',            'mobil',   None),
    ('Handy_2',            'mobil',   'zweit'),
    ('Fax',               'fax',     None),
]


def clean(v):
    if v is None:
        return ''
    v = v.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        v = v[1:-1]
    return v.strip()


def to_iso(d):
    d = clean(d)
    if not d:
        return None
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_nr(s):
    s = clean(s)
    try:
        return int(s)
    except ValueError:
        return None


def funktion_key_name(raw):
    if raw in FUNKTION_MAP:
        return FUNKTION_MAP[raw]
    key = (raw.lower().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
           .replace('ß', 'ss'))
    key = ''.join(c if c.isalnum() else '_' for c in key).strip('_')
    return key, raw


def parse_csv(path):
    text = open(path, 'rb').read().decode('cp1252')
    rows = list(csv.reader(text.splitlines(), delimiter=';'))
    hdr = [clean(h) for h in rows[0]]
    idx = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        out.append({h: (clean(r[i]) if i < len(r) else '') for h, i in idx.items()})
    return out


def build_contacts(row):
    """Liefert [(typ, wert, label, ist_primaer)] – je Typ wird der erste Wert primär."""
    result = []
    primary_seen = set()
    for col, typ, label in CONTACT_FIELDS:
        wert = row.get(col, '')
        if not wert:
            continue
        primaer = typ not in primary_seen
        primary_seen.add(typ)
        result.append((typ, wert, label, primaer))
    return result


def main():
    ap = argparse.ArgumentParser(description="SPG-Verein CSV-Import")
    ap.add_argument('csv_path')
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--commit', action='store_true', help='tatsächlich schreiben (sonst Dry-Run)')
    ap.add_argument('--update', action='store_true', help='bestehende Mitglieder aktualisieren statt überspringen')
    ap.add_argument('--limit', type=int, default=0, help='nur die ersten N Zeilen')
    args = ap.parse_args()

    if not args.database_url:
        sys.exit("Fehler: --database-url oder VTB_DATABASE_URL erforderlich")

    rows = parse_csv(args.csv_path)
    if args.limit:
        rows = rows[:args.limit]
    print(f"Gelesen: {len(rows)} Datenzeilen aus {os.path.basename(args.csv_path)}")
    print(f"Modus: {'COMMIT (schreibt)' if args.commit else 'DRY-RUN (schreibt nichts)'}"
          f"{' +update' if args.update else ''}\n")

    db = Database(args.database_url)  # migriert das Schema bei Bedarf hoch
    conn = db.conn
    m_repo = MitgliedRepository(conn)
    k_repo = MitgliedKontaktRepository(conn)
    a_repo = AbteilungRepository(conn)
    ma_repo = MitgliedAbteilungRepository(conn)
    f_repo = FunktionRepository(conn)
    mf_repo = MitgliedFunktionRepository(conn)

    # --- Kataloge vorbereiten: Abteilungen + Funktionen ---
    abt_names = set()
    funk_keys = {}  # key -> name
    for row in rows:
        for i in range(1, 8):
            n = row.get(f'Abteilung_{i}', '')
            if n:
                abt_names.add(n)
        for i in range(1, 11):
            raw = row.get(f'Funktion_{i}', '')
            if raw:
                k, name = funktion_key_name(raw)
                funk_keys[k] = name

    abt_map = {a.name: a.id for a in a_repo.list_abteilungen()}
    neue_abt = sorted(n for n in abt_names if n not in abt_map)
    neue_funk = sorted(k for k in funk_keys if f_repo.get_by_key(k) is None)
    if args.commit:
        for n in neue_abt:
            created = a_repo.create_abteilung(Abteilung(name=n), ACTOR)
            abt_map[n] = created.id
        for k in neue_funk:
            f_repo.create(k, funk_keys[k], 'aus SPG-Import', ACTOR)

    def lookup_mitglied(nr):
        with conn.cursor() as cur:
            cur.execute("SELECT id, version FROM mitglied WHERE mitgliedsnummer=%s AND deleted_at IS NULL", (nr,))
            return cur.fetchone()

    st = dict(neu=0, aktualisiert=0, skip_exist=0, skip_noname=0, skip_nonr=0,
              kontakte=0, abteilungen=0, funktionen=0, warn=0)

    for row in rows:
        nachname = row.get('Nachname', '')
        if not nachname:
            st['skip_noname'] += 1
            continue
        nr = to_nr(row.get('Mitglieds_Nr', ''))
        if nr is None:
            st['skip_nonr'] += 1
            continue

        austritt = to_iso(row.get('Austritt_Datum'))
        eintritt = to_iso(row.get('Eintritt_Datum'))
        zahler = row.get('Zahler', '')
        vorname = row.get('Vorname', '')
        m = Mitglied(
            mitgliedsnummer=nr,
            vorname=vorname, nachname=nachname,
            geburtsdatum=to_iso(row.get('Geburtsdatum')),
            strasse=row.get('Strasse') or None,
            plz=row.get('PLZ') or None,
            ort=row.get('Ort') or None,
            land=row.get('Land') or None,
            eintrittsdatum=eintritt,
            austrittsdatum=austritt,
            status='ausgetreten' if austritt else 'aktiv',
            zahlungsart=ZAHLART.get(row.get('Zahlart', ''), 'lastschrift'),
            iban=row.get('IBAN_Nr') or None,
            bic=row.get('BIC_Nr') or None,
            kontoinhaber=zahler or f"{vorname} {nachname}".strip(),
            geschlecht=row.get('Geschlecht') or None,
            bemerkungen=row.get('Bemerkungen') or None,
            sepa_mandatsref=row.get('Sepa_Mandats_Ref') or None,
            sepa_mandatsdatum=to_iso(row.get('Sepa_Datum_Mandats_Ref')),
        )

        contacts = build_contacts(row)
        abteilungen = []  # (abteilung_name, status, von)
        for i in range(1, 8):
            n = row.get(f'Abteilung_{i}', '')
            if not n:
                continue
            abteilungen.append((n, ABT_STATUS.get(row.get(f'Abt_Status_{i}', ''), 'aktiv'),
                                to_iso(row.get(f'Abteilung_Datum_{i}'))))
        funktionen = []  # (key, von, bis)
        for i in range(1, 11):
            raw = row.get(f'Funktion_{i}', '')
            if not raw:
                continue
            k, _ = funktion_key_name(raw)
            von = to_iso(row.get(f'Funkt_von_Datum_{i}')) or eintritt or '1900-01-01'
            funktionen.append((k, von, to_iso(row.get(f'Funkt_Bis_Datum_{i}'))))

        st['kontakte'] += len(contacts)
        st['abteilungen'] += len(abteilungen)
        st['funktionen'] += len(funktionen)

        existing = lookup_mitglied(nr)
        if existing and not args.update:
            st['skip_exist'] += 1
            continue

        if not args.commit:
            st['aktualisiert' if existing else 'neu'] += 1
            continue

        # --- schreiben ---
        if existing:
            m.id = existing['id']
            m.version = existing['version']
            m_repo.update_mitglied(m, ACTOR)
            mid = existing['id']
            for z in k_repo.list_for_mitglied(mid):
                k_repo.mark_deleted(z.id, ACTOR)
            for z in ma_repo.list_for_mitglied(mid):
                ma_repo.mark_deleted(z.id, ACTOR)
            for z in mf_repo.list_for_mitglied(mid):
                mf_repo.mark_deleted(z.id, ACTOR)
            st['aktualisiert'] += 1
        else:
            mid = m_repo.create_mitglied(m, ACTOR).id
            st['neu'] += 1

        for typ, wert, label, primaer in contacts:
            k_repo.create(mid, typ, wert, label, primaer, ACTOR)
        for name, status, von in abteilungen:
            ma_repo.create(mid, abt_map[name], status, von, None, ACTOR)
        for key, von, bis in funktionen:
            mf_repo.create(mid, None, key, von, bis, ACTOR)

    db.close()

    print("=== Ergebnis ===")
    print(f"  Mitglieder neu:             {st['neu']}")
    print(f"  Mitglieder aktualisiert:    {st['aktualisiert']}")
    print(f"  übersprungen (existiert):   {st['skip_exist']}")
    print(f"  übersprungen (kein Name):   {st['skip_noname']}")
    print(f"  übersprungen (keine Nr):    {st['skip_nonr']}")
    print(f"  Kontakte:                   {st['kontakte']}")
    print(f"  Abteilungs-Zuordnungen:     {st['abteilungen']}")
    print(f"  Funktions-Zuordnungen:      {st['funktionen']}")
    print(f"  neue Abteilungen:           {len(neue_abt)} {neue_abt if neue_abt else ''}")
    print(f"  neue Funktions-Katalog:     {len(neue_funk)} {neue_funk if neue_funk else ''}")
    if not args.commit:
        print("\n(DRY-RUN – es wurde nichts geschrieben. Mit --commit ausführen.)")


if __name__ == '__main__':
    main()
