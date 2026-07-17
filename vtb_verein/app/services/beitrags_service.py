"""
BeitragsService – Vorschau-Berechnung und Sollstellungs-Generierung.

Ablauf:
1. vorschau(zeitraum) → Liste der zu erzeugenden Sollstellungen (ohne DB-Schreibzugriff)
2. abrechnen(zeitraum, erstellt_von) → Sollstellungen + Kassenbuchungen anlegen
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from app.models.beitrag import Beitragsregel, BeitragSollstellung


# ---------------------------------------------------------------------------
# Hilfstypen für die Vorschau
# ---------------------------------------------------------------------------

@dataclass
class VorschauPosition:
    mitglied_id: int
    mitglied_vorname: str
    mitglied_nachname: str
    mitglied_iban: Optional[str]
    beitragsregel_id: int
    beitragsregel_name: str
    beitragsregel_abteilung_id: Optional[int]
    beitragsregel_abteilung_name: Optional[str]
    betrag: float
    zahler_typ: str                   # mitglied | abteilung
    zeitraum: str
    faelligkeitsdatum: str
    bereits_vorhanden: bool           # True = Duplikat, wird übersprungen
    # Alle Abteilungen, denen das Mitglied aktuell angehört (für Frontend-Filter).
    mitglied_abteilung_ids: list[int] = field(default_factory=list)
    # Anteilige Abrechnung: tatsächlich berechnete Monate / Monate im Turnus.
    anzahl_monate: int = 0
    monate_im_zeitraum: int = 0


@dataclass
class AbrechnungErgebnis:
    zeitraum: str                     # zusammengefasstes Label, z.B. "2026-Q1 – 2026-Q2"
    angelegt: int
    uebersprungen: int                # Duplikate
    zeitraeume: list[str] = field(default_factory=list)  # tatsächlich neu angelegte Zeiträume


@dataclass
class DashboardAbteilung:
    """Aggregierte Beitrags-Projektion einer Abteilung (bzw. des Vereinsbeitrags)."""
    abteilung_id: Optional[int]
    abteilung_name: str
    summe: float
    anzahl_zahler: int                # verschiedene Mitglieder mit Forderung
    anzahl_positionen: int


@dataclass
class DashboardErgebnis:
    zeitraum: str                     # Quartal des Stichtags, z.B. '2026-Q4'
    stichtag: str
    gruppen: list[DashboardAbteilung]
    gesamt_summe: float
    gesamt_zahler: int                # verschiedene Mitglieder insgesamt
    gesamt_positionen: int


# ---------------------------------------------------------------------------
# Zeitraum-Hilfsfunktionen
# ---------------------------------------------------------------------------

def zeitraum_label(turnus: str, stichtag: date) -> str:
    """Erzeugt ein lesbares Zeitraum-Kürzel, z.B. '2026-Q4', '2026-01'."""
    if turnus == 'monat':
        return stichtag.strftime('%Y-%m')
    if turnus == 'quartal':
        q = (stichtag.month - 1) // 3 + 1
        return f"{stichtag.year}-Q{q}"
    if turnus == 'halbjahr':
        h = 1 if stichtag.month <= 6 else 2
        return f"{stichtag.year}-H{h}"
    return str(stichtag.year)


def faelligkeitsdatum(turnus: str, stichtag: date) -> str:
    """Fälligkeitsdatum = letzter Tag des Einzugszeitraums."""
    if turnus == 'monat':
        # Letzter Tag des Monats
        naechster = (stichtag.replace(day=1) + timedelta(days=32)).replace(day=1)
        return (naechster - timedelta(days=1)).isoformat()
    if turnus == 'quartal':
        q = (stichtag.month - 1) // 3
        letzter_monat = (q + 1) * 3
        naechster = date(stichtag.year + (1 if letzter_monat == 12 else 0),
                         letzter_monat % 12 + 1, 1)
        return (naechster - timedelta(days=1)).isoformat()
    if turnus == 'halbjahr':
        letzter_monat = 6 if stichtag.month <= 6 else 12
        naechster = date(stichtag.year + (1 if letzter_monat == 12 else 0),
                         letzter_monat % 12 + 1, 1)
        return (naechster - timedelta(days=1)).isoformat()
    # jahr
    return date(stichtag.year, 12, 31).isoformat()


def _letzter_tag(jahr: int, monat: int) -> date:
    """Letzter Kalendertag eines Monats."""
    if monat == 12:
        return date(jahr, 12, 31)
    return date(jahr, monat + 1, 1) - timedelta(days=1)


def zeitraum_monate(turnus: str, stichtag: date) -> list[tuple[int, int]]:
    """Alle Kalendermonate (jahr, monat) im Abrechnungszeitraum des Stichtags."""
    if turnus == 'monat':
        return [(stichtag.year, stichtag.month)]
    if turnus == 'quartal':
        start = ((stichtag.month - 1) // 3) * 3 + 1
        return [(stichtag.year, start + i) for i in range(3)]
    if turnus == 'halbjahr':
        start = 1 if stichtag.month <= 6 else 7
        return [(stichtag.year, start + i) for i in range(6)]
    # jahr
    return [(stichtag.year, m) for m in range(1, 13)]


# ---------------------------------------------------------------------------
# Aufhol-Abrechnung: Quartals-Fenster mit harter Untergrenze
# ---------------------------------------------------------------------------

# Hartes Mindest-Rückgriffsdatum: vor diesem Tag wird NIE eine Sollstellung
# erzeugt, egal wie weit die Quartals-Rückschau (Einstellung) zurückreicht.
# Einmaliger Stichtag der Beitrags-Ersterfassung – bewusst Code-Konstante, kein
# Setting (kann später zum Setting werden, wenn nötig).
RUECKGRIFF_MINIMUM = date(2026, 4, 1)


def quartal_start(d: date) -> date:
    """Erster Tag des Quartals, in dem `d` liegt."""
    monat = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, monat, 1)


def quartal_verschieben(q_start: date, anzahl: int) -> date:
    """Verschiebt einen Quartals-Start um `anzahl` Quartale (negativ = zurück)."""
    monate = q_start.year * 12 + (q_start.month - 1) + anzahl * 3
    return date(monate // 12, monate % 12 + 1, 1)


def aufhol_quartale(bis: date, quartale_rueckschau: int) -> list[date]:
    """Quartals-Startdaten vom (aktuellen Quartal − Rückschau) bis zum aktuellen
    Quartal des Stichtags `bis` – nie vor `RUECKGRIFF_MINIMUM`.

    `quartale_rueckschau` = Anzahl der Quartale VOR dem aktuellen, die mitgenommen
    werden (0 = nur aktuelles Quartal). Negative Werte zählen wie 0.
    """
    aktuell = quartal_start(bis)
    start = max(quartal_verschieben(aktuell, -max(quartale_rueckschau, 0)),
                quartal_start(RUECKGRIFF_MINIMUM))
    quartale: list[date] = []
    q = start
    while q <= aktuell:
        quartale.append(q)
        q = quartal_verschieben(q, 1)
    return quartale


def perioden_im_quartal(turnus: str, q_start: date) -> list[date]:
    """Stichtage (je ein Periodenstart) des Turnus, die in das Quartal `q_start` fallen.

    - monat        → die drei Monatsanfänge des Quartals
    - quartal      → der Quartalsanfang
    - halbjahr/jahr→ der Quartalsanfang (degeneriert; die exists()-Duplikatsperre
      verhindert Mehrfach-Sollstellungen für denselben Halbjahres-/Jahres-Zeitraum).
      Kommt im Verein nicht vor – Quartal ist der längste genutzte Turnus.
    """
    if turnus == 'monat':
        return [date(q_start.year, q_start.month + i, 1) for i in range(3)]
    return [q_start]


def parse_datum(s: Optional[str]) -> Optional[date]:
    """Parst ein TEXT-Datum (führende 10 Zeichen, ISO) zu date; leer/ungültig → None."""
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def aktive_monate_menge(monate: list[tuple[int, int]],
                        von: Optional[date],
                        bis: Optional[date]) -> set[tuple[int, int]]:
    """
    Teilmenge der `monate`, in denen das Aktiv-Intervall [von, bis] mindestens einen
    Tag überlappt – „angefangener Monat zählt voll", der Austrittsmonat zählt mit.
    von=None → seit jeher aktiv; bis=None → unbefristet aktiv.
    """
    treffer: set[tuple[int, int]] = set()
    for jahr, monat in monate:
        monat_start = date(jahr, monat, 1)
        monat_ende = _letzter_tag(jahr, monat)
        if (von is None or von <= monat_ende) and (bis is None or bis >= monat_start):
            treffer.add((jahr, monat))
    return treffer


def _monate_je_schluessel(monate: list[tuple[int, int]], rows, schluessel: str
                          ) -> dict[int, dict]:
    """Aggregiert Intervall-Zeilen (`von`/`bis`) je Mitglied und `schluessel`-Wert zu
    Monatsmengen.

    rows: Iterable von dicts mit 'mitglied_id', `schluessel`, 'von', 'bis'.
    Returns {mitglied_id: {schluessel_wert: set[(jahr, monat)]}}.
    """
    result: dict[int, dict] = {}
    for r in rows:
        menge = aktive_monate_menge(monate, parse_datum(r.get('von')), parse_datum(r.get('bis')))
        if not menge:
            continue
        result.setdefault(r['mitglied_id'], {}).setdefault(r[schluessel], set()).update(menge)
    return result


def funktions_monats_restriktion(regel, mitglied_ids, monate: list[tuple[int, int]],
                                 funktion_rows, abteilung_rows) -> dict[int, dict]:
    """Bestimmt je Mitglied die Monats-Restriktion aus Funktions-Einschlüssen/-Ausnahmen.

    Funktions-/Ausnahme-Bedingungen wirken **zeitraumgenau**: ein Monat zählt für die
    Beitragsauswirkung, wenn die Funktion – und, falls index-gleich eine Abteilung
    gepaart ist, auch die Abteilungsmitgliedschaft – in diesem Monat mindestens einen
    Tag bestand („angefangener Monat zählt voll", analog zu `aktive_monate_menge`).

    Mehrere Einschlüsse bzw. Ausnahmen werden je Mitglied **vereinigt** (ODER über die
    Paare). Ein Paar mit Abteilungsbezug zählt nur in Monaten, in denen Funktion **und**
    Abteilungsmitgliedschaft bestanden (None = vereinsweit).

    Returns {mid: {'incl': set | None, 'excl': set}}:
      - 'incl' None  → die Regel hat keine Einschluss-Funktionen (keine Einschränkung).
      - 'incl' set   → nur diese Monate dürfen verbleiben (Schnittmenge im Service).
      - 'excl' set   → diese Monate werden abgezogen.
    """
    funktion_monate = _monate_je_schluessel(monate, funktion_rows, 'funktion')
    abteilung_monate = _monate_je_schluessel(monate, abteilung_rows, 'abteilung_id')

    def _paar_monate(mid: int, funktion: str, abt_id) -> set:
        fm = funktion_monate.get(mid, {}).get(funktion, set())
        if abt_id is None:
            return set(fm)
        return fm & abteilung_monate.get(mid, {}).get(abt_id, set())

    bed_abt = regel.bedingung_abteilung_ids or []
    aus_abt = regel.ausnahme_abteilung_ids or []

    result: dict[int, dict] = {}
    for mid in mitglied_ids:
        incl = None
        if regel.bedingung_funktionen:
            incl = set()
            for i, funktion in enumerate(regel.bedingung_funktionen):
                abt_id = bed_abt[i] if i < len(bed_abt) else None
                incl |= _paar_monate(mid, funktion, abt_id)
        excl: set = set()
        for i, funktion in enumerate(regel.ausnahme_funktionen or []):
            abt_id = aus_abt[i] if i < len(aus_abt) else None
            excl |= _paar_monate(mid, funktion, abt_id)
        result[mid] = {'incl': incl, 'excl': excl}
    return result


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BeitragsService:

    def __init__(self, db):
        self.db = db

    def vorschau(self, stichtag_str: str,
                 mitglied_id: Optional[int] = None) -> list[VorschauPosition]:
        """
        Berechnet welche Sollstellungen für die EINE Periode des Stichtags erzeugt
        würden (je Regel ein Zeitraum). Schreibt nichts in die DB. Genutzt vom
        Dashboard (Projektion aktuelles Quartal) und – mit ``mitglied_id`` – für die
        Beitragsvorschau eines einzelnen Mitglieds (Mitglied-Editor).
        """
        positionen: list[VorschauPosition] = []
        for regel in self.db.beitragsregeln.list_aktive(stichtag_str):
            positionen.extend(self._positionen_fuer_regel(regel, stichtag_str, mitglied_id))
        self._attach_mitglied_abteilungen(positionen)
        return positionen

    def vorschau_aufholen(self, bis_stichtag_str: str,
                          quartale_rueckschau: int) -> list[VorschauPosition]:
        """
        Aufhol-Vorschau: alle (noch nicht abgerechneten) Perioden vom (aktuellen
        Quartal − `quartale_rueckschau`) bis zum Quartal des Stichtags `bis_stichtag_str`
        – nie vor `RUECKGRIFF_MINIMUM`. Schreibt nichts in die DB.

        Bereits vorhandene Sollstellungen sind als `bereits_vorhanden` markiert; der
        eigentliche Duplikatschutz greift beim Anlegen in `abrechnen`. Mehrfach
        erzeugte Positionen (z.B. degenerierter Halbjahres-Turnus über zwei Quartale)
        werden je (Mitglied, Regel, Zeitraum) entdoppelt.
        """
        bis = date.fromisoformat(bis_stichtag_str)
        positionen: list[VorschauPosition] = []
        for q_start in aufhol_quartale(bis, quartale_rueckschau):
            q_start_str = q_start.isoformat()
            for regel in self.db.beitragsregeln.list_aktive(q_start_str):
                for periode in perioden_im_quartal(regel.einzug_turnus, q_start):
                    positionen.extend(
                        self._positionen_fuer_regel(regel, periode.isoformat()))

        gesehen: set[tuple] = set()
        eindeutig: list[VorschauPosition] = []
        for p in positionen:
            schluessel = (p.mitglied_id, p.beitragsregel_id, p.zeitraum)
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            eindeutig.append(p)

        self._attach_mitglied_abteilungen(eindeutig)
        return eindeutig

    def _positionen_fuer_regel(self, regel: Beitragsregel, stichtag_str: str,
                               mitglied_id: Optional[int] = None) -> list[VorschauPosition]:
        """Vorschau-Positionen einer Regel für die Periode des Stichtags (anteilige
        Monate, Funktions-/Ausnahme-/Alters-Bedingungen). Ohne DB-Schreibzugriff.
        Mit ``mitglied_id`` auf dieses eine Mitglied beschränkt."""
        stichtag = date.fromisoformat(stichtag_str)
        zeitraum = zeitraum_label(regel.einzug_turnus, stichtag)
        faellig = faelligkeitsdatum(regel.einzug_turnus, stichtag)
        monate = zeitraum_monate(regel.einzug_turnus, stichtag)
        periode_start = date(monate[0][0], monate[0][1], 1)
        periode_ende = _letzter_tag(monate[-1][0], monate[-1][1])

        # Ein Mitglied kann mehrere Aktiv-Intervalle haben (z.B. mehrere
        # Abteilungs-Mitgliedschaften); Treffer-Monate werden vereinigt.
        aktiv_pro_mitglied: dict[int, dict] = {}
        for mitglied in self._betroffene_mitglieder(
                regel, stichtag_str, periode_start, periode_ende, mitglied_id):
            von = parse_datum(mitglied.get('aktiv_von'))
            bis = parse_datum(mitglied.get('aktiv_bis'))
            # Vereinsaustritt deckelt das Abteilungs-Intervall, auch wenn die
            # Mitgliedschaft selbst kein Ende-Datum hat.
            verein_bis = parse_datum(mitglied.get('verein_bis'))
            if verein_bis is not None and (bis is None or verein_bis < bis):
                bis = verein_bis
            eintrag = aktiv_pro_mitglied.setdefault(
                mitglied['id'], {'mitglied': mitglied, 'monate': set()})
            eintrag['monate'] |= aktive_monate_menge(monate, von, bis)

        # Funktions-/Ausnahme-Bedingungen wirken zeitraumgenau auf die Monate
        # (nicht mehr als Ja/Nein-Filter zum heutigen Tag): Einschluss schränkt die
        # berechneten Monate ein, Ausnahme zieht Monate ab.
        if regel.bedingung_funktionen or regel.ausnahme_funktionen:
            restriktion = self._funktions_restriktion(
                regel, set(aktiv_pro_mitglied), monate)
            for mid, eintrag in aktiv_pro_mitglied.items():
                r = restriktion.get(mid, {})
                if r.get('incl') is not None:
                    eintrag['monate'] &= r['incl']
                if r.get('excl'):
                    eintrag['monate'] -= r['excl']

        positionen: list[VorschauPosition] = []
        for mid, eintrag in aktiv_pro_mitglied.items():
            anzahl = len(eintrag['monate'])
            if anzahl == 0:
                continue  # im Abrechnungszeitraum nicht aktiv → keine Forderung
            mitglied = eintrag['mitglied']
            # betrag_pro_monat × volle Monate – immer ganze Cent, keine Rundung nötig.
            betrag = round(regel.betrag_pro_monat * anzahl, 2)
            bereits = self.db.sollstellungen.exists(mid, regel.id, zeitraum)
            positionen.append(VorschauPosition(
                mitglied_id=mid,
                mitglied_vorname=mitglied['vorname'],
                mitglied_nachname=mitglied['nachname'],
                mitglied_iban=mitglied.get('iban'),
                beitragsregel_id=regel.id,
                beitragsregel_name=regel.name,
                beitragsregel_abteilung_id=regel.abteilung_id,
                beitragsregel_abteilung_name=regel.abteilung_name,
                betrag=betrag,
                zahler_typ=regel.zahler_typ,
                zeitraum=zeitraum,
                faelligkeitsdatum=faellig,
                bereits_vorhanden=bereits,
                anzahl_monate=anzahl,
                monate_im_zeitraum=len(monate),
            ))
        return positionen

    def _attach_mitglied_abteilungen(self, positionen: list[VorschauPosition]) -> None:
        """Abteilungs-Mitgliedschaften der betroffenen Mitglieder nachladen, damit
        das Frontend nach "Mitglied gehört zu Abteilung X" filtern kann."""
        mitglied_ids = {p.mitglied_id for p in positionen}
        if not mitglied_ids:
            return
        mitgliedschaften = self._mitglied_abteilungen(mitglied_ids)
        for p in positionen:
            p.mitglied_abteilung_ids = mitgliedschaften.get(p.mitglied_id, [])

    def abrechnen(self, bis_stichtag_str: str, erstellt_von: str,
                  quartale_rueckschau: int) -> AbrechnungErgebnis:
        """
        Holt alle noch nicht abgerechneten Perioden bis zum Quartal des Stichtags
        nach (Rückschau = `quartale_rueckschau` Quartale, frühestens
        `RUECKGRIFF_MINIMUM`) und legt die fehlenden Sollstellungen an. Bereits
        vorhandene werden übersprungen (Duplikat-Schutz). Beiträge werden nie auf
        Kassen gebucht.
        """
        positionen = self.vorschau_aufholen(bis_stichtag_str, quartale_rueckschau)
        angelegt = 0
        uebersprungen = 0
        zeitraeume: set[str] = set()

        for pos in positionen:
            if pos.bereits_vorhanden:
                uebersprungen += 1
                continue

            s = BeitragSollstellung(
                mitglied_id=pos.mitglied_id,
                beitragsregel_id=pos.beitragsregel_id,
                zeitraum=pos.zeitraum,
                betrag_soll=pos.betrag,
                faelligkeitsdatum=pos.faelligkeitsdatum,
            )
            self.db.sollstellungen.create(s, created_by=erstellt_von)
            angelegt += 1
            zeitraeume.add(pos.zeitraum)

        sortiert = sorted(zeitraeume)
        if len(sortiert) > 1:
            label = f"{sortiert[0]} – {sortiert[-1]}"
        else:
            label = sortiert[0] if sortiert else ''
        return AbrechnungErgebnis(
            zeitraum=label,
            angelegt=angelegt,
            uebersprungen=uebersprungen,
            zeitraeume=sortiert,
        )

    def dashboard(self, stichtag_str: str) -> DashboardErgebnis:
        """
        Aggregiert die Projektion (vorschau) zum Stichtag: Summen und Zahler-Zahl
        je Abteilung (Vereinsbeitrag = ohne Abteilung) sowie Gesamtwerte.
        Die Beträge sind anteilig (siehe vorschau); Duplikate werden mitgezählt.
        """
        positionen = self.vorschau(stichtag_str)

        gruppen: dict[Optional[int], dict] = {}
        alle_zahler: set[int] = set()
        for p in positionen:
            g = gruppen.setdefault(p.beitragsregel_abteilung_id, {
                'abteilung_id': p.beitragsregel_abteilung_id,
                'abteilung_name': p.beitragsregel_abteilung_name or 'Vereinsbeitrag',
                'summe': 0.0,
                'zahler': set(),
                'anzahl_positionen': 0,
            })
            g['summe'] += p.betrag
            g['zahler'].add(p.mitglied_id)
            g['anzahl_positionen'] += 1
            alle_zahler.add(p.mitglied_id)

        gruppen_liste = [
            DashboardAbteilung(
                abteilung_id=g['abteilung_id'],
                abteilung_name=g['abteilung_name'],
                summe=round(g['summe'], 2),
                anzahl_zahler=len(g['zahler']),
                anzahl_positionen=g['anzahl_positionen'],
            )
            for g in gruppen.values()
        ]
        # Vereinsbeitrag (ohne Abteilung) zuerst, danach Abteilungen alphabetisch.
        gruppen_liste.sort(key=lambda x: (x.abteilung_id is not None,
                                          x.abteilung_name.lower()))

        return DashboardErgebnis(
            zeitraum=zeitraum_label('quartal', date.fromisoformat(stichtag_str)),
            stichtag=stichtag_str,
            gruppen=gruppen_liste,
            gesamt_summe=round(sum(p.betrag for p in positionen), 2),
            gesamt_zahler=len(alle_zahler),
            gesamt_positionen=len(positionen),
        )

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _mitglied_abteilungen(self, mitglied_ids: set[int]) -> dict[int, list[int]]:
        """Mappt mitglied_id → Liste aktueller Abteilungs-IDs (aktive Mitgliedschaften)."""
        placeholders = ','.join(['%s'] * len(mitglied_ids))
        sql = f"""
            SELECT mitglied_id, abteilung_id
            FROM mitglied_abteilung
            WHERE deleted_at IS NULL
              AND (bis IS NULL OR bis::date >= CURRENT_DATE)
              AND mitglied_id IN ({placeholders})
        """
        result: dict[int, list[int]] = {}
        with self.db.conn.cursor() as cur:
            cur.execute(sql, list(mitglied_ids))
            for row in cur.fetchall():
                result.setdefault(row['mitglied_id'], []).append(row['abteilung_id'])
        return result

    def _funktion_intervalle(self, mitglied_ids: set[int], funktionen: set[str]) -> list[dict]:
        """Funktions-Intervalle (`von`/`bis`) der Mitglieder für die genannten Funktionen."""
        if not mitglied_ids or not funktionen:
            return []
        mid_ph = ','.join(['%s'] * len(mitglied_ids))
        fn_ph = ','.join(['%s'] * len(funktionen))
        sql = (f"SELECT mitglied_id, funktion, von, bis FROM mitglied_funktion "
               f"WHERE deleted_at IS NULL AND mitglied_id IN ({mid_ph}) "
               f"AND funktion IN ({fn_ph})")
        with self.db.conn.cursor() as cur:
            cur.execute(sql, list(mitglied_ids) + list(funktionen))
            return [dict(r) for r in cur.fetchall()]

    def _abteilung_intervalle(self, mitglied_ids: set[int], abteilung_ids: set[int]) -> list[dict]:
        """Abteilungs-Mitgliedschafts-Intervalle für die (in Funktions-Paaren) genannten Abteilungen."""
        if not mitglied_ids or not abteilung_ids:
            return []
        mid_ph = ','.join(['%s'] * len(mitglied_ids))
        abt_ph = ','.join(['%s'] * len(abteilung_ids))
        sql = (f"SELECT mitglied_id, abteilung_id, von, bis FROM mitglied_abteilung "
               f"WHERE deleted_at IS NULL AND mitglied_id IN ({mid_ph}) "
               f"AND abteilung_id IN ({abt_ph})")
        with self.db.conn.cursor() as cur:
            cur.execute(sql, list(mitglied_ids) + list(abteilung_ids))
            return [dict(r) for r in cur.fetchall()]

    def _funktions_restriktion(self, regel: Beitragsregel, mitglied_ids: set[int],
                               monate: list[tuple[int, int]]) -> dict[int, dict]:
        """Lädt die nötigen Funktions-/Abteilungs-Intervalle und delegiert an die reine
        Berechnung `funktions_monats_restriktion` (Einschluss-/Ausnahme-Monate je Mitglied)."""
        funktionen = set(regel.bedingung_funktionen or []) | set(regel.ausnahme_funktionen or [])
        abteilung_ids = {a for a in
                         (list(regel.bedingung_abteilung_ids or []) + list(regel.ausnahme_abteilung_ids or []))
                         if a is not None}
        funktion_rows = self._funktion_intervalle(mitglied_ids, funktionen)
        abteilung_rows = self._abteilung_intervalle(mitglied_ids, abteilung_ids)
        return funktions_monats_restriktion(regel, mitglied_ids, monate, funktion_rows, abteilung_rows)

    def _betroffene_mitglieder(self, regel: Beitragsregel, stichtag_str: str,
                               periode_start: date, periode_ende: date,
                               mitglied_id: Optional[int] = None) -> list[dict]:
        """
        Ermittelt alle Mitglieder auf die eine Regel zutrifft, inkl. ihres Aktiv-
        Intervalls (`aktiv_von`/`aktiv_bis`) für die anteilige Monatsberechnung.
        Mit ``mitglied_id`` auf dieses eine Mitglied beschränkt (Einzel-Vorschau).

        - Vereinsbeitrag (abteilung_id IS NULL): Vereinsmitglieder; Intervall = Eintritt/Austritt
        - Abteilungsbeitrag: Mitglieder der Abteilung; Intervall = von/bis der Mitgliedschaft
        - bedingung_alter_min/max: Alter (am Stichtag) muss im Bereich liegen; Mitglieder
          ohne gültiges Geburtsdatum werden bei gesetzter Altersbedingung ausgeschlossen

        Funktions-Einschlüsse/-Ausnahmen werden hier NICHT mehr gefiltert: sie wirken
        zeitraumgenau auf die abgerechneten Monate und rechnet der Service über
        `funktions_monats_restriktion` (Einschluss = Schnittmenge, Ausnahme = Abzug).
        Diese Methode liefert daher alle Mitgliedschaften der Regel; die maßgebliche
        Monatsüberlappung bestimmt der Service.

        Der Datums-Vorfilter grenzt nur grob auf den Zeitraum ein (string-Vergleich,
        regex-geschützt gegen ungültige Werte).
        """
        joins: list[str] = []
        # Gastspieler (art='gastspieler') sind keine Vereinsmitglieder und werden
        # nie beitragspflichtig – auch nicht über Abteilungsregeln, obwohl sie
        # eine mitglied_abteilung-Zuordnung haben (Gast-Kreis der Termine, #95).
        where: list[str] = ["m.deleted_at IS NULL", "m.art = 'mitglied'"]
        params: list = []

        # Einzel-Vorschau: nur dieses Mitglied (Klausel + Param zusammen, damit die
        # Param-Reihenfolge zu den folgenden %s passt).
        if mitglied_id is not None:
            where.append("m.id = %s")
            params.append(mitglied_id)

        # Datums-Vorfilter: NULL/leer/ungültig immer einschließen (die maßgebliche
        # Monatsüberlappung rechnet der Service); nur gültige Daten ausserhalb des
        # Zeitraums vorab ausschließen. Wichtig: ohne das explizite IS NULL würde
        # NOT(... AND ...) bei NULL zu NULL → die Zeile fiele aus der WHERE-Klausel.
        if regel.abteilung_id is None:
            aktiv_cols = "m.eintrittsdatum AS aktiv_von, m.austrittsdatum AS aktiv_bis"
            where += [
                "(m.eintrittsdatum IS NULL OR m.eintrittsdatum !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' OR left(m.eintrittsdatum,10) <= %s)",
                "(m.austrittsdatum IS NULL OR m.austrittsdatum !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' OR left(m.austrittsdatum,10) >= %s)",
            ]
            params.extend([periode_ende.isoformat(), periode_start.isoformat()])
        else:
            # Vereinsaustritt beendet implizit auch die Abteilungsmitgliedschaft:
            # austrittsdatum wird mitgeladen und im Service als Obergrenze des
            # Aktiv-Intervalls angewendet (min(ma.bis, austrittsdatum)).
            aktiv_cols = ("ma.von AS aktiv_von, ma.bis AS aktiv_bis, "
                          "m.austrittsdatum AS verein_bis")
            joins.append("JOIN mitglied_abteilung ma ON ma.mitglied_id = m.id")
            where += [
                "ma.abteilung_id = %s", "ma.deleted_at IS NULL",
                "(ma.von IS NULL OR ma.von !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' OR left(ma.von,10) <= %s)",
                "(ma.bis IS NULL OR ma.bis !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' OR left(ma.bis,10) >= %s)",
                "(m.austrittsdatum IS NULL OR m.austrittsdatum !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' OR left(m.austrittsdatum,10) >= %s)",
            ]
            params.extend([regel.abteilung_id, periode_ende.isoformat(),
                           periode_start.isoformat(), periode_start.isoformat()])

            status_filter = regel.bedingung_status_liste
            if status_filter:
                placeholders = ','.join(['%s'] * len(status_filter))
                where.append(f"ma.status IN ({placeholders})")
                params.extend(status_filter)

        # Funktions-Einschlüsse/-Ausnahmen werden bewusst NICHT hier gefiltert (siehe
        # Docstring): der Service wertet sie zeitraumgenau über die Monate aus.

        if regel.bedingung_alter_min is not None or regel.bedingung_alter_max is not None:
            # Alter am Stichtag aus geburtsdatum; ungültige/fehlende Daten -> ausgeschlossen
            age_expr = ("(CASE WHEN m.geburtsdatum ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
                        "THEN date_part('year', age(%s::date, left(m.geburtsdatum,10)::date)) END)")
            if regel.bedingung_alter_min is not None:
                where.append(f"{age_expr} >= %s")
                params.extend([stichtag_str, regel.bedingung_alter_min])
            if regel.bedingung_alter_max is not None:
                where.append(f"{age_expr} <= %s")
                params.extend([stichtag_str, regel.bedingung_alter_max])

        sql = f"""
            SELECT DISTINCT m.id, m.vorname, m.nachname, m.iban, m.kontoinhaber,
                   {aktiv_cols}
            FROM mitglied m
            {' '.join(joins)}
            WHERE {' AND '.join(where)}
            ORDER BY m.nachname, m.vorname
        """
        with self.db.conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
