"""
Tests für Multi-Channel Notification User Preferences (Phase 2)

Testet:
- UserService.update_contact_preferences() Methode
- Validierung
- Error Handling
"""
import pytest
from unittest.mock import patch, MagicMock
from app.models.user import User
from app.services.user_service import UserService
from app.services.telegram_service import TelegramService
from app.services.matrix_service import MatrixService


class TestUserServiceContactPreferences:
    """Tests für update_contact_preferences"""
    
    def _create_test_user(self):
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
            updated_by='admin'
        )
    
    def _create_mock_db(self):
        """Helper um Mock-DB zu erstellen"""
        mock_db = MagicMock()
        mock_db.user_repository = MagicMock()
        return mock_db
    
    def test_update_contact_preferences_email_default(self):
        """Prüft dass Email als Standard-Kanal gespeichert werden kann"""
        user = self._create_test_user()
        mock_db = self._create_mock_db()
        
        mock_db.user_repository.update_contact_preferences.return_value = True
        mock_db.user_repository.get_by_id.return_value = user
        
        service = UserService(mock_db)
        
        result = service.update_contact_preferences(
            user_id=1,
            telegram_id=None,
            matrix_id=None,
            preferred_contact='email',
            updated_by='testuser',
            expected_version=1
        )
        
        assert result is not None
        assert mock_db.user_repository.update_contact_preferences.called
    
    def test_update_contact_preferences_invalid_channel(self):
        """Prüft dass ungültiger Kanal abgelehnt wird"""
        mock_db = self._create_mock_db()
        
        service = UserService(mock_db)
        
        with pytest.raises(ValueError, match="preferred_contact muss einer sein von"):
            service.update_contact_preferences(
                user_id=1,
                telegram_id=None,
                matrix_id=None,
                preferred_contact='invalid_channel',
                updated_by='testuser',
                expected_version=1
            )
    
    def test_update_contact_preferences_telegram_required_when_primary(self):
        """Prüft dass Telegram-ID erforderlich ist wenn als primärer Kanal gewählt"""
        mock_db = self._create_mock_db()
        
        service = UserService(mock_db)
        
        with pytest.raises(ValueError, match="Telegram-ID erforderlich"):
            service.update_contact_preferences(
                user_id=1,
                telegram_id=None,
                matrix_id=None,
                preferred_contact='telegram',
                updated_by='testuser',
                expected_version=1
            )
    
    def test_update_contact_preferences_matrix_required_when_primary(self):
        """Prüft dass Matrix-ID erforderlich ist wenn als primärer Kanal gewählt"""
        mock_db = self._create_mock_db()
        
        service = UserService(mock_db)
        
        with pytest.raises(ValueError, match="Matrix-ID erforderlich"):
            service.update_contact_preferences(
                user_id=1,
                telegram_id=None,
                matrix_id=None,
                preferred_contact='matrix',
                updated_by='testuser',
                expected_version=1
            )
    
    def test_update_contact_preferences_invalid_telegram_id(self):
        """Prüft dass ungültige Telegram-ID abgelehnt wird"""
        mock_db = self._create_mock_db()
        
        service = UserService(mock_db)
        
        # Nur 3 Ziffern, zu kurz
        with pytest.raises(ValueError, match="Ungültige Telegram-ID"):
            service.update_contact_preferences(
                user_id=1,
                telegram_id='123',
                matrix_id=None,
                preferred_contact='email',
                updated_by='testuser',
                expected_version=1
            )
    
    def test_update_contact_preferences_invalid_matrix_id(self):
        """Prüft dass ungültige Matrix-ID abgelehnt wird"""
        mock_db = self._create_mock_db()
        
        service = UserService(mock_db)
        
        # Keine @ am Anfang
        with pytest.raises(ValueError, match="Ungültige Matrix-ID"):
            service.update_contact_preferences(
                user_id=1,
                telegram_id=None,
                matrix_id='user:matrix.org',
                preferred_contact='email',
                updated_by='testuser',
                expected_version=1
            )
    
    def test_update_contact_preferences_valid_telegram(self):
        """Prüft dass gültige Telegram-ID akzeptiert wird"""
        user = self._create_test_user()
        mock_db = self._create_mock_db()
        
        mock_db.user_repository.update_contact_preferences.return_value = True
        mock_db.user_repository.get_by_id.return_value = user
        
        service = UserService(mock_db)
        
        result = service.update_contact_preferences(
            user_id=1,
            telegram_id='@validusername',
            matrix_id=None,
            preferred_contact='telegram',
            updated_by='testuser',
            expected_version=1
        )
        
        assert result is not None
        assert mock_db.user_repository.update_contact_preferences.called
    
    def test_update_contact_preferences_valid_matrix(self):
        """Prüft dass gültige Matrix-ID akzeptiert wird"""
        user = self._create_test_user()
        mock_db = self._create_mock_db()
        
        mock_db.user_repository.update_contact_preferences.return_value = True
        mock_db.user_repository.get_by_id.return_value = user
        
        service = UserService(mock_db)
        
        result = service.update_contact_preferences(
            user_id=1,
            telegram_id=None,
            matrix_id='@user:matrix.org',
            preferred_contact='matrix',
            updated_by='testuser',
            expected_version=1
        )
        
        assert result is not None
        assert mock_db.user_repository.update_contact_preferences.called
    
    def test_update_contact_preferences_version_conflict(self):
        """Prüft dass Version-Konflikt entsprechend gehandhabt wird"""
        mock_db = self._create_mock_db()
        
        mock_db.user_repository.update_contact_preferences.return_value = False  # Version conflict
        
        service = UserService(mock_db)
        
        with pytest.raises(ValueError, match="Version-Konflikt"):
            service.update_contact_preferences(
                user_id=1,
                telegram_id=None,
                matrix_id=None,
                preferred_contact='email',
                updated_by='testuser',
                expected_version=1
            )
