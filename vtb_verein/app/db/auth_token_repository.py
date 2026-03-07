"""
Repository für Auth-Token Verwaltung
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.db.database import Database

class AuthTokenRepository:
    """Repository für Authentifizierungs-Token (Magic-Links, Remember-Me)"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def create_token(
        self, 
        user_id: int, 
        token_type: str, 
        expires_days: int = 7
    ) -> str:
        """
        Erstellt neuen Auth-Token
        
        Args:
            user_id: User-ID
            token_type: 'magic_link' oder 'remember_me'
            expires_days: Gültigkeit in Tagen
            
        Returns:
            Token-String (URL-safe)
        """
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=expires_days)
        
        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_tokens (
                    user_id, token, token_type, expires_at
                ) VALUES (?, ?, ?, ?)
                """,
                (user_id, token, token_type, expires_at.isoformat())
            )
        
        return token
    
    def validate_and_use_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validiert Token und markiert ihn als verwendet
        
        Args:
            token: Token-String
            
        Returns:
            Dict mit user_id und token_type wenn gültig, sonst None
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, token_type, expires_at, used_at
                FROM auth_tokens
                WHERE token = ?
                """,
                (token,)
            )
            row = cur.fetchone()
            
            if not row:
                return None
            
            # Prüfungen
            token_id = row['id']
            expires_at = datetime.fromisoformat(row['expires_at'])
            used_at = row['used_at']
            
            # Token bereits verwendet?
            if used_at:
                return None
            
            # Token abgelaufen?
            if datetime.now() > expires_at:
                return None
            
            # Token als verwendet markieren
            cur.execute(
                """
                UPDATE auth_tokens
                SET used_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (token_id,)
            )
            
            return {
                'user_id': row['user_id'],
                'token_type': row['token_type']
            }
    
    def cleanup_expired_tokens(self) -> int:
        """
        Löscht abgelaufene Tokens (Hard-Delete, kein Soft-Delete)
        
        Returns:
            Anzahl gelöschter Tokens
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                DELETE FROM auth_tokens
                WHERE expires_at < CURRENT_TIMESTAMP
                """
            )
            return cur.rowcount
    
    def revoke_user_tokens(self, user_id: int, token_type: Optional[str] = None):
        """
        Widerruft alle Tokens eines Users (optional nach Typ gefiltert)
        
        Args:
            user_id: User-ID
            token_type: Optional - nur Tokens dieses Typs widerrufen
        """
        with self.db.cursor() as cur:
            if token_type:
                cur.execute(
                    """
                    DELETE FROM auth_tokens
                    WHERE user_id = ? AND token_type = ?
                    """,
                    (user_id, token_type)
                )
            else:
                cur.execute(
                    """
                    DELETE FROM auth_tokens
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )
