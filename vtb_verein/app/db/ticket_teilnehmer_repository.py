'''
TicketTeilnehmerRepository - Verwaltung von ticket_teilnehmer

Phase 4.1 - Ticket-System Repository & Service

Soft-Delete-only + Audit-History (Trigger): Hinzufügen legt eine aktive Zeile an,
Entfernen ist ein Soft-Delete (deleted_at/deleted_by, version + 1). Aktive Teilnahme
ist über den partiellen Unique-Index `uix_ticket_teilnehmer_active` eindeutig; nach
einem Soft-Delete kann dieselbe Person erneut hinzugefügt werden (neue Zeile).
'''

from app.models.ticket import TicketTeilnehmer


class TicketTeilnehmerRepository:

    def __init__(self, conn):
        self.conn = conn

    def list_by_ticket(self, ticket_id: int) -> list[TicketTeilnehmer]:
        cursor = self.conn.execute(
            "SELECT ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am "
            "FROM ticket_teilnehmer WHERE ticket_id = %s AND deleted_at IS NULL "
            "ORDER BY hinzugefuegt_am ASC",
            (ticket_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def add(self, ticket_id: int, member_id: int, added_by: int, by: str) -> bool:
        """Fügt eine aktive Teilnahme hinzu. False, wenn bereits aktiv (Unique-Index)."""
        try:
            self.conn.execute(
                "INSERT INTO ticket_teilnehmer "
                "(ticket_id, user_id, hinzugefuegt_von, created_by, updated_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (ticket_id, member_id, added_by, by, by)
            )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            return False

    def remove(self, ticket_id: int, member_id: int, by: str) -> bool:
        """Soft-Delete der aktiven Teilnahme (version + 1 → Audit-Trigger)."""
        cursor = self.conn.execute(
            "UPDATE ticket_teilnehmer "
            "SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "    updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE ticket_id = %s AND user_id = %s AND deleted_at IS NULL",
            (by, by, ticket_id, member_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def is_teilnehmer(self, ticket_id: int, member_id: int) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM ticket_teilnehmer "
            "WHERE ticket_id = %s AND user_id = %s AND deleted_at IS NULL",
            (ticket_id, member_id)
        )
        return cursor.fetchone() is not None

    def _map(self, row) -> TicketTeilnehmer:
        return TicketTeilnehmer(
            ticket_id=row['ticket_id'], user_id=row['user_id'],
            hinzugefuegt_von=row['hinzugefuegt_von'], hinzugefuegt_am=row['hinzugefuegt_am']
        )
