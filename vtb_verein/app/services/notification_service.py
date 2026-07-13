"""
Notification-Service für E-Mail und Matrix Benachrichtigungen.

Bevorzugter Kanal: Matrix (wenn konfiguriert), Fallback immer E-Mail.
"""
from app.models.user import User
from app.services.email_service import EmailService
from app.services.matrix_service import MatrixService
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger(__name__)

# Kleiner Hintergrund-Pool für nicht-blockierenden Versand. Benachrichtigungen
# sind best-effort – der auslösende HTTP-Request (z. B. Ticket-Statuswechsel)
# soll NICHT auf SMTP/Matrix warten (IONOS-Timeouts u. Ä.).
# WICHTIG: Im Hintergrund-Thread dürfen KEINE DB-Zugriffe passieren – die
# get_db()-Verbindung ist ein nicht-thread-sicheres Singleton. Aufrufer laden
# das User-Objekt daher im Request-Thread und übergeben es fertig.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="notify")


class NotificationService:
    """Zentrale Service für Versand von Benachrichtigungen"""

    @staticmethod
    def send_notification(user: User, title: str, message: str, push_service=None) -> bool:
        """
        Sendet Benachrichtigung über bevorzugten Kanal mit E-Mail-Fallback.

        Der bevorzugte Kanal (user.preferred_contact) wird zuerst versucht,
        E-Mail bleibt immer garantierter Fallback ("erster Erfolg gewinnt"):
          - 'matrix' → Matrix (falls matrix_id gesetzt)
          - 'push'   → Web-Push an alle Geräte (falls push_service übergeben & konfiguriert)

        Args:
            push_service: optionaler PushService (nur nötig, wenn Push zugestellt
                werden soll; ohne ihn wird der Push-Kanal übersprungen → E-Mail).

        Returns:
            True wenn über mindestens einen Kanal erfolgreich versendet
        """
        channels_to_try = []

        if user.preferred_contact == 'matrix' and user.matrix_id:
            channels_to_try.append(('matrix', user.matrix_id))

        if user.preferred_contact == 'push' and push_service is not None:
            channels_to_try.append(('push', None))

        channels_to_try.append(('email', user.email))

        for channel, address in channels_to_try:
            try:
                if channel == 'matrix':
                    success = MatrixService.send_notification(address, title, message)
                elif channel == 'push':
                    success = push_service.send_to_user(user.id, title, message) > 0
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
    def send_notification_async(user: User, title: str, message: str, push_service=None) -> None:
        """Nicht-blockierender Versand: reiht den Versand in den Hintergrund-Pool
        ein und kehrt sofort zurück. Voraussetzung: `user` ist bereits vollständig
        geladen. Der Hintergrund-Thread nutzt für Push denselben DB-Singleton wie
        die FastAPI-Worker (psycopg-Connection ist thread-safe); Fehler werden
        innerhalb von send_notification geloggt (best-effort)."""
        _executor.submit(NotificationService.send_notification, user, title, message, push_service)

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
