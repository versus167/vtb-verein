'''
TicketKategorieRepository - CRUD für ticket_kategorien

Phase 4.1 - Ticket-System Repository & Service
'''

from typing import Optional
from app.models.ticket import TicketKategorie


class TicketKategorieRepository:

    def __init__(self, conn):
        self.conn = conn

    def get(self, id: int) -> Optional[TicketKategorie]:
        cursor = self.conn.execute(
            "SELECT id, name, icon, version, deleted_at, deleted_by "
            "FROM ticket_kategorien WHERE id = %s",
            (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_all(self, include_deleted: bool = False) -> list[TicketKategorie]:
        if include_deleted:
            cursor = self.conn.execute(
                "SELECT id, name, icon, version, deleted_at, deleted_by "
                "FROM ticket_kategorien ORDER BY name"
            )
        else:
            cursor = self.conn.execute(
                "SELECT id, name, icon, version, deleted_at, deleted_by "
                "FROM ticket_kategorien WHERE deleted_at IS NULL ORDER BY name"
            )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, kategorie: TicketKategorie, created_by: str) -> TicketKategorie:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kategorien (name, icon) VALUES (%s, %s) RETURNING id",
            (kategorie.name, kategorie.icon)
        )
        self.conn.commit()
        return self.get(cursor.fetchone()['id'])

    def update(self, kategorie: TicketKategorie, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kategorien SET name = %s, icon = %s, version = version + 1 "
            "WHERE id = %s AND version = %s AND deleted_at IS NULL",
            (kategorie.name, kategorie.icon, kategorie.id, kategorie.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kategorien SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1 "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map(self, row) -> TicketKategorie:
        return TicketKategorie(
            id=row['id'], name=row['name'], icon=row['icon'],
            version=row['version'], deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )
