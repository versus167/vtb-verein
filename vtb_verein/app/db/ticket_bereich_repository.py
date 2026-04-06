'''
TicketBereichRepository - CRUD für ticket_bereiche

Phase 4.1 - Ticket-System Repository & Service
'''

from typing import Optional
from app.models.ticket import TicketBereich


class TicketBereichRepository:

    def __init__(self, conn):
        self.conn = conn

    def get(self, id: int) -> Optional[TicketBereich]:
        cursor = self.conn.execute(
            "SELECT id, name, beschreibung, version, created_at, deleted_at, deleted_by "
            "FROM ticket_bereiche WHERE id = ?",
            (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_all(self, include_deleted: bool = False) -> list[TicketBereich]:
        if include_deleted:
            cursor = self.conn.execute(
                "SELECT id, name, beschreibung, version, created_at, deleted_at, deleted_by "
                "FROM ticket_bereiche ORDER BY name"
            )
        else:
            cursor = self.conn.execute(
                "SELECT id, name, beschreibung, version, created_at, deleted_at, deleted_by "
                "FROM ticket_bereiche WHERE deleted_at IS NULL ORDER BY name"
            )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, bereich: TicketBereich, created_by: str) -> TicketBereich:
        cursor = self.conn.execute(
            "INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by) VALUES (?, ?, ?, ?)",
            (bereich.name, bereich.beschreibung, created_by, created_by)
        )
        self.conn.commit()
        return self.get(cursor.lastrowid)

    def update(self, bereich: TicketBereich, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET name = ?, beschreibung = ?, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = ? "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (bereich.name, bereich.beschreibung, updated_by, bereich.id, bereich.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET deleted_at = datetime('now'), deleted_by = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map(self, row) -> TicketBereich:
        return TicketBereich(
            id=row[0], name=row[1], beschreibung=row[2],
            version=row[3], created_at=row[4],
            deleted_at=row[5], deleted_by=row[6]
        )
