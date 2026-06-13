"""
User-Modell für die Vereinsverwaltung
"""
from dataclasses import dataclass, field

from app.models.permission import EffectivePermissions


@dataclass
class User:
    """Benutzer-Entität."""
    id: int
    username: str
    email: str
    password_hash: str
    role: str  # 'admin' | 'mitglied' (seit Stufe D, siehe BERECHTIGUNGEN.md)
    active: bool
    last_login: str | None
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: str | None = None
    deleted_by: str | None = None

    last_seen: str | None = None                # letzter authentifizierter Request ("zuletzt aktiv")
    matrix_id: str | None = None                # Matrix-ID (z.B. @user:matrix.org)
    preferred_contact: str = 'email'            # 'email', 'matrix'
    
    # Wird nach dem Laden aus der DB befüllt (nicht in users-Tabelle).
    # permissions = flache effektive Key-Menge (lenient, inkl. Sockel + Funktionsrechte);
    # effective trägt zusätzlich Scope- und Herkunfts-Information (BERECHTIGUNGEN.md).
    permissions: set[str] = field(default_factory=set)
    effective: EffectivePermissions | None = None

    @staticmethod
    def get_available_roles() -> dict[str, str]:
        """Verfügbare Benutzerrollen (seit Stufe D nur noch admin/mitglied)."""
        return {
            'admin':    'Administrator – uneingeschränkter Zugriff',
            'mitglied': 'Mitglied – Rechte über Funktionen und individuelle Vergabe',
        }

    def has_permission(self, permission: str) -> bool:
        """Prüft ob dieser User eine bestimmte Permission hat. Admins haben immer alle.

        Lenient-Semantik: auch ein nur abteilungsgebunden geerbtes Recht erfüllt
        die Prüfung (Scope-Durchsetzung folgt in einer späteren Stufe, s. BERECHTIGUNGEN.md).
        """
        if self.role == 'admin':
            return True
        return permission in self.permissions

    def has_permission_global(self, permission: str) -> bool:
        """Nur vereinsweit wirksame Rechte (Sockel, vereinsweite Funktion, Grant)."""
        if self.role == 'admin':
            return True
        if self.effective is None:
            return permission in self.permissions
        return permission in self.effective.global_perms

    def has_permission_for_abteilung(self, permission: str, abteilung_id: int) -> bool:
        """Recht global ODER für die konkrete Abteilung geerbt."""
        if self.has_permission_global(permission):
            return True
        if self.effective is None:
            return False
        return abteilung_id in self.effective.scoped.get(permission, set())

    def allowed_abteilungen(self, permission: str) -> set[int] | None:
        """Abteilungs-Scope eines Rechts: None = global/alle, sonst erlaubte IDs.

        Vorbereitet für die Scope-Durchsetzung (Stufe E) – z. B. Listen-Filterung.
        """
        if self.has_permission_global(permission):
            return None
        if self.effective is None:
            return set()
        return set(self.effective.scoped.get(permission, set()))

    def can_manage_users(self) -> bool:
        from app.models.permission import Permission
        return self.has_permission(Permission.PERSONEN_PERMISSIONS)

    def can_edit(self) -> bool:
        from app.models.permission import Permission
        return self.has_permission(Permission.PERSONEN_WRITE)

    def can_view(self) -> bool:
        from app.models.permission import Permission
        return self.active and self.has_permission(Permission.PERSONEN_READ)
