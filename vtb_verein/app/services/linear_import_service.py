"""LINEAR-CSV-Import als zweite Import-Variante neben SPG-Verein.

Zuschnitt und Entscheidungen: `LINEAR_IMPORT_PLAN.md`. Das Schreib-Gerüst folgt
dem SPG-Import (Dry-Run über ``commit=False``, Abteilungen werden **nur
gematcht, nie angelegt**, Wiedererkennung beim Re-Import über einen Vermerk in
``bemerkungen``); neu sind Parser und Feld-Mapping.

Der wesentliche Unterschied zu SPG liegt nicht in der Syntax, sondern in der
Semantik: LINEAR führt die Abteilungen als **Kreuz-Spalten** — eine Spalte je
Abteilung, Zugehörigkeit als „X". Welche Spalten das sind, ist vereinsspezifisch
und darf deshalb nicht fest verdrahtet werden: Alles hinter der letzten bekannten
Stammdatenspalte gilt als Abteilung.

Bewusst NICHT übernommen: die Staatsangehörigkeit (Entscheidung 3 im Plan — die
Vereinsverwaltung hat für die Angabe keinen Zweck) sowie Anrede (steckt im
Geschlecht). Was die Datei ohnehin nicht liefert: E-Mail-Adressen,
SEPA-Mandatsdaten, Funktionen, Mannschaften, Beiträge.
"""
import csv
from collections import Counter
from dataclasses import dataclass

from app.models.mitglied import Mitglied
from app.db.mitglied_repository import MitgliedRepository
from app.db.mitglied_kontakt_repository import MitgliedKontaktRepository
from app.db.abteilung_repository import AbteilungRepository
from app.db.mitglied_abteilung_repository import MitgliedAbteilungRepository
from app.services.import_common import clean, decode_csv, norm_abt, to_iso
from app.services.spg_import_service import ImportResult

ACTOR = 'linear-import'


@dataclass
class LinearImportResult(ImportResult):
    """Wie das SPG-Ergebnis, plus zwei Zähler für nicht gedeutete Werte.

    Unbekannte Geschlechts- oder Status-Angaben werden nicht geraten, sondern
    leer gelassen — hier stehen sie als Zahl, damit sie im Dry-Run auffallen,
    bevor jemand committet.
    """
    geschlecht_unbekannt: int = 0
    status_unbekannt: int = 0

# Stammdatenspalten in der Reihenfolge des Exports. Die LETZTE ist zugleich die
# Grenze: Alles danach sind Abteilungs-Kreuzspalten.
STAMMDATEN_SPALTEN = (
    'MITGLNR', 'Anrede', 'Nachname', 'Vorname', 'Geburtsdatum', 'Strasse', 'PLZ',
    'Ort', 'IBAN1', 'BIC1', 'Status', 'Eintritt', 'Austritt', 'Telefon',
    'Geschlecht', 'Staatsangehörigkeit', 'Mobiltelefon',
)
LETZTE_STAMMDATENSPALTE = 'Mobiltelefon'

GESCHLECHT = {'MÄNNLICH': 'm', 'WEIBLICH': 'w', 'DIVERS': 'd'}
STATUS = {'AKTIV': 'aktiv', 'PASSIV': 'passiv'}

# Kontaktspalten: (Spalte, Kontakttyp). Die erste ihres Typs wird Primärkontakt.
KONTAKT_SPALTEN = (('Telefon', 'telefon'), ('Mobiltelefon', 'mobil'))

# Ein „X" in der Abteilungsspalte heißt Zugehörigkeit. Groß/klein egal; ein
# anderer Inhalt (etwa ein Datum) zählt ebenfalls als gesetzt — leer heißt nein.
def _ist_gesetzt(wert: str) -> bool:
    return bool(clean(wert))


def ort_ohne_zusatz(ort: str) -> str:
    """„Chemnitz , Sachs" → „Chemnitz".

    Der Zusatz hinter dem Komma unterscheidet postalisch gleichnamige Orte und
    ist in der App nur Ballast (Entscheidung 4 im Plan).
    """
    return clean((ort or '').split(',', 1)[0])


