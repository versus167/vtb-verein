'''
TicketTeilnehmerRepository - Verwaltung von ticket_teilnehmer

Phase 4.1 - Ticket-System Repository & Service
'''

from app.models.ticket import TicketTeilnehmer


class TicketTeilnehmerRepository:

    def __init__(self, conn):
        self.conn = conn

    def list_by_ticket(self, ticket_id: int) -> list[TicketTeilnehmer]:
        cursor = self.conn.execute(
            "SELECT ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am "
            "FROM ticket_teilnehmer WHERE ticket_id = ? ORDER BY hinzugefuegt_am ASC",
            (ticket_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def add(self, ticket_id: int, member_id: int, added_by: int) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO ticket_teilnehmer (ticket_id, user_id, hinzugefuegt_von) VALUES (?, ?, ?)",
                (ticket_id, member_id, added_by)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def remove(self, ticket_id: int, member_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM ticket_teilnehmer WHERE ticket_id = ? AND user_id = ?",
            (ticket_id, member_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def is_teilnehmer(self, ticket_id: int, member_id: int) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM ticket_teilnehmer WHERE ticket_id = ? AND user_id = ?",
            (ticket_id, member_id)
        )
        return cursor.fetchone() is not None

    def _map(self, row) -> TicketTeilnehmer:
        return TicketTeilnehmer(
            ticket_id=row[0], user_id=row[1],
            hinzugefuegt_von=row[2], hinzugefuegt_am=row[3]
        )
