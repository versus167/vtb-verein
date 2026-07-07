"""Unit-Tests der Tresor-Verschlüsselung (#85) – ohne Datenbank.

Deckt Round-Trip, „nicht konfiguriert" (kein/ungültiger Key → VaultNotConfigured) und
den Fall eines falschen/rotierten Schlüssels (VaultDecryptError) ab.
"""
import sys
from pathlib import Path

import pytest

# backend/ liegt im Repo-Root (nicht unter vtb_verein) → für den Import auf den Pfad legen.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cryptography.fernet import Fernet  # noqa: E402
import backend.core.config as cfg  # noqa: E402
from backend.core import vault_crypto as vc  # noqa: E402


@pytest.fixture
def with_key():
    """Setzt einen frischen, gültigen Tresor-Key für die Dauer des Tests."""
    alt = cfg.settings.VAULT_KEY
    cfg.settings.VAULT_KEY = Fernet.generate_key().decode()
    yield cfg.settings.VAULT_KEY
    cfg.settings.VAULT_KEY = alt


def test_round_trip(with_key):
    tok = vc.encrypt_secret("geheim123", "PIN 4711")
    assert isinstance(tok, (bytes, bytearray))
    assert vc.decrypt_secret(tok) == {"passwort": "geheim123", "notiz": "PIN 4711"}


def test_unicode(with_key):
    tok = vc.encrypt_secret("paßwörtü", "nötíz ✓")
    assert vc.decrypt_secret(tok) == {"passwort": "paßwörtü", "notiz": "nötíz ✓"}


def test_not_configured_when_empty():
    alt = cfg.settings.VAULT_KEY
    cfg.settings.VAULT_KEY = ""
    try:
        assert vc.is_configured() is False
        with pytest.raises(vc.VaultNotConfigured):
            vc.encrypt_secret("x")
    finally:
        cfg.settings.VAULT_KEY = alt


def test_not_configured_when_invalid():
    alt = cfg.settings.VAULT_KEY
    cfg.settings.VAULT_KEY = "kein-gueltiger-fernet-key"
    try:
        assert vc.is_configured() is False
    finally:
        cfg.settings.VAULT_KEY = alt


def test_wrong_key_raises(with_key):
    tok = vc.encrypt_secret("geheim", "")
    cfg.settings.VAULT_KEY = Fernet.generate_key().decode()  # Schlüssel „rotiert"
    with pytest.raises(vc.VaultDecryptError):
        vc.decrypt_secret(tok)
