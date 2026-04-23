"""
Matrix-Service für Multi-Channel Notifications

Verwendet matrix-client (HTTP-Requests) oder nio für Matrix-Kommunikation.
Server-URL und Bot-Token müssen in Umgebungsvariablen gesetzt sein.
"""
from typing import Optional
import os
import logging
import json

logger = logging.getLogger(__name__)


class MatrixService:
    """Service für Matrix (Element.io) Benachrichtigungen"""
    
    # Konfiguration aus Umgebungvariablen
    HOMESERVER_URL = os.getenv('MATRIX_HOMESERVER_URL', '')  # z.B. https://matrix.org
    BOT_USER_ID = os.getenv('MATRIX_BOT_USER_ID', '')          # z.B. @bot:matrix.org
    BOT_TOKEN = os.getenv('MATRIX_BOT_TOKEN', '')              # Access Token / Device ID
    
    @staticmethod
    def is_configured() -> bool:
        """Prüft ob Matrix-Service konfiguriert ist"""
        return bool(
            MatrixService.HOMESERVER_URL and 
            MatrixService.BOT_USER_ID and 
            MatrixService.BOT_TOKEN
        )
    
    @staticmethod
    def send_message(user_id: str, message: str) -> bool:
        """
        Sendet Nachricht an Matrix-User.
        
        Erstellt einen Direct Message Room, falls noch nicht vorhanden.
        
        Args:
            user_id: Matrix User-ID (z.B. @user:matrix.org)
            message: Nachricht-Text (Markdown-formatiert möglich)
            
        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not MatrixService.is_configured():
            logger.warning("❌ Matrix nicht konfiguriert (Umgebungsvariablen fehlen)")
            return False
        
        try:
            # Lazy import: Nur laden wenn wirklich benötigt
            import requests
            
            # 1. Room erstellen oder finden für Direct Message
            room_create_payload = {
                "invite": [user_id],
                "is_direct": True,
                "room_alias_name": None
            }
            
            room_response = requests.post(
                f"{MatrixService.HOMESERVER_URL}/_matrix/client/r0/createRoom",
                json=room_create_payload,
                params={"access_token": MatrixService.BOT_TOKEN},
                timeout=10
            )
            
            if room_response.status_code not in [200, 409]:  # 409 = room exists
                logger.error(f"❌ Matrix Room-Erstellung fehlgeschlagen: {room_response.text}")
                return False
            
            room_id = room_response.json().get('room_id')
            if not room_id:
                logger.error(f"❌ Keine Room-ID in Matrix-Response: {room_response.text}")
                return False
            
            # 2. Nachricht in Room posten
            message_payload = {
                "msgtype": "m.text",
                "body": message
            }
            
            msg_response = requests.post(
                f"{MatrixService.HOMESERVER_URL}/_matrix/client/r0/rooms/{room_id}/send/m.room.message",
                json=message_payload,
                params={"access_token": MatrixService.BOT_TOKEN},
                timeout=10
            )
            
            if msg_response.status_code != 200:
                logger.error(f"❌ Matrix Nachricht-Versand fehlgeschlagen: {msg_response.text}")
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
