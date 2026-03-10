"""
Permission-Konstanten für die Vereinsverwaltung.

Jede Permission hat die Form 'ressource.aktion'.
Rollen werden beim Anlegen eines Users als Default-Permissions vergeben.
"""
from dataclasses import dataclass, field


class Permission:
    """Alle verfügbaren Permissions als Konstanten."""

    # --- Mitglieder ---
    MITGLIEDER_READ   = 'mitglieder.read'
    MITGLIEDER_WRITE  = 'mitglieder.write'
    MITGLIEDER_DELETE = 'mitglieder.delete'   # Soft-Delete

    # --- Abteilungen ---
    ABTEILUNGEN_READ  = 'abteilungen.read'
    ABTEILUNGEN_WRITE = 'abteilungen.write'
    ABTEILUNGEN_DELETE = 'abteilungen.delete'

    # --- Beiträge ---
    BEITRAEGE_READ    = 'beitraege.read'
    BEITRAEGE_WRITE   = 'beitraege.write'

    # --- Berichte / Export ---
    BERICHTE_READ     = 'berichte.read'
    BERICHTE_EXPORT   = 'berichte.export'

    # --- Benutzerverwaltung ---
    USERS_READ        = 'users.read'
    USERS_MANAGE      = 'users.manage'        # Erstellen, Bearbeiten, Deaktivieren

    # --- System ---
    SYSTEM_CONFIG     = 'system.config'       # App-Konfiguration

    @classmethod
    def all(cls) -> list[str]:
        """Alle definierten Permissions."""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith('_') and isinstance(v, str)
        ]

    @classmethod
    def defaults_for_role(cls, role: str) -> set[str]:
        """
        Gibt die Standard-Permissions für eine Rolle zurück.
        Diese werden beim Anlegen eines Users automatisch gesetzt.

        Args:
            role: 'admin', 'user' oder 'readonly'

        Returns:
            Set mit Permission-Strings
        """
        if role == 'admin':
            return set(cls.all())

        if role == 'user':
            return {
                cls.MITGLIEDER_READ,
                cls.MITGLIEDER_WRITE,
                cls.MITGLIEDER_DELETE,
                cls.ABTEILUNGEN_READ,
                cls.ABTEILUNGEN_WRITE,
                cls.ABTEILUNGEN_DELETE,
                cls.BEITRAEGE_READ,
                cls.BEITRAEGE_WRITE,
                cls.BERICHTE_READ,
                cls.BERICHTE_EXPORT,
                cls.USERS_READ,
            }

        if role == 'readonly':
            return {
                cls.MITGLIEDER_READ,
                cls.ABTEILUNGEN_READ,
                cls.BEITRAEGE_READ,
                cls.BERICHTE_READ,
            }

        # Unbekannte Rolle: keine Permissions
        return set()


@dataclass
class UserPermission:
    """Einzelner Permission-Eintrag für einen User (entspricht einer DB-Zeile)."""
    id: int
    user_id: int
    permission: str
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: str | None = None
    deleted_by: str | None = None
