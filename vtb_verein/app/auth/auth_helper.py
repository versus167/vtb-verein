"""
Authentication Helper für NiceGUI
"""
from nicegui import app, ui
from functools import wraps
from typing import Optional, Callable
from datetime import datetime, timedelta
from app.models.user import User

class AuthHelper:
    """Helper-Klasse für Authentifizierung und Session-Management"""
    
    @staticmethod
    def get_current_user() -> Optional[User]:
        """Gibt den aktuell eingeloggten User zurück"""
        # Session-Ablauf prüfen
        if AuthHelper.is_session_expired():
            AuthHelper.logout()
            return None
        
        user_data = app.storage.user.get('current_user')
        if user_data is None:
            return None
        
        # Falls es bereits ein User-Objekt ist (sollte nicht passieren, aber sicher ist sicher)
        if isinstance(user_data, User):
            return user_data
        
        # Dict zurück in User-Objekt konvertieren
        return User(**user_data)
    
    @staticmethod
    def set_current_user(user: User, remember_me: bool = False):
        """
        Setzt den aktuell eingeloggten User mit rollenbezogener Session-Dauer
        
        Args:
            user: User-Objekt
            remember_me: Wenn True, wird Session verlngert
        """
        app.storage.user['current_user'] = user
        app.storage.user['authenticated'] = True
        app.storage.user['remember_me'] = remember_me
        
        # Session-Timeout basierend auf Rolle und Remember-Me
        timeout_days = AuthHelper._get_session_timeout_days(user.role, remember_me)
        expires_at = datetime.now() + timedelta(days=timeout_days)
        app.storage.user['session_expires'] = expires_at.isoformat()
        
        # Letzten Login-Zeitpunkt speichern
        app.storage.user['last_activity'] = datetime.now().isoformat()
    
    @staticmethod
    def _get_session_timeout_days(role: str, remember_me: bool) -> int:
        """
        Berechnet Session-Timeout in Tagen basierend auf Rolle
        
        Args:
            role: User-Rolle ('admin', 'user', 'special', 'readonly')
            remember_me: Remember-Me aktiviert?
            
        Returns:
            Anzahl Tage bis Session abläuft
        """
        if remember_me:
            # Verlängerte Sessions mit Remember-Me
            if role in ['admin', 'user']:
                return 30  # 30 Tage für Admins/Users
            elif role == 'special':
                return 14  # 14 Tage für Abteilungs-/Übungsleiter
            else:  # readonly
                return 7   # 7 Tage für Readonly
        else:
            # Standard-Sessions (ohne Remember-Me)
            return 1  # 24 Stunden für alle
    
    @staticmethod
    def is_session_expired() -> bool:
        """Prüft ob die aktuelle Session abgelaufen ist"""
        expires_str = app.storage.user.get('session_expires')
        if not expires_str:
            return False
        
        try:
            expires_at = datetime.fromisoformat(expires_str)
            return datetime.now() > expires_at
        except (ValueError, TypeError):
            return True
    
    @staticmethod
    def update_activity():
        """Aktualisiert letzten Aktivitäts-Zeitpunkt (für Idle-Timeout)"""
        if AuthHelper.is_authenticated():
            app.storage.user['last_activity'] = datetime.now().isoformat()
    
    @staticmethod
    def logout():
        """Loggt den aktuellen User aus"""
        app.storage.user.clear()
    
    @staticmethod
    def is_authenticated() -> bool:
        """Prüft ob ein User eingeloggt ist"""
        if app.storage.user.get('authenticated', False):
            # Session-Ablauf prüfen
            if AuthHelper.is_session_expired():
                AuthHelper.logout()
                return False
            return True
        return False
    
    @staticmethod
    def has_role(required_role: str) -> bool:
        """
        Prüft ob aktueller User eine bestimmte Rolle hat
        
        Args:
            required_role: 'admin', 'user', 'special' oder 'readonly'
        """
        user = AuthHelper.get_current_user()
        if not user:
            return False
        
        # Admin hat immer alle Rechte
        if user.role == 'admin':
            return True
        
        # User hat user + readonly Rechte
        if user.role == 'user' and required_role in ['user', 'readonly']:
            return True
        
        # Special hat special + readonly Rechte
        if user.role == 'special' and required_role in ['special', 'readonly']:
            return True
        
        # Readonly hat nur readonly Rechte
        if user.role == 'readonly' and required_role == 'readonly':
            return True
        
        return False
    
    @staticmethod
    def can_edit() -> bool:
        """Prüft ob aktueller User editieren darf"""
        user = AuthHelper.get_current_user()
        return user.can_edit() if user else False
    
    @staticmethod
    def can_manage_users() -> bool:
        """Prüft ob aktueller User User verwalten darf"""
        user = AuthHelper.get_current_user()
        return user.can_manage_users() if user else False


def require_auth(redirect_to: str = '/login'):
    """
    Decorator für Seiten die Authentifizierung erfordern
    
    Usage:
        @require_auth()
        def protected_page():
            ui.label('Diese Seite ist geschützt')
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not AuthHelper.is_authenticated():
                ui.navigate.to(redirect_to)
                return
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(required_role: str, redirect_to: str = '/unauthorized'):
    """
    Decorator für Seiten die eine bestimmte Rolle erfordern
    
    Usage:
        @require_role('admin')
        def admin_page():
            ui.label('Nur für Admins')
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not AuthHelper.is_authenticated():
                ui.navigate.to('/login')
                return
            
            if not AuthHelper.has_role(required_role):
                ui.navigate.to(redirect_to)
                return
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_edit_permission(redirect_to: str = '/unauthorized'):
    """
    Decorator für Seiten/Funktionen die Edit-Rechte erfordern
    
    Usage:
        @require_edit_permission()
        def edit_member():
            ui.label('Mitglied bearbeiten')
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not AuthHelper.is_authenticated():
                ui.navigate.to('/login')
                return
            
            if not AuthHelper.can_edit():
                ui.navigate.to(redirect_to)
                return
            
            return func(*args, **kwargs)
        return wrapper
    return decorator
