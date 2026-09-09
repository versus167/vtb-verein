"""Repository für den Laufzeitstatus des einen Vereins-TTLock-Kontos (Single-Row, id=1).

Hält NUR Laufzeit-Tokens + Sync-Zeitstempel. clientId/clientSecret/Konto-Login kommen
ausschließlich aus der Env (.env) und liegen NIE in der DB.
"""
from typing import Optional

from app.models.schliessanlage import TTLockKonto
from app.db.base_repository import BaseRepository

_COLS = ("id, endpoint, ttlock_uid, access_token, refresh_token, token_expires_at, "
         "letzter_sync_at, letzter_voll_sync_at, letzter_log_sync_at, "
         "version, created_at, created_by, updated_at, updated_by")


# Die drei Zeitstempel, die `_touch` setzen darf (der Spaltenname landet im SQL).
_TOUCH_SPALTEN = ('letzter_sync_at', 'letzter_log_sync_at', 'letzter_voll_sync_at')


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
        """Zeitpunkt des letzten erfolgreichen Syncs festhalten (Anzeige auf der Seite)."""
        self._touch('letzter_sync_at', when_iso, endpoint=endpoint, by=by)

    def touch_log_sync(self, when_iso: str, *, endpoint: str = 'https://euapi.ttlock.com',
                       by: str = 'SYSTEM') -> None:
        """Zeitpunkt des letzten Log-Syncs festhalten – daran hängt der Log-Takt (#61)."""
        self._touch('letzter_log_sync_at', when_iso, endpoint=endpoint, by=by)

    def touch_voll_sync(self, when_iso: str, *, endpoint: str = 'https://euapi.ttlock.com',
                        by: str = 'SYSTEM') -> None:
        """Zeitpunkt des letzten VOLLEN Laufs festhalten – daran hängt der große Takt (#61).

        Gesetzt vom Sync-Lauf selbst (tools/zutritt_sync.py), nicht von den einzelnen
        Teil-Syncs: „voll" heißt Inventar UND IC-Karten UND Credentials UND Logs.
        """
        self._touch('letzter_voll_sync_at', when_iso, endpoint=endpoint, by=by)

    def _touch(self, spalte: str, when_iso: str, *, endpoint: str, by: str) -> None:
        """Einen der Zeitstempel setzen. Bewusst ohne `version`-Bump: Laufzeitspuren,
        keine inhaltliche Änderung (die Tabelle hat ohnehin keine History)."""
        if spalte not in _TOUCH_SPALTEN:      # der Name geht ins SQL, also nur bekannte
            raise ValueError(f"Unbekannte Zeitstempel-Spalte: {spalte}")
        with self.cursor() as cur:
            self._ensure(cur, endpoint)
            cur.execute(
                f"UPDATE ttlock_konto SET {spalte}=%s, updated_at=CURRENT_TIMESTAMP, "
                "updated_by=%s WHERE id = 1",
                (when_iso, by),
            )
