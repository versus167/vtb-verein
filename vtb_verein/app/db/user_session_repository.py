"""
Repository für serverseitige Sessions ("angemeldete Geräte", Ticket #24).

Jeder Login legt eine Session-Zeile an; ihre ID (sid) wandert in den JWT.
So lassen sich angemeldete Geräte auflisten und einzeln bzw. "en bloc"
abmelden. Abmelden ist Soft-Revoke (revoked_at) – kein Hard-Delete.
"""
import re
import secrets
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.db.database import Database


def derive_device_label(user_agent: Optional[str]) -> str:
    """Leitet aus dem User-Agent eine menschenlesbare Geräte-Bezeichnung ab.

    Bewusst grob (kein UA-Parser als Dependency) – "<Browser> auf <OS>",
    z. B. "Chrome auf Windows". Fällt auf "Unbekanntes Gerät" zurück.
    """
    if not user_agent:
        return "Unbekanntes Gerät"
    ua = user_agent

    # Betriebssystem (vor Browser, da iOS/Android auch "Safari"/"Chrome" tragen)
    if "Android" in ua:
        os_name = "Android"
    elif re.search(r"iPhone|iPad|iPod", ua):
        os_name = "iPhone/iPad"
    elif "Windows" in ua:
        os_name = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = None

    # Browser (Reihenfolge wichtig: Edge/Opera tragen auch "Chrome")
    if "Edg" in ua:
        browser = "Edge"
    elif "OPR" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Chrome" in ua or "CriOS" in ua:
        browser = "Chrome"
    elif "Firefox" in ua or "FxiOS" in ua:
        browser = "Firefox"
    elif "Safari" in ua:
        browser = "Safari"
    else:
        browser = None

    if browser and os_name:
        return f"{browser} auf {os_name}"
    if browser:
        return browser
    if os_name:
        return os_name
    return "Unbekanntes Gerät"


class UserSessionRepository:
    """Repository für serverseitige Login-Sessions (angemeldete Geräte)."""

    def __init__(self, db: Database):
        self.db = db

    def create_session(
        self,
        user_id: int,
        expires_at: datetime,
        user_agent: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> str:
        """Legt eine neue Session an und gibt ihre sid zurück (für den JWT)."""
        sid = secrets.token_urlsafe(32)
        device_label = derive_device_label(user_agent)
        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_sessions (
                    user_id, sid, user_agent, ip, device_label, expires_at, last_seen_at
                ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (user_id, sid, user_agent, ip, device_label, expires_at.isoformat()),
            )
        return sid

    def get_active_session(self, sid: str) -> Optional[Dict[str, Any]]:
        """Gibt die aktive (nicht widerrufene, nicht abgelaufene) Session zurück."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, sid, expires_at, revoked_at
                FROM user_sessions
                WHERE sid = %s
                  AND revoked_at IS NULL
                  AND expires_at::timestamptz > now()
                """,
                (sid,),
            )
            return cur.fetchone()

    def touch_session(self, sid: str) -> bool:
        """Aktualisiert last_seen_at (gedrosselt auf 1×/Minute, ohne Versions-Bump)."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE user_sessions SET last_seen_at = CURRENT_TIMESTAMP
                WHERE sid = %s AND revoked_at IS NULL
                  AND (last_seen_at IS NULL
                       OR last_seen_at::timestamptz < now() - interval '1 minute')
                """,
                (sid,),
            )
            return cur.rowcount == 1

    def list_active_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Alle aktiven Sessions eines Users (zuletzt aktiv zuerst)."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT id, sid, user_agent, ip, device_label,
                       created_at, last_seen_at, expires_at
                FROM user_sessions
                WHERE user_id = %s
                  AND revoked_at IS NULL
                  AND expires_at::timestamptz > now()
                ORDER BY last_seen_at DESC NULLS LAST, created_at DESC
                """,
                (user_id,),
            )
            return cur.fetchall()

    def revoke_session(self, session_id: int, user_id: int, revoked_by: str) -> bool:
        """Soft-Revoke einer einzelnen Session – nur wenn sie dem User gehört."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE user_sessions
                SET revoked_at = CURRENT_TIMESTAMP,
                    revoked_by = %s,
                    version = version + 1
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                """,
                (revoked_by, session_id, user_id),
            )
            return cur.rowcount == 1

    def revoke_by_sid(self, sid: str, revoked_by: str) -> bool:
        """Soft-Revoke der Session anhand ihrer sid (für normalen Logout)."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE user_sessions
                SET revoked_at = CURRENT_TIMESTAMP,
                    revoked_by = %s,
                    version = version + 1
                WHERE sid = %s AND revoked_at IS NULL
                """,
                (revoked_by, sid),
            )
            return cur.rowcount == 1

    def revoke_others(self, user_id: int, keep_sid: Optional[str], revoked_by: str) -> int:
        """Soft-Revoke aller aktiven Sessions des Users außer keep_sid ("en bloc").

        Ist keep_sid None (z. B. Legacy-Token ohne sid), werden alle widerrufen.
        Gibt die Anzahl der abgemeldeten Geräte zurück.
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE user_sessions
                SET revoked_at = CURRENT_TIMESTAMP,
                    revoked_by = %s,
                    version = version + 1
                WHERE user_id = %s
                  AND revoked_at IS NULL
                  AND (%s::text IS NULL OR sid <> %s)
                """,
                (revoked_by, user_id, keep_sid, keep_sid),
            )
            return cur.rowcount

    def cleanup_expired(self) -> int:
        """Hard-Delete abgelaufener Sessions (Prune-Job). Aktive bleiben unberührt."""
        with self.db.cursor() as cur:
            cur.execute(
                "DELETE FROM user_sessions WHERE expires_at::timestamptz < now()"
            )
            return cur.rowcount
