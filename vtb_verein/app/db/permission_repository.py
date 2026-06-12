# vtb_verein/app/db/permission_repository.py
"""
Repository für User-Permissions.

Verwaltet die user_permissions-Tabelle nach dem Repository-Pattern.
Alle Schreiboperationen erfolgen mit Soft-Delete und Versionierung.

Seit Schema v35 (siehe BERECHTIGUNGEN.md) ist user_permissions ein
Tri-State-Override (effect 'grant'|'deny'); die effektiven Rechte eines
Users werden in get_effective_permissions berechnet:
    (Sockel ∪ Funktionsrechte ∪ Grants) − Denies
"""
from psycopg import Connection as PgConnection
from datetime import date, datetime
from app.db.base_repository import BaseRepository
from app.models.permission import (
    Permission, UserPermission,
    EffectivePermissions, compute_effective_permissions,
)


class PermissionRepository(BaseRepository):
    """Repository für User-Permissions."""

    def get_permissions_for_user(self, user_id: int) -> set[str]:
        """Individuelle Grants eines Users (ohne Funktionsrechte/Sockel/Denies).

        Bewusst nur effect='grant': die bestehenden Aufrufer (UserPermissionsPage,
        Rollen-Default-Materialisierung) arbeiten mit der Grant-Menge; Denies
        werden davon nicht angefasst.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT permission
                FROM user_permissions
                WHERE user_id = %s AND deleted_at IS NULL AND effect = 'grant'
                """,
                (user_id,),
            )
            return {row['permission'] for row in cur.fetchall()}

    def get_effective_permissions(
        self,
        user_id: int,
        stichtag: str | None = None,
    ) -> EffectivePermissions:
        """Effektive Rechte eines Users inkl. Funktions-Vererbung.

        Kette: users ← mitglied.user_id → mitglied_funktion (am Stichtag gültig)
               → funktion (aktiver Katalog-Eintrag) → funktion_permission.
        Dazu individuelle Overrides aus user_permissions (grant/deny).
        Zwei konstante Queries, unabhängig von der Anzahl der Funktionen.
        """
        if stichtag is None:
            # Serverzeit, identische Semantik wie _gueltig_heute (backend/api/personen.py)
            stichtag = date.today().isoformat()

        with self.cursor() as cur:
            cur.execute(
                """
                SELECT fp.permission,
                       mf.abteilung_id,
                       f.name  AS funktion_name,
                       a.name  AS abteilung_name
                FROM mitglied m
                JOIN mitglied_funktion mf
                     ON mf.mitglied_id = m.id
                    AND mf.deleted_at IS NULL
                    AND mf.von <= %s
                    AND (mf.bis IS NULL OR mf.bis >= %s)
                JOIN funktion f
                     ON f.key = mf.funktion AND f.deleted_at IS NULL
                JOIN funktion_permission fp
                     ON fp.funktion_id = f.id AND fp.deleted_at IS NULL
                LEFT JOIN abteilung a ON a.id = mf.abteilung_id
                WHERE m.user_id = %s AND m.deleted_at IS NULL
                """,
                (stichtag, stichtag, user_id),
            )
            funktion_rows = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT permission, effect, abteilung_id
                FROM user_permissions
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            override_rows = [dict(row) for row in cur.fetchall()]

        return compute_effective_permissions(funktion_rows, override_rows)

    def get_overrides_for_user(self, user_id: int) -> dict[str, set[str]]:
        """Individuelle Overrides eines Users, getrennt nach grant/deny."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT permission, effect
                FROM user_permissions
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return {
            'grants': {r['permission'] for r in rows if r['effect'] == 'grant'},
            'denies': {r['permission'] for r in rows if r['effect'] == 'deny'},
        }

    def set_overrides_for_user(
        self,
        user_id: int,
        grants: set[str],
        denies: set[str],
        actor: str,
    ) -> None:
        """Setzt die individuellen Overrides eines Users (Tri-State).

        grant/deny pro Permission; wegen UNIQUE(user_id, permission) existiert je
        Permission genau eine Zeile – ein Wechsel grant↔deny ist ein UPDATE des
        effect, Entfernen ein Soft-Delete, Hinzufügen ein Insert/Reaktivieren.
        Bei Überschneidung gewinnt deny.
        """
        desired: dict[str, str] = {p: 'grant' for p in grants}
        desired.update({p: 'deny' for p in denies})  # deny schlägt grant
        now = datetime.now().isoformat()

        with self.cursor() as cur:
            cur.execute(
                """
                SELECT permission, effect FROM user_permissions
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            current = {r['permission']: r['effect'] for r in cur.fetchall()}

            # Nicht mehr gewünschte Overrides soft-deleten
            for perm in current.keys() - desired.keys():
                cur.execute(
                    """
                    UPDATE user_permissions
                    SET deleted_at = %s, deleted_by = %s,
                        updated_at = %s, updated_by = %s, version = version + 1
                    WHERE user_id = %s AND permission = %s AND deleted_at IS NULL
                    """,
                    (now, actor, now, actor, user_id, perm),
                )

            for perm, effect in desired.items():
                if perm in current:
                    if current[perm] != effect:
                        cur.execute(
                            """
                            UPDATE user_permissions
                            SET effect = %s, updated_at = %s, updated_by = %s, version = version + 1
                            WHERE user_id = %s AND permission = %s AND deleted_at IS NULL
                            """,
                            (effect, now, actor, user_id, perm),
                        )
                    continue
                # Inaktive (soft-deleted) Zeile reaktivieren oder neu anlegen
                cur.execute(
                    "SELECT id FROM user_permissions WHERE user_id = %s AND permission = %s",
                    (user_id, perm),
                )
                if cur.fetchone():
                    cur.execute(
                        """
                        UPDATE user_permissions
                        SET deleted_at = NULL, deleted_by = NULL, effect = %s,
                            updated_at = %s, updated_by = %s, version = version + 1
                        WHERE user_id = %s AND permission = %s
                        """,
                        (effect, now, actor, user_id, perm),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO user_permissions
                            (user_id, permission, effect, created_at, created_by, updated_at, updated_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, perm, effect, now, actor, now, actor),
                    )

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
                        effect = 'grant',
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
