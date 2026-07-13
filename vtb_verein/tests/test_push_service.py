"""Unit-Tests für den PushService (#96) – ohne DB, Repo & pywebpush gemockt."""
import os
from unittest.mock import MagicMock, patch

from app.services.push_service import PushService
from app.config.push_config import PushConfig


def _sub(endpoint='https://push.example/ep1'):
    return {'endpoint': endpoint, 'p256dh': 'p', 'auth': 'a'}


class TestPushConfig:
    def test_not_configured_without_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            assert PushConfig.is_configured() is False

    def test_configured_with_keys(self):
        with patch.dict(os.environ, {'VAPID_PUBLIC_KEY': 'pub', 'VAPID_PRIVATE_KEY': 'priv'}):
            assert PushConfig.is_configured() is True


class TestPushServiceSend:
    def test_send_to_user_returns_zero_when_unconfigured(self):
        repo = MagicMock()
        svc = PushService(repo)
        with patch.dict(os.environ, {}, clear=True):
            assert svc.send_to_user(1, 'T', 'M') == 0
        # Ohne Konfiguration werden gar keine Subscriptions geladen
        repo.list_active_for_user.assert_not_called()

    def test_send_to_user_delivers_to_all_devices(self):
        repo = MagicMock()
        repo.list_active_for_user.return_value = [_sub('e1'), _sub('e2')]
        svc = PushService(repo)
        with patch.dict(os.environ, {'VAPID_PUBLIC_KEY': 'pub', 'VAPID_PRIVATE_KEY': 'priv'}), \
             patch('pywebpush.webpush') as webpush:
            delivered = svc.send_to_user(1, 'Titel', 'Text', url='/tickets')
        assert delivered == 2
        assert webpush.call_count == 2
        assert repo.touch.call_count == 2
        repo.revoke_by_endpoint.assert_not_called()

    def test_send_revokes_gone_endpoint(self):
        from pywebpush import WebPushException
        repo = MagicMock()
        repo.list_active_for_user.return_value = [_sub('dead')]
        svc = PushService(repo)

        resp = MagicMock()
        resp.status_code = 410
        exc = WebPushException('gone', response=resp)

        with patch.dict(os.environ, {'VAPID_PUBLIC_KEY': 'pub', 'VAPID_PRIVATE_KEY': 'priv'}), \
             patch('pywebpush.webpush', side_effect=exc):
            delivered = svc.send_to_user(1, 'T', 'M')

        assert delivered == 0
        repo.revoke_by_endpoint.assert_called_once_with('dead', revoked_by='SYSTEM')
        repo.touch.assert_not_called()

    def test_send_keeps_subscription_on_transient_error(self):
        from pywebpush import WebPushException
        repo = MagicMock()
        repo.list_active_for_user.return_value = [_sub('e1')]
        svc = PushService(repo)

        resp = MagicMock()
        resp.status_code = 503  # vorübergehend – NICHT revoken
        exc = WebPushException('busy', response=resp)

        with patch.dict(os.environ, {'VAPID_PUBLIC_KEY': 'pub', 'VAPID_PRIVATE_KEY': 'priv'}), \
             patch('pywebpush.webpush', side_effect=exc):
            delivered = svc.send_to_user(1, 'T', 'M')

        assert delivered == 0
        repo.revoke_by_endpoint.assert_not_called()


class TestPushServiceSubscriptions:
    def test_subscribe_delegates_to_repo(self):
        repo = MagicMock()
        svc = PushService(repo)
        svc.subscribe(7, 'ep', 'p', 'a', 'Mozilla/5.0')
        repo.upsert.assert_called_once_with(
            user_id=7, endpoint='ep', p256dh='p', auth='a',
            user_agent='Mozilla/5.0', created_by='7')

    def test_unsubscribe_delegates_to_repo(self):
        repo = MagicMock()
        svc = PushService(repo)
        svc.unsubscribe('ep', revoked_by='alice')
        repo.revoke_by_endpoint.assert_called_once_with('ep', 'alice')
