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
        "SELECT id, ticket_id, comment_id, original_name, stored_name, "
        "mime_type, file_size, uploaded_by, uploaded_at, deleted_at, deleted_by "
        "FROM ticket_anhaenge"
    )

    def get(self, id: int) -> Optional[TicketAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_by_ticket(self, ticket_id: int) -> list[TicketAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE ticket_id = ? AND deleted_at IS NULL ORDER BY uploaded_at ASC",
            (ticket_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def list_by_comment(self, comment_id: int) -> list[TicketAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE comment_id = ? AND deleted_at IS NULL ORDER BY uploaded_at ASC",
            (comment_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, anhang: TicketAnhang) -> TicketAnhang:
        """Legt Anhang an. stored_name wird nach INSERT anhand der ID gesetzt."""
        ext = os.path.splitext(anhang.original_name)[1].lower()
        cursor = self.conn.execute(
            "INSERT INTO ticket_anhaenge "
            "(ticket_id, comment_id, original_name, stored_name, mime_type, file_size, uploaded_by) "
            "VALUES (?, ?, ?, '', ?, ?, ?)",
            (
                anhang.ticket_id, anhang.comment_id, anhang.original_name,
                anhang.mime_type, anhang.file_size, anhang.uploaded_by
            )
        )
        new_id = cursor.lastrowid
        stored_name = f"att_{new_id:06d}{ext}"
        self.conn.execute(
            "UPDATE ticket_anhaenge SET stored_name = ? WHERE id = ?",
            (stored_name, new_id)
        )
        self.conn.commit()
        return self.get(new_id)

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_anhaenge SET deleted_at = datetime('now'), deleted_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map(self, row) -> TicketAnhang:
        return TicketAnhang(
            id=row[0], ticket_id=row[1], comment_id=row[2],
            original_name=row[3], stored_name=row[4],
            mime_type=row[5], file_size=row[6],
            uploaded_by=row[7], uploaded_at=row[8],
            deleted_at=row[9], deleted_by=row[10]
        )
