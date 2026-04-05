'''
TicketRepository - CRUD für tickets

Phase 4.1 - Ticket-System Repository & Service
'''

from typing import Optional
from app.models.ticket import Ticket


class TicketRepository:

    def __init__(self, conn):
        self.conn = conn

    _SELECT = (
        "SELECT id, title, description, status, priority, area_id, category_id, "
        "reported_by, assigned_to, due_date, closed_at, closed_by, "
        "version, created_at, deleted_at, deleted_by FROM tickets"
    )

    def get(self, id: int) -> Optional[Ticket]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_all(self, include_deleted: bool = False) -> list[Ticket]:
        if include_deleted:
            cursor = self.conn.execute(
                self._SELECT + " ORDER BY created_at DESC"
            )
        else:
            cursor = self.conn.execute(
                self._SELECT + " WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        return [self._map(row) for row in cursor.fetchall()]

    def list_by_status(self, status: str) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE status = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (status,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def list_by_assigned(self, user_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE assigned_to = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (user_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def list_by_reporter(self, user_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE reported_by = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (user_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, ticket: Ticket, created_by: str) -> Ticket:
        cursor = self.conn.execute(
            "INSERT INTO tickets (title, description, status, priority, area_id, category_id, "
            "reported_by, assigned_to, due_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ticket.title, ticket.description, ticket.status, ticket.priority,
                ticket.area_id, ticket.category_id, ticket.reported_by,
                ticket.assigned_to, ticket.due_date
            )
        )
        self.conn.commit()
        return self.get(cursor.lastrowid)

    def update(self, ticket: Ticket, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE tickets SET title = ?, description = ?, status = ?, priority = ?, "
            "area_id = ?, category_id = ?, assigned_to = ?, due_date = ?, "
            "closed_at = ?, closed_by = ?, version = version + 1 "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (
                ticket.title, ticket.description, ticket.status, ticket.priority,
                ticket.area_id, ticket.category_id, ticket.assigned_to, ticket.due_date,
                ticket.closed_at, ticket.closed_by,
                ticket.id, ticket.version
            )
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE tickets SET deleted_at = datetime('now'), deleted_by = ?, version = version + 1 "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_history(self, ticket_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT history_id, id, title, status, priority, area_id, category_id, "
            "assigned_to, due_date, closed_at, closed_by, deleted_at, deleted_by, "
            "version, changed_at "
            "FROM tickets_history WHERE id = ? ORDER BY version ASC",
            (ticket_id,)
        )
        cols = [
            'history_id', 'id', 'title', 'status', 'priority', 'area_id', 'category_id',
            'assigned_to', 'due_date', 'closed_at', 'closed_by', 'deleted_at', 'deleted_by',
            'version', 'changed_at'
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def _map(self, row) -> Ticket:
        return Ticket(
            id=row[0], title=row[1], description=row[2], status=row[3], priority=row[4],
            area_id=row[5], category_id=row[6], reported_by=row[7], assigned_to=row[8],
            due_date=row[9], closed_at=row[10], closed_by=row[11],
            version=row[12], created_at=row[13], deleted_at=row[14], deleted_by=row[15]
        )
