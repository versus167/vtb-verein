"""Repository für Kalender-Abos (#153, Schema v89): der persönliche ICS-Feed.

Sicherheit wie bei auth_tokens: In der DB liegt ausschließlich der SHA-256-Hash
des Tokens, nie der Klartext. Den gibt es genau einmal — beim Erzeugen des Abos.
Der Token steht in der URL des Feeds, denn Kalender-Clients können sich nicht
anmelden; er IST damit das Geheimnis. 256 Bit Entropie (`secrets.token_urlsafe(32)`)
machen Raten aussichtslos, ein Passwort-KDF ist für einen Zufallswert dieser Größe
nicht nötig.

Je User höchstens ein aktives Abo (partieller Unique-Index): „Link neu erzeugen"
widerruft das alte, statt ein zweites danebenzulegen — sonst bliebe ein einmal
weitergegebener Link gültig, obwohl der Nutzer ihn für ersetzt hält.
"""
import hashlib
import secrets
from typing import Optional

from app.db.base_repository import BaseRepository


def hash_token(token: str) -> str:
    """SHA-256-Hex-Digest des Tokens – das, was tatsächlich in der DB landet."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class KalenderAboRepository(BaseRepository):

    def get_for_user(self, user_id: int) -> Optional[dict]:
        """Das aktive Abo des Users (ohne Token – der ist nicht rekonstruierbar)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, letzter_abruf_at, abrufe, version,
                       created_at, created_by, updated_at, updated_by
                FROM kalender_abo
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            return cur.fetchone()

    def list_all(self) -> list[dict]:
        """Alle aktiven Abos mit Kontonamen – Aufsicht darüber, wer einen Feed-Link
        besitzt. Ein solcher Link ist eine dauerhafte, anmeldungsfreie
        Leseberechtigung auf persönliche Termine; ohne diese Liste wüsste niemand,
        wie viele davon im Umlauf sind."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT k.id, k.user_id, u.username,
                       -- Anzeigename wie im UI (_klarname in auth.py): der steht
                       -- am verknüpften Mitglied, nicht am Konto.
                       NULLIF(TRIM(COALESCE(m.vorname, '') || ' '
                                   || COALESCE(m.nachname, '')), '') AS display_name,
                       k.letzter_abruf_at, k.abrufe, k.created_at
                FROM kalender_abo k
                JOIN users u ON u.id = k.user_id
                LEFT JOIN mitglied m ON m.user_id = u.id AND m.deleted_at IS NULL
                WHERE k.deleted_at IS NULL
                ORDER BY k.letzter_abruf_at DESC NULLS LAST, k.created_at DESC
                """
            )
            return cur.fetchall()

    def create_for_user(self, user_id: int, actor: str) -> str:
        """Neues Abo anlegen und den Klartext-Token zurückgeben (einmalig!).

        Ein vorhandenes Abo wird vorher widerrufen — der alte Link ist damit sofort
        tot. Beides in EINER Transaktion, sonst stünde der Nutzer bei einem Fehler
        dazwischen ohne Abo da.
        """
        token = secrets.token_urlsafe(32)
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kalender_abo
                SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s,
                    updated_at = CURRENT_TIMESTAMP, updated_by = %s,
                    version = version + 1
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (actor, actor, user_id),
            )
            cur.execute(
                """
                INSERT INTO kalender_abo (user_id, token_hash, created_by, updated_by)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, hash_token(token), actor, actor),
            )
        return token

    def revoke_for_user(self, user_id: int, actor: str) -> bool:
        """Abo widerrufen (Soft-Delete). True, wenn es eins gab."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kalender_abo
                SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s,
                    updated_at = CURRENT_TIMESTAMP, updated_by = %s,
                    version = version + 1
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (actor, actor, user_id),
            )
            return cur.rowcount > 0

    def resolve_token(self, token: str) -> Optional[int]:
        """Token → user_id, und den Abruf gleich mitzählen.

        Prüfung und Zählung in EINEM UPDATE … RETURNING: Der Feed wird von
        Kalender-Clients regelmäßig und gern parallel geholt; getrennte Schritte
        würden sich gegenseitig überholen. `version` bleibt bewusst unangetastet —
        sonst schriebe jeder Abruf eine History-Zeile, und die Tabelle wüchse mit
        jedem Kalender-Poll statt mit jeder echten Änderung.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kalender_abo
                SET letzter_abruf_at = CURRENT_TIMESTAMP, abrufe = abrufe + 1
                WHERE token_hash = %s AND deleted_at IS NULL
                RETURNING user_id
                """,
                (hash_token(token),),
            )
            row = cur.fetchone()
            return row['user_id'] if row else None
