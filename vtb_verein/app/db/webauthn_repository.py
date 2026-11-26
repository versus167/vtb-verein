"""
WebAuthnRepository – Passkeys je Gerät und die zugehörigen Challenges (Schema v126).

Credentials sind Gerätebindungen wie push_subscriptions: Soft-Revoke über
revoked_at/revoked_by + version-Bump (→ History via Trigger), kein Hard-Delete.
Gespeichert wird nur der öffentliche Schlüssel.

Challenges gibt der Server signiert und mit Ablaufzeit aus (backend/api/passkeys.py)
und schreibt dabei NICHTS in die DB – sonst könnte jeder ohne Anmeldung die Tabelle
füllen. Erst beim Einlösen landet ihr SHA-256-Hash hier; der Unique-Index macht sie
damit genau einmal einlösbar.
"""
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.db.base_repository import BaseRepository
from app.db.user_session_repository import derive_device_label

_CRED_FELDER = (
    "id, user_id, credential_id, sign_count, transports, backed_up, geraet_label, "
    "last_used_at, created_at"
)


def challenge_hash(challenge: bytes) -> str:
    return hashlib.sha256(challenge).hexdigest()


class WebAuthnRepository(BaseRepository):
    """CRUD für webauthn_credential und webauthn_challenge."""

    # ------------------------------------------------------------- Challenges

    def challenge_verbrauchen(self, challenge: bytes, zweck: str,
                              user_id: Optional[int], expires_at: datetime) -> bool:
        """Markiert eine (bereits als echt und unabgelaufen geprüfte) Challenge als
        verbraucht. False, wenn sie schon einmal eingelöst wurde."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO webauthn_challenge
                    (challenge_hash, zweck, user_id, expires_at, used_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (challenge_hash) DO NOTHING
                """,
                (challenge_hash(challenge), zweck, user_id, expires_at),
            )
            return cur.rowcount == 1

    # ------------------------------------------------------------ Credentials

    def anlegen(self, user_id: int, credential_id: str, public_key: bytes,
                sign_count: int, transports: List[str], aaguid: Optional[str],
                backed_up: bool, user_agent: Optional[str]) -> Dict[str, Any]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO webauthn_credential
                    (user_id, credential_id, public_key, sign_count, transports,
                     aaguid, backed_up, geraet_label, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_CRED_FELDER}
                """,
                (user_id, credential_id, public_key, sign_count,
                 ",".join(transports) or None, aaguid, backed_up,
                 derive_device_label(user_agent), user_agent),
            )
            return dict(cur.fetchone())

    def aktiv_nach_credential_id(self, credential_id: str) -> Optional[Dict[str, Any]]:
        """Das aktive Credential zur ID – inkl. öffentlichem Schlüssel (für den Login)."""
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_CRED_FELDER}, public_key FROM webauthn_credential "
                "WHERE credential_id = %s AND revoked_at IS NULL",
                (credential_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_active_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_CRED_FELDER} FROM webauthn_credential "
                "WHERE user_id = %s AND revoked_at IS NULL ORDER BY created_at",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def credential_ids_for_user(self, user_id: int) -> List[str]:
        """IDs der aktiven Passkeys (für excludeCredentials). Widerrufene bewusst
        nicht: Ein Gerät, dessen Passkey entfernt wurde, soll sich neu einrichten
        lassen, statt am Filter zu scheitern."""
        return [r["credential_id"] for r in self.list_active_for_user(user_id)]

    def nach_login(self, cred_id: int, sign_count: int, backed_up: bool) -> None:
        """Zähler und Zeitpunkt nachführen – OHNE version-Bump (kein History-
        Eintrag je Anmeldung, analog push_subscriptions.touch)."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE webauthn_credential SET sign_count = %s, backed_up = %s, "
                "last_used_at = CURRENT_TIMESTAMP WHERE id = %s",
                (sign_count, backed_up, cred_id),
            )

    def umbenennen(self, cred_id: int, user_id: int, label: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE webauthn_credential SET geraet_label = %s, version = version + 1 "
                "WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
                (label, cred_id, user_id),
            )
            return cur.rowcount == 1

    def widerrufen(self, cred_id: int, user_id: int, revoked_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE webauthn_credential SET revoked_at = CURRENT_TIMESTAMP, "
                "revoked_by = %s, version = version + 1 "
                "WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
                (revoked_by, cred_id, user_id),
            )
            return cur.rowcount == 1

    def widerrufen_alle_fuer_user(self, user_id: int, revoked_by: str) -> int:
        """Alle aktiven Passkeys eines Kontos widerrufen (z. B. Handy gestohlen –
        ein synchronisierter Passkey liegt auch auf den anderen Geräten)."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE webauthn_credential SET revoked_at = CURRENT_TIMESTAMP, "
                "revoked_by = %s, version = version + 1 "
                "WHERE user_id = %s AND revoked_at IS NULL",
                (revoked_by, user_id),
            )
            return cur.rowcount
