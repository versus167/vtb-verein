"""
SPG-Verein CSV-Import als wiederverwendbarer Service.

Wird sowohl vom CLI (tools/import_spg.py) als auch vom Admin-API-Endpunkt genutzt.
`run_import` arbeitet auf einer offenen psycopg-Verbindung und liefert ein strukturiertes
ImportResult zurück (kein print/exit) – Dry-Run (commit=False) schreibt nichts.

Mapping-Regeln siehe Modul-Konstanten. Abteilungen werden NUR gematcht (keine Auto-Anlage);
'Ehrenmitglieder' ist keine Sparte, sondern wird zur Funktion 'ehrenmitglied'.
Bewusst NICHT importiert: Beiträge, Einmalbeträge, Ehrungen.
"""
import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.models.mitglied import Mitglied
from app.db.mitglied_repository import MitgliedRepository
from app.db.mitglied_kontakt_repository import MitgliedKontaktRepository
from app.db.abteilung_repository import AbteilungRepository
from app.db.mitglied_abteilung_repository import MitgliedAbteilungRepository
from app.db.funktion_repository import FunktionRepository
from app.db.mitglied_funktion_repository import MitgliedFunktionRepository

ACTOR = 'spg-import'
EHRENMITGLIED_ABT = 'Ehrenmitglieder'
EHRENMITGLIED_FUNKTION = ('ehrenmitglied', 'Ehrenmitglied')

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
ABT_ALIAS = {}  # optionale Aliasse: {CSV-Name: App-Name}

CONTACT_FIELDS = [
    ('Email',              'email',   None),
    ('Telefon_Privat',     'telefon', 'privat'),
    ('Telefon_Dienstlich', 'telefon', 'dienstlich'),
    ('Handy_1',            'mobil',   None),
    ('Handy_2',            'mobil',   'zweit'),
    ('Fax',               'fax',     None),
]


@dataclass
class ImportResult:
    rows: int = 0
    target_db: str = ''        # host:port/dbname der Ziel-DB (ohne Credentials)
    committed: bool = False
    update: bool = False
    aborted: bool = False
    abort_reason: Optional[str] = None
    neu: int = 0
    aktualisiert: int = 0
    skip_exist: int = 0
    skip_noname: int = 0
    skip_nonr: int = 0
    ehrenmitglied: int = 0
    kontakte: int = 0
    abteilungen: int = 0
    funktionen: int = 0
    abt_unmatched_zuordnungen: int = 0
    neue_funktionen: list = field(default_factory=list)
    unmatched_abteilungen: list = field(default_factory=list)
    # [{name, count, matched}] für die Anzeige
    abteilungs_abgleich: list = field(default_factory=list)
    ehrenmitglieder_count: int = 0


