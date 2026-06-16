from dataclasses import dataclass
from typing import Optional
from app.db.base_repository import BaseRepository


@dataclass
class Funktion:
    id: Optional[int] = None
    key: str = ''
    name: str = ''
    beschreibung: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class FunktionRepository(BaseRepository):

    _SELECT = """
        SELECT id, key, name, beschreibung, version, created_at, created_by, updated_at, updated_by
        FROM funktion
        WHERE deleted_at IS NULL
    """

    def list_all(self) -> list[Funktion]:
        with self.cursor() as cur:
            cur.execute(self._SELECT + " ORDER BY name")
            return [Funktion(**dict(row)) for row in cur.fetchall()]

    def get(self, id: int) -> Optional[Funktion]:
        with self.cursor() as cur:
            cur.execute(self._SELECT + " AND id = %s", (id,))
            row = cur.fetchone()
            return Funktion(**dict(row)) if row else None

    def get_by_key(self, key: str) -> Optional[Funktion]:
        with self.cursor() as cur:
            cur.execute(self._SELECT + " AND key = %s", (key,))
            row = cur.fetchone()
            return Funktion(**dict(row)) if row else None

    def list_keys(self) -> list[str]:
        with self.cursor() as cur:
            cur.execute("SELECT key FROM funktion WHERE deleted_at IS NULL ORDER BY name")
            return [row['key'] for row in cur.fetchall()]

    def create(self, key: str, name: str, beschreibung: Optional[str], created_by: str) -> Funktion:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO funktion (key, name, beschreibung, created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (key, name, beschreibung, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            cur.execute(self._SELECT + " AND id = %s", (new_id,))
            return Funktion(**dict(cur.fetchone()))

    def update(self, id: int, name: str, beschreibung: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE funktion
                SET name = %s, beschreibung = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (name, beschreibung, updated_by, id, expected_version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE funktion
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1

    def has_active_mitglied_funktion_references(self, id: int) -> bool:
        """Prüft, ob es nicht-gelöschte mitglied_funktion-Zuordnungen gibt.

        mitglied_funktion verweist über den Text-Key (funktion.key), nicht per FK.
        Wie bei Abteilungen (has_active_mitglied_abteilung_references) werden auch
        Zuordnungen soft-gelöschter Mitglieder gezählt (kein Join auf
        mitglied.deleted_at) – endgültige Bereinigung übernimmt der Prune.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM mitglied_funktion mf
                JOIN funktion f ON f.key = mf.funktion
                WHERE f.id = %s AND mf.deleted_at IS NULL
                LIMIT 1
                """,
                (id,),
            )
            return cur.fetchone() is not None
