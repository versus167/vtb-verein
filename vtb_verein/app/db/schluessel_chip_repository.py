"""Repository für physische Chips (↔ Mitglied bei Ausgabe, sonst Standort)."""
from typing import Optional

from app.models.schliessanlage import SchluesselChip
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT c.id, c.kartennummer, c.bezeichnung, c.mitglied_id, c.aufbewahrungsort, c.status,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           m.mitgliedsnummer AS mitgliedsnummer,
           c.version, c.created_at, c.created_by, c.updated_at, c.updated_by,
           c.deleted_at, c.deleted_by
    FROM schluessel_chip c
    LEFT JOIN mitglied m ON m.id = c.mitglied_id
"""


def _map(row) -> SchluesselChip:
    return SchluesselChip(**dict(row))


class SchluesselChipRepository(BaseRepository):

    def get(self, id: int) -> Optional[SchluesselChip]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE c.id = %s AND c.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def find_active_by_kartennummer(self, kartennummer: str) -> Optional[SchluesselChip]:
        """Für die Log-Auflösung Kartennummer → Chip → Mitglied."""
        if not kartennummer:
            return None
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE c.kartennummer = %s AND c.deleted_at IS NULL",
                        (kartennummer,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_all(self) -> list[SchluesselChip]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE c.deleted_at IS NULL ORDER BY c.bezeichnung, c.id")
            return [_map(r) for r in cur.fetchall()]

    def create(self, c: SchluesselChip, created_by: str) -> SchluesselChip:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO schluessel_chip
                    (kartennummer, bezeichnung, mitglied_id, aufbewahrungsort, status,
                     created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (c.kartennummer, c.bezeichnung, c.mitglied_id, c.aufbewahrungsort,
                 c.status, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, c: SchluesselChip, updated_by: str) -> Optional[SchluesselChip]:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE schluessel_chip
                SET bezeichnung=%s, mitglied_id=%s, aufbewahrungsort=%s, status=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (c.bezeichnung, c.mitglied_id, c.aufbewahrungsort, c.status,
                 updated_by, c.id, c.version),
            )
            if cur.rowcount == 0:
                return None
        return self.get(c.id)

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE schluessel_chip SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount > 0
