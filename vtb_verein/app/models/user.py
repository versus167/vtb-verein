"""
User-Modell für die Vereinsverwaltung
"""
from dataclasses import dataclass, field


@dataclass
class User:
    """Benutzer-Entität."""
    id: int
    username: str
    email: str
    password_hash: str
    role: str  # 'admin', 'user', 'readonly'
    active: bool
    last_login: str | None
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: str | None = None
    deleted_by: str | None = None
    # Wird nach dem Laden aus der DB befüllt (nicht in users-Tabelle)
    permissions: set[str] = field(default_factory=set)

    @staticmethod
    def get_available_roles() -> dict[str, str]:
        """Verfügbare Benutzerrollen."""
        return {
            'admin':    'Administrator – Volle Rechte inkl. Benutzerverwaltung',
            'user':     'Bearbeiter – Kann alle Inhaltsdaten lesen und schreiben',
            'readonly': 'Nur Lesen – Kann ausschließlich Daten ansehen',
        }

    def has_permission(self, permission: str) -> bool:
        """Prüft ob dieser User eine bestimmte Permission hat."""
        return permission in self.permissions

    def can_manage_users(self) -> bool:
        """Prüft ob User Benutzerverwaltung durchführen darf."""
        from app.models.permission import Permission
        return self.has_permission(Permission.USERS_MANAGE)

    def can_edit(self) -> bool:
        """Prüft ob User Mitgliedsdaten bearbeiten darf."""
        from app.models.permission import Permission
        return self.has_permission(Permission.MITGLIEDER_WRITE)

    def can_view(self) -> bool:
        """Prüft ob User Mitgliedsdaten ansehen darf."""
        from app.models.permission import Permission
        return self.active and self.has_permission(Permission.MITGLIEDER_READ)
