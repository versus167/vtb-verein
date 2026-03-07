"""
User-Service mit Authentifizierung und Magic-Link-Funktionalität
"""
import bcrypt
from typing import Optional, List
from datetime import datetime
from app.models.user import User
from app.db.datastore import VereinsDB
from app.services.email_service import EmailService
from app.config.email_config import EmailConfig

class UserService:
    """Service für User-Verwaltung und Authentifizierung"""
    
    def __init__(self, db: VereinsDB):
        self.db = db
        self.user_repo = db.user_repository
        self.token_repo = db.auth_token_repository
    
    # ============================================
    # Authentifizierung
    # ============================================
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """
        Authentifiziert User mit Username und Passwort
        
        Args:
            username: Benutzername
            password: Passwort (Klartext)
            
        Returns:
            User-Objekt wenn erfolgreich, sonst None
        """
        user = self.user_repo.get_by_username(username)
        
        if not user:
            return None
        
        if not user.active:
            return None
        
        # Passwort prüfen
        if bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            # Last-Login aktualisieren
            self.user_repo.update_last_login(user.id)
            return user
        
        return None
    
    # ============================================
    # Magic-Link Authentication
    # ============================================
    
    def send_magic_link(self, email: str) -> bool:
        """
        Sendet Magic-Link an User per E-Mail
        
        Args:
            email: E-Mail-Adresse des Users
            
        Returns:
            True wenn erfolgreich, False wenn E-Mail nicht gefunden oder Versand fehlgeschlagen
        """
        # E-Mail-Konfiguration prüfen
        if not EmailConfig.is_configured():
            print("⚠️  E-Mail nicht konfiguriert. Bitte .env-Datei prüfen.")
            return False
        
        # User anhand E-Mail finden
        user = self.user_repo.get_by_email(email)
        
        if not user:
            print(f"⚠️  Keine User mit E-Mail {email} gefunden")
            return False
        
        if not user.active:
            print(f"⚠️  User {user.username} ist deaktiviert")
            return False
        
        # Token erstellen (7 Tage Gültigkeit)
        token = self.token_repo.create_token(
            user_id=user.id,
            token_type='magic_link',
            expires_days=7
        )
        
        # E-Mail senden
        success = EmailService.send_magic_link(
            recipient_email=email,
            token=token,
            username=user.username
        )
        
        if success:
            print(f"✅ Magic-Link gesendet an {email} für User {user.username}")
        else:
            print(f"❌ E-Mail-Versand fehlgeschlagen an {email}")
        
        return success
    
    def validate_magic_link(self, token: str) -> Optional[User]:
        """
        Validiert Magic-Link-Token und gibt User zurück
        
        Args:
            token: Magic-Link-Token
            
        Returns:
            User-Objekt wenn Token gültig, sonst None
        """
        # Token validieren und als verwendet markieren
        result = self.token_repo.validate_and_use_token(token)
        
        if not result:
            print("❌ Token ungültig oder bereits verwendet")
            return None
        
        if result['token_type'] != 'magic_link':
            print(f"❌ Falscher Token-Typ: {result['token_type']}")
            return None
        
        # User laden
        user = self.user_repo.get_by_id(result['user_id'])
        
        if not user:
            print(f"❌ User mit ID {result['user_id']} nicht gefunden")
            return None
        
        if not user.active:
            print(f"❌ User {user.username} ist deaktiviert")
            return None
        
        # Last-Login aktualisieren
        self.user_repo.update_last_login(user.id)
        
        print(f"✅ Magic-Link-Login erfolgreich für User {user.username}")
        return user
    
    # ============================================
    # User-Management (CRUD)
    # ============================================
    
    def list_all(self) -> List[User]:
        """Liste alle User"""
        return self.user_repo.list_all()
    
    def get_by_id(self, user_id: int) -> Optional[User]:
        """User anhand ID laden"""
        return self.user_repo.get_by_id(user_id)
    
    def count_active_admins(self) -> int:
        """Zähle aktive Administratoren"""
        return self.user_repo.count_active_admins()
    
    def create(self, username: str, email: str, password: str, role: str, 
               active: bool, created_by: str) -> User:
        """
        Erstellt neuen User
        
        Args:
            username: Benutzername
            email: E-Mail-Adresse
            password: Passwort (Klartext, wird gehasht)
            role: Rolle ('admin', 'user', 'special', 'readonly')
            active: Aktiv-Status
            created_by: Username des Erstellers
            
        Returns:
            Erstellter User
            
        Raises:
            ValueError: Bei ungültigen Daten oder Duplikaten
        """
        # Validierung
        if not username or not email or not password:
            raise ValueError("Username, E-Mail und Passwort dürfen nicht leer sein")
        
        if len(password) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen lang sein")
        
        # Passwort hashen
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # User erstellen
        return self.user_repo.create(
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            created_by=created_by,
            active=active
        )
    
    def update(self, user_id: int, username: str, email: str, role: str,
               active: bool, updated_by: str, expected_version: int) -> bool:
        """
        Aktualisiert User-Daten (ohne Passwort)
        
        Args:
            user_id: ID des Users
            username: Neuer Username
            email: Neue E-Mail
            role: Neue Rolle
            active: Neuer Aktiv-Status
            updated_by: Username des Updaters
            expected_version: Erwartete Version (Optimistic Locking)
            
        Returns:
            True wenn erfolgreich
            
        Raises:
            ValueError: Bei Validierungsfehlern oder Versionskonflikten
        """
        # Prüfe "letzter Admin" Constraint
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User nicht gefunden")
        
        # Wenn aktuell ein aktiver Admin -> inaktiv oder herabgestuft wird
        if user.role == 'admin' and user.active:
            will_be_deactivated = (role == 'admin' and not active)
            will_be_demoted = (role != 'admin')
            
            if (will_be_deactivated or will_be_demoted):
                if self.user_repo.count_active_admins() <= 1:
                    raise ValueError("Der letzte aktive Administrator kann nicht deaktiviert oder herabgestuft werden")
        
        # Update durchführen
        success = self.user_repo.update(
            user_id=user_id,
            username=username,
            email=email,
            role=role,
            active=active,
            updated_by=updated_by,
            expected_version=expected_version
        )
        
        if not success:
            raise ValueError("Update fehlgeschlagen - möglicher Versionskonflikt")
        
        return True
    
    def change_password(self, user_id: int, new_password: str, updated_by: str) -> bool:
        """
        Ändert Passwort eines Users
        
        Args:
            user_id: ID des Users
            new_password: Neues Passwort (Klartext)
            updated_by: Username des Updaters
            
        Returns:
            True wenn erfolgreich
            
        Raises:
            ValueError: Bei ungültigem Passwort oder User nicht gefunden
        """
        if len(new_password) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen lang sein")
        
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User nicht gefunden")
        
        # Passwort hashen
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Update durchführen
        success = self.user_repo.update_password(
            user_id=user_id,
            password_hash=password_hash,
            updated_by=updated_by,
            expected_version=user.version
        )
        
        if not success:
            raise ValueError("Passwort-Änderung fehlgeschlagen")
        
        return True
    
    def delete(self, user_id: int, deleted_by: str) -> bool:
        """
        Löscht User (Soft-Delete)
        
        Args:
            user_id: ID des Users
            deleted_by: Username des Löschenden
            
        Returns:
            True wenn erfolgreich
            
        Raises:
            ValueError: Wenn letzter aktiver Admin gelöscht werden soll
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User nicht gefunden")
        
        # Prüfe "letzter Admin" Constraint
        if user.role == 'admin' and user.active:
            if self.user_repo.count_active_admins() <= 1:
                raise ValueError("Der letzte aktive Administrator kann nicht gelöscht werden")
        
        # Soft-Delete durchführen
        success = self.user_repo.mark_user_deleted(user_id, deleted_by)
        
        if not success:
            raise ValueError("Löschen fehlgeschlagen")
        
        return True
