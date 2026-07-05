"""Repository für den append-only Konnektivitäts-/Status-Log je Schloss (#82).

Ein Eintrag je online↔offline-Wechsel (geschrieben aus `upsert_inventory`, sobald sich
`gateway_online` ändert). Reines Lesen hier; der Insert passiert atomar in der
Schloss-Repo-Transaktion, damit Status-Wechsel und Log-Eintrag konsistent bleiben.
"""
from app.models.schliessanlage import TuerSchlossStatusLog
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT id, schloss_id, online, geaendert_am, created_at
    FROM tuer_schloss_status_log
"""


def _map(row) -> TuerSchlossStatusLog:
    return TuerSchlossStatusLog(**dict(row))


class TuerSchlossStatusLogRepository(BaseRepository):

    def list_for_schloss(self, schloss_id: int, limit: int = 200) -> list[TuerSchlossStatusLog]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE schloss_id = %s ORDER BY geaendert_am DESC, id DESC LIMIT %s",
                (schloss_id, limit),
            )
            return [_map(r) for r in cur.fetchall()]
