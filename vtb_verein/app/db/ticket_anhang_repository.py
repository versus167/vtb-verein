'''
TicketAnhangRepository - Upload-Verwaltung für ticket_anhaenge

Phase 4.1 - Ticket-System Repository & Service

stored_name-Logik: nach INSERT wird stored_name = att_{id:06d}.{ext} per UPDATE gesetzt.
'''

import os
from typing import Optional
from app.models.ticket import TicketAnhang


class TicketAnhangRepository:

    def __init__(self, conn):
        self.conn = conn

    _SELECT = (
        "SELECT id, ticket_id, kommentar_id, original_name, stored_name, "
        "mime_type, dateigroesse, hochgeladen_von, hochgeladen_am, deleted_at, deleted_by "
        "FROM ticket_anhaenge"
    )

    def get(self, id: int) -> Optional[TicketAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE id = %s", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_by_ticket(self, ticket_id: int) -> list[TicketAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE ticket_id = %s AND deleted_at IS NULL ORDER BY hochgeladen_am ASC",
            (ticket_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def list_by_comment(self, comment_id: int) -> list[TicketAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE kommentar_id = %s AND deleted_at IS NULL ORDER BY hochgeladen_am ASC",
            (comment_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, anhang: TicketAnhang) -> TicketAnhang:
        """Legt Anhang an. stored_name wird nach INSERT anhand der ID gesetzt."""
        ext = os.path.splitext(anhang.original_name)[1].lower()
        cursor = self.conn.execute(
            "INSERT INTO ticket_anhaenge "
            "(ticket_id, kommentar_id, original_name, stored_name, mime_type, dateigroesse, hochgeladen_von) "
            "VALUES (%s, %s, %s, '', %s, %s, %s) RETURNING id",
            (
                anhang.ticket_id, anhang.kommentar_id, anhang.original_name,
                anhang.mime_type, anhang.dateigroesse, anhang.hochgeladen_von
            )
        )
        new_id = cursor.fetchone()['id']
        stored_name = f"att_{new_id:06d}{ext}"
        self.conn.execute(
            "UPDATE ticket_anhaenge SET stored_name = %s WHERE id = %s",
            (stored_name, new_id)
        )
        self.conn.commit()
        return self.get(new_id)

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_anhaenge SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map(self, row) -> TicketAnhang:
        return TicketAnhang(
            id=row['id'], ticket_id=row['ticket_id'], kommentar_id=row['kommentar_id'],
            original_name=row['original_name'], stored_name=row['stored_name'],
            mime_type=row['mime_type'], dateigroesse=row['dateigroesse'],
            hochgeladen_von=row['hochgeladen_von'], hochgeladen_am=row['hochgeladen_am'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )
