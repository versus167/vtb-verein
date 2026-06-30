"""Repository für die kurzzeitige App-Betätigungs-Berechtigung (User darf Schloss
befristet per App öffnen, ohne Chip).

Getrennt von tuer_berechtigung (Chip↔Schloss/IC-Card): hier gibt es keinen Chip,
nur das App-/Gateway-Öffnen über ein Gültigkeitsfenster.
"""
from typing import Optional

from app.models.schliessanlage import TuerAppBerechtigung
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT b.id, b.user_id, b.schloss_id, b.gueltig_von, b.gueltig_bis, b.grund,
           b.erteilt_von,
           s.name AS schloss_name, u.username AS user_username,
           e.username AS erteilt_von_username,
           b.version, b.created_at, b.created_by, b.updated_at, b.updated_by,
           b.deleted_at, b.deleted_by
    FROM tuer_app_berechtigung b
    LEFT JOIN tuer_schloss s ON s.id = b.schloss_id
    LEFT JOIN users u ON u.id = b.user_id
    LEFT JOIN users e ON e.id = b.erteilt_von
"""


def _map(row) -> TuerAppBerechtigung:
    return TuerAppBerechtigung(**dict(row))


class TuerAppBerechtigungRepository(BaseRepository):

    def get(self, id: int) -> Optional[TuerAppBerechtigung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE b.id = %s AND b.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_schloss(self, schloss_id: int) -> list[TuerAppBerechtigung]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE b.schloss_id = %s AND b.deleted_at IS NULL "
                          "ORDER BY b.gueltig_bis NULLS LAST, b.id DESC",
                (schloss_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_user(self, user_id: int) -> list[TuerAppBerechtigung]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE b.user_id = %s AND b.deleted_at IS NULL "
                          "ORDER BY b.gueltig_bis NULLS LAST, b.id DESC",
                (user_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def create(self, b: TuerAppBerechtigung, created_by: str) -> TuerAppBerechtigung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tuer_app_berechtigung
                    (user_id, schloss_id, gueltig_von, gueltig_bis, grund, erteilt_von,
                     created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (b.user_id, b.schloss_id, b.gueltig_von, b.gueltig_bis, b.grund,
                 b.erteilt_von, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tuer_app_berechtigung SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount > 0

    def user_has_valid_for_schloss(self, user_id: int, schloss_id: int) -> bool:
        """Hat der User aktuell eine gültige (im Zeitfenster liegende) App-Berechtigung
        für genau dieses Schloss? Datums-Vergleich gegen now() (ISO-Text → timestamptz)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM tuer_app_berechtigung
                WHERE user_id = %s AND schloss_id = %s AND deleted_at IS NULL
                  AND (gueltig_von IS NULL OR NULLIF(gueltig_von, '')::timestamptz <= now())
                  AND (gueltig_bis IS NULL OR NULLIF(gueltig_bis, '')::timestamptz >= now())
                LIMIT 1
                """,
                (user_id, schloss_id),
            )
            return cur.fetchone() is not None
