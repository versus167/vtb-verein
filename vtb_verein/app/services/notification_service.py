"""
Notification-Service als Abstraktions-Layer für Multi-Channel Benachrichtigungen

Delegiert Benachrichtigungen basierend auf user.preferred_contact zu:
- EmailService (Fallback und Standard)
- TelegramService
- MatrixService

Mit Fallback-Logik: Wenn bevorzugter Kanal fehlschlägt, tries andere Kanäle
"""
from typing import Optional
from app.models.user import User
from app.services.email_service import EmailService
from app.services.telegram_service import TelegramService
from app.services.matrix_service import MatrixService
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Zentrale Service für Versand von Multi-Channel Benachrichtigungen"""
    
    @staticmethod
    def send_welcome_notification(user: User) -> bool:
        """
        Sendet Willkommens-Benachrichtigung über bevorzugten Kanal
        
        Args:
            user: User-Objekt mit preferred_contact und Kontaktdaten
            
        Returns:
            True wenn erfolgreich versendet (über bevorzugten oder Fallback-Kanal)
        """
        username = user.username
        
        # Versuche bevorzugten Kanal
        if user.preferred_contact == 'telegram' and user.telegram_id:
            if TelegramService.send_welcome_message(user.telegram_id, username):
                return True
            logger.warning(f"Telegram-Versand zu {user.id} fehlgeschlagen, fallback zu Email")
        
        elif user.preferred_contact == 'matrix' and user.matrix_id:
            if MatrixService.send_welcome_message(user.matrix_id, username):
                return True
            logger.warning(f"Matrix-Versand zu {user.id} fehlgeschlagen, fallback zu Email")
        
        # Fallback zu Email (oder Standard)
        return EmailService.send_magic_link(user.email, None, username)  # Für Willkommen anpassen
    
    @staticmethod
    def send_notification(user: User, title: str, message: str) -> bool:
        """
        Sendet Benachrichtigung über bevorzugten Kanal mit Fallback-Logik
        
        Args:
            user: User-Objekt mit preferred_contact und Kontaktdaten
            title: Benachrichtigungs-Titel
            message: Benachrichtigungs-Inhalt
            
        Returns:
            True wenn erfolgreich versendet
        """
        channels_to_try = []
        
        # 1. Primärer Kanal
        if user.preferred_contact == 'telegram' and user.telegram_id:
            channels_to_try.append(('telegram', user.telegram_id))
        elif user.preferred_contact == 'matrix' and user.matrix_id:
            channels_to_try.append(('matrix', user.matrix_id))
        else:
            channels_to_try.append(('email', user.email))
        
        # 2. Fallback-Kanäle (wenn primärer fehlschlägt)
        if user.preferred_contact != 'telegram' and user.telegram_id:
            channels_to_try.append(('telegram', user.telegram_id))
        if user.preferred_contact != 'matrix' and user.matrix_id:
            channels_to_try.append(('matrix', user.matrix_id))
        if user.preferred_contact != 'email':
            channels_to_try.append(('email', user.email))
        
        # Versuche Kanäle nacheinander
        for channel, address in channels_to_try:
            try:
                success = False
                
                if channel == 'telegram':
                    success = TelegramService.send_notification(address, title, message)
                elif channel == 'matrix':
                    success = MatrixService.send_notification(address, title, message)
                else:  # email
                    # Für Email: Einfacher Versand ohne HTML-Template für Phase 1
                    success = EmailService.send_text_email(
                        recipient_email=address,
                        subject=title,
                        body=message
                    )
                
                if success:
                    logger.info(f"✅ Benachrichtigung an {user.username} via {channel} versendet")
                    return True
                    
            except Exception as e:
                logger.error(f"❌ Fehler beim {channel}-Versand an {user.username}: {str(e)}")
                # Weiter zum nächsten Kanal
                continue
        
        logger.error(f"❌ Benachrichtigung an {user.username} konnte über keinen Kanal versendet werden")
        return False
    
    @staticmethod
    def send_member_notification(user: User, subject: str, member_name: str, message: str) -> bool:
        """
        Sendet Benachrichtigung zu Mitglied-Ereignis
        (z.B. "Neuer Mitglied 'Max Mustermann' hinzugefügt")
        
        Args:
            user: User der benachrichtigt werden soll
            subject: Kurzer Betreff (z.B. "Mitglied hinzugefügt")
            member_name: Name des betroffenen Mitglieds
            message: Detaillierte Nachricht
            
        Returns:
            True wenn erfolgreich
        """
        title = f"👤 {subject}: {member_name}"
        return NotificationService.send_notification(user, title, message)
    
    @staticmethod
    def send_payment_notification(user: User, member_name: str, amount: float, due_date: str) -> bool:
        """
        Sendet Beitrags-Benachrichtigung
        
        Args:
            user: User der benachrichtigt werden soll
            member_name: Name des Mitglieds
            amount: Beitragsbetrag
            due_date: Fälligkeitsdatum
            
        Returns:
            True wenn erfolgreich
        """
        title = f"💰 Beitrag fällig: {member_name}"
        message = f"""Der Beitrag für {member_name} in Höhe von {amount}€ ist fällig.

Fälligkeitsdatum: {due_date}

Bitte kümmern Sie sich um die Zahlung oder Einziehung."""
        
        return NotificationService.send_notification(user, title, message)
    
    @staticmethod
    def send_ticket_notification(user: User, ticket_number: str, title_text: str, action: str) -> bool:
        """
        Sendet Ticket-Benachrichtigung
        
        Args:
            user: User der benachrichtigt werden soll
            ticket_number: Ticket-Nummer oder -ID
            title_text: Ticket-Titel
            action: Was passiert ist (z.B. "erstellt", "zugewiesen", "aktualisiert")
            
        Returns:
            True wenn erfolgreich
        """
        title = f"🎫 Ticket #{ticket_number} {action}"
        message = f"Titel: {title_text}"
        
        return NotificationService.send_notification(user, title, message)
