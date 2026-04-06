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
                self._SELECT +
                " WHERE ticket_id = ? AND sichtbarkeit = 'oeffentlich' AND deleted_at IS NULL "
                "ORDER BY created_at ASC",
                (ticket_id,)
            )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kommentare "
            "(ticket_id, autor_id, inhalt, sichtbarkeit, created_by, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                kommentar.ticket_id, kommentar.autor_id, kommentar.inhalt,
                kommentar.sichtbarkeit, created_by, created_by
            )
        )
        self.conn.commit()
        return self.get(cursor.lastrowid)

    def update(self, kommentar: TicketKommentar, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET inhalt = ?, sichtbarkeit = ?, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = ?, version = version + 1 "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (kommentar.inhalt, kommentar.sichtbarkeit, updated_by, kommentar.id, kommentar.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET deleted_at = datetime('now'), deleted_by = ?, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = ?, version = version + 1 "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_history(self, kommentar_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT id, version, ticket_id, autor_id, inhalt, sichtbarkeit, "
            "deleted_at, deleted_by, created_at "
            "FROM ticket_kommentare_history WHERE id = ? ORDER BY version ASC",
            (kommentar_id,)
        )
        cols = [
            'id', 'version', 'ticket_id', 'autor_id', 'inhalt', 'sichtbarkeit',
            'deleted_at', 'deleted_by', 'created_at'
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def _map(self, row) -> TicketKommentar:
        return TicketKommentar(
            id=row[0], ticket_id=row[1], autor_id=row[2], inhalt=row[3],
            sichtbarkeit=row[4], version=row[5], created_at=row[6],
            deleted_at=row[7], deleted_by=row[8]
        )
