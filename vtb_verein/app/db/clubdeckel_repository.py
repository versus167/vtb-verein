"""Repository für den Teamtresor/Clubdeckel (#98) inkl. Kader-Rechteableitung.

Die Rechte sind komplett teamintern und kommen NICHT aus globalen Permissions:
Wer am Stichtag aktiv (von/bis) im Kader der Mannschaft steht, nutzt deren
Teamtresor ('mitglied'); die Kader-Rollen betreuer/uebungsleiter verwalten ihn
('verwalten': einschalten, Stammdaten, Warte ernennen). Die Zwischenstufe „Wart"
(Katalog, Buchungen) liegt in clubdeckel_berechtigung und wird in der API-Schicht
mit der Kader-Stufe kombiniert. Admin-Bypass entscheidet die API.

Stammdaten des Deckels: Monatsbeitrag (beitrag + beitrag_ab 'YYYY-MM'),
Zahlungsempfänger (Mitglied) und dessen Zahlwege (IBAN/WERO/PayPal).

Kader-CTE bewusst aus termin_repository übernommen statt importiert
(Domain-Isolation; Aktiv-Semantik identisch zu mitglied_mannschaft).
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.clubdeckel import Clubdeckel
from app.db.base_repository import BaseRepository

# Kader-Rollen, die den Teamtresor ihrer Mannschaft verwalten dürfen.
VERWALTEN_ROLLEN = ('betreuer', 'uebungsleiter')

# Gemeinsame CTE: aktive Kader-Zugehörigkeiten des Users am Stichtag.
# Erwartet die benannten Parameter %(uid)s (user_id) und %(tag)s (ISO-Datum).
_KADER_CTE = """
    WITH kader AS (
        SELECT mm.mannschaft_id, mm.rolle
        FROM mitglied m
        JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id AND mm.deleted_at IS NULL
            AND mm.von <= %(tag)s
            AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
        WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
    )
