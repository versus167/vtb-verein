"""
Notification-Service für E-Mail und Matrix Benachrichtigungen.

Bevorzugter Kanal: Matrix (wenn konfiguriert), Fallback immer E-Mail.
"""
from app.models.user import User
from app.services.email_service import EmailService
from app.services.matrix_service import MatrixService
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Zentrale Service für Versand von Benachrichtigungen"""

    @staticmethod
    def send_notification(user: User, title: str, message: str) -> bool:
        """
        Sendet Benachrichtigung über bevorzugten Kanal mit E-Mail-Fallback.

        Returns:
            True wenn erfolgreich versendet
        """
        channels_to_try = []

        if user.preferred_contact == 'matrix' and user.matrix_id:
            channels_to_try.append(('matrix', user.matrix_id))

        channels_to_try.append(('email', user.email))

        for channel, address in channels_to_try:
            try:
                if channel == 'matrix':
                    success = MatrixService.send_notification(address, title, message)
                else:
                    success = EmailService.send_text_email(
                        recipient_email=address,
                        subject=title,
                        body=message
                    )

                if success:
                    logger.info(f"Benachrichtigung an {user.username} via {channel} versendet")
                    return True

            except Exception as e:
                logger.error(f"Fehler beim {channel}-Versand an {user.username}: {str(e)}")
                continue

        logger.error(f"Benachrichtigung an {user.username} konnte nicht versendet werden")
        return False

    @staticmethod
    def send_member_notification(user: User, subject: str, member_name: str, message: str) -> bool:
        title = f"Mitglied {subject}: {member_name}"
        return NotificationService.send_notification(user, title, message)

    @staticmethod
    def send_payment_notification(user: User, member_name: str, amount: float, due_date: str) -> bool:
        title = f"Beitrag fällig: {member_name}"
        message = (
            f"Der Beitrag für {member_name} in Höhe von {amount}€ ist fällig.\n\n"
            f"Fälligkeitsdatum: {due_date}\n\n"
            f"Bitte kümmern Sie sich um die Zahlung oder Einziehung."
        )
        return NotificationService.send_notification(user, title, message)

    @staticmethod
    def send_ticket_notification(user: User, ticket_number: str, title_text: str, action: str) -> bool:
        title = f"Ticket #{ticket_number} {action}"
        message = f"Titel: {title_text}"
        return NotificationService.send_notification(user, title, message)
