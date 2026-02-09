"""
User-Modell für die Vereinsverwaltung
"""
from dataclasses import dataclass

@dataclass
class User:
    """Benutzer-Entität"""
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
    
    @staticmethod
    def get_available_roles():
        """Verfügbare Benutzerrollen"""
        return {
            'admin': 'Administrator - Volle Rechte inkl. Benutzerverwaltung',
            'user': 'Bearbeiter - Kann alle Daten editieren',
            'readonly': 'Nur Lesen - Kann nur Daten ansehen'
        }
    
    def can_manage_users(self) -> bool:
        """Prüft ob User Benutzerverwaltung durchführen darf"""
        return self.role == 'admin'
    
    def can_edit(self) -> bool:
        """Prüft ob User Daten bearbeiten darf"""
        return self.role in ['admin', 'user']
    
    def can_view(self) -> bool:
        """Prüft ob User Daten ansehen darf"""
        return self.active  # Alle aktiven User können ansehen
