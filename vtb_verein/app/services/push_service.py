"""
PushService – Versand von Web-Push-Nachrichten (VAPID) und Verwaltung der
geräte-gebundenen Subscriptions (Ticket #96).

Push ist ein *zusätzlicher* Benachrichtigungskanal: Nutzer abonnieren pro Gerät
über den Service Worker; hier landen Anlegen/Abmelden sowie der eigentliche
verschlüsselte Versand via pywebpush. Tote Endpunkte (404/410) werden dabei
automatisch soft-revoket (Push-Hygiene).

Ist keine VAPID-Konfiguration hinterlegt, ist Push deaktiviert – send_to_user
liefert dann 0 (der NotificationService fällt auf E-Mail zurück).
"""
import json
import logging
from typing import Optional, List, Dict, Any

from app.config.push_config import PushConfig
from app.db.push_subscription_repository import PushSubscriptionRepository

logger = logging.getLogger(__name__)


class PushService:
    """Business-Logik für Web-Push (Subscriptions + Versand)."""

    def __init__(self, subscription_repo: PushSubscriptionRepository):
        self._repo = subscription_repo

    # --- Konfiguration -----------------------------------------------------

    @staticmethod
    def is_configured() -> bool:
        return PushConfig.is_configured()

    @staticmethod
    def public_key() -> Optional[str]:
        """Öffentlicher VAPID-Key (applicationServerKey fürs Frontend)."""
        return PushConfig.get_public_key()

    # --- Geräte-/Subscription-Verwaltung -----------------------------------

    def subscribe(self, user_id: int, endpoint: str, p256dh: str, auth: str,
                  user_agent: Optional[str]) -> Dict[str, Any]:
        """Registriert (oder aktualisiert) die Push-Subscription eines Geräts."""
        return self._repo.upsert(
            user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth,
            user_agent=user_agent, created_by=str(user_id),
        )

    def unsubscribe(self, endpoint: str, revoked_by: str) -> bool:
        """Meldet ein Gerät ab (Soft-Revoke)."""
        return self._repo.revoke_by_endpoint(endpoint, revoked_by)

    def has_active(self, user_id: int) -> bool:
        return self._repo.has_active(user_id)

    # --- Versand -----------------------------------------------------------

    def send_to_user(self, user_id: int, title: str, message: str, url: str = '/') -> int:
        """Sendet an alle aktiven Geräte des Users. Liefert die Zahl erfolgreich
        zugestellter Nachrichten (0 = nichts zugestellt / Push nicht konfiguriert)."""
        if not self.is_configured():
            return 0
        subs = self._repo.list_active_for_user(user_id)
        delivered = 0
        for sub in subs:
            if self._send_one(sub, title, message, url):
                delivered += 1
        return delivered

    def _send_one(self, sub: Dict[str, Any], title: str, message: str, url: str) -> bool:
        """Ein einzelner verschlüsselter Push. Tote Endpunkte (404/410) werden
        revoket. Fehler werden geloggt, nie propagiert (best-effort)."""
        from pywebpush import webpush, WebPushException
        payload = json.dumps({'title': title, 'body': message, 'url': url})
        try:
            webpush(
                subscription_info={
                    'endpoint': sub['endpoint'],
                    'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']},
                },
                data=payload,
                vapid_private_key=PushConfig.get_private_key(),
                vapid_claims={'sub': PushConfig.get_subject()},
                ttl=PushConfig.get_ttl(),
                timeout=10,
            )
            self._repo.touch(sub['endpoint'])
            return True
        except WebPushException as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status in (404, 410):
                # Endpoint ist beim Dienst nicht mehr gültig → Subscription revoken
                self._repo.revoke_by_endpoint(sub['endpoint'], revoked_by='SYSTEM')
                logger.info(f"Push-Endpoint tot ({status}), Subscription revoket")
            else:
                logger.error(f"Push-Fehler (status={status}): {e}")
            return False
        except Exception as e:  # noqa: BLE001 - best-effort, nie den Aufrufer stören
            logger.error(f"Push-Versand fehlgeschlagen: {e}")
            return False
