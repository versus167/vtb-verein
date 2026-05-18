from dataclasses import dataclass
from typing import Optional
from app.db.base_repository import BaseRepository

VALID_STATUS = ('aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied')


@dataclass
class MitgliedAbteilung:
    id: Optional[int] = None
    mitglied_id: Optional[int] = None
    abteilung_id: Optional[int] = None
    abteilung_name: Optional[str] = None
    abteilung_kuerzel: Optional[str] = None
    status: str = 'aktiv'
    von: Optional[str] = None
    bis: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


class MitgliedAbteilungRepository(BaseRepository):

    _SELECT = """
        SELECT ma.id, ma.mitglied_id, ma.abteilung_id,
               a.name AS abteilung_name, a.kuerzel AS abteilung_kuerzel,
               ma.status, ma.von, ma.bis,
               ma.version, ma.created_at, ma.created_by,
               ma.updated_at, ma.updated_by,
               ma.deleted_at, ma.deleted_by
        FROM mitglied_abteilung ma
        JOIN abteilung a ON a.id = ma.abteilung_id
    """

    def get(self, id: int) -> Optional[MitgliedAbteilung]:
        with self.cursor() as cur:
            cur.execute(self._SELECT + " WHERE ma.id = %s", (id,))
            row = cur.fetchone()
            return MitgliedAbteilung(**dict(row)) if row else None

    def list_for_mitglied(self, mitglied_id: int) -> list[MitgliedAbteilung]:
        with self.cursor() as cur:
            cur.execute(
                self._SELECT + " WHERE ma.mitglied_id = %s AND ma.deleted_at IS NULL ORDER BY a.name",
                (mitglied_id,),
            )
            return [MitgliedAbteilung(**dict(row)) for row in cur.fetchall()]

    def exists_active(self, mitglied_id: int, abteilung_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM mitglied_abteilung "
                "WHERE mitglied_id = %s AND abteilung_id = %s AND deleted_at IS NULL LIMIT 1",
                (mitglied_id, abteilung_id),
            )
            return cur.fetchone() is not None

    def create(self, mitglied_id: int, abteilung_id: int, status: str,
               von: Optional[str], bis: Optional[str], created_by: str) -> MitgliedAbteilung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mitglied_abteilung
                    (mitglied_id, abteilung_id, status, von, bis, created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (mitglied_id, abteilung_id, status, von, bis, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            cur.execute(self._SELECT + " WHERE ma.id = %s", (new_id,))
            return MitgliedAbteilung(**dict(cur.fetchone()))

    def update(self, id: int, status: str, von: Optional[str], bis: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_abteilung
                SET status = %s, von = %s, bis = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (status, von, bis, updated_by, id, expected_version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_abteilung
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1