"""

_COLS = ("id, mannschaft_id, name, aktiv, beitrag, beitrag_ab, "
         "zahlungsempfaenger_mitglied_id, zahlweg_iban, zahlweg_wero, zahlweg_paypal, "
         "version, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")
_C_COLS = ", ".join("c." + s.strip() for s in _COLS.split(","))


def _map(row) -> Clubdeckel:
    return Clubdeckel(**dict(row))


class ClubdeckelRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, deckel_id: int) -> Optional[Clubdeckel]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_C_COLS},
                       ma.name AS mannschaft_name,
                       ze.vorname || ' ' || ze.nachname AS zahlungsempfaenger_name
                FROM clubdeckel c
                JOIN mannschaft ma ON ma.id = c.mannschaft_id
                LEFT JOIN mitglied ze ON ze.id = c.zahlungsempfaenger_mitglied_id
                WHERE c.id = %s AND c.deleted_at IS NULL
                """,
                (deckel_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_by_mannschaft(self, mannschaft_id: int) -> Optional[Clubdeckel]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM clubdeckel "
                "WHERE mannschaft_id = %s AND deleted_at IS NULL",
                (mannschaft_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_aktive_mit_beitrag(self) -> list[Clubdeckel]:
        """Aktive Teamtresore mit konfiguriertem Monatsbeitrag — Grundlage für
        den Sammellauf (Sidecar), der den fälligen Beitrag am Monatsersten
        nachbucht. Gleiche Bedingung wie der Lazy-Lauf in der API."""
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM clubdeckel "
                "WHERE deleted_at IS NULL AND aktiv = 1 "
                "AND beitrag IS NOT NULL AND beitrag > 0 AND beitrag_ab IS NOT NULL "
                "ORDER BY id"
            )
            return [_map(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------ CRUD
    def create(self, mannschaft_id: int, name: str, created_by: str) -> Clubdeckel:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel (mannschaft_id, name, created_by, updated_by) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (mannschaft_id, name, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, deckel_id: int, name: str, aktiv: int,
               beitrag: Optional[Decimal],
               zahlungsempfaenger_mitglied_id: Optional[int],
               zahlweg_iban: Optional[str], zahlweg_wero: Optional[str],
               zahlweg_paypal: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        """Stammdaten-Update. beitrag_ab wird automatisch geführt: Wird der
        Monatsbeitrag neu gesetzt, startet er im laufenden Monat; wird er
        entfernt, endet der automatische Beitragslauf (beitrag_ab = NULL)."""
        alt = self.get(deckel_id)
        if alt is None:
            return False
        if beitrag and beitrag > 0:
            beitrag_ab = alt.beitrag_ab or date.today().strftime('%Y-%m')
        else:
            beitrag, beitrag_ab = None, None
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel SET name=%s, aktiv=%s, beitrag=%s, beitrag_ab=%s, "
                "zahlungsempfaenger_mitglied_id=%s, zahlweg_iban=%s, zahlweg_wero=%s, "
                "zahlweg_paypal=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (name, aktiv, beitrag, beitrag_ab, zahlungsempfaenger_mitglied_id,
                 zahlweg_iban, zahlweg_wero, zahlweg_paypal,
                 updated_by, deckel_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, deckel_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, deckel_id),
            )
            return cur.rowcount > 0

    # ----------------------------------------------------------------- ACL
    def get_access_for_user(self, user_id: int, mannschaft_id: int,
                            stichtag: Optional[str] = None) -> Optional[str]:
        """Kader-Stufe des Users für die Mannschaft: None | 'mitglied' | 'verwalten'.

        Mehrfach-Zugehörigkeit (z. B. spieler + uebungsleiter) ergibt die höchste
        Stufe. Die Wart-Stufe (ACL) und der Admin-Bypass liegen in der API-Schicht.
        """
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _KADER_CTE + """
                SELECT bool_or(rolle = ANY(%(vroll)s)) AS darf_verwalten
                FROM kader WHERE mannschaft_id = %(mid)s
                """,
                {"uid": user_id, "tag": tag, "mid": mannschaft_id,
                 "vroll": list(VERWALTEN_ROLLEN)},
            )
            row = cur.fetchone()
            if row is None or row['darf_verwalten'] is None:
                return None
            return 'verwalten' if row['darf_verwalten'] else 'mitglied'

    def get_kader_mitglied_id(self, user_id: int, mannschaft_id: int,
                              stichtag: Optional[str] = None) -> Optional[int]:
        """mitglied_id des Users im aktiven Kader der Mannschaft — für die eigene
        Konsum-Buchung. None, wenn der User dort kein aktives Kader-Mitglied ist."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT m.id
                FROM mitglied m
                JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL AND mm.mannschaft_id = %(mid)s
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
                LIMIT 1
                """,
                {"uid": user_id, "mid": mannschaft_id, "tag": tag},
            )
            row = cur.fetchone()
            return row['id'] if row else None

    def is_mitglied_in_kader(self, mitglied_id: int, mannschaft_id: int,
                             stichtag: Optional[str] = None) -> bool:
        """Ob ein Mitglied am Stichtag aktiv im Kader steht (Ziel-Prüfung für
        Zahlung/Einkauf/Wart-Ernennung/Verkäufer durch Verwalter/Wart)."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM mitglied_mannschaft
                WHERE mitglied_id = %(mid)s AND mannschaft_id = %(man)s
                  AND deleted_at IS NULL
                  AND von <= %(tag)s AND (bis IS NULL OR bis >= %(tag)s)
                LIMIT 1
                """,
                {"mid": mitglied_id, "man": mannschaft_id, "tag": tag},
            )
            return cur.fetchone() is not None

    # ----------------------------------------------------------- Team-Listen
    def list_teams_for_user(self, user_id: int,
                            stichtag: Optional[str] = None) -> list[dict]:
        """„Meine Teamtresore": alle Mannschaften, in deren Kader der User am
        Stichtag aktiv ist — je Team die Kader-Stufe und der Deckel (oder None).
        Die API filtert daraus Teams ohne Deckel für Nicht-Verwalter heraus."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _KADER_CTE + f"""
                , zugriff AS (
                    SELECT mannschaft_id, bool_or(rolle = ANY(%(vroll)s)) AS darf_verwalten
                    FROM kader GROUP BY mannschaft_id
                )
                SELECT ma.id AS team_id, ma.name AS team_name,
                       z.darf_verwalten,
                       {_C_COLS}
                FROM zugriff z
                JOIN mannschaft ma ON ma.id = z.mannschaft_id AND ma.deleted_at IS NULL
                LEFT JOIN clubdeckel c ON c.mannschaft_id = ma.id AND c.deleted_at IS NULL
                ORDER BY ma.name, ma.id
                """,
                {"uid": user_id, "tag": tag, "vroll": list(VERWALTEN_ROLLEN)},
            )
            return [self._team_row(r) for r in cur.fetchall()]

    def list_all_teams(self) -> list[dict]:
        """Admin-Pfad: alle Mannschaften mit Deckel-oder-None, Stufe 'verwalten'."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT ma.id AS team_id, ma.name AS team_name,
                       TRUE AS darf_verwalten,
                       {_C_COLS}
                FROM mannschaft ma
                LEFT JOIN clubdeckel c ON c.mannschaft_id = ma.id AND c.deleted_at IS NULL
                WHERE ma.deleted_at IS NULL
                ORDER BY ma.name, ma.id
                """,
            )
            return [self._team_row(r) for r in cur.fetchall()]

    @staticmethod
    def _team_row(r) -> dict:
        # ma.id/ma.name sind als team_id/team_name aliasiert, damit die
        # gleichnamigen Deckel-Spalten (c.name, c.mannschaft_id) sie im
        # dict-Row nicht überschreiben.
        deckel = None
        if r['id'] is not None:
            deckel = {"id": r['id'], "name": r['name'], "aktiv": r['aktiv'],
                      "version": r['version']}
        return {
            "mannschaft_id": r['team_id'],
            "mannschaft_name": r['team_name'],
            "zugriff": 'verwalten' if r['darf_verwalten'] else 'mitglied',
            "deckel": deckel,
        }
