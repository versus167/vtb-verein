"""Repository für Berechtigungen (Chip an einem Schloss = eine TTLock-IC-Card).

Phase 2: Anlegen (pending → aktiv/fehler), Gültigkeit ändern und Entziehen
(Soft-Delete). Die eigentlichen Cloud-Writes (`identityCard/add|changePeriod|delete`)
orchestriert der :class:`ZutrittService`; dieses Repo hält nur den lokalen Spiegel
(inkl. `ttlock_card_id`/`sync_status`) konsistent. Jede Änderung bumpt `version`,
damit der UPDATE-Trigger einen History-Eintrag schreibt.
"""
from typing import Optional

from app.models.schliessanlage import SYNC_AKTIV, SYNC_PENDING

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

    def find_active_for_chip_schloss(self, chip_id: int, schloss_id: int) -> Optional[TuerBerechtigung]:
        """Aktive (nicht gelöschte) Berechtigung dieses Chips an genau diesem Schloss.
        Spiegelt den partiellen Unique-Index (chip_id, schloss_id) WHERE deleted_at IS NULL."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE b.chip_id = %s AND b.schloss_id = %s AND b.deleted_at IS NULL",
                (chip_id, schloss_id),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, b: TuerBerechtigung, created_by: str) -> TuerBerechtigung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tuer_berechtigung
                    (chip_id, schloss_id, ttlock_card_id, gueltig_von, gueltig_bis,
                     sync_status, sync_fehler, erteilt_von, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (b.chip_id, b.schloss_id, b.ttlock_card_id, b.gueltig_von, b.gueltig_bis,
                 b.sync_status or SYNC_PENDING, b.sync_fehler, b.erteilt_von,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def set_sync(self, id: int, *, ttlock_card_id: Optional[int], sync_status: str,
                 sync_fehler: Optional[str], by: str) -> Optional[TuerBerechtigung]:
        """Sync-Ergebnis eines Cloud-Writes festhalten (cardId/Status/Fehler)."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE tuer_berechtigung
                SET ttlock_card_id=%s, sync_status=%s, sync_fehler=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (ttlock_card_id, sync_status, sync_fehler, by, id),
            )
            if cur.rowcount == 0:
                return None
        return self.get(id)

    def update_period(self, id: int, *, gueltig_von: Optional[str],
                      gueltig_bis: Optional[str], by: str) -> Optional[TuerBerechtigung]:
        """Gültigkeit fortschreiben. Wird nur nach erfolgreichem Cloud-changePeriod
        aufgerufen → Sync-Status auf 'aktiv' setzen und einen evtl. Altfehler löschen."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE tuer_berechtigung
                SET gueltig_von=%s, gueltig_bis=%s, sync_status=%s, sync_fehler=NULL,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (gueltig_von, gueltig_bis, SYNC_AKTIV, by, id),
            )
            if cur.rowcount == 0:
                return None
        return self.get(id)

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tuer_berechtigung SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount > 0

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
