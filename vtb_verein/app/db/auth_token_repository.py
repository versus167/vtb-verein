"""
Repository für Auth-Token Verwaltung
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.db.database import Database

class AuthTokenRepository:
    """Repository für Authentifizierungs-Token (Magic-Links, Remember-Me)

    Sicherheit: In der DB liegt ausschließlich der SHA-256-Hash des Tokens
    (Spalte `token_hash`), nie der Klartext. Der Klartext-Token wird nur einmal
    beim Erstellen zurückgegeben (für den Magic-Link) und ist danach nicht mehr
    rekonstruierbar – bei einem DB-Leak sind die Hashes für einen Angreifer
    wertlos. Tokens haben 256 Bit Entropie (`secrets.token_urlsafe(32)`), daher
    genügt ein schneller Hash; ein Passwort-KDF (bcrypt o. Ä.) ist nicht nötig.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _hash_token(token: str) -> str:
        """SHA-256-Hex-Digest des Tokens – das, was tatsächlich in der DB landet."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

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
            Token-Klartext (URL-safe) – wird nur hier zurückgegeben, in der DB
            steht nur dessen Hash.
        """
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=expires_days)

        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_tokens (
                    user_id, token_hash, token_type, expires_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (user_id, self._hash_token(token), token_type, expires_at.isoformat())
            )

        return token

    def validate_and_use_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validiert Token und markiert ihn atomar als verwendet (Single-Use).

        Prüfung (nicht verwendet + nicht abgelaufen) und Markierung passieren in
        EINEM UPDATE … WHERE … RETURNING. Damit gibt es kein TOCTOU-Fenster: zwei
        gleichzeitige Einlösungen desselben Tokens können sich nicht gegenseitig
        überholen – höchstens eine bekommt eine Zeile zurück.

        Args:
            token: Token-Klartext (wird zum Vergleich gehasht)

        Returns:
            Dict mit user_id und token_type wenn gültig, sonst None
        """
        token_hash = self._hash_token(token)
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_tokens
                SET used_at = CURRENT_TIMESTAMP
                WHERE token_hash = %s
                  AND used_at IS NULL
                  AND expires_at > %s
                RETURNING user_id, token_type
                """,
                (token_hash, datetime.now().isoformat())
            )
            row = cur.fetchone()
            if not row:
                return None
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
                    WHERE user_id = %s AND token_type = %s
                    """,
                    (user_id, token_type)
                )
            else:
                cur.execute(
                    """
                    DELETE FROM auth_tokens
                    WHERE user_id = %s
                    """,
                    (user_id,)
                )
