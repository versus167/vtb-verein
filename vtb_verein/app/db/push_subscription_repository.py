"""
PushSubscriptionRepository – Web-Push-Subscriptions je Gerät/Browser (Ticket #96).

Analog zu user_sessions: geräte-gebunden, Soft-Revoke über revoked_at/revoked_by
(kein Hard-Delete), History via Audit-Trigger. Der endpoint ist der eindeutige
Schlüssel einer Subscription; re-subscriben desselben Geräts aktualisiert die
Zeile (Keys/Owner) und hebt einen früheren Revoke wieder auf.
"""
from typing import Optional, List, Dict, Any
from app.db.base_repository import BaseRepository
from app.db.user_session_repository import derive_device_label


class PushSubscriptionRepository(BaseRepository):
    """CRUD für push_subscriptions (Web-Push je Gerät)."""

    def upsert(self, user_id: int, endpoint: str, p256dh: str, auth: str,
               user_agent: Optional[str], created_by: str) -> Dict[str, Any]:
        """Legt eine Subscription an oder aktualisiert die bestehende (per endpoint).

        Re-Subscribe desselben Endpoints aktualisiert Owner/Keys, hebt einen
        früheren Revoke auf und bumpt version (→ History-Eintrag via Trigger).
        """
        device_label = derive_device_label(user_agent)
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO push_subscriptions
                    (user_id, endpoint, p256dh, auth, user_agent, device_label,
                     version, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (endpoint) DO UPDATE SET
                    user_id      = EXCLUDED.user_id,
                    p256dh       = EXCLUDED.p256dh,
                    auth         = EXCLUDED.auth,
                    user_agent   = EXCLUDED.user_agent,
                    device_label = EXCLUDED.device_label,
                    revoked_at   = NULL,
                    revoked_by   = NULL,
                    version      = push_subscriptions.version + 1
                RETURNING id, user_id, endpoint, device_label, created_at
                """,
                (user_id, endpoint, p256dh, auth, user_agent, device_label),
            )
            return dict(cur.fetchone())

    def list_active_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Alle nicht-revoketen Subscriptions eines Users (für den Versand)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, endpoint, p256dh, auth, device_label, created_at, last_used_at
                FROM push_subscriptions
                WHERE user_id = %s AND revoked_at IS NULL
                ORDER BY created_at
                """,
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def has_active(self, user_id: int) -> bool:
        """Ob der User mindestens ein aktives Push-Gerät hat."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM push_subscriptions WHERE user_id = %s AND revoked_at IS NULL LIMIT 1",
                (user_id,),
            )
            return cur.fetchone() is not None

    def revoke_by_endpoint(self, endpoint: str, revoked_by: str) -> bool:
        """Soft-Revoke einer Subscription per endpoint (z. B. bei 404/410 vom Dienst
        oder beim Abmelden des Geräts)."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE push_subscriptions
                SET revoked_at = CURRENT_TIMESTAMP, revoked_by = %s, version = version + 1
                WHERE endpoint = %s AND revoked_at IS NULL
                """,
                (revoked_by, endpoint),
            )
            return cur.rowcount == 1

    def touch(self, endpoint: str) -> None:
        """Aktualisiert last_used_at OHNE version-Bump (kein History-Eintrag) –
        reine Aktivitäts-Notiz, analog users.last_seen."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE push_subscriptions SET last_used_at = CURRENT_TIMESTAMP "
                "WHERE endpoint = %s AND revoked_at IS NULL",
                (endpoint,),
            )

    def cleanup_revoked(self, older_than_days: int = 90) -> int:
        """Zeitbasierter Prune: löscht lange revokete Subscriptions endgültig
        (analog user_sessions/access_log – kein Soft-Delete-Registry-Eintrag,
        da revoked_at-basiert statt deleted_at)."""
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM push_subscriptions "
                "WHERE revoked_at IS NOT NULL "
                "AND revoked_at::timestamptz < now() - make_interval(days => %s)",
                (older_than_days,),
            )
            return cur.rowcount
