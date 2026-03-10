"""
Repository für User-Permissions.

Verwaltet die user_permissions-Tabelle nach dem Repository-Pattern.
Alle Schreiboperationen erfolgen mit Soft-Delete und Versionierung.
"""
import sqlite3
from datetime import datetime
from app.db.base_repository import BaseRepository
from app.models.permission import Permission, UserPermission


class PermissionRepository(BaseRepository):
    """Repository für User-Permissions."""

    def get_permissions_for_user(self, user_id: int) -> set[str]:
        """
        Gibt alle aktiven Permissions eines Users als Set zurück.

        Args:
            user_id: ID des Users

        Returns:
            Set mit Permission-Strings, z.B. {'mitglieder.read', 'beitraege.write'}
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT permission
                FROM user_permissions
                WHERE user_id = ? AND deleted_at IS NULL
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
        """
        Setzt die Permissions eines Users (ersetzt bestehende komplett).

        Bestehende Permissions die nicht mehr im Set sind werden soft-deleted.
        Neue Permissions werden eingefügt.

        Args:
            user_id: ID des Users
            permissions: Neues vollständiges Set an Permissions
            actor:  Username der die Änderung durchführt (für Audit)
        """
        now = datetime.now().isoformat()
        current = self.get_permissions_for_user(user_id)

        to_add    = permissions - current
        to_remove = current - permissions

        with self.db.cursor() as cur:
            # Entfernte Permissions soft-deleten
            for perm in to_remove:
                cur.execute(
                    """
                    UPDATE user_permissions
                    SET deleted_at = ?, deleted_by = ?,
                        updated_at = ?, updated_by = ?,
                        version = version + 1
                    WHERE user_id = ? AND permission = ? AND deleted_at IS NULL
                    """,
                    (now, actor, now, actor, user_id, perm),
                )

            # Neue Permissions einfügen
            for perm in to_add:
                cur.execute(
                    """
                    INSERT INTO user_permissions
                        (user_id, permission, created_at, created_by, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, perm, now, actor, now, actor),
                )

    def grant_permission(
        self,
        user_id: int,
        permission: str,
        actor: str,
    ) -> None:
        """
        Fügt eine einzelne Permission hinzu (idempotent).

        Args:
            user_id:    ID des Users
            permission: Permission-String
            actor:      Ausführender User (Audit)
        """
        current = self.get_permissions_for_user(user_id)
        if permission in current:
            return  # bereits vorhanden, nichts tun
        now = datetime.now().isoformat()
        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_permissions
                    (user_id, permission, created_at, created_by, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, permission, now, actor, now, actor),
            )

    def revoke_permission(
        self,
        user_id: int,
        permission: str,
        actor: str,
    ) -> None:
        """
        Entzieht eine einzelne Permission (Soft-Delete).

        Args:
            user_id:    ID des Users
            permission: Permission-String
            actor:      Ausführender User (Audit)
        """
        now = datetime.now().isoformat()
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE user_permissions
                SET deleted_at = ?, deleted_by = ?,
                    updated_at = ?, updated_by = ?,
                    version = version + 1
                WHERE user_id = ? AND permission = ? AND deleted_at IS NULL
                """,
                (now, actor, now, actor, user_id, permission),
            )

    def revoke_all_permissions_for_user(self, user_id: int, actor: str) -> None:
        """
        Entzieht alle aktiven Permissions eines Users (z.B. beim Deaktivieren).

        Args:
            user_id: ID des Users
            actor:   Ausführender User (Audit)
        """
        now = datetime.now().isoformat()
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE user_permissions
                SET deleted_at = ?, deleted_by = ?,
                    updated_at = ?, updated_by = ?,
                    version = version + 1
                WHERE user_id = ? AND deleted_at IS NULL
                """,
                (now, actor, now, actor, user_id),
            )
