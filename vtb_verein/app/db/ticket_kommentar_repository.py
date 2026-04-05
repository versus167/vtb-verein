'''
TicketKommentarRepository - CRUD für ticket_kommentare

Phase 4.1 - Ticket-System Repository & Service
'''

from typing import Optional
from app.models.ticket import TicketKommentar


class TicketKommentarRepository:

    def __init__(self, conn):
        self.conn = conn

    _SELECT = (
        "SELECT id, ticket_id, author_id, body, visibility, version, "
        "created_at, deleted_at, deleted_by FROM ticket_kommentare"
    )

    def get(self, id: int) -> Optional[TicketKommentar]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_by_ticket(self, ticket_id: int, include_internal: bool = False) -> list[TicketKommentar]:
        if include_internal:
            cursor = self.conn.execute(
                self._SELECT + " WHERE ticket_id = ? AND deleted_at IS NULL ORDER BY created_at ASC",
                (ticket_id,)
            )
        else:
            cursor = self.conn.execute(
                self._SELECT + " WHERE ticket_id = ? AND visibility = 'public' AND deleted_at IS NULL "
                "ORDER BY created_at ASC",
                (ticket_id,)
            )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kommentare (ticket_id, author_id, body, visibility) "
            "VALUES (?, ?, ?, ?)",
            (kommentar.ticket_id, kommentar.author_id, kommentar.body, kommentar.visibility)
        )
        self.conn.commit()
        return self.get(cursor.lastrowid)

    def update(self, kommentar: TicketKommentar, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET body = ?, visibility = ?, version = version + 1 "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (kommentar.body, kommentar.visibility, kommentar.id, kommentar.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET deleted_at = datetime('now'), deleted_by = ?, "
            "version = version + 1 WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_history(self, kommentar_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT history_id, id, ticket_id, body, visibility, deleted_at, deleted_by, "
            "version, changed_at "
            "FROM ticket_kommentare_history WHERE id = ? ORDER BY version ASC",
            (kommentar_id,)
        )
        cols = [
            'history_id', 'id', 'ticket_id', 'body', 'visibility',
            'deleted_at', 'deleted_by', 'version', 'changed_at'
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def _map(self, row) -> TicketKommentar:
        return TicketKommentar(
            id=row[0], ticket_id=row[1], author_id=row[2], body=row[3],
            visibility=row[4], version=row[5], created_at=row[6],
            deleted_at=row[7], deleted_by=row[8]
        )
