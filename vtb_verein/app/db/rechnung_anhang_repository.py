"""Repository für Rechnungs-Belege (rechnung_anhaenge).

Blatt ohne version/History – die Datei selbst liegt im Upload-Pfad und wird über den
AnhangService geschrieben/gelöscht. stored_name wird nach dem INSERT anhand der ID
gesetzt (rech_{id:06d}.{ext}), analog kabu_/att_.
"""
import os
from typing import Optional

from app.models.rechnung import RechnungAnhang
from app.db.base_repository import BaseRepository


_SELECT = """
    SELECT id, rechnung_id, original_name, stored_name, mime_type, dateigroesse,
           hochgeladen_von, hochgeladen_am, deleted_at, deleted_by
    FROM rechnung_anhaenge
"""


def _map(row) -> RechnungAnhang:
    return RechnungAnhang(**dict(row))


class RechnungAnhangRepository(BaseRepository):

    def get(self, id: int) -> Optional[RechnungAnhang]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE id = %s", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_by_rechnung(self, rechnung_id: int) -> list[RechnungAnhang]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE rechnung_id = %s AND deleted_at IS NULL "
                          " ORDER BY hochgeladen_am ASC, id ASC",
                (rechnung_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def count_by_rechnung(self, rechnung_id: int) -> int:
        with self.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS anzahl FROM rechnung_anhaenge "
                "WHERE rechnung_id = %s AND deleted_at IS NULL",
                (rechnung_id,),
            )
            return cur.fetchone()["anzahl"]

    def create(self, anhang: RechnungAnhang) -> RechnungAnhang:
        """Legt den Anhang an; stored_name folgt aus der vergebenen ID."""
        ext = os.path.splitext(anhang.original_name)[1].lower()
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rechnung_anhaenge
                    (rechnung_id, original_name, stored_name, mime_type,
                     dateigroesse, hochgeladen_von)
                VALUES (%s,%s,'',%s,%s,%s)
                RETURNING id
                """,
                (anhang.rechnung_id, anhang.original_name, anhang.mime_type,
                 anhang.dateigroesse, anhang.hochgeladen_von),
            )
            new_id = cur.fetchone()["id"]
            cur.execute(
                "UPDATE rechnung_anhaenge SET stored_name = %s WHERE id = %s",
                (f"rech_{new_id:06d}{ext}", new_id),
            )
        return self.get(new_id)

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE rechnung_anhaenge SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s "
                "WHERE id = %s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount == 1
