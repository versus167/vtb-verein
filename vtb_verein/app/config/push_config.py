"""
Web-Push-Konfiguration (VAPID) für den Versand von Browser-Push-Nachrichten.

Schlüssel werden EINMALIG erzeugt und über Env bereitgestellt:
  VAPID_PUBLIC_KEY   base64url (uncompressed EC point) – auch das Frontend braucht ihn
  VAPID_PRIVATE_KEY  base64url des privaten EC-Schlüssels
  VAPID_SUBJECT      Kontakt für den Push-Dienst (mailto: oder https-URL)

Fehlen die Schlüssel, ist Push schlicht deaktiviert (Fallback auf E-Mail).
"""
import os
from typing import Optional


class PushConfig:
    """VAPID-Konfiguration aus Environment-Variablen."""

    @staticmethod
    def get_public_key() -> Optional[str]:
        return os.getenv('VAPID_PUBLIC_KEY')

    @staticmethod
    def get_private_key() -> Optional[str]:
        return os.getenv('VAPID_PRIVATE_KEY')

    @staticmethod
    def get_subject() -> str:
        return os.getenv('VAPID_SUBJECT', 'mailto:admin@vtbchemnitz.de')

    @staticmethod
    def get_ttl() -> int:
        """Time-to-live (Sekunden), die der Push-Dienst die Nachricht vorhält."""
        return int(os.getenv('VAPID_TTL', '86400'))

    @staticmethod
    def is_configured() -> bool:
        return bool(PushConfig.get_public_key() and PushConfig.get_private_key())
