"""Repository für Tresor-Kontakte (#106).

Wichtige Ansprechpartner (Firma/Notdienst, Telefon, E-Mail) je Tresor — bewusst
unverschlüsselt, damit die Nummern in der App direkt anklickbar sind. Zugriff
regelt die tresor_freigabe des zugehörigen Tresors (siehe API-Schicht).
"""
from typing import Optional

from app.models.tresor import TresorKontakt
from app.db.base_repository import BaseRepository

_COLS = ("id, tresor_id, name, ansprechpartner, telefon, email, notiz, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")


def _map(row) -> TresorKontakt:
    return TresorKontakt(**dict(row))


class TresorKontaktRepository(BaseRepository):

    def list_for_tresor(self, tresor_id: int) -> list[TresorKontakt]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM tresor_kontakt "
                "WHERE tresor_id = %s AND deleted_at IS NULL ORDER BY lower(name)",
                (tresor_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, kontakt_id: int) -> Optional[TresorKontakt]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM tresor_kontakt WHERE id = %s AND deleted_at IS NULL",
                (kontakt_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, tresor_id: int, name: str, ansprechpartner: Optional[str],
               telefon: Optional[str], email: Optional[str], notiz: Optional[str],
               created_by: str) -> TresorKontakt:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO tresor_kontakt "
                "(tresor_id, name, ansprechpartner, telefon, email, notiz, created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (tresor_id, name, ansprechpartner, telefon, email, notiz,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, kontakt_id: int, name: str, ansprechpartner: Optional[str],
               telefon: Optional[str], email: Optional[str], notiz: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_kontakt SET name=%s, ansprechpartner=%s, telefon=%s, "
                "email=%s, notiz=%s, updated_at=CURRENT_TIMESTAMP, updated_by=%s, "
                "version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (name, ansprechpartner, telefon, email, notiz, updated_by,
                 kontakt_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, kontakt_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_kontakt SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, kontakt_id),
            )
            return cur.rowcount > 0
