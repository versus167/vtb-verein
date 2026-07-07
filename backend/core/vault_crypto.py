"""At-rest-Verschlüsselung der Passwort-Tresor-Secrets (#85).

Die geheime Nutzlast eines Tresor-Eintrags – ``{"passwort": ..., "notiz": ...}`` – wird
mit Fernet (AES-128-CBC + HMAC-SHA256) symmetrisch verschlüsselt und ausschließlich als
Ciphertext (BYTEA, ``tresor_eintrag.secret_ciphertext``) gespeichert. Die Metadaten
(Titel/Benutzername/URL) bleiben Klartext für Liste und Suche.

Der Schlüssel kommt AUSSCHLIESSLICH aus der Env (``VTB_VAULT_KEY``). Fehlt oder ist er
ungültig, gilt das Feature als nicht konfiguriert – die API antwortet dann mit 503 statt
zu crashen. Bewusst KEIN Zero-Knowledge: Wer Server + Key besitzt, kann entschlüsseln.
Für geteilte Betriebsgeheimnisse (WLAN etc.) ist das der gewählte Trade-off.

Key erzeugen:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import json
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


class VaultNotConfigured(RuntimeError):
    """VTB_VAULT_KEY ist nicht oder nicht gültig gesetzt (Feature deaktiviert)."""


class VaultDecryptError(RuntimeError):
    """Ciphertext passt nicht zum aktuellen Key (falscher/rotierter Schlüssel)."""


def _build_fernet() -> Optional[Fernet]:
    """Fernet aus der Env bauen; None, wenn kein/ungültiger Key hinterlegt ist."""
    key = (settings.VAULT_KEY or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        return None


def is_configured() -> bool:
    """True, wenn ein gültiger Tresor-Schlüssel in der Env liegt."""
    return _build_fernet() is not None


def _require_fernet() -> Fernet:
    f = _build_fernet()
    if f is None:
        raise VaultNotConfigured(
            "VTB_VAULT_KEY ist nicht oder ungültig gesetzt – Tresor-Feature deaktiviert."
        )
    return f


def encrypt_secret(passwort: str, notiz: str = "") -> bytes:
    """Verschlüsselt die geheime Nutzlast zu einem Fernet-Token (bytes)."""
    payload = json.dumps(
        {"passwort": passwort or "", "notiz": notiz or ""},
        ensure_ascii=False,
    ).encode("utf-8")
    return _require_fernet().encrypt(payload)


def decrypt_secret(token: bytes) -> dict:
    """Entschlüsselt einen Fernet-Token zu ``{'passwort': ..., 'notiz': ...}``."""
    try:
        raw = _require_fernet().decrypt(bytes(token))
    except InvalidToken as exc:
        raise VaultDecryptError(
            "Ciphertext passt nicht zum aktuellen VTB_VAULT_KEY."
        ) from exc
    data = json.loads(raw.decode("utf-8"))
    return {"passwort": data.get("passwort", ""), "notiz": data.get("notiz", "")}
