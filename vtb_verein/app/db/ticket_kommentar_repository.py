'''
TicketKommentarRepository - CRUD für ticket_kommentare

Phase 4.1 - Ticket-System Repository & Service
fix     - englische Spaltennamen -> deutsche Spaltennamen gemäß DB-Schema
            author_id -> autor_id
            body      -> inhalt
            visibility-> sichtbarkeit
'''

from typing import Optional
from app.models.ticket import TicketKommentar


class TicketKommentarRepository:

    def __init__(self, conn):
        self.conn = conn

    _SELECT = (
        "SELECT id, ticket_id, autor_id, inhalt, sichtbarkeit, version, "
        "created_at, deleted_at, deleted_by FROM ticket_kommentare"
    )

    def get(self, id: int) -> Optional[TicketKommentar]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE id = %s", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_by_ticket(self, ticket_id: int, include_internal: bool = False) -> list[TicketKommentar]:
        if include_internal:
            cursor = self.conn.execute(
                self._SELECT + " WHERE ticket_id = %s AND deleted_at IS NULL ORDER BY created_at ASC",
                (ticket_id,)
            )
        else:
            cursor = self.conn.execute(
                self._SELECT +
                " WHERE ticket_id = %s AND sichtbarkeit = 'oeffentlich' AND deleted_at IS NULL "
                "ORDER BY created_at ASC",
                (ticket_id,)
            )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kommentare "
            "(ticket_id, autor_id, inhalt, sichtbarkeit, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                kommentar.ticket_id, kommentar.autor_id, kommentar.inhalt,
                kommentar.sichtbarkeit, created_by, created_by
            )
        )
        self.conn.commit()
        return self.get(cursor.fetchone()['id'])

    def update(self, kommentar: TicketKommentar, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET inhalt = %s, sichtbarkeit = %s, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE id = %s AND version = %s AND deleted_at IS NULL",
            (kommentar.inhalt, kommentar.sichtbarkeit, updated_by, kommentar.id, kommentar.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_history(self, kommentar_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT id, version, ticket_id, autor_id, inhalt, sichtbarkeit, "
            "deleted_at, deleted_by, created_at "
            "FROM ticket_kommentare_history WHERE id = %s ORDER BY version ASC",
            (kommentar_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def _map(self, row) -> TicketKommentar:
        return TicketKommentar(
            id=row['id'], ticket_id=row['ticket_id'], autor_id=row['autor_id'],
            inhalt=row['inhalt'], sichtbarkeit=row['sichtbarkeit'],
            version=row['version'], created_at=row['created_at'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )
