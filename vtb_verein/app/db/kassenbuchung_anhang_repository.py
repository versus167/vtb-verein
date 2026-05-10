'''
KassenbuchungAnhangRepository - Upload-Verwaltung für kassenbuchung_anhaenge

stored_name-Logik: nach INSERT wird stored_name = kabu_{id:06d}.{ext} per UPDATE gesetzt.
'''

import os
from typing import Optional
from app.models.kasse import KassenbuchungAnhang


class KassenbuchungAnhangRepository:

    def __init__(self, conn):
        self.conn = conn

    _SELECT = (
        "SELECT id, buchung_id, original_name, stored_name, "
        "mime_type, dateigroesse, hochgeladen_von, hochgeladen_am, deleted_at, deleted_by "
        "FROM kassenbuchung_anhaenge"
    )

    def get(self, id: int) -> Optional[KassenbuchungAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_by_buchung(self, buchung_id: int) -> list[KassenbuchungAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE buchung_id = ? AND deleted_at IS NULL ORDER BY hochgeladen_am ASC",
            (buchung_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def create(self, anhang: KassenbuchungAnhang) -> KassenbuchungAnhang:
        """Legt Anhang an. stored_name wird nach INSERT anhand der ID gesetzt."""
        ext = os.path.splitext(anhang.original_name)[1].lower()
        cursor = self.conn.execute(
            "INSERT INTO kassenbuchung_anhaenge "
            "(buchung_id, original_name, stored_name, mime_type, dateigroesse, hochgeladen_von) "
            "VALUES (?, ?, '', ?, ?, ?)",
            (
                anhang.buchung_id, anhang.original_name,
                anhang.mime_type, anhang.dateigroesse, anhang.hochgeladen_von
            )
        )
        new_id = cursor.lastrowid
        stored_name = f"kabu_{new_id:06d}{ext}"
        self.conn.execute(
            "UPDATE kassenbuchung_anhaenge SET stored_name = ? WHERE id = ?",
            (stored_name, new_id)
        )
        self.conn.commit()
        return self.get(new_id)

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE kassenbuchung_anhaenge SET deleted_at = datetime('now'), deleted_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map(self, row) -> KassenbuchungAnhang:
        return KassenbuchungAnhang(
            id=row[0], buchung_id=row[1],
            original_name=row[2], stored_name=row[3],
            mime_type=row[4], dateigroesse=row[5],
            hochgeladen_von=row[6], hochgeladen_am=row[7],
            deleted_at=row[8], deleted_by=row[9]
        )
