"""Repository für Berechtigungen (Chip an einem Schloss = eine TTLock-IC-Card).

Phase 1 ist read-only-Anzeige (welche Chips hängen an einer Tür / an welchen Türen
ein Chip). Das Anlernen/Sperren über die Cloud (create/sperren) folgt in Phase 2.
"""
from typing import Optional

from app.models.schliessanlage import TuerBerechtigung
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT b.id, b.chip_id, b.schloss_id, b.ttlock_card_id, b.gueltig_von, b.gueltig_bis,
           b.sync_status, b.sync_fehler, b.erteilt_von,
           s.name AS schloss_name, c.bezeichnung AS chip_bezeichnung,
           c.kartennummer AS kartennummer, c.mitglied_id AS mitglied_id,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           b.version, b.created_at, b.created_by, b.updated_at, b.updated_by,
           b.deleted_at, b.deleted_by
    FROM tuer_berechtigung b
    LEFT JOIN tuer_schloss s ON s.id = b.schloss_id
    LEFT JOIN schluessel_chip c ON c.id = b.chip_id
    LEFT JOIN mitglied m ON m.id = c.mitglied_id
"""


def _map(row) -> TuerBerechtigung:
    return TuerBerechtigung(**dict(row))


class TuerBerechtigungRepository(BaseRepository):

    def get(self, id: int) -> Optional[TuerBerechtigung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE b.id = %s AND b.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_schloss(self, schloss_id: int) -> list[TuerBerechtigung]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE b.schloss_id = %s AND b.deleted_at IS NULL "
                          "ORDER BY c.bezeichnung, b.id",
                (schloss_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_chip(self, chip_id: int) -> list[TuerBerechtigung]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE b.chip_id = %s AND b.deleted_at IS NULL "
                          "ORDER BY s.name, b.id",
                (chip_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def user_has_valid_for_schloss(self, user_id: int, schloss_id: int) -> bool:
        """Self-Service-Check: hat der eingeloggte User (über sein Mitglied → Chip) eine
        aktuell gültige, nicht gesperrte Berechtigung für genau dieses Schloss?

        Datums-Vergleich der (als ISO-Text gespeicherten) Gültigkeit gegen now()."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM tuer_berechtigung b
                JOIN schluessel_chip c ON c.id = b.chip_id AND c.deleted_at IS NULL
                JOIN mitglied m ON m.id = c.mitglied_id
                WHERE b.schloss_id = %s AND m.user_id = %s
                  AND b.deleted_at IS NULL
                  AND c.status = 'aktiv'
                  AND b.sync_status <> 'gesperrt'
                  AND (b.gueltig_von IS NULL OR NULLIF(b.gueltig_von, '')::timestamptz <= now())
                  AND (b.gueltig_bis IS NULL OR NULLIF(b.gueltig_bis, '')::timestamptz >= now())
                LIMIT 1
                """,
                (schloss_id, user_id),
            )
            return cur.fetchone() is not None
