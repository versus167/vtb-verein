"""
User-Service mit Authentifizierung und Magic-Link-Funktionalität
"""
import bcrypt
from typing import Optional
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
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """
        Authentifiziert User mit Username und Passwort
        
        Args:
            username: Benutzername
            password: Passwort (Klartext)
            
        Returns:
            User-Objekt wenn erfolgreich, sonst None
        """
        user = self.user_repo.get_user_by_username(username)
        
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
        user = self.user_repo.get_user_by_email(email)
        
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
        user = self.user_repo.get_user_by_id(result['user_id'])
        
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
    
    def create_user(self, username: str, email: str, password: str, 
                   role: str, created_by: str) -> Optional[User]:
        """
        Erstellt neuen User
        
        Args:
            username: Benutzername
            email: E-Mail-Adresse
            password: Passwort (Klartext, wird gehasht)
            role: Rolle ('admin', 'user', 'special', 'readonly')
            created_by: Username des Erstellers
            
        Returns:
            User-Objekt wenn erfolgreich, sonst None
        """
        # Passwort hashen
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        try:
            user_id = self.user_repo.create_user(
                username=username,
                email=email,
                password_hash=password_hash,
                role=role,
                created_by=created_by
            )
            
            return self.user_repo.get_user_by_id(user_id)
        except Exception as e:
            print(f"❌ User-Erstellung fehlgeschlagen: {e}")
            return None
