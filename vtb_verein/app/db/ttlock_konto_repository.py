"""Repository für den Laufzeitstatus des einen Vereins-TTLock-Kontos (Single-Row, id=1).

Hält NUR Laufzeit-Tokens + Sync-Zeitstempel. clientId/clientSecret/Konto-Login kommen
ausschließlich aus der Env (.env) und liegen NIE in der DB.
"""
from typing import Optional

from app.models.schliessanlage import TTLockKonto
from app.db.base_repository import BaseRepository

_COLS = ("id, endpoint, ttlock_uid, access_token, refresh_token, token_expires_at, "
         "letzter_sync_at, version, created_at, created_by, updated_at, updated_by")


class TTLockKontoRepository(BaseRepository):

    def get(self) -> Optional[TTLockKonto]:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM ttlock_konto WHERE id = 1")
            row = cur.fetchone()
            return TTLockKonto(**dict(row)) if row else None

    @staticmethod
    def _ensure(cur, endpoint: str) -> None:
        cur.execute(
            "INSERT INTO ttlock_konto (id, endpoint, created_by, updated_by) "
            "VALUES (1, %s, 'SYSTEM', 'SYSTEM') ON CONFLICT (id) DO NOTHING",
            (endpoint,),
        )

    def save_tokens(self, *, endpoint: str, ttlock_uid: Optional[int],
                    access_token: Optional[str], refresh_token: Optional[str],
                    token_expires_at: Optional[str], by: str = 'SYSTEM') -> None:
        """Token-Stand persistieren (vom TTLockClient via Callback aufgerufen)."""
        with self.cursor() as cur:
            self._ensure(cur, endpoint)
            cur.execute(
                """
                UPDATE ttlock_konto
                SET endpoint=%s, ttlock_uid=%s, access_token=%s, refresh_token=%s,
                    token_expires_at=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id = 1
                """,
                (endpoint, ttlock_uid, access_token, refresh_token, token_expires_at, by),
            )

    def touch_sync(self, when_iso: str, *, endpoint: str = 'https://euapi.ttlock.com',
                   by: str = 'SYSTEM') -> None:
        """Zeitpunkt des letzten erfolgreichen Syncs festhalten."""
        with self.cursor() as cur:
            self._ensure(cur, endpoint)
            cur.execute(
                "UPDATE ttlock_konto SET letzter_sync_at=%s, updated_at=CURRENT_TIMESTAMP, "
                "updated_by=%s WHERE id = 1",
                (when_iso, by),
            )
