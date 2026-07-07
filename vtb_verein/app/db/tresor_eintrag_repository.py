"""Repository für Tresor-Einträge (#85).

Die geheime Nutzlast liegt ausschließlich als Fernet-Ciphertext in secret_ciphertext
(BYTEA). List/Get liefern NUR Metadaten (Titel/Benutzer/URL) – der Ciphertext wird
gezielt über get_ciphertext() geholt und erst in der API-Schicht entschlüsselt (Reveal).
"""
from typing import Optional

from app.models.tresor import TresorEintrag
from app.db.base_repository import BaseRepository

_COLS = ("id, tresor_id, titel, benutzername, url, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")


def _map(row) -> TresorEintrag:
    return TresorEintrag(**dict(row))


class TresorEintragRepository(BaseRepository):

    def list_for_tresor(self, tresor_id: int) -> list[TresorEintrag]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM tresor_eintrag "
                "WHERE tresor_id = %s AND deleted_at IS NULL ORDER BY lower(titel)",
                (tresor_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, eintrag_id: int) -> Optional[TresorEintrag]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM tresor_eintrag WHERE id = %s AND deleted_at IS NULL",
                (eintrag_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_ciphertext(self, eintrag_id: int) -> Optional[bytes]:
        """Verschlüsselte Nutzlast eines aktiven Eintrags (für den Reveal)."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT secret_ciphertext FROM tresor_eintrag "
                "WHERE id = %s AND deleted_at IS NULL",
                (eintrag_id,),
            )
            row = cur.fetchone()
            return bytes(row['secret_ciphertext']) if row else None

    def list_history(self, eintrag_id: int) -> list[dict]:
        """Versions-Verlauf eines Eintrags – Metadaten je Version (OHNE Ciphertext),
        neueste zuerst. Jede Zeile ist der Zustand DIESER Version (Audit-Trigger)."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT version, titel, benutzername, url, updated_at, updated_by, "
                "created_by, deleted_at FROM tresor_eintrag_history "
                "WHERE id = %s ORDER BY version DESC",
                (eintrag_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_history_ciphertext(self, eintrag_id: int, version: int) -> Optional[bytes]:
        """Verschlüsselte Nutzlast einer bestimmten früheren Version (Reveal/Restore)."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT secret_ciphertext FROM tresor_eintrag_history "
                "WHERE id = %s AND version = %s",
                (eintrag_id, version),
            )
            row = cur.fetchone()
            if row is None or row['secret_ciphertext'] is None:
                return None
            return bytes(row['secret_ciphertext'])

    def create(self, tresor_id: int, titel: str, benutzername: Optional[str],
               url: Optional[str], secret_ciphertext: bytes, created_by: str) -> TresorEintrag:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO tresor_eintrag "
                "(tresor_id, titel, benutzername, url, secret_ciphertext, created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (tresor_id, titel, benutzername, url, secret_ciphertext, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, eintrag_id: int, titel: str, benutzername: Optional[str],
               url: Optional[str], secret_ciphertext: Optional[bytes],
               updated_by: str, expected_version: int) -> bool:
        """Metadaten aktualisieren; secret_ciphertext nur ersetzen, wenn übergeben
        (None = Passwort bleibt unverändert)."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_eintrag SET titel=%s, benutzername=%s, url=%s, "
                "secret_ciphertext=COALESCE(%s, secret_ciphertext), "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (titel, benutzername, url, secret_ciphertext, updated_by,
                 eintrag_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, eintrag_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_eintrag SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, eintrag_id),
            )
            return cur.rowcount > 0
