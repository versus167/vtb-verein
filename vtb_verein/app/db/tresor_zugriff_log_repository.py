"""Repository für das Tresor-Zugriffs-Log (#85).

Append-only: jedes Enthüllen (Reveal) eines Eintrags wird protokolliert. Kein
History/Soft-Delete – das Log IST der Audit-Datensatz (analog access_log). Titel des
Eintrags wird als Snapshot mitgeschrieben, damit das Log auch nach dem Löschen des
Eintrags lesbar bleibt.
"""
from typing import Optional

from app.models.tresor import TresorZugriffLog
from app.db.base_repository import BaseRepository

_COLS = ("id, tresor_id, eintrag_id, eintrag_titel, user_id, username, aktion, ip, created_at")


def _map(row) -> TresorZugriffLog:
    return TresorZugriffLog(**dict(row))


class TresorZugriffLogRepository(BaseRepository):

    def log(self, *, tresor_id: Optional[int], eintrag_id: Optional[int],
            eintrag_titel: Optional[str], user_id: Optional[int], username: Optional[str],
            aktion: str = 'reveal', ip: Optional[str] = None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO tresor_zugriff_log "
                "(tresor_id, eintrag_id, eintrag_titel, user_id, username, aktion, ip) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (tresor_id, eintrag_id, eintrag_titel, user_id, username, aktion, ip),
            )

    def list_recent(self, limit: int = 200, tresor_id: Optional[int] = None) -> list[TresorZugriffLog]:
        clause = "WHERE tresor_id = %s" if tresor_id is not None else ""
        params: tuple = (tresor_id, limit) if tresor_id is not None else (limit,)
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM tresor_zugriff_log {clause} "
                "ORDER BY created_at DESC, id DESC LIMIT %s",
                params,
            )
            return [_map(r) for r in cur.fetchall()]
