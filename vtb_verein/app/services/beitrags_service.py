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
    zeitraum: str
    angelegt: int
    uebersprungen: int                # Duplikate


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


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BeitragsService:

    def __init__(self, db):
        self.db = db

    def vorschau(self, stichtag_str: str) -> list[VorschauPosition]:
        """
        Berechnet welche Sollstellungen für den Stichtag erzeugt werden würden.
        Schreibt nichts in die DB.
        """
        stichtag = date.fromisoformat(stichtag_str)
        regeln = self.db.beitragsregeln.list_aktive(stichtag_str)
        positionen = []

        for regel in regeln:
            zeitraum = zeitraum_label(regel.einzug_turnus, stichtag)
            faellig = faelligkeitsdatum(regel.einzug_turnus, stichtag)
            monate = zeitraum_monate(regel.einzug_turnus, stichtag)
            periode_start = date(monate[0][0], monate[0][1], 1)
            periode_ende = _letzter_tag(monate[-1][0], monate[-1][1])

            # Ein Mitglied kann mehrere Aktiv-Intervalle haben (z.B. mehrere
            # Abteilungs-Mitgliedschaften); Treffer-Monate werden vereinigt.
            aktiv_pro_mitglied: dict[int, dict] = {}
            for mitglied in self._betroffene_mitglieder(
                    regel, stichtag_str, periode_start, periode_ende):
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

        # Abteilungs-Mitgliedschaften der betroffenen Mitglieder nachladen, damit
        # das Frontend nach "Mitglied gehört zu Abteilung X" filtern kann.
        mitglied_ids = {p.mitglied_id for p in positionen}
        if mitglied_ids:
            mitgliedschaften = self._mitglied_abteilungen(mitglied_ids)
            for p in positionen:
                p.mitglied_abteilung_ids = mitgliedschaften.get(p.mitglied_id, [])

        return positionen

    def abrechnen(self, stichtag_str: str, erstellt_von: str) -> AbrechnungErgebnis:
        """
        Legt Sollstellungen für den Stichtag an. Überspringt bereits vorhandene
        Einträge (Duplikat-Schutz). Beiträge werden nie auf Kassen gebucht.
        """
        positionen = self.vorschau(stichtag_str)
        angelegt = 0
        uebersprungen = 0

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

        return AbrechnungErgebnis(
            zeitraum=zeitraum_label(
                self.db.beitragsregeln.list_aktive(stichtag_str)[0].einzug_turnus
                if positionen else 'quartal',
                date.fromisoformat(stichtag_str),
            ),
            angelegt=angelegt,
            uebersprungen=uebersprungen,
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

    def _betroffene_mitglieder(self, regel: Beitragsregel, stichtag_str: str,
                               periode_start: date, periode_ende: date) -> list[dict]:
        """
        Ermittelt alle Mitglieder auf die eine Regel zutrifft, inkl. ihres Aktiv-
        Intervalls (`aktiv_von`/`aktiv_bis`) für die anteilige Monatsberechnung.

        - Vereinsbeitrag (abteilung_id IS NULL): Vereinsmitglieder; Intervall = Eintritt/Austritt
        - Abteilungsbeitrag: Mitglieder der Abteilung; Intervall = von/bis der Mitgliedschaft
        - ausnahme_funktionen: Mitglieder mit (irgend)einer dieser Funktionen werden ausgeschlossen
        - bedingung_funktionen: nur Mitglieder mit (mind.) einer dieser Funktionen werden eingeschlossen
        - bedingung_alter_min/max: Alter (am Stichtag) muss im Bereich liegen; Mitglieder
          ohne gültiges Geburtsdatum werden bei gesetzter Altersbedingung ausgeschlossen

        Der Datums-Vorfilter grenzt nur grob auf den Zeitraum ein (string-Vergleich,
        regex-geschützt gegen ungültige Werte); die maßgebliche Monatsüberlappung
        bestimmt der Service über `aktive_monate_menge`.
        """
        joins: list[str] = []
        where: list[str] = ["m.deleted_at IS NULL"]
        params: list = []

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

        if regel.bedingung_funktionen:
            # Mitglied muss mindestens eine der gewählten Funktionen haben (ODER).
            # DISTINCT im finalen SELECT entdoppelt Mehrfach-Treffer aus dem JOIN.
            joins.append("JOIN mitglied_funktion mf_incl ON mf_incl.mitglied_id = m.id")
            where += ["mf_incl.funktion = ANY(%s)", "mf_incl.deleted_at IS NULL",
                      "(mf_incl.bis IS NULL OR mf_incl.bis::date >= CURRENT_DATE)"]
            params.append(regel.bedingung_funktionen)
            # Abteilungs-Zusatz an der Funktions-Bedingung = MITGLIEDSCHAFT in dieser
            # Abteilung (nicht: Funktion auf die Abteilung getaggt). Die Regel greift nur,
            # wenn das Mitglied die Funktion hat UND in der Abteilung ist.
            if regel.bedingung_funktion_abteilung_id is not None:
                where.append(
                    "EXISTS (SELECT 1 FROM mitglied_abteilung ma_bf "
                    "WHERE ma_bf.mitglied_id = m.id AND ma_bf.abteilung_id = %s "
                    "AND ma_bf.deleted_at IS NULL "
                    "AND (ma_bf.bis IS NULL OR ma_bf.bis::date >= CURRENT_DATE))"
                )
                params.append(regel.bedingung_funktion_abteilung_id)

        if regel.ausnahme_funktionen:
            # Ausschluss greift, wenn das Mitglied (irgend)eine der Funktionen hat; mit
            # Abteilungs-Zusatz zusätzlich nur, wenn es auch Mitglied dieser Abteilung ist.
            cond = ("EXISTS (SELECT 1 FROM mitglied_funktion mf_excl "
                    "WHERE mf_excl.mitglied_id = m.id AND mf_excl.funktion = ANY(%s) "
                    "AND mf_excl.deleted_at IS NULL "
                    "AND (mf_excl.bis IS NULL OR mf_excl.bis::date >= CURRENT_DATE))")
            params.append(regel.ausnahme_funktionen)
            if regel.ausnahme_funktion_abteilung_id is not None:
                cond += (" AND EXISTS (SELECT 1 FROM mitglied_abteilung ma_excl "
                         "WHERE ma_excl.mitglied_id = m.id AND ma_excl.abteilung_id = %s "
                         "AND ma_excl.deleted_at IS NULL "
                         "AND (ma_excl.bis IS NULL OR ma_excl.bis::date >= CURRENT_DATE))")
                params.append(regel.ausnahme_funktion_abteilung_id)
            where.append(f"NOT ({cond})")

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
