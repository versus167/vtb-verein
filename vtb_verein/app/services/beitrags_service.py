"""
BeitragsService – Vorschau-Berechnung und Sollstellungs-Generierung.

Ablauf:
1. vorschau(zeitraum) → Liste der zu erzeugenden Sollstellungen (ohne DB-Schreibzugriff)
2. abrechnen(zeitraum, erstellt_von) → Sollstellungen + Kassenbuchungen anlegen
"""
from dataclasses import dataclass
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
    betrag: float
    zahler_typ: str                   # mitglied | abteilung
    zahler_kasse_id: Optional[int]
    zeitraum: str
    faelligkeitsdatum: str
    bereits_vorhanden: bool           # True = Duplikat, wird übersprungen


@dataclass
class AbrechnungErgebnis:
    zeitraum: str
    angelegt: int
    uebersprungen: int                # Duplikate
    umbuchungen: int                  # erzeugte Kassenbuchungen


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
        naechster = date(stichtag.year + (1 if letzter_monat > 12 else 0),
                         letzter_monat % 12 + 1, 1)
        return (naechster - timedelta(days=1)).isoformat()
    if turnus == 'halbjahr':
        letzter_monat = 6 if stichtag.month <= 6 else 12
        naechster = date(stichtag.year + (1 if letzter_monat == 12 else 0),
                         letzter_monat % 12 + 1, 1)
        return (naechster - timedelta(days=1)).isoformat()
    # jahr
    return date(stichtag.year, 12, 31).isoformat()


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
            betrag = regel.betrag_pro_einzug

            for mitglied in self._betroffene_mitglieder(regel, stichtag_str):
                bereits = self.db.sollstellungen.exists(
                    mitglied['id'], regel.id, zeitraum
                )
                positionen.append(VorschauPosition(
                    mitglied_id=mitglied['id'],
                    mitglied_vorname=mitglied['vorname'],
                    mitglied_nachname=mitglied['nachname'],
                    mitglied_iban=mitglied.get('iban'),
                    beitragsregel_id=regel.id,
                    beitragsregel_name=regel.name,
                    betrag=betrag,
                    zahler_typ=regel.zahler_typ,
                    zahler_kasse_id=regel.zahler_kasse_id,
                    zeitraum=zeitraum,
                    faelligkeitsdatum=faellig,
                    bereits_vorhanden=bereits,
                ))

        return positionen

    def abrechnen(self, stichtag_str: str, erstellt_von: str) -> AbrechnungErgebnis:
        """
        Legt Sollstellungen und ggf. Kassenbuchungen für den Stichtag an.
        Überspringt bereits vorhandene Einträge (Duplikat-Schutz).
        """
        positionen = self.vorschau(stichtag_str)
        angelegt = 0
        uebersprungen = 0
        umbuchungen = 0

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
            sollstellung = self.db.sollstellungen.create(s, created_by=erstellt_von)
            angelegt += 1

            # Bei Abteilungs-Zahler: Kassenbuchung als Ausgabe anlegen
            if pos.zahler_typ == 'abteilung' and pos.zahler_kasse_id:
                buchung_id = self._erstelle_umbuchung(
                    kasse_id=pos.zahler_kasse_id,
                    sollstellung=sollstellung,
                    erstellt_von=erstellt_von,
                )
                self.db.sollstellungen.set_kassenbuchung(
                    sollstellung.id, buchung_id, updated_by=erstellt_von
                )
                umbuchungen += 1

        return AbrechnungErgebnis(
            zeitraum=zeitraum_label(
                self.db.beitragsregeln.list_aktive(stichtag_str)[0].einzug_turnus
                if positionen else 'quartal',
                date.fromisoformat(stichtag_str),
            ),
            angelegt=angelegt,
            uebersprungen=uebersprungen,
            umbuchungen=umbuchungen,
        )

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _betroffene_mitglieder(self, regel: Beitragsregel, stichtag_str: str) -> list[dict]:
        """
        Ermittelt alle Mitglieder auf die eine Regel zutrifft.

        - Vereinsbeitrag (abteilung_id IS NULL): alle aktiven Vereinsmitglieder
        - Abteilungsbeitrag: Mitglieder der Abteilung, gefiltert nach Status/Funktion
        - ausnahme_funktion: Mitglieder mit dieser Funktion werden immer ausgeschlossen
        - bedingung_funktion: nur Mitglieder mit dieser Funktion werden eingeschlossen
        - bedingung_alter_min/max: Alter (am Stichtag) muss im Bereich liegen; Mitglieder
          ohne gültiges Geburtsdatum werden bei gesetzter Altersbedingung ausgeschlossen
        """
        joins: list[str] = []
        where: list[str] = ["m.deleted_at IS NULL"]
        params: list = []

        if regel.abteilung_id is None:
            where.append("(m.austrittsdatum IS NULL OR m.austrittsdatum = '')")
        else:
            joins.append("JOIN mitglied_abteilung ma ON ma.mitglied_id = m.id")
            where += ["ma.abteilung_id = %s", "ma.deleted_at IS NULL",
                      "(ma.bis IS NULL OR ma.bis::date >= CURRENT_DATE)"]
            params.append(regel.abteilung_id)

            status_filter = regel.bedingung_status_liste
            if status_filter:
                placeholders = ','.join(['%s'] * len(status_filter))
                where.append(f"ma.status IN ({placeholders})")
                params.extend(status_filter)

        if regel.bedingung_funktion:
            joins.append("JOIN mitglied_funktion mf_incl ON mf_incl.mitglied_id = m.id")
            where += ["mf_incl.funktion = %s", "mf_incl.deleted_at IS NULL",
                      "(mf_incl.bis IS NULL OR mf_incl.bis::date >= CURRENT_DATE)"]
            params.append(regel.bedingung_funktion)
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

        if regel.ausnahme_funktion:
            # Ausschluss greift, wenn das Mitglied die Funktion hat; mit Abteilungs-Zusatz
            # zusätzlich nur, wenn es auch Mitglied dieser Abteilung ist.
            cond = ("EXISTS (SELECT 1 FROM mitglied_funktion mf_excl "
                    "WHERE mf_excl.mitglied_id = m.id AND mf_excl.funktion = %s "
                    "AND mf_excl.deleted_at IS NULL "
                    "AND (mf_excl.bis IS NULL OR mf_excl.bis::date >= CURRENT_DATE))")
            params.append(regel.ausnahme_funktion)
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
            SELECT DISTINCT m.id, m.vorname, m.nachname, m.iban, m.kontoinhaber
            FROM mitglied m
            {' '.join(joins)}
            WHERE {' AND '.join(where)}
            ORDER BY m.nachname, m.vorname
        """
        with self.db.conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def _erstelle_umbuchung(
        self, kasse_id: int, sollstellung: BeitragSollstellung, erstellt_von: str
    ) -> int:
        """Legt eine Kassenbuchung (Ausgabe) in der Abteilungs-Kasse an."""
        from app.models.kasse import Kassenbuchung
        name = f"{sollstellung.mitglied_vorname or ''} {sollstellung.mitglied_nachname or ''}".strip()
        kb = Kassenbuchung(
            kasse_id=kasse_id,
            buchungsdatum=date.today().isoformat(),
            buchungstext=f"Vereinsbeitrag {name} – {sollstellung.zeitraum}",
            kategorie="Beiträge",
            einnahme_cent=0,
            ausgabe_cent=round(sollstellung.betrag_soll * 100),
            notiz=f"Automatisch erzeugte Umbuchung für Sollstellung #{sollstellung.id}",
        )
        buchung = self.db.kassenbuch.create_buchung(kb, created_by=erstellt_von)
        return buchung.id