# --- Hilfsfunktionen ---------------------------------------------------------

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
    key = (raw.lower().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss'))
    key = ''.join(c if c.isalnum() else '_' for c in key).strip('_')
    return key, raw


def norm_abt(s):
    s = (s or '').lower().replace('ß', 'ss')
    return ''.join(c for c in s if c.isalnum())


def parse_csv_bytes(data: bytes):
    text = data.decode('cp1252')
    rows = list(csv.reader(text.splitlines(), delimiter=';'))
    if not rows:
        return []
    hdr = [clean(h) for h in rows[0]]
    idx = {h: i for i, h in enumerate(hdr)}
    ncols = len(hdr)
    bem_idx = idx.get('Bemerkungen')
    out = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        # Fortsetzungszeile: SPG exportiert Zeilenumbrüche in Bemerkungen ohne Quoting.
        # Erkennungsmerkmal: deutlich weniger Spalten als der Header.
        if len(r) < ncols // 3 and out and bem_idx is not None:
            extra = clean(r[0]).lstrip('|').strip().rstrip("'")
            if extra:
                prev_bem = out[-1].get('Bemerkungen', '')
                out[-1]['Bemerkungen'] = (prev_bem + ' ' + extra).strip()
            continue
        row = {h: (clean(r[i]) if i < len(r) else '') for h, i in idx.items()}
        # Residuale führende Anführungszeichen aus mehrzeiligen Bemerkungen entfernen
        if bem_idx is not None and row.get('Bemerkungen', '').startswith("'"):
            row['Bemerkungen'] = row['Bemerkungen'].lstrip("'").strip()
        out.append(row)
    return out


def build_contacts(row):
    result, primary_seen = [], set()
    for col, typ, label in CONTACT_FIELDS:
        wert = row.get(col, '')
        if not wert:
            continue
        result.append((typ, wert, label, typ not in primary_seen))
        primary_seen.add(typ)
    return result


def row_abteilungen(row):
    sparten, ehren = [], False
    for i in range(1, 8):
        n = row.get(f'Abteilung_{i}', '')
        if not n:
            continue
        if norm_abt(n) == norm_abt(EHRENMITGLIED_ABT):
            ehren = True
            continue
        sparten.append((n, ABT_STATUS.get(row.get(f'Abt_Status_{i}', ''), 'aktiv'),
                        to_iso(row.get(f'Abteilung_Datum_{i}'))))
    return sparten, ehren


# --- Kern --------------------------------------------------------------------

def run_import(conn, csv_bytes: bytes, *, commit: bool = False, update: bool = False,
               allow_unmatched: bool = False, limit: int = 0) -> ImportResult:
    """Führt den Import auf der gegebenen Verbindung aus. Dry-Run, wenn commit=False."""
    m_repo = MitgliedRepository(conn)
    k_repo = MitgliedKontaktRepository(conn)
    a_repo = AbteilungRepository(conn)
    ma_repo = MitgliedAbteilungRepository(conn)
    f_repo = FunktionRepository(conn)
    mf_repo = MitgliedFunktionRepository(conn)

    rows = parse_csv_bytes(csv_bytes)
    if limit:
        rows = rows[:limit]

    res = ImportResult(rows=len(rows), committed=commit, update=update)
    try:
        res.target_db = f"{conn.info.host}:{conn.info.port}/{conn.info.dbname}"
    except Exception:
        res.target_db = ''

    # CSV-Kataloge sammeln
    abt_count, funk_keys = Counter(), {}
    for row in rows:
        for i in range(1, 8):
            n = row.get(f'Abteilung_{i}', '')
            if n:
                abt_count[n] += 1
        for i in range(1, 11):
            raw = row.get(f'Funktion_{i}', '')
            if raw:
                k, name = funktion_key_name(raw)
                funk_keys[k] = name

    # Abteilungen NUR matchen
    abt_by_norm = {norm_abt(a.name): a.id for a in a_repo.list_abteilungen()}

    def match_abt(name):
        name = ABT_ALIAS.get(name, name)
        return abt_by_norm.get(norm_abt(name))

    csv_sparten = [n for n in abt_count if norm_abt(n) != norm_abt(EHRENMITGLIED_ABT)]
    matched = {n: match_abt(n) for n in csv_sparten}
    res.unmatched_abteilungen = sorted(n for n, i in matched.items() if i is None)
    res.ehrenmitglieder_count = abt_count.get(EHRENMITGLIED_ABT, 0)
    res.abteilungs_abgleich = [
        {'name': n, 'count': abt_count[n], 'matched': matched[n] is not None}
        for n in sorted(csv_sparten)
    ]

    # Abbruch bei nicht gematchten Abteilungen (außer ausdrücklich erlaubt)
    if res.unmatched_abteilungen and commit and not allow_unmatched:
        res.aborted = True
        res.abort_reason = ("Nicht zugeordnete Abteilungen: " + ", ".join(res.unmatched_abteilungen)
                            + ". Bitte erst in der App anlegen (oder 'unmatched zulassen').")
        return res

    # Ehrenmitglied-Funktion in den Katalog aufnehmen
    if res.ehrenmitglieder_count > 0:
        funk_keys[EHRENMITGLIED_FUNKTION[0]] = EHRENMITGLIED_FUNKTION[1]

    res.neue_funktionen = sorted(k for k in funk_keys if f_repo.get_by_key(k) is None)
    if commit:
        for k in res.neue_funktionen:
            f_repo.create(k, funk_keys[k], 'aus SPG-Import', ACTOR)

    def lookup_mitglied(spg_nr: int):
        """Findet ein bereits importiertes Mitglied anhand des SPG-Vermerks in bemerkungen."""
        tag = f'[SPG:{spg_nr}]'
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, version FROM mitglied WHERE bemerkungen LIKE %s AND deleted_at IS NULL LIMIT 1",
                (f'%{tag}%',),
            )
            return cur.fetchone()

    for row in rows:
        nachname = row.get('Nachname', '')
        if not nachname:
            res.skip_noname += 1
            continue
        nr = to_nr(row.get('Mitglieds_Nr', ''))
        if nr is None:
            res.skip_nonr += 1
            continue

        sparten, ehren = row_abteilungen(row)
        eintritt = to_iso(row.get('Eintritt_Datum'))
        austritt = to_iso(row.get('Austritt_Datum'))
        vorname = row.get('Vorname', '')
        zahler = row.get('Zahler', '')

        # SPG-Nummer als Vermerk in bemerkungen; neue interne Nummer wird auto-vergeben
        spg_tag = f'[SPG:{nr}]'
        csv_bemerk = row.get('Bemerkungen', '').strip()
        bemerkungen = spg_tag if not csv_bemerk else f'{spg_tag} {csv_bemerk}'

        m = Mitglied(
            mitgliedsnummer=None,   # neue interne Nummer wird automatisch vergeben
            vorname=vorname, nachname=nachname,
            geburtsdatum=to_iso(row.get('Geburtsdatum')),
            strasse=row.get('Strasse') or None, plz=row.get('PLZ') or None,
            ort=row.get('Ort') or None, land=row.get('Land') or None,
            eintrittsdatum=eintritt, austrittsdatum=austritt,
            status='ausgetreten' if austritt else 'aktiv',
            zahlungsart=ZAHLART.get(row.get('Zahlart', ''), 'lastschrift'),
            iban=row.get('IBAN_Nr') or None, bic=row.get('BIC_Nr') or None,
            kontoinhaber=zahler or f"{vorname} {nachname}".strip(),
            geschlecht=row.get('Geschlecht') or None,
            bemerkungen=bemerkungen,
            sepa_mandatsref=row.get('Sepa_Mandats_Ref') or None,
            sepa_mandatsdatum=to_iso(row.get('Sepa_Datum_Mandats_Ref')),
        )

        contacts = build_contacts(row)
        funktionen = []
        for i in range(1, 11):
            raw = row.get(f'Funktion_{i}', '')
            if not raw:
                continue
            k, _ = funktion_key_name(raw)
            von = to_iso(row.get(f'Funkt_von_Datum_{i}')) or eintritt or '1900-01-01'
            funktionen.append((k, von, to_iso(row.get(f'Funkt_Bis_Datum_{i}'))))
        if ehren:
            funktionen.append((EHRENMITGLIED_FUNKTION[0], eintritt or '1900-01-01', None))
            res.ehrenmitglied += 1

        zuordnungen = []
        for name, status, von in sparten:
            aid = matched.get(name)
            if aid is None:
                res.abt_unmatched_zuordnungen += 1
            else:
                zuordnungen.append((aid, status, von))

        res.kontakte += len(contacts)
        res.abteilungen += len(zuordnungen)
        res.funktionen += len(funktionen)

        existing = lookup_mitglied(nr)
        if existing and not update:
            res.skip_exist += 1
            continue
        if not commit:
            if existing:
                res.aktualisiert += 1
            else:
                res.neu += 1
            continue

        if existing:
            m.id, m.version = existing['id'], existing['version']
            # Interne Mitgliedsnummer aus dem bestehenden Datensatz übernehmen
            existing_full = m_repo.get_mitglied(existing['id'])
            m.mitgliedsnummer = existing_full.mitgliedsnummer
            m_repo.update_mitglied(m, ACTOR)
            mid = existing['id']
            for z in k_repo.list_for_mitglied(mid):
                k_repo.mark_deleted(z.id, ACTOR)
            for z in ma_repo.list_for_mitglied(mid):
                ma_repo.mark_deleted(z.id, ACTOR)
            for z in mf_repo.list_for_mitglied(mid):
                mf_repo.mark_deleted(z.id, ACTOR)
            res.aktualisiert += 1
        else:
            mid = m_repo.create_mitglied(m, ACTOR).id
            res.neu += 1

        for typ, wert, label, primaer in contacts:
            k_repo.create(mid, typ, wert, label, primaer, ACTOR)
        for aid, status, von in zuordnungen:
            ma_repo.create(mid, aid, status, von, None, ACTOR)
        for key, von, bis in funktionen:
            mf_repo.create(mid, None, key, von, bis, ACTOR)

    return res
