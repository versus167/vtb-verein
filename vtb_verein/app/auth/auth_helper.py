"""
Authentication Helper für NiceGUI
"""
from nicegui import app, ui
from functools import wraps
from typing import Optional, Callable
from datetime import datetime, timedelta
from app.models.user import User
from app.models.permission import Permission


class AuthHelper:
    """Helper-Klasse für Authentifizierung und Session-Management."""

    @staticmethod
    def get_current_user() -> Optional[User]:
        """Gibt den aktuell eingeloggten User zurück."""
        if AuthHelper.is_session_expired():
            AuthHelper.logout()
            return None

        user_data = app.storage.user.get('current_user')
        if user_data is None:
            return None

        if isinstance(user_data, User):
            return user_data

        # Dict → User-Objekt konvertieren; permissions als set wiederherstellen
        user_dict = dict(user_data)
        user_dict['permissions'] = set(user_dict.get('permissions', []))
        return User(**user_dict)

    @staticmethod
    def set_current_user(user: User, remember_me: bool = False):
        """
        Setzt den aktuell eingeloggten User mit rollenbezogener Session-Dauer.

        Args:
            user:        User-Objekt (inkl. befülltem permissions-Set)
            remember_me: Wenn True, wird Session verlängert
        """
        # permissions-Set für Storage serialisierbar machen
        user_dict = {
            k: (list(v) if isinstance(v, set) else v)
            for k, v in user.__dict__.items()
        }
        app.storage.user['current_user'] = user_dict
        app.storage.user['authenticated'] = True
        app.storage.user['remember_me'] = remember_me

        timeout_days = AuthHelper._get_session_timeout_days(user.role, remember_me)
        expires_at = datetime.now() + timedelta(days=timeout_days)
        app.storage.user['session_expires'] = expires_at.isoformat()
        app.storage.user['last_activity'] = datetime.now().isoformat()

    @staticmethod
    def _get_session_timeout_days(role: str, remember_me: bool) -> int:
        """
        Berechnet Session-Timeout in Tagen basierend auf Rolle.

        Args:
            role:        User-Rolle ('admin', 'user', 'readonly')
            remember_me: Remember-Me aktiviert?

        Returns:
            Anzahl Tage bis Session abläuft
        """
        if remember_me:
            return 30 if role in ['admin', 'user'] else 7
        return 1  # 24 Stunden ohne Remember-Me

    @staticmethod
    def is_session_expired() -> bool:
        """Prüft ob die aktuelle Session abgelaufen ist."""
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
        """Aktualisiert letzten Aktivitäts-Zeitpunkt (für Idle-Timeout)."""
        if AuthHelper.is_authenticated():
            app.storage.user['last_activity'] = datetime.now().isoformat()

    @staticmethod
    def logout():
        """Loggt den aktuellen User aus."""
        app.storage.user.clear()

    @staticmethod
    def is_authenticated() -> bool:
        """Prüft ob ein User eingeloggt ist."""
        if app.storage.user.get('authenticated', False):
            if AuthHelper.is_session_expired():
                AuthHelper.logout()
                return False
            return True
        return False

    @staticmethod
    def has_permission(permission: str) -> bool:
        """
        Prüft ob der aktuelle User eine bestimmte Permission hat.

        Args:
            permission: Permission-String, z.B. 'mitglieder.write'

        Returns:
            True wenn Permission vorhanden, sonst False
        """
        user = AuthHelper.get_current_user()
        if not user:
            return False
        return user.has_permission(permission)

    @staticmethod
    def can_edit() -> bool:
        """Prüft ob aktueller User Mitgliedsdaten bearbeiten darf."""
        return AuthHelper.has_permission(Permission.MITGLIEDER_WRITE)

    @staticmethod
    def can_manage_users() -> bool:
        """Prüft ob aktueller User User verwalten darf."""
        return AuthHelper.has_permission(Permission.USERS_MANAGE)


def require_auth(redirect_to: str = '/login'):
    """
    Decorator für Seiten die Authentifizierung erfordern.

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


def require_permission(permission: str, redirect_to: str = '/unauthorized'):
    """
    Decorator für Seiten/Funktionen die eine bestimmte Permission erfordern.

    Usage:
        @require_permission(Permission.MITGLIEDER_WRITE)
        def edit_member():
            ui.label('Mitglied bearbeiten')
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not AuthHelper.is_authenticated():
                ui.navigate.to('/login')
                return
            if not AuthHelper.has_permission(permission):
                ui.navigate.to(redirect_to)
                return
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_edit_permission(redirect_to: str = '/unauthorized'):
    """
    Decorator für Seiten/Funktionen die Edit-Rechte erfordern.
    Kurzform für @require_permission(Permission.MITGLIEDER_WRITE).

    Usage:
        @require_edit_permission()
        def edit_member():
            ui.label('Mitglied bearbeiten')
    """
    return require_permission(Permission.MITGLIEDER_WRITE, redirect_to)


# Legacy-Alias – wird entfernt sobald alle Aufrufe auf require_permission umgestellt sind
def require_role(required_role: str, redirect_to: str = '/unauthorized'):
    """
    DEPRECATED: Bitte require_permission() verwenden.
    Nur noch als Kompatibilitäts-Shim vorhanden.
    """
    from app.models.permission import Permission
    _role_to_permission = {
        'admin':    Permission.USERS_MANAGE,
        'user':     Permission.MITGLIEDER_WRITE,
        'readonly': Permission.MITGLIEDER_READ,
        'special':  Permission.ABTEILUNGEN_READ,
    }
    perm = _role_to_permission.get(required_role, Permission.MITGLIEDER_READ)
    return require_permission(perm, redirect_to)
