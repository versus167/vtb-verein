# vtb_verein/app/db/funktion_permission_repository.py
"""
Repository für Funktions-Permissions (Berechtigungsmatrix pro Katalog-Funktion).

Verwaltet die funktion_permission-Tabelle nach dem Repository-Pattern.
Alle Schreiboperationen erfolgen mit Soft-Delete und Versionierung
(gleiches Upsert-/Reaktivierungs-Muster wie PermissionRepository).

Siehe BERECHTIGUNGEN.md: Mitglieder erben diese Rechte über ihre aktiven
Funktions-Zuordnungen (mitglied_funktion, von/bis-gültig).
"""
from datetime import datetime, timezone

from app.db.base_repository import BaseRepository


class FunktionPermissionRepository(BaseRepository):
    """Repository für die Berechtigungen einer Katalog-Funktion."""

    def get_permissions_for_funktion(self, funktion_id: int) -> set[str]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT permission
                FROM funktion_permission
                WHERE funktion_id = %s AND deleted_at IS NULL
                """,
                (funktion_id,),
            )
            return {row['permission'] for row in cur.fetchall()}

    def set_permissions_for_funktion(
        self,
        funktion_id: int,
        permissions: set[str],
        actor: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        current = self.get_permissions_for_funktion(funktion_id)

        to_add    = permissions - current
        to_remove = current - permissions

        with self.cursor() as cur:
            # Entfernte Permissions soft-deleten
            for perm in to_remove:
                cur.execute(
                    """
                    UPDATE funktion_permission
                    SET deleted_at = %s, deleted_by = %s,
                        updated_at = %s, updated_by = %s,
                        version = version + 1
                    WHERE funktion_id = %s AND permission = %s AND deleted_at IS NULL
                    """,
                    (now, actor, now, actor, funktion_id, perm),
                )

            # Neue Permissions einfügen oder reaktivieren
            for perm in to_add:
                cur.execute(
                    """
                    SELECT id FROM funktion_permission
                    WHERE funktion_id = %s AND permission = %s
                    """,
                    (funktion_id, perm),
                )
                row = cur.fetchone()
                if row:
                    # War soft-deleted → reaktivieren
                    cur.execute(
                        """
                        UPDATE funktion_permission
                        SET deleted_at = NULL, deleted_by = NULL,
                            updated_at = %s, updated_by = %s,
                            version = version + 1
                        WHERE funktion_id = %s AND permission = %s
                        """,
                        (now, actor, funktion_id, perm),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO funktion_permission
                            (funktion_id, permission, created_at, created_by, updated_at, updated_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (funktion_id, perm, now, actor, now, actor),
                    )
