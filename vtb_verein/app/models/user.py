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
    role: str  # 'admin', 'user', 'readonly', 'special'
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
            'readonly': 'Nur Lesen - Kann nur Daten ansehen',
            'special': 'Spezielle Funktion - Nur über zugewiesene Bereiche (Abteilungsleiter, Übungsleiter)'
        }
    
    def can_manage_users(self) -> bool:
        """Prüft ob User Benutzerverwaltung durchführen darf"""
        return self.role == 'admin'
    
    def can_edit(self) -> bool:
        """Prüft ob User Daten bearbeiten darf"""
        return self.role in ['admin', 'user']
    
    def can_view(self) -> bool:
        """Prüft ob User Daten ansehen darf"""
        # Special-Rolle kann ansehen, aber nur in speziellen Bereichen
        # Die Berechtigung wird dann in den jeweiligen Features geprüft
        return self.active and self.role != 'special'
    
    def has_special_role(self) -> bool:
        """Prüft ob User eine spezielle Funktion hat (Abteilungsleiter, Übungsleiter)"""
        return self.role == 'special'
