# vtb_verein/app/db/permission_repository.py
"""
Repository für User-Permissions.

Verwaltet die user_permissions-Tabelle nach dem Repository-Pattern.
Alle Schreiboperationen erfolgen mit Soft-Delete und Versionierung.
"""
from psycopg import Connection as PgConnection
from datetime import datetime
from app.db.base_repository import BaseRepository
from app.models.permission import Permission, UserPermission


class PermissionRepository(BaseRepository):
    """Repository für User-Permissions."""

    def get_permissions_for_user(self, user_id: int) -> set[str]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT permission
                FROM user_permissions
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            return {row['permission'] for row in cur.fetchall()}

    def set_permissions_for_user(
        self,
        user_id: int,
        permissions: set[str],
        actor: str,
    ) -> None:
        now = datetime.now().isoformat()
        current = self.get_permissions_for_user(user_id)

        to_add    = permissions - current
        to_remove = current - permissions

        with self.cursor() as cur:
            # Entfernte Permissions soft-deleten
            for perm in to_remove:
                cur.execute(
                    """
                    UPDATE user_permissions
                    SET deleted_at = %s, deleted_by = %s,
                        updated_at = %s, updated_by = %s,
                        version = version + 1
                    WHERE user_id = %s AND permission = %s AND deleted_at IS NULL
                    """,
                    (now, actor, now, actor, user_id, perm),
                )

            # Neue Permissions einfügen oder reaktivieren
            for perm in to_add:
                cur.execute(
                    """
                    SELECT id FROM user_permissions
                    WHERE user_id = %s AND permission = %s
                    """,
                    (user_id, perm),
                )
                row = cur.fetchone()
                if row:
                    # War soft-deleted → reaktivieren
                    cur.execute(
                        """
                        UPDATE user_permissions
                        SET deleted_at = NULL, deleted_by = NULL,
                            updated_at = %s, updated_by = %s,
                            version = version + 1
                        WHERE user_id = %s AND permission = %s
                        """,
                        (now, actor, user_id, perm),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO user_permissions
                            (user_id, permission, created_at, created_by, updated_at, updated_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, perm, now, actor, now, actor),
                    )

    def grant_permission(
        self,
        user_id: int,
        permission: str,
        actor: str,
    ) -> None:
        """Fügt eine einzelne Permission hinzu (idempotent)."""
        current = self.get_permissions_for_user(user_id)
        if permission in current:
            return
        now = datetime.now().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM user_permissions
                WHERE user_id = %s AND permission = %s
                """,
                (user_id, permission),
            )
            row = cur.fetchone()
            if row:
                # War soft-deleted → reaktivieren
                cur.execute(
                    """
                    UPDATE user_permissions
                    SET deleted_at = NULL, deleted_by = NULL,
                        updated_at = %s, updated_by = %s,
                        version = version + 1
                    WHERE user_id = %s AND permission = %s
                    """,
                    (now, actor, user_id, permission),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO user_permissions
                        (user_id, permission, created_at, created_by, updated_at, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, permission, now, actor, now, actor),
                )

    def revoke_permission(
        self,
        user_id: int,
        permission: str,
        actor: str,
    ) -> None:
        """Entzieht eine einzelne Permission (Soft-Delete)."""
        now = datetime.now().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE user_permissions
                SET deleted_at = %s, deleted_by = %s,
                    updated_at = %s, updated_by = %s,
                    version = version + 1
                WHERE user_id = %s AND permission = %s AND deleted_at IS NULL
                """,
                (now, actor, now, actor, user_id, permission),
            )

    def revoke_all_permissions_for_user(self, user_id: int, actor: str) -> None:
        """Entzieht alle aktiven Permissions eines Users."""
        now = datetime.now().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE user_permissions
                SET deleted_at = %s, deleted_by = %s,
                    updated_at = %s, updated_by = %s,
                    version = version + 1
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (now, actor, now, actor, user_id),
            )
