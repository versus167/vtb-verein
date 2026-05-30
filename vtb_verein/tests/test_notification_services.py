"""
Tests für Notification Services

Testet:
- MatrixService: Matrix-ID Validierung
- NotificationService: Delegierung nach preferred_contact (email/matrix)
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from app.models.user import User
from app.services.matrix_service import MatrixService
from app.services.notification_service import NotificationService


class TestMatrixService:
    """Tests für MatrixService"""

    def test_is_configured_incomplete(self):
        """Prüft dass is_configured False zurückgibt wenn Konfiguration unvollständig"""
        with patch.dict(os.environ, {'MATRIX_HOMESERVER_URL': 'https://matrix.org', 'MATRIX_BOT_TOKEN': 'token'}):
            os.environ.pop('MATRIX_BOT_USER_ID', None)
            assert MatrixService.is_configured() is False

    def test_is_configured_complete(self):
        """Prüft dass is_configured True zurückgibt wenn vollständig konfiguriert"""
        with patch.dict(os.environ, {
            'MATRIX_HOMESERVER_URL': 'https://matrix.org',
            'MATRIX_BOT_USER_ID': '@bot:matrix.org',
            'MATRIX_BOT_TOKEN': 'token123',
        }):
            assert MatrixService.is_configured() is True

    def test_verify_matrix_id_valid_format(self):
        """Prüft dass gültige Matrix-IDs validiert werden"""
        assert MatrixService.verify_matrix_id('@user:matrix.org') is True
        assert MatrixService.verify_matrix_id('@alice:example.com') is True

    def test_verify_matrix_id_invalid_format(self):
        """Prüft dass ungültige Matrix-IDs abgelehnt werden"""
        assert MatrixService.verify_matrix_id('user:matrix.org') is False
        assert MatrixService.verify_matrix_id('@usermatrix.org') is False
        assert MatrixService.verify_matrix_id('@user:matrix:org') is False
        assert MatrixService.verify_matrix_id('@:matrix.org') is False
        assert MatrixService.verify_matrix_id('@user:localhost') is False

    def test_send_message_not_configured(self):
        """Prüft dass Versand fehlschlägt wenn nicht konfiguriert"""
        with patch.dict(os.environ, {}, clear=True):
            for key in ('MATRIX_HOMESERVER_URL', 'MATRIX_BOT_USER_ID', 'MATRIX_BOT_TOKEN'):
                os.environ.pop(key, None)
            assert MatrixService.is_configured() is False


class TestNotificationService:
    """Tests für NotificationService"""

    def _create_test_user(self, preferred_contact='email', matrix_id=None):
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
            matrix_id=matrix_id,
            preferred_contact=preferred_contact
        )

    @patch('app.services.notification_service.MatrixService')
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_matrix_primary(self, mock_email, mock_matrix):
        """Prüft dass Matrix als primärer Kanal verwendet wird"""
        mock_matrix.send_notification.return_value = True

        user = self._create_test_user(preferred_contact='matrix', matrix_id='@user:matrix.org')

        result = NotificationService.send_notification(user, 'Test', 'message')

        assert result is True
        mock_matrix.send_notification.assert_called_once()
        mock_email.send_text_email.assert_not_called()

    @patch('app.services.notification_service.MatrixService')
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_email_default(self, mock_email, mock_matrix):
        """Prüft dass Email als Standard-Kanal verwendet wird"""
        mock_email.send_text_email.return_value = True

        user = self._create_test_user(preferred_contact='email')

        result = NotificationService.send_notification(user, 'Test', 'message')

        assert result is True
        mock_email.send_text_email.assert_called_once()
        mock_matrix.send_notification.assert_not_called()

    @patch('app.services.notification_service.MatrixService')
    @patch('app.services.notification_service.EmailService')
    def test_send_notification_matrix_fallback_to_email(self, mock_email, mock_matrix):
        """Prüft dass bei Matrix-Fehler auf E-Mail ausgewichen wird"""
        mock_matrix.send_notification.return_value = False
        mock_email.send_text_email.return_value = True

        user = self._create_test_user(preferred_contact='matrix', matrix_id='@user:matrix.org')

        result = NotificationService.send_notification(user, 'Test', 'message')

        assert result is True
        mock_matrix.send_notification.assert_called_once()
        mock_email.send_text_email.assert_called_once()

    @patch('app.services.notification_service.EmailService')
    def test_send_notification_email_only_when_no_matrix(self, mock_email):
        """Prüft dass ohne Matrix-ID immer E-Mail verwendet wird"""
        mock_email.send_text_email.return_value = True

        user = self._create_test_user(preferred_contact='matrix', matrix_id=None)

        result = NotificationService.send_notification(user, 'Test', 'message')

        assert result is True
        mock_email.send_text_email.assert_called_once()