def parse_csv_bytes(data: bytes):
    """(Zeilen als dicts, Liste der Abteilungsspalten) aus den Rohdaten.

    Die Kodierung wird durchprobiert (s. import_common); die Leerzeilen unter
    dem Header fallen als „Zeile ohne jeden Inhalt" heraus.
    """
    text = decode_csv(data)
    rows = list(csv.reader(text.splitlines(), delimiter=';'))
    if not rows:
        return [], []

    hdr = [clean(h) for h in rows[0]]
    # Abteilungsspalten = alles hinter der letzten Stammdatenspalte. Fehlt die
    # Grenzspalte, gilt der Rest hinter der letzten bekannten Stammdatenspalte;
    # ist auch die nicht da, gibt es keine Abteilungen statt falscher Treffer.
    grenze = hdr.index(LETZTE_STAMMDATENSPALTE) if LETZTE_STAMMDATENSPALTE in hdr else -1
    if grenze < 0:
        bekannt = [i for i, h in enumerate(hdr) if h in STAMMDATEN_SPALTEN]
        grenze = max(bekannt) if bekannt else len(hdr) - 1
    abteilungs_spalten = [h for h in hdr[grenze + 1:] if h]

    out = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue                      # Leerzeilen unter dem Header
        out.append({h: (clean(r[i]) if i < len(r) else '')
                    for i, h in enumerate(hdr) if h})
    return out, abteilungs_spalten


def row_abteilungen(row, abteilungs_spalten):
    """Namen der Abteilungen, in denen dieses Mitglied ein Kreuz hat."""
    return [s for s in abteilungs_spalten if _ist_gesetzt(row.get(s, ''))]


def build_contacts(row):
    """[(typ, wert, label, primaer)] — je Typ ist der erste Treffer primär."""
    ergebnis, gesehen = [], set()
    for spalte, typ in KONTAKT_SPALTEN:
        wert = row.get(spalte, '')
        if not wert:
            continue
        ergebnis.append((typ, wert, None, typ not in gesehen))
        gesehen.add(typ)
    return ergebnis


