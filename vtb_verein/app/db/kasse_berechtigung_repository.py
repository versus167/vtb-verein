"""
KasseBerechtigungRepository

Verwaltet kassenspezifische Berechtigungen (wer darf lesen/schreiben/exportieren).
Admins (users.manage) umgehen diese Tabelle und haben immer vollen Zugriff.
"""
from __future__ import annotations

from psycopg import Connection as PgConnection
from dataclasses import dataclass
from typing import Optional


@dataclass
class KasseBerechtigung:
    """Repräsentiert einen Berechtigungseintrag für einen User auf eine Kasse."""
    id: int
    kasse_id: int
    user_id: int
    darf_lesen: bool
    darf_schreiben: bool
    darf_exportieren: bool
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


class KasseBerechtigungRepository:
    """Repository für kassenspezifische Berechtigungen."""

    def __init__(self, conn: PgConnection):
        self._conn = conn

    # ------------------------------------------------------------------
    # Abfragen
    # ------------------------------------------------------------------

    def get_berechtigungen_fuer_kasse(self, kasse_id: int) -> list[KasseBerechtigung]:
        """Alle aktiven Berechtigungseinträge für eine Kasse."""
        cur = self._conn.execute(
            """
            SELECT * FROM kasse_berechtigungen
            WHERE kasse_id = %s AND deleted_at IS NULL
            ORDER BY user_id
            """,
            (kasse_id,),
        )
        return [self._row_to_obj(row) for row in cur.fetchall()]

    def get_berechtigung(self, kasse_id: int, user_id: int) -> Optional[KasseBerechtigung]:
        """Aktiver Berechtigungseintrag für einen konkreten User+Kasse-Kombination."""
        cur = self._conn.execute(
            """
            SELECT * FROM kasse_berechtigungen
            WHERE kasse_id = %s AND user_id = %s AND deleted_at IS NULL
            """,
            (kasse_id, user_id),
        )
        row = cur.fetchone()
        return self._row_to_obj(row) if row else None

    def get_kassen_ids_fuer_user(self, user_id: int) -> list[int]:
        """IDs aller Kassen, auf die der User mind. Lesezugriff hat."""
        cur = self._conn.execute(
            """
            SELECT kasse_id FROM kasse_berechtigungen
            WHERE user_id = %s AND darf_lesen = 1 AND deleted_at IS NULL
            """,
            (user_id,),
        )
        return [row['kasse_id'] for row in cur.fetchall()]

    def hat_lesezugriff(self, kasse_id: int, user_id: int) -> bool:
        b = self.get_berechtigung(kasse_id, user_id)
        return b is not None and b.darf_lesen

    def hat_schreibzugriff(self, kasse_id: int, user_id: int) -> bool:
        b = self.get_berechtigung(kasse_id, user_id)
        return b is not None and b.darf_schreiben

    def hat_exportrecht(self, kasse_id: int, user_id: int) -> bool:
        b = self.get_berechtigung(kasse_id, user_id)
        return b is not None and b.darf_exportieren

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def set_berechtigung(
        self,
        kasse_id: int,
        user_id: int,
        darf_lesen: bool,
        darf_schreiben: bool,
        darf_exportieren: bool,
        actor: str,
    ) -> KasseBerechtigung:
        """
        Legt einen Berechtigungseintrag an oder aktualisiert einen bestehenden.
        Reaktiviert ggf. einen soft-gelöschten Eintrag.
        """
        cur = self._conn.execute(
            """
            SELECT * FROM kasse_berechtigungen
            WHERE kasse_id = %s AND user_id = %s
            """,
            (kasse_id, user_id),
        )
        existing = cur.fetchone()

        if existing is None:
            self._conn.execute(
                """
                INSERT INTO kasse_berechtigungen
                    (kasse_id, user_id, darf_lesen, darf_schreiben, darf_exportieren,
                     created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (kasse_id, user_id,
                 int(darf_lesen), int(darf_schreiben), int(darf_exportieren),
                 actor, actor),
            )
        else:
            self._conn.execute(
                """
                UPDATE kasse_berechtigungen
                SET darf_lesen      = %s,
                    darf_schreiben  = %s,
                    darf_exportieren = %s,
                    deleted_at      = NULL,
                    deleted_by      = NULL,
                    updated_at      = CURRENT_TIMESTAMP,
                    updated_by      = %s,
                    version         = version + 1
                WHERE kasse_id = %s AND user_id = %s
                """,
                (int(darf_lesen), int(darf_schreiben), int(darf_exportieren),
                 actor, kasse_id, user_id),
            )
        self._conn.commit()
        return self.get_berechtigung(kasse_id, user_id)

    def revoke_berechtigung(self, kasse_id: int, user_id: int, actor: str) -> bool:
        """Entzieht alle Kassenrechte für einen User (Soft-Delete)."""
        result = self._conn.execute(
            """
            UPDATE kasse_berechtigungen
            SET deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s,
                version    = version + 1
            WHERE kasse_id = %s AND user_id = %s AND deleted_at IS NULL
            """,
            (actor, actor, kasse_id, user_id),
        )
        self._conn.commit()
        return result.rowcount > 0

    def revoke_alle_berechtigungen_fuer_user(self, user_id: int, actor: str) -> int:
        """Entzieht einem User alle Kassenrechte (z.B. beim User-Löschen)."""
        result = self._conn.execute(
            """
            UPDATE kasse_berechtigungen
            SET deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s,
                version    = version + 1
            WHERE user_id = %s AND deleted_at IS NULL
            """,
            (actor, actor, user_id),
        )
        self._conn.commit()
        return result.rowcount

    def revoke_alle_berechtigungen_fuer_kasse(self, kasse_id: int, actor: str) -> int:
        """Entzieht allen Usern die Rechte für eine Kasse (z.B. beim Löschen der Kasse)."""
        result = self._conn.execute(
            """
            UPDATE kasse_berechtigungen
            SET deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s,
                version    = version + 1
            WHERE kasse_id = %s AND deleted_at IS NULL
            """,
            (actor, actor, kasse_id),
        )
        self._conn.commit()
        return result.rowcount

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_obj(row: dict) -> KasseBerechtigung:
        return KasseBerechtigung(
            id=row['id'],
            kasse_id=row['kasse_id'],
            user_id=row['user_id'],
            darf_lesen=bool(row['darf_lesen']),
            darf_schreiben=bool(row['darf_schreiben']),
            darf_exportieren=bool(row['darf_exportieren']),
            version=row['version'],
            created_at=row['created_at'],
            created_by=row['created_by'],
            updated_at=row['updated_at'],
            updated_by=row['updated_by'],
            deleted_at=row['deleted_at'],
            deleted_by=row['deleted_by'],
        )
