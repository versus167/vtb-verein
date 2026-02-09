"""
User-Service für Benutzerverwaltung
"""
from typing import List, Optional
import bcrypt
from app.models.user import User
from app.db.datastore import VereinsDB

class UserService:
    """Service für Benutzerverwaltung"""
    
    def __init__(self, db: VereinsDB):
        self.db = db
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """
        Authentifiziert einen Benutzer
        
        Args:
            username: Benutzername
            password: Klartext-Passwort
            
        Returns:
            User-Objekt bei erfolgreicher Authentifizierung, sonst None
        """
        user = self.get_by_username(username)
        if not user or not user.active:
            return None
        
        if bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            # Letzten Login aktualisieren (ohne Version zu erhöhen)
            self._update_last_login(user.id)
            return user
        
        return None
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Findet User nach Benutzername (nur nicht gelöschte)"""
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE username = ? AND deleted_at IS NULL",
                (username,)
            )
            row = cur.fetchone()
            return self._row_to_user(row) if row else None
    
    def get_by_id(self, user_id: int) -> Optional[User]:
        """Findet User nach ID (nur nicht gelöschte)"""
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL",
                (user_id,)
            )
            row = cur.fetchone()
            return self._row_to_user(row) if row else None
    
    def list_all(self) -> List[User]:
        """Listet alle Benutzer (nur nicht gelöschte)"""
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE deleted_at IS NULL ORDER BY username"
            )
            return [self._row_to_user(row) for row in cur.fetchall()]
    
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
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role, active, 
                                   version, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (username, email, password_hash, role, active, created_by, created_by)
            )
            user_id = cur.lastrowid
        
        return self.get_by_id(user_id)
    
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
        user = self.get_by_id(user_id)
        if not user:
            raise ValueError(f"User mit ID {user_id} nicht gefunden")
        
        if expected_version is not None and user.version != expected_version:
            raise ValueError("Versionkonflikt - Datensatz wurde zwischenzeitlich geändert")
        
        # Nur übergebene Werte aktualisieren
        new_username = username if username is not None else user.username
        new_email = email if email is not None else user.email
        new_role = role if role is not None else user.role
        new_active = active if active is not None else user.active
        
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE users 
                SET username = ?, email = ?, role = ?, active = ?,
                    version = version + 1, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (new_username, new_email, new_role, new_active, updated_by, user_id, user.version)
            )
            if cur.rowcount == 0:
                raise ValueError("Update fehlgeschlagen - Versionkonflikt oder User gelöscht")
        
        return self.get_by_id(user_id)
    
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
        user = self.get_by_id(user_id)
        if not user:
            raise ValueError(f"User mit ID {user_id} nicht gefunden")
        
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE users 
                SET password_hash = ?, version = version + 1, 
                    updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (password_hash, updated_by, user_id, user.version)
            )
            if cur.rowcount == 0:
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
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (deleted_by, user_id)
            )
            return cur.rowcount == 1
    
    def _update_last_login(self, user_id: int):
        """Aktualisiert den letzten Login-Zeitstempel (ohne Version zu erhöhen)"""
        with self.db.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
                (user_id,)
            )
    
    def _row_to_user(self, row) -> User:
        """Konvertiert DB-Row zu User-Objekt"""
        return User(
            id=row[0],
            username=row[1],
            email=row[2],
            password_hash=row[3],
            role=row[4],
            active=bool(row[5]),
            last_login=row[6],
            version=row[7],
            created_at=row[8],
            created_by=row[9],
            updated_at=row[10],
            updated_by=row[11]
            # deleted_at=row[12] und deleted_by=row[13] werden nicht im User-Objekt gespeichert
            # da wir nur nicht-gelöschte User zurückgeben
        )