def run_import(conn, csv_bytes: bytes, *, commit: bool = False, update: bool = False,
               allow_unmatched: bool = False, limit: int = 0) -> LinearImportResult:
    """Führt den Import auf der gegebenen Verbindung aus. Dry-Run, wenn commit=False."""
    m_repo = MitgliedRepository(conn)
    k_repo = MitgliedKontaktRepository(conn)
    a_repo = AbteilungRepository(conn)
    ma_repo = MitgliedAbteilungRepository(conn)

    rows, abteilungs_spalten = parse_csv_bytes(csv_bytes)
    if limit:
        rows = rows[:limit]

    res = LinearImportResult(rows=len(rows), committed=commit, update=update)
    try:
        res.target_db = f"{conn.info.host}:{conn.info.port}/{conn.info.dbname}"
    except Exception:
        res.target_db = ''

    # Abteilungen NUR matchen, nie anlegen — wie beim SPG-Import.
    abt_by_norm = {norm_abt(a.name): a.id for a in a_repo.list_abteilungen()}
    zugeordnet = {name: abt_by_norm.get(norm_abt(name)) for name in abteilungs_spalten}

    abt_count = Counter()
    for row in rows:
        for name in row_abteilungen(row, abteilungs_spalten):
            abt_count[name] += 1

    # Nur Spalten melden, in denen überhaupt jemand steht: Eine leere Spalte im
    # Export ist kein Grund, den Lauf abzubrechen.
    benutzt = [n for n in abteilungs_spalten if abt_count[n] > 0]
    res.unmatched_abteilungen = sorted(n for n in benutzt if zugeordnet[n] is None)
    res.abteilungs_abgleich = [
        {'name': n, 'count': abt_count[n], 'matched': zugeordnet[n] is not None}
        for n in sorted(benutzt)
    ]

    if res.unmatched_abteilungen and commit and not allow_unmatched:
        res.aborted = True
        res.abort_reason = ("Nicht zugeordnete Abteilungen: "
                            + ", ".join(res.unmatched_abteilungen)
                            + ". Bitte erst in der App anlegen (oder 'unmatched zulassen').")
        return res

    def lookup_mitglied(linear_nr: str):
        """Bereits importiertes Mitglied am LINEAR-Vermerk in bemerkungen finden."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, version FROM mitglied "
                "WHERE bemerkungen LIKE %s AND deleted_at IS NULL LIMIT 1",
                (f'%[LINEAR:{linear_nr}]%',),
            )
            return cur.fetchone()

    for row in rows:
        nachname = row.get('Nachname', '')
        if not nachname:
            res.skip_noname += 1
            continue
        # Die Nummer bleibt Text: führende Nullen („0999") gehören zur Kennung
        # und gingen als int verloren (Entscheidung 2 im Plan).
        nr = row.get('MITGLNR', '')
        if not nr:
            res.skip_nonr += 1
            continue

        vorname = row.get('Vorname', '')
        eintritt = to_iso(row.get('Eintritt'))
        austritt = to_iso(row.get('Austritt'))
        iban = row.get('IBAN1') or None

        # Unbekannte Werte werden NICHT geraten, sondern bleiben leer und fallen
        # im Dry-Run über die Zähler auf (Technischer Punkt 5 im Plan).
        geschlecht_roh = row.get('Geschlecht', '').upper()
        geschlecht = GESCHLECHT.get(geschlecht_roh)
        if geschlecht_roh and geschlecht is None:
            res.geschlecht_unbekannt += 1

        status_roh = row.get('Status', '').upper()
        status = STATUS.get(status_roh)
        if status_roh and status is None:
            res.status_unbekannt += 1
        # Der Status sagt nur, welche Form die Mitgliedschaft hat (aktiv/passiv).
        # Ob jemand noch dabei ist, steht im Austrittsdatum – das wird unverändert
        # übernommen und nicht mehr in den Status gespiegelt (#173).
        status = status or 'aktiv'

        linear_tag = f'[LINEAR:{nr}]'
        m = Mitglied(
            mitgliedsnummer=None,      # neue interne Nummer wird automatisch vergeben
            vorname=vorname, nachname=nachname,
            geburtsdatum=to_iso(row.get('Geburtsdatum')),
            strasse=row.get('Strasse') or None,
            plz=row.get('PLZ') or None,
            ort=ort_ohne_zusatz(row.get('Ort', '')) or None,
            eintrittsdatum=eintritt, austrittsdatum=austritt,
            status=status,
            # LINEAR kennt kein Zahlungsart-Feld; die IBAN ist das einzige Indiz.
            zahlungsart='lastschrift' if iban else 'ueberweisung',
            iban=iban, bic=row.get('BIC1') or None,
            # Kein Zahler-Feld im Export — das Mitglied zahlt für sich selbst.
            kontoinhaber=f"{vorname} {nachname}".strip(),
            geschlecht=geschlecht,
            bemerkungen=linear_tag,
        )

        contacts = build_contacts(row)
        zuordnungen = []
        for name in row_abteilungen(row, abteilungs_spalten):
            aid = zugeordnet.get(name)
            if aid is None:
                res.abt_unmatched_zuordnungen += 1
            else:
                zuordnungen.append(aid)

        res.kontakte += len(contacts)
        res.abteilungen += len(zuordnungen)

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
            # Interne Mitgliedsnummer des Bestandssatzes behalten.
            m.mitgliedsnummer = m_repo.get_mitglied(existing['id']).mitgliedsnummer
            m_repo.update_mitglied(m, ACTOR)
            mid = existing['id']
            # Kinder soft-löschen und neu schreiben (Muster aus dem SPG-Import).
            for z in k_repo.list_for_mitglied(mid):
                k_repo.mark_deleted(z.id, ACTOR)
            for z in ma_repo.list_for_mitglied(mid):
                ma_repo.mark_deleted(z.id, ACTOR)
            res.aktualisiert += 1
        else:
            mid = m_repo.create_mitglied(m, ACTOR).id
            res.neu += 1

        for typ, wert, label, primaer in contacts:
            k_repo.create(mid, typ, wert, label, primaer, ACTOR)
        for aid in zuordnungen:
            # Von-Datum = Eintritt; ohne Eintritt bleibt es offen statt erfunden.
            ma_repo.create(mid, aid, 'aktiv', eintritt, None, ACTOR)

    return res
