"""
Authentication Helper für NiceGUI
"""
from nicegui import app, ui
from functools import wraps
from typing import Optional, Callable
from app.models.user import User

class AuthHelper:
    """Helper-Klasse für Authentifizierung und Session-Management"""
    
    @staticmethod
    def get_current_user() -> Optional[User]:
        """Gibt den aktuell eingeloggten User zurück"""
        user_data = app.storage.user.get('current_user')
        if user_data is None:
            return None
        
        # Falls es bereits ein User-Objekt ist (sollte nicht passieren, aber sicher ist sicher)
        if isinstance(user_data, User):
            return user_data
        
        # Dict zurück in User-Objekt konvertieren
        return User(**user_data)
    
    @staticmethod
    def set_current_user(user: User):
        """Setzt den aktuell eingeloggten User"""
        app.storage.user['current_user'] = user
        app.storage.user['authenticated'] = True
    
    @staticmethod
    def logout():
        """Loggt den aktuellen User aus"""
        app.storage.user.clear()
    
    @staticmethod
    def is_authenticated() -> bool:
        """Prüft ob ein User eingeloggt ist"""
        return app.storage.user.get('authenticated', False)
    
    @staticmethod
    def has_role(required_role: str) -> bool:
        """
        Prüft ob aktueller User eine bestimmte Rolle hat
        
        Args:
            required_role: 'admin', 'user', oder 'readonly'
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
