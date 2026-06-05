"""Repository für Einmalgebühren-Katalog (gebuehr)."""
from typing import Optional
from app.models.gebuehr import Gebuehr
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT g.id, g.name, g.abteilung_id, a.name AS abteilung_name,
           g.betrag, g.anlass, g.gueltig_ab, g.gueltig_bis,
           g.zahler_typ, g.zahler_kasse_id, k.name AS zahler_kasse_name,
           g.version, g.created_at, g.created_by, g.updated_at, g.updated_by
    FROM gebuehr g
    LEFT JOIN abteilung a ON a.id = g.abteilung_id AND a.deleted_at IS NULL
    LEFT JOIN kassen k ON k.id = g.zahler_kasse_id AND k.deleted_at IS NULL
"""


def _map(row) -> Gebuehr:
    return Gebuehr(**dict(row))


class GebuehrRepository(BaseRepository):

    def list_all(self) -> list[Gebuehr]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE g.deleted_at IS NULL ORDER BY g.name")
            return [_map(r) for r in cur.fetchall()]

    def list_aktive(self, stichtag: str) -> list[Gebuehr]:
        """Gebühren, die am Stichtag gültig sind."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                WHERE g.deleted_at IS NULL
                  AND g.gueltig_ab <= %s
                  AND (g.gueltig_bis IS NULL OR g.gueltig_bis >= %s)
                ORDER BY g.name
                """,
                (stichtag, stichtag),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, id: int) -> Optional[Gebuehr]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE g.id = %s AND g.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, g: Gebuehr, created_by: str) -> Gebuehr:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gebuehr (name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                                     zahler_typ, zahler_kasse_id, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (g.name, g.abteilung_id, g.betrag, g.anlass, g.gueltig_ab, g.gueltig_bis,
                 g.zahler_typ, g.zahler_kasse_id, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, g: Gebuehr, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE gebuehr
                SET name=%s, abteilung_id=%s, betrag=%s, anlass=%s, gueltig_ab=%s, gueltig_bis=%s,
                    zahler_typ=%s, zahler_kasse_id=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (g.name, g.abteilung_id, g.betrag, g.anlass, g.gueltig_ab, g.gueltig_bis,
                 g.zahler_typ, g.zahler_kasse_id, updated_by, g.id, g.version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE gebuehr SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount == 1
