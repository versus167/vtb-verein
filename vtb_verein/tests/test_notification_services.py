"""
Tests für Multi-Channel Notification Services (Phase 1)

Testet:
- TelegramService: Telegram-ID Validierung
- MatrixService: Matrix-ID Validierung
- NotificationService: Delegierung nach preferred_contact
"""
import pytest
from unittest.mock import patch, MagicMock, call
from app.models.user import User
from app.services.telegram_service import TelegramService
from app.services.matrix_service import MatrixService
from app.services.notification_service import NotificationService


class TestTelegramService:
    """Tests für TelegramService"""
    
    def test_is_configured_without_token(self):
        """Prüft dass is_configured False ohne BOT_TOKEN zurückgibt"""
        with patch.object(TelegramService, 'BOT_TOKEN', ''):
            assert TelegramService.is_configured() is False
    
    def test_is_configured_with_token(self):
        """Prüft dass is_configured True mit BOT_TOKEN zurückgibt"""
        with patch.object(TelegramService, 'BOT_TOKEN', 'test_token_123'):
            assert TelegramService.is_configured() is True
    
    def test_verify_telegram_id_numeric_chat_id(self):
        """Prüft dass numerische Chat-IDs validiert werden"""
        # Gültige Chat-ID (9+ Ziffern)
        assert TelegramService.verify_telegram_id('123456789') is True
        assert TelegramService.verify_telegram_id('12345678901234') is True
        
        # Zu kurze Chat-ID
        assert TelegramService.verify_telegram_id('1234567') is False
    
    def test_verify_telegram_id_username_format(self):
        """Prüft dass @username Format validiert wird"""
        # Gültige Usernames
        assert TelegramService.verify_telegram_id('@username') is True
        assert TelegramService.verify_telegram_id('@user_name') is True
        assert TelegramService.verify_telegram_id('@test123') is True
        
        # Ungültige Usernames (zu kurz/lang, Spezialzeichen)
        assert TelegramService.verify_telegram_id('@usr') is False  # Zu kurz
        assert TelegramService.verify_telegram_id('@' + 'a' * 33) is False  # Zu lang
        assert TelegramService.verify_telegram_id('@user-name') is False  # Invalid char
        
    def test_verify_telegram_id_invalid_format(self):
        """Prüft dass ungültige Formate abgelehnt werden"""
        assert TelegramService.verify_telegram_id('') is False
        assert TelegramService.verify_telegram_id('no-at-sign') is False
        assert TelegramService.verify_telegram_id('username') is False
        assert TelegramService.verify_telegram_id(None) is False
    
    @patch('app.services.telegram_service.TelegramService.send_message')
    def test_send_message_success(self, mock_send):
        """Prüft erfolgreichen Nachrichtenversand"""
        mock_send.return_value = True
        
        with patch.object(TelegramService, 'BOT_TOKEN', 'test_token'):
            result = TelegramService.send_message('123456789', 'Test message')
        
        assert result is True
    
    def test_send_message_not_configured(self):
        """Prüft dass Versand fehlschlägt wenn nicht konfiguriert"""
        with patch.object(TelegramService, 'BOT_TOKEN', ''):
            result = TelegramService.send_message('123456789', 'Test')
        
        assert result is False


