"""
Repository für Auth-Token Verwaltung
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
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

    def create_magic_link_mit_code(
        self,
        user_id: int,
        code_hash_fn,
        expires_days: int = 7,
        code_minuten: int = 15,
    ) -> Tuple[str, str]:
        """Login-Link samt 6-stelligem Login-Code in EINER Zeile (Ticket #208).

        Der Code ist für die installierte App gedacht: Ein Link aus der Mail öffnet
        am Handy den Browser, dessen Cookies die App nicht sieht. Weil Link und Code
        dieselbe Zeile teilen, verbraucht das Einlösen des einen auch das andere.

        Der Code hat nur 20 Bit – ein schneller Hash wäre in Mikrosekunden
        zurückgerechnet. Deshalb hasht der Aufrufer ihn mit einem Server-Geheimnis
        (`code_hash_fn`, HMAC); wer nur die DB liest, kommt damit nicht weiter.

        Returns:
            (Token-Klartext für den Link, Code-Klartext für die Mail)
        """
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(10 ** 6):06d}"
        expires_at = datetime.now() + timedelta(days=expires_days)
        code_expires_at = datetime.now() + timedelta(minutes=code_minuten)

        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_tokens (
                    user_id, token_hash, token_type, expires_at, code_hash, code_expires_at
                ) VALUES (%s, %s, 'magic_link', %s, %s, %s)
                """,
                (user_id, self._hash_token(token), expires_at.isoformat(),
                 code_hash_fn(code), code_expires_at.isoformat())
            )

        return token, code

    def loese_code_ein(self, user_id: int, code_hash: str, max_versuche: int) -> bool:
        """Löst den Login-Code des jüngsten offenen Login-Links ein.

        Nur der jüngste Link zählt: Wer mehrfach anfordert, nimmt den Code aus der
        neuesten Mail. Ist dessen Code gesperrt, wird nicht auf ältere ausgewichen –
        sonst multiplizierte jede weitere Anforderung die erlaubten Rateversuche.

        Zweistufig und dadurch dicht:
        1. Versuch zählen – atomar und nur, solange noch Versuche frei sind. Damit
           sind es auch bei parallelen Anfragen nie mehr als `max_versuche`.
        2. Nur bei passendem Code `used_at` setzen, mit `used_at IS NULL` im WHERE:
           Ein zeitgleicher Klick auf den Link kann nicht beide gewinnen lassen.

        Returns:
            True, wenn der Code gepasst hat und der Link damit verbraucht ist.
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_tokens
                   SET code_versuche = code_versuche + 1
                 WHERE id = (
                        SELECT id FROM auth_tokens
                         WHERE user_id = %s
                           AND token_type = 'magic_link'
                           AND used_at IS NULL
                           AND code_hash IS NOT NULL
                         ORDER BY id DESC
                         LIMIT 1
                       )
                   AND used_at IS NULL
                   AND code_expires_at > %s
                   AND code_versuche < %s
                RETURNING id, code_hash
                """,
                (user_id, datetime.now().isoformat(), max_versuche)
            )
            row = cur.fetchone()
            if not row or not hmac.compare_digest(row['code_hash'], code_hash):
                return False
            cur.execute(
                """
                UPDATE auth_tokens SET used_at = CURRENT_TIMESTAMP
                 WHERE id = %s AND used_at IS NULL
                RETURNING id
                """,
                (row['id'],)
            )
            return cur.fetchone() is not None

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
    
    def entwerte_offene_tokens(self, user_id: int, token_type: Optional[str] = None) -> int:
        """Entwertet alle noch offenen Tokens eines Users – ohne sie zu löschen.

        Gesetzt wird `used_at`, genau wie beim Einlösen: Ein damit entwerteter Link
        läuft danach in denselben Zweig wie ein bereits benutzter ("invalid_or_used"),
        und die Zeile bleibt als Spur erhalten (vgl. `revoke_user_tokens`, das hart
        löscht und deshalb hier nicht in Frage kommt).

        Gebraucht beim Wechsel der Login-Adresse: Der Link, der an die alte Adresse
        ging, darf danach nicht mehr in das Konto führen.

        Returns:
            Anzahl der entwerteten Tokens
        """
        with self.db.cursor() as cur:
            sql = """
                UPDATE auth_tokens SET used_at = CURRENT_TIMESTAMP
                 WHERE user_id = %s AND used_at IS NULL
            """
            params = [user_id]
            if token_type:
                sql += " AND token_type = %s"
                params.append(token_type)
            cur.execute(sql, tuple(params))
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
