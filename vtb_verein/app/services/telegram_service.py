"""
Telegram-Service für Multi-Channel Notifications

Verwendet die Telegram Bot HTTP-API direkt via requests.
Bot-Token muss in Umgebungsvariable TELEGRAM_BOT_TOKEN gesetzt sein.
"""
import os
import logging

logger = logging.getLogger(__name__)


class TelegramService:
    """Service für Telegram-Benachrichtigungen"""

    @staticmethod
    def is_configured() -> bool:
        """Prüft ob Telegram-Service konfiguriert ist (BOT_TOKEN vorhanden)"""
        return bool(os.getenv('TELEGRAM_BOT_TOKEN'))

    @staticmethod
    def send_message(chat_id: str | int, message: str) -> bool:
        """
        Sendet Nachricht an Telegram-Chat via Bot HTTP-API.

        Args:
            chat_id: Telegram Chat-ID oder @username
            message: Nachricht-Text (Markdown V1 formatiert möglich)

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not TelegramService.is_configured():
            logger.warning("❌ Telegram nicht konfiguriert (TELEGRAM_BOT_TOKEN fehlt)")
            return False

        try:
            import requests

            token = os.getenv('TELEGRAM_BOT_TOKEN', '')
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                timeout=10
            )

            if response.status_code != 200:
                logger.error(f"❌ Telegram-Fehler an {chat_id}: {response.text}")
                return False

            logger.info(f"✅ Telegram-Nachricht an {chat_id} versendet")
            return True

        except Exception as e:
            logger.error(f"❌ Unerwarteter Fehler beim Telegram-Versand: {str(e)}")
            return False
    
    @staticmethod
    def send_welcome_message(chat_id: str | int, username: str) -> bool:
        """
        Sendet Willkommens-Nachricht
        
        Args:
            chat_id: Telegram Chat-ID
            username: Benutzername
            
        Returns:
            True wenn erfolgreich
        """
        message = f"""
👋 Willkommen {username}!

Du hast deinen Telegram-Account erfolgreich mit der VTB-Vereinsverwaltung verbunden.

Ab sofort erhältst du wichtige Benachrichtigungen über diesen Kanal.

ℹ️ Du kannst deine Kommunikationspräferenzen jederzeit in deinem Profil anpassen.
"""
        return TelegramService.send_message(chat_id, message)
    
    @staticmethod
    def send_notification(chat_id: str | int, title: str, message: str) -> bool:
        """
        Sendet Benachrichtigung mit Titel und Inhalt
        
        Args:
            chat_id: Telegram Chat-ID
            title: Benachrichtigungs-Titel (wird BOLD formatiert)
            message: Benachrichtigungs-Inhalt
            
        Returns:
            True wenn erfolgreich
        """
        formatted_message = f"*{title}*\n\n{message}"
        return TelegramService.send_message(chat_id, formatted_message)
    
    @staticmethod
    def verify_telegram_id(telegram_id: str) -> bool:
        """
        Versucht die Telegram-ID zu validieren.
        
        Dies ist eine einfache Check: Die ID muss entweder
        - Ein numerischer Chat-ID sein, oder
        - Mit @ anfangen (@username Format)
        
        Args:
            telegram_id: Zu validierende ID
            
        Returns:
            True wenn Format gültig
        """
        if not telegram_id:
            return False
        
        telegram_id = str(telegram_id).strip()
        
        # Numerische Chat-ID
        if telegram_id.isdigit():
            return len(telegram_id) >= 8  # Telegram Chat-IDs sind typischerweise >= 9 Ziffern
        
        # @username Format
        if telegram_id.startswith('@'):
            username = telegram_id[1:]
            # Telegram Usernames sind 5-32 Zeichen, alphanumerisch + _
            return 5 <= len(username) <= 32 and username.replace('_', '').isalnum()
        
        return False
