"""
Matrix-Service für Multi-Channel Notifications

Verwendet die Matrix Client-Server API v3 via HTTP-Requests.
Server-URL und Bot-Token müssen in Umgebungsvariablen gesetzt sein.
"""
from typing import Optional
import os
import logging
import time

logger = logging.getLogger(__name__)


class MatrixService:
    """Service für Matrix (Element.io) Benachrichtigungen"""

    @staticmethod
    def is_configured() -> bool:
        """Prüft ob Matrix-Service konfiguriert ist"""
        return bool(
            os.getenv('MATRIX_HOMESERVER_URL') and
            os.getenv('MATRIX_BOT_USER_ID') and
            os.getenv('MATRIX_BOT_TOKEN')
        )

    @staticmethod
    def _headers() -> dict:
        return {"Authorization": f"Bearer {os.getenv('MATRIX_BOT_TOKEN', '')}"}

    @staticmethod
    def _get_or_create_dm_room(import_requests, user_id: str) -> Optional[str]:
        """
        Gibt Room-ID für DM mit user_id zurück.
        Sucht zuerst in m.direct account data des Bots, erstellt nur wenn nötig.
        """
        base = os.getenv('MATRIX_HOMESERVER_URL', '')
        bot_user = os.getenv('MATRIX_BOT_USER_ID', '')
        headers = MatrixService._headers()

        # 1. Bekannte DM-Rooms aus account_data des Bots lesen
        r = import_requests.get(
            f"{base}/_matrix/client/v3/user/{bot_user}/account_data/m.direct",
            headers=headers,
            timeout=10
        )
        dm_map: dict = r.json() if r.status_code == 200 else {}

        # 2. Bestehenden, noch gejointen Room wiederverwenden
        candidate_rooms = dm_map.get(user_id, [])
        if candidate_rooms:
            joined_r = import_requests.get(
                f"{base}/_matrix/client/v3/joined_rooms",
                headers=headers,
                timeout=10
            )
            joined = set(joined_r.json().get("joined_rooms", [])) if joined_r.status_code == 200 else set()
            for room_id in candidate_rooms:
                if room_id in joined:
                    return room_id

        # 3. Neuen DM-Room erstellen
        create_r = import_requests.post(
            f"{base}/_matrix/client/v3/createRoom",
            json={"invite": [user_id], "is_direct": True, "preset": "trusted_private_chat"},
            headers=headers,
            timeout=10
        )
        if create_r.status_code != 200:
            logger.error(f"❌ Matrix Room-Erstellung fehlgeschlagen: {create_r.text}")
            return None

        new_room_id = create_r.json().get("room_id")
        if not new_room_id:
            return None

        # 4. Neuen Room in m.direct speichern damit spätere Aufrufe ihn wiederfinden
        dm_map.setdefault(user_id, []).append(new_room_id)
        import_requests.put(
            f"{base}/_matrix/client/v3/user/{bot_user}/account_data/m.direct",
            json=dm_map,
            headers=headers,
            timeout=10
        )

        return new_room_id

    @staticmethod
    def send_message(user_id: str, message: str) -> bool:
        """
        Sendet Nachricht an Matrix-User.

        Verwendet einen bestehenden DM-Room wenn vorhanden, erstellt sonst einen neuen.

        Args:
            user_id: Matrix User-ID (z.B. @user:matrix.org)
            message: Nachricht-Text

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not MatrixService.is_configured():
            logger.warning("❌ Matrix nicht konfiguriert (Umgebungsvariablen fehlen)")
            return False

        try:
            import requests

            room_id = MatrixService._get_or_create_dm_room(requests, user_id)
            if not room_id:
                return False

            # Eindeutige Transaktions-ID verhindert Duplikate bei Retry
            txn_id = f"vtb_{int(time.time() * 1000)}"
            msg_r = requests.put(
                f"{os.getenv('MATRIX_HOMESERVER_URL', '')}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
                json={"msgtype": "m.text", "body": message},
                headers=MatrixService._headers(),
                timeout=10
            )

            if msg_r.status_code != 200:
                logger.error(f"❌ Matrix Nachricht-Versand fehlgeschlagen: {msg_r.text}")
                return False

            logger.info(f"✅ Matrix-Nachricht an {user_id} versendet")
            return True

        except Exception as e:
            logger.error(f"❌ Fehler beim Matrix-Versand an {user_id}: {str(e)}")
            return False
    
    @staticmethod
    def send_welcome_message(user_id: str, username: str) -> bool:
        """
        Sendet Willkommens-Nachricht
        
        Args:
            user_id: Matrix User-ID
            username: Benutzername
            
        Returns:
            True wenn erfolgreich
        """
        message = f"""👋 Willkommen {username}!

Du hast deinen Matrix-Account erfolgreich mit der VTB-Vereinsverwaltung verbunden.

Ab sofort erhältst du wichtige Benachrichtigungen über diesen Kanal.

ℹ️ Du kannst deine Kommunikationspräferenzen jederzeit in deinem Profil anpassen."""
        
        return MatrixService.send_message(user_id, message)
    
    @staticmethod
    def send_notification(user_id: str, title: str, message: str) -> bool:
        """
        Sendet Benachrichtigung mit Titel und Inhalt
        
        Args:
            user_id: Matrix User-ID
            title: Benachrichtigungs-Titel (wird formatiert)
            message: Benachrichtigungs-Inhalt
            
        Returns:
            True wenn erfolgreich
        """
        formatted_message = f"**{title}**\n\n{message}"
        return MatrixService.send_message(user_id, formatted_message)
    
    @staticmethod
    def verify_matrix_id(matrix_id: str) -> bool:
        """
        Validiert Matrix-ID Format.
        
        Matrix-IDs haben Format: @local:domain.tld
        
        Args:
            matrix_id: Zu validierende ID
            
        Returns:
            True wenn Format gültig
        """
        if not matrix_id:
            return False
        
        matrix_id = str(matrix_id).strip()
        
        # Muss mit @ anfangen
        if not matrix_id.startswith('@'):
            return False
        
        # Muss genau ein : enthalten (@ kann nur einmal vorkommen)
        parts = matrix_id.split(':')
        if len(parts) != 2:
            return False
        
        local_part = parts[0][1:]  # Remove @
        domain_part = parts[1]
        
        # Local part: alphanumerisch + . _ - =
        if not local_part or not all(c.isalnum() or c in '._-=' for c in local_part):
            return False
        
        # Domain: mindestens domain.tld
        if not domain_part or '.' not in domain_part:
            return False
        
        return True
