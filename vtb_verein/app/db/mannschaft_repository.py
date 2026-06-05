"""Repository für Mannschaften/Teams (gehören zu einer Abteilung)."""
from dataclasses import dataclass
from typing import Optional
from app.db.base_repository import BaseRepository


@dataclass
class Mannschaft:
    id: Optional[int] = None
    abteilung_id: Optional[int] = None
    abteilung_name: Optional[str] = None      # per JOIN befüllt
    name: str = ''
    saison: Optional[str] = None
    beschreibung: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


_SELECT = """
    SELECT m.id, m.abteilung_id, a.name AS abteilung_name,
           m.name, m.saison, m.beschreibung,
           m.version, m.created_at, m.created_by, m.updated_at, m.updated_by,
           m.deleted_at, m.deleted_by
    FROM mannschaft m
    LEFT JOIN abteilung a ON a.id = m.abteilung_id
"""


def _map(row) -> Mannschaft:
    return Mannschaft(**dict(row))


class MannschaftRepository(BaseRepository):

    def list_all(self, abteilung_id: Optional[int] = None) -> list[Mannschaft]:
        where = "WHERE m.deleted_at IS NULL"
        params: list = []
        if abteilung_id is not None:
            where += " AND m.abteilung_id = %s"
            params.append(abteilung_id)
        with self.cursor() as cur:
            cur.execute(_SELECT + where + " ORDER BY a.name, m.name", params)
            return [_map(r) for r in cur.fetchall()]

    def get(self, id: int) -> Optional[Mannschaft]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE m.id = %s AND m.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, m: Mannschaft, created_by: str) -> Mannschaft:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mannschaft (abteilung_id, name, saison, beschreibung,
                                        created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (m.abteilung_id, m.name, m.saison, m.beschreibung, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, m: Mannschaft, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mannschaft
                SET abteilung_id=%s, name=%s, saison=%s, beschreibung=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (m.abteilung_id, m.name, m.saison, m.beschreibung, updated_by, m.id, m.version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mannschaft
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1

    def has_active_mitglied_references(self, mannschaft_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM mitglied_mannschaft WHERE mannschaft_id=%s AND deleted_at IS NULL LIMIT 1",
                (mannschaft_id,),
            )
            return cur.fetchone() is not None
