"""
Notification-Service für E-Mail-, Matrix- und Web-Push-Benachrichtigungen.

Web-Push ist ein additiver Kanal (#108): Geräte mit aktiver Push-Subscription
werden immer beliefert. Der Hauptkanal (preferred_contact) bestimmt zusätzlich
E-Mail bzw. Matrix; 'push' heißt "keine zusätzliche E-Mail, solange Push zustellt".
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
        Sendet eine Benachrichtigung; Web-Push ist additiver Kanal (#108).

        Push geht immer zuerst best-effort an alle aktiven Geräte des Nutzers
        (falls push_service übergeben & konfiguriert). Zusätzlich der Hauptkanal
        nach user.preferred_contact:
          - 'email' (Standard) → E-Mail
          - 'matrix' → Matrix (falls matrix_id gesetzt), E-Mail-Fallback bei Fehlschlag
          - 'push'   → keine zusätzliche E-Mail; erreicht Push aber kein Gerät,
                       geht die Nachricht als Notfall-Fallback per E-Mail raus

        Args:
            push_service: optionaler PushService (ohne ihn entfällt der Push-Kanal;
                bei preferred_contact='push' greift dann der E-Mail-Fallback).

        Returns:
            True wenn über mindestens einen Kanal erfolgreich versendet
        """
        push_ok = False
        if push_service is not None:
            try:
                push_ok = push_service.send_to_user(user.id, title, message) > 0
                if push_ok:
                    logger.info(f"Benachrichtigung an {user.username} via push versendet")
            except Exception as e:
                logger.error(f"Fehler beim push-Versand an {user.username}: {str(e)}")

        def send_email() -> bool:
            try:
                ok = EmailService.send_text_email(
                    recipient_email=user.email,
                    subject=title,
                    body=message
                )
                if ok:
                    logger.info(f"Benachrichtigung an {user.username} via email versendet")
                return ok
            except Exception as e:
                logger.error(f"Fehler beim email-Versand an {user.username}: {str(e)}")
                return False

        if user.preferred_contact == 'push':
            # E-Mail bewusst abgeschaltet — nur wenn Push kein Gerät erreicht
            # hat, geht die Nachricht als Notfall-Fallback per E-Mail raus.
            main_ok = push_ok or send_email()
        elif user.preferred_contact == 'matrix' and user.matrix_id:
            try:
                main_ok = MatrixService.send_notification(user.matrix_id, title, message)
                if main_ok:
                    logger.info(f"Benachrichtigung an {user.username} via matrix versendet")
            except Exception as e:
                logger.error(f"Fehler beim matrix-Versand an {user.username}: {str(e)}")
                main_ok = False
            if not main_ok:
                main_ok = send_email()
        else:
            main_ok = send_email()

        if not (push_ok or main_ok):
            logger.error(f"Benachrichtigung an {user.username} konnte nicht versendet werden")
            return False
        return True

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
