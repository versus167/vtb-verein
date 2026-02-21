'''
User-Service für Benutzerverwaltung

Refactored to use UserRepository for data access.
'''
from typing import List, Optional
import bcrypt
from app.models.user import User
from app.db.datastore import VereinsDB

class UserService:
    """Service für Benutzerverwaltung.
    
    Handles business logic:
    - Password hashing and verification
    - Last admin protection
    - Authentication workflow
    
    Data access is delegated to UserRepository via VereinsDB.
    """
    
    def __init__(self, db: VereinsDB):
        self.db = db
        # Access repository through VereinsDB facade
        self._user_repo = db._user_repo
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """
        Authentifiziert einen Benutzer
        
        Args:
            username: Benutzername
            password: Klartext-Passwort
            
        Returns:
            User-Objekt bei erfolgreicher Authentifizierung, sonst None
        """
        user = self._user_repo.get_by_username(username)
        if not user or not user.active:
            return None
        
        if bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            # Letzten Login aktualisieren (ohne Version zu erhöhen)
            self._user_repo.update_last_login(user.id)
            return user
        
        return None
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Findet User nach Benutzername (nur nicht gelöschte)"""
        return self._user_repo.get_by_username(username)
    
    def get_by_id(self, user_id: int) -> Optional[User]:
        """Findet User nach ID (nur nicht gelöschte)"""
        return self._user_repo.get_by_id(user_id)
    
    def list_all(self) -> List[User]:
        """Listet alle Benutzer (nur nicht gelöschte)"""
        return self._user_repo.list_all()
    
    def count_active_admins(self) -> int:
        """Zählt die Anzahl aktiver Administratoren"""
        return self._user_repo.count_active_admins()
    
    def create(self, username: str, email: str, password: str, role: str, 
               created_by: str, active: bool = True) -> User:
        """
        Erstellt neuen Benutzer
        
        Args:
            username: Eindeutiger Benutzername
            email: E-Mail-Adresse
            password: Klartext-Passwort (wird gehasht)
            role: Rolle ('admin', 'user', 'readonly')
            created_by: Username des Erstellers
            active: Ob User aktiv ist
            
        Returns:
            Erstellter User (History wird automatisch durch Trigger geschrieben)
        """
        # Business Logic: Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Delegate to repository
        return self._user_repo.create(username, email, password_hash, role, created_by, active)
    
    def update(self, user_id: int, username: str = None, email: str = None,
               role: str = None, active: bool = None, updated_by: str = None,
               expected_version: int = None) -> User:
        """
        Aktualisiert Benutzerdaten (ohne Passwort)
        
        Args:
            user_id: ID des zu aktualisierenden Users
            username: Neuer Benutzername (optional)
            email: Neue E-Mail (optional)
            role: Neue Rolle (optional)
            active: Neuer aktiv-Status (optional)
            updated_by: Username des Bearbeiters
            expected_version: Erwartete Version für optimistic locking
            
        Returns:
            Aktualisierter User (History wird automatisch durch Trigger geschrieben)
        """
        user = self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User mit ID {user_id} nicht gefunden")
        
        if expected_version is not None and user.version != expected_version:
            raise ValueError("Versionkonflikt - Datensatz wurde zwischenzeitlich geändert")
        
        # Nur übergebene Werte aktualisieren
        new_username = username if username is not None else user.username
        new_email = email if email is not None else user.email
        new_role = role if role is not None else user.role
        new_active = active if active is not None else user.active
        
        # Business Logic: Prüfen, ob der letzte aktive Admin betroffen ist
        user_is_currently_active_admin = (user.role == 'admin' and user.active)
        user_will_be_active_admin = (new_role == 'admin' and new_active)
        
        if user_is_currently_active_admin and not user_will_be_active_admin:
            if self._user_repo.count_active_admins() <= 1:
                raise ValueError("Der letzte aktive Administrator kann nicht herabgestuft oder deaktiviert werden")
        
        # Delegate to repository
        success = self._user_repo.update(
            user_id, new_username, new_email, new_role, new_active, 
            updated_by, user.version
        )
        
        if not success:
            raise ValueError("Update fehlgeschlagen - Versionkonflikt oder User gelöscht")
        
        return self._user_repo.get_by_id(user_id)
    
    def change_password(self, user_id: int, new_password: str, updated_by: str) -> bool:
        """
        Ändert das Passwort eines Benutzers
        
        Args:
            user_id: ID des Users
            new_password: Neues Klartext-Passwort
            updated_by: Username des Bearbeiters
            
        Returns:
            True bei Erfolg (History wird automatisch durch Trigger geschrieben)
        """
        # Aktuellen User holen für Version-Check
        user = self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User mit ID {user_id} nicht gefunden")
        
        # Business Logic: Hash password
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Delegate to repository
        success = self._user_repo.update_password(user_id, password_hash, updated_by, user.version)
        
        if not success:
            raise ValueError("Passwort-Änderung fehlgeschlagen - Versionkonflikt oder User gelöscht")
        
        return True
    
    def delete(self, user_id: int, deleted_by: str) -> bool:
        """
        Löscht einen Benutzer (soft delete)
        History wird automatisch durch Trigger geschrieben
        
        Args:
            user_id: ID des zu löschenden Users
            deleted_by: Username des Löschenden
            
        Returns:
            True bei Erfolg
        """
        # Business Logic: Prüfen, ob der letzte aktive Admin gelöscht werden soll
        user = self._user_repo.get_by_id(user_id)
        if user and user.role == 'admin' and user.active:
            if self._user_repo.count_active_admins() <= 1:
                raise ValueError("Der letzte aktive Administrator kann nicht gelöscht werden")
        
        # Delegate to repository
        return self._user_repo.mark_user_deleted(user_id, deleted_by)