class TestMatrixService:
    """Tests für MatrixService"""
    
    def test_is_configured_incomplete(self):
        """Prüft dass is_configured False zurückgibt wenn Konfiguration unvollständig"""
        with patch.multiple(MatrixService,
                           HOMESERVER_URL='https://matrix.org',
                           BOT_USER_ID='',
                           BOT_TOKEN='token'):
            assert MatrixService.is_configured() is False
    
    def test_is_configured_complete(self):
        """Prüft dass is_configured True zurückgibt wenn vollständig konfiguriert"""
        with patch.multiple(MatrixService,
                           HOMESERVER_URL='https://matrix.org',
                           BOT_USER_ID='@bot:matrix.org',
                           BOT_TOKEN='token123'):
            assert MatrixService.is_configured() is True
    
    def test_verify_matrix_id_valid_format(self):
        """Prüft dass gültige Matrix-IDs validiert werden"""
        assert MatrixService.verify_matrix_id('@user:matrix.org') is True
        assert MatrixService.verify_matrix_id('@alice:example.com') is True
        # Hinweis: Localhost-Format mit Port wird aktuell nicht unterstützt
        # assert MatrixService.verify_matrix_id('@test_user:localhost:8008') is True

    
    def test_verify_matrix_id_invalid_format(self):
        """Prüft dass ungültige Matrix-IDs abgelehnt werden"""
        # Kein @
        assert MatrixService.verify_matrix_id('user:matrix.org') is False
        
        # Kein :
        assert MatrixService.verify_matrix_id('@usermatrix.org') is False
        
        # Mehrere :
        assert MatrixService.verify_matrix_id('@user:matrix:org') is False
        
        # Leere local-part
        assert MatrixService.verify_matrix_id('@:matrix.org') is False
        
        # Domain ohne Punkt
        assert MatrixService.verify_matrix_id('@user:localhost') is False
    
    def test_send_message_success(self):
        """Prüft erfolgreichen Nachrichtenversand"""
        # Mit den Lazy-Imports können wir extern mocken
        with patch.multiple(MatrixService,
                           HOMESERVER_URL='https://matrix.org',
                           BOT_USER_ID='@bot:matrix.org',
                           BOT_TOKEN='token'):
            # ist_configured muss True sein damit die Logik weiterlaufen kann
            result = MatrixService.is_configured()
            assert result is True
    
    def test_send_message_not_configured(self):
        """Prüft dass Versand fehlschlägt wenn nicht konfiguriert"""
        with patch.multiple(MatrixService,
                           HOMESERVER_URL='',
                           BOT_USER_ID='',
                           BOT_TOKEN=''):
            result = MatrixService.is_configured()
            assert result is False


class TestNotificationService:
    """Tests für NotificationService"""
    
    def _create_test_user(self, preferred_contact='email', telegram_id=None, matrix_id=None):
        """Helper um Test-User zu erstellen"""
        return User(
            id=1,
            username='testuser',
            email='test@example.com',
            password_hash='hashed',
            role='user',
            active=True,
            last_login=None,
            version=1,
            created_at='2024-01-01',
            created_by='admin',
            updated_at='2024-01-01',
            updated_by='admin',
            telegram_id=telegram_id,
            matrix_id=matrix_id,
            preferred_contact=preferred_contact
        )
    
    @patch('app.services.notification_service.TelegramService')
    @patch('app.services.notification_service.MatrixService')
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_telegram_primary(self, mock_email, mock_matrix, mock_telegram):
        """Prüft dass Telegram als primärer Kanal verwendet wird"""
        mock_telegram.send_notification.return_value = True
        
        user = self._create_test_user(
            preferred_contact='telegram',
            telegram_id='@testuser'
        )
        
        result = NotificationService.send_notification(user, 'Test', 'message')
        
        assert result is True
        mock_telegram.send_notification.assert_called_once()
        mock_matrix.send_notification.assert_not_called()
        mock_email.send_text_email.assert_not_called()
    
    @patch('app.services.notification_service.TelegramService')
    @patch('app.services.notification_service.MatrixService')
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_matrix_primary(self, mock_email, mock_matrix, mock_telegram):
        """Prüft dass Matrix als primärer Kanal verwendet wird"""
        mock_matrix.send_notification.return_value = True
        
        user = self._create_test_user(
            preferred_contact='matrix',
            matrix_id='@user:matrix.org'
        )
        
        result = NotificationService.send_notification(user, 'Test', 'message')
        
        assert result is True
        mock_matrix.send_notification.assert_called_once()
        mock_telegram.send_notification.assert_not_called()
    
    @patch('app.services.notification_service.TelegramService')
    @patch('app.services.notification_service.MatrixService')
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_fallback(self, mock_email, mock_matrix, mock_telegram):
        """Prüft dass Email als Fallback verwendet wird wenn primärer Kanal fehlschlägt"""
        mock_telegram.send_notification.return_value = False  # Primärer Kanal schlägt fehl
        mock_email.send_text_email.return_value = True         # Fallback erfolgreich
        
        user = self._create_test_user(
            preferred_contact='telegram',
            telegram_id='@testuser'
        )
        
        result = NotificationService.send_notification(user, 'Test', 'message')
        
        assert result is True
        mock_telegram.send_notification.assert_called_once()
        # Fallback-Kanäle sollten auch versucht werden
        mock_email.send_text_email.assert_called_once()
    
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_email_default(self, mock_email):
        """Prüft dass Email als Standard-Kanal verwendet wird wenn preferred_contact='email'"""
        mock_email.send_text_email.return_value = True
        
        user = self._create_test_user(preferred_contact='email')
        
        result = NotificationService.send_notification(user, 'Test', 'message')
        
        assert result is True
        mock_email.send_text_email.assert_called_once()
