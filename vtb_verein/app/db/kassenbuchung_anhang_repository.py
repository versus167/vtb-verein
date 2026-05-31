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
            self._SELECT + " WHERE id = %s", (id,)
        )
        row = cursor.fetchone()
        return self._map(row) if row else None

    def list_by_buchung(self, buchung_id: int) -> list[KassenbuchungAnhang]:
        cursor = self.conn.execute(
            self._SELECT + " WHERE buchung_id = %s AND deleted_at IS NULL ORDER BY hochgeladen_am ASC",
            (buchung_id,)
        )
        return [self._map(row) for row in cursor.fetchall()]

    def list_all_by_buchung(self, buchung_id: int) -> list[dict]:
        """Alle Anhänge (inkl. gelöschter) mit Usernamen für die History-Anzeige."""
        cursor = self.conn.execute(
            """
            SELECT a.id, a.original_name, a.dateigroesse, a.mime_type,
                   a.hochgeladen_am, u.username AS hochgeladen_von,
                   a.deleted_at, a.deleted_by
            FROM kassenbuchung_anhaenge a
            LEFT JOIN users u ON u.id = a.hochgeladen_von
            WHERE a.buchung_id = %s
            ORDER BY a.hochgeladen_am ASC
            """,
            (buchung_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def create(self, anhang: KassenbuchungAnhang) -> KassenbuchungAnhang:
        """Legt Anhang an. stored_name wird nach INSERT anhand der ID gesetzt."""
        ext = os.path.splitext(anhang.original_name)[1].lower()
        cursor = self.conn.execute(
            "INSERT INTO kassenbuchung_anhaenge "
            "(buchung_id, original_name, stored_name, mime_type, dateigroesse, hochgeladen_von) "
            "VALUES (%s, %s, '', %s, %s, %s) RETURNING id",
            (
                anhang.buchung_id, anhang.original_name,
                anhang.mime_type, anhang.dateigroesse, anhang.hochgeladen_von
            )
        )
        new_id = cursor.fetchone()['id']
        stored_name = f"kabu_{new_id:06d}{ext}"
        self.conn.execute(
            "UPDATE kassenbuchung_anhaenge SET stored_name = %s WHERE id = %s",
            (stored_name, new_id)
        )
        self.conn.commit()
        return self.get(new_id)

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE kassenbuchung_anhaenge SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map(self, row) -> KassenbuchungAnhang:
        return KassenbuchungAnhang(
            id=row['id'], buchung_id=row['buchung_id'],
            original_name=row['original_name'], stored_name=row['stored_name'],
            mime_type=row['mime_type'], dateigroesse=row['dateigroesse'],
            hochgeladen_von=row['hochgeladen_von'], hochgeladen_am=row['hochgeladen_am'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )
