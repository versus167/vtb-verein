'''
Created on 06.04.2026

Repository für bereichsspezifische Ticket-Berechtigungen.
Analog zu kasse_berechtigung_repository.py.

@author: AI Assistant
'''

from typing import Optional
from psycopg import Connection as PgConnection


class TicketBereichBerechtigungRepository:
    """Verwaltet bereichsspezifische Ticket-Berechtigungen (ticket_bereich_berechtigungen)."""

    def __init__(self, conn: PgConnection):
        self._conn = conn

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_berechtigung(self, bereich_id: int, user_id: int) -> Optional[dict]:
        """Gibt die aktive Berechtigung eines Users für einen Bereich zurück oder None."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, bereich_id, user_id,
                   darf_lesen, darf_bearbeiten, darf_schliessen,
                   version, created_at, created_by, updated_at, updated_by
            FROM ticket_bereich_berechtigungen
            WHERE bereich_id = %s AND user_id = %s AND deleted_at IS NULL
            """,
            (bereich_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def list_berechtigungen_fuer_bereich(self, bereich_id: int) -> list[dict]:
        """Alle aktiven Berechtigungen für einen Bereich (inkl. Username)."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT tbb.id, tbb.bereich_id, tbb.user_id,
                   tbb.darf_lesen, tbb.darf_bearbeiten, tbb.darf_schliessen,
                   tbb.version,
                   u.username, u.email
            FROM ticket_bereich_berechtigungen tbb
            JOIN users u ON u.id = tbb.user_id
            WHERE tbb.bereich_id = %s AND tbb.deleted_at IS NULL
            ORDER BY u.username
            """,
            (bereich_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def list_berechtigungen_fuer_user(self, user_id: int) -> list[dict]:
        """Alle aktiven Berechtigungen eines Users (inkl. Bereichsname)."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT tbb.id, tbb.bereich_id, tbb.user_id,
                   tbb.darf_lesen, tbb.darf_bearbeiten, tbb.darf_schliessen,
                   tbb.version,
                   tb.name AS bereich_name
            FROM ticket_bereich_berechtigungen tbb
            JOIN ticket_bereiche tb ON tb.id = tbb.bereich_id
            WHERE tbb.user_id = %s AND tbb.deleted_at IS NULL
            ORDER BY tb.name
            """,
            (user_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def list_alle_berechtigungen(self) -> list[dict]:
        """Alle aktiven Berechtigungen (für Admin-Übersicht), inkl. Namen."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT tbb.id, tbb.bereich_id, tbb.user_id,
                   tbb.darf_lesen, tbb.darf_bearbeiten, tbb.darf_schliessen,
                   tbb.version,
                   u.username, u.email,
                   tb.name AS bereich_name
            FROM ticket_bereich_berechtigungen tbb
            JOIN users u ON u.id = tbb.user_id
            JOIN ticket_bereiche tb ON tb.id = tbb.bereich_id
            WHERE tbb.deleted_at IS NULL
            ORDER BY tb.name, u.username
            """,
        )
        return [dict(row) for row in cur.fetchall()]

    def user_darf_lesen(self, bereich_id: int, user_id: int) -> bool:
        """Prüft ob ein User einen Bereich lesen darf."""
        b = self.get_berechtigung(bereich_id, user_id)
        return bool(b and b['darf_lesen'])

    def user_darf_bearbeiten(self, bereich_id: int, user_id: int) -> bool:
        """Prüft ob ein User Tickets in einem Bereich bearbeiten darf."""
        b = self.get_berechtigung(bereich_id, user_id)
        return bool(b and b['darf_bearbeiten'])

    def user_darf_schliessen(self, bereich_id: int, user_id: int) -> bool:
        """Prüft ob ein User Tickets in einem Bereich schließen/eskalieren darf."""
        b = self.get_berechtigung(bereich_id, user_id)
        return bool(b and b['darf_schliessen'])

    def get_lesbare_bereich_ids(self, user_id: int) -> list[int]:
        """Gibt alle Bereich-IDs zurück, die ein User lesen darf."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT bereich_id FROM ticket_bereich_berechtigungen
            WHERE user_id = %s AND darf_lesen = 1 AND deleted_at IS NULL
            """,
            (user_id,),
        )
        return [row['bereich_id'] for row in cur.fetchall()]

    def list_user_ids_bearbeiten_oder_schliessen(self, bereich_id: int) -> list[int]:
        """User-IDs mit darf_bearbeiten=1 oder darf_schliessen=1 für einen Bereich."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT user_id FROM ticket_bereich_berechtigungen
            WHERE bereich_id = %s AND deleted_at IS NULL
              AND (darf_bearbeiten = 1 OR darf_schliessen = 1)
            """,
            (bereich_id,),
        )
        return [row['user_id'] for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def set_berechtigung(
        self,
        bereich_id: int,
        user_id: int,
        darf_lesen: bool,
        darf_bearbeiten: bool,
        darf_schliessen: bool,
        by: str,
    ) -> None:
        """
        Legt eine Berechtigung an oder aktualisiert sie (Upsert via UNIQUE-Constraint).
        Wenn alle drei Flags False sind, wird die Berechtigung per Soft-Delete entfernt.
        """
        existing = self.get_berechtigung(bereich_id, user_id)

        # Alle False -> Soft-Delete falls vorhanden
        if not darf_lesen and not darf_bearbeiten and not darf_schliessen:
            if existing:
                self.mark_berechtigung_deleted(bereich_id, user_id, by)
            return

        cur = self._conn.cursor()
        if existing is None:
            # Neu anlegen (auch wenn es ein gelöschtes gibt - UNIQUE nur auf aktiven)
            cur.execute(
                """
                INSERT INTO ticket_bereich_berechtigungen
                    (bereich_id, user_id, darf_lesen, darf_bearbeiten, darf_schliessen,
                     created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    bereich_id, user_id,
                    int(darf_lesen), int(darf_bearbeiten), int(darf_schliessen),
                    by, by,
                ),
            )
        else:
            # Aktualisieren
            cur.execute(
                """
                UPDATE ticket_bereich_berechtigungen
                SET darf_lesen      = %s,
                    darf_bearbeiten = %s,
                    darf_schliessen = %s,
                    updated_at      = CURRENT_TIMESTAMP,
                    updated_by      = %s,
                    version         = version + 1
                WHERE bereich_id = %s AND user_id = %s AND deleted_at IS NULL
                """,
                (
                    int(darf_lesen), int(darf_bearbeiten), int(darf_schliessen),
                    by, bereich_id, user_id,
                ),
            )
        self._conn.commit()

    def mark_berechtigung_deleted(
        self, bereich_id: int, user_id: int, deleted_by: str
    ) -> bool:
        """Soft-Delete einer Berechtigung."""
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE ticket_bereich_berechtigungen
            SET deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s,
                version    = version + 1,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s
            WHERE bereich_id = %s AND user_id = %s AND deleted_at IS NULL
            """,
            (deleted_by, deleted_by, bereich_id, user_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def mark_alle_berechtigungen_fuer_bereich_deleted(
        self, bereich_id: int, deleted_by: str
    ) -> int:
        """Soft-Delete aller Berechtigungen eines Bereichs (z.B. bei Bereich-Löschung)."""
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE ticket_bereich_berechtigungen
            SET deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s,
                version    = version + 1,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s
            WHERE bereich_id = %s AND deleted_at IS NULL
            """,
            (deleted_by, deleted_by, bereich_id),
        )
        self._conn.commit()
        return cur.rowcount
