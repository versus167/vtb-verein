"""Artikel-Gruppen des Teamtresors (#98): clubdeckel_gruppe.

Jede Gruppe („Getränke", „Essen", …) hat einen VERKÄUFER: das Team
(verkaeufer_mitglied_id NULL) oder ein Mitglied — z. B. verkauft ein Mitglied
die Roster selbst. Der Verkäufer bestimmt beim Konsum, wem der Erlös gutge-
schrieben wird (Team implizit bzw. 'verkauf'-Gegenzeile beim Mitglied).
"""
from typing import Optional

from app.models.clubdeckel import ClubdeckelGruppe
from app.db.base_repository import BaseRepository

_COLS = ("id, deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")
_G_COLS = ", ".join("g." + s.strip() for s in _COLS.split(","))


def _map(row) -> ClubdeckelGruppe:
    return ClubdeckelGruppe(**dict(row))


class ClubdeckelGruppeRepository(BaseRepository):

    def list_for_deckel(self, deckel_id: int) -> list[ClubdeckelGruppe]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_G_COLS},
                       v.vorname || ' ' || v.nachname AS verkaeufer_name
                FROM clubdeckel_gruppe g
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                WHERE g.deckel_id = %s AND g.deleted_at IS NULL
                ORDER BY g.sortierung, lower(g.name), g.id
                """,
                (deckel_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, gruppe_id: int) -> Optional[ClubdeckelGruppe]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_G_COLS},
                       v.vorname || ' ' || v.nachname AS verkaeufer_name
                FROM clubdeckel_gruppe g
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                WHERE g.id = %s AND g.deleted_at IS NULL
                """,
                (gruppe_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, deckel_id: int, name: str,
               verkaeufer_mitglied_id: Optional[int], aktiv: int,
               sortierung: int, created_by: str) -> ClubdeckelGruppe:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_gruppe "
                "(deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung, "
                " created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, gruppe_id: int, name: str,
               verkaeufer_mitglied_id: Optional[int], aktiv: int,
               sortierung: int, updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_gruppe SET name=%s, verkaeufer_mitglied_id=%s, "
                "aktiv=%s, sortierung=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (name, verkaeufer_mitglied_id, aktiv, sortierung, updated_by,
                 gruppe_id, expected_version),
            )
            return cur.rowcount > 0

    def has_active_artikel(self, gruppe_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM clubdeckel_artikel "
                "WHERE gruppe_id = %s AND deleted_at IS NULL LIMIT 1",
                (gruppe_id,),
            )
            return cur.fetchone() is not None

    def mark_deleted(self, gruppe_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_gruppe SET deleted_at=CURRENT_TIMESTAMP, "
                "deleted_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, gruppe_id),
            )
            return cur.rowcount > 0
