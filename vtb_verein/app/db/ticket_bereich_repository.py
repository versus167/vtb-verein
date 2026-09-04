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
            "FROM ticket_bereiche WHERE id = %s",
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
            "INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (bereich.name, bereich.beschreibung, created_by, created_by)
        )
        self.conn.commit()
        return self.get(cursor.fetchone()['id'])

    def update(self, bereich: TicketBereich, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET name = %s, beschreibung = %s, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = %s "
            "WHERE id = %s AND version = %s AND deleted_at IS NULL",
            (bereich.name, bereich.beschreibung, updated_by, bereich.id, bereich.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        """Soft-Delete des Bereichs — samt der Rechte AUF ihn.

        Die Tickets bleiben bewusst stehen: Ein Ticket ist der fachliche Vorgang, der
        Bereich nur seine Einsortierung (so auch PRUNE_REGISTRY). Die Berechtigungen
        dagegen sind ohne ihren Bereich sinnlos. Blieben sie aktiv, hinge ein aktives
        Kind an einem gelöschten Parent — die Konsistenzprüfung meldet das, und Tor 4
        des Prune hielte den Bereich dauerhaft im Papierkorb fest.

        Beide UPDATEs teilen sich einen Commit: Ein Bereich ohne seine Rechte oder
        Rechte ohne ihren Bereich wäre genau der Zwischenzustand, den die Prüfung
        anschließend anmahnt.
        """
        cur = self.conn.cursor()
        try:
            cur.execute(
                "UPDATE ticket_bereiche SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
                "WHERE id = %s AND deleted_at IS NULL",
                (deleted_by, deleted_by, id)
            )
            if cur.rowcount == 0:
                self.conn.rollback()
                return False
            cur.execute(
                "UPDATE ticket_bereich_berechtigungen "
                "SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
                "WHERE bereich_id = %s AND deleted_at IS NULL",
                (deleted_by, deleted_by, id)
            )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def _map(self, row) -> TicketBereich:
        return TicketBereich(
            id=row['id'], name=row['name'], beschreibung=row['beschreibung'],
            version=row['version'], created_at=row['created_at'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )
