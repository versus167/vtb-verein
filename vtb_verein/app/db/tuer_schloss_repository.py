"""Repository für das gespiegelte Schloss-/Tür-Inventar (aus v3/lock/list)."""
from typing import Optional

from app.models.schliessanlage import TuerSchloss
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT s.id, s.ttlock_lock_id, s.name, s.standort, s.abteilung_id,
           s.ttlock_gateway_id, s.gateway_online, s.lock_mac, s.akku_prozent, s.akku_stand_at,
           s.aktiv, s.notiz, s.letzter_log_serverdate, s.letztes_event_at, s.letztes_event_type,
           (SELECT MAX(sl.geaendert_am) FROM tuer_schloss_status_log sl
              WHERE sl.schloss_id = s.id) AS gateway_online_seit,
           (SELECT COALESCE(
                     NULLIF(TRIM(COALESCE(m.vorname, '') || ' ' || COALESCE(m.nachname, '')), ''),
                     c.bezeichnung, l.key_name, l.ttlock_username)
              FROM tuer_zutritt_log l
              LEFT JOIN mitglied m ON m.id = l.mitglied_id
              LEFT JOIN schluessel_chip c ON c.id = l.chip_id
              WHERE l.schloss_id = s.id
              ORDER BY l.server_date DESC NULLS LAST
              LIMIT 1) AS letztes_event_wer,
           ab.name AS abteilung_name,
           s.version, s.created_at, s.created_by, s.updated_at, s.updated_by,
           s.deleted_at, s.deleted_by
    FROM tuer_schloss s
    LEFT JOIN abteilung ab ON ab.id = s.abteilung_id
"""


def _map(row) -> TuerSchloss:
    return TuerSchloss(**dict(row))


class TuerSchlossRepository(BaseRepository):

    def get(self, id: int) -> Optional[TuerSchloss]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.id = %s AND s.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def get_by_lock_id(self, ttlock_lock_id: int) -> Optional[TuerSchloss]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.ttlock_lock_id = %s AND s.deleted_at IS NULL",
                        (ttlock_lock_id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_all(self, *, nur_aktive: bool = False) -> list[TuerSchloss]:
        where = "WHERE s.deleted_at IS NULL"
        if nur_aktive:
            where += " AND s.aktiv = TRUE"
        with self.cursor() as cur:
            cur.execute(_SELECT + where + " ORDER BY s.name, s.id")
            return [_map(r) for r in cur.fetchall()]

    def upsert_inventory(self, *, ttlock_lock_id: int, name: str,
                         lock_mac: Optional[str], ttlock_gateway_id: Optional[int],
                         gateway_online: Optional[bool], akku_prozent: Optional[int],
                         akku_stand_at: Optional[str], by: str = 'SYSTEM') -> int:
        """Cloud-Inventar spiegeln. Bei Bestand werden NUR cloud-abgeleitete Felder
        aktualisiert – name/standort/abteilung/notiz/aktiv bleiben user-gepflegt.
        Gibt die lokale Schloss-id zurück."""
        existing = self.get_by_lock_id(ttlock_lock_id)
        with self.cursor() as cur:
            if existing:
                # No-Op-Schutz: nur schreiben (Version-Bump → History), wenn sich ein
                # cloud-abgeleitetes Feld tatsächlich geändert hat.
                unchanged = (
                    existing.lock_mac == lock_mac
                    and existing.ttlock_gateway_id == ttlock_gateway_id
                    and existing.gateway_online == gateway_online
                    and existing.akku_prozent == akku_prozent
                    and existing.akku_stand_at == akku_stand_at
                )
                if unchanged:
                    return existing.id
                # Online-Status separat prüfen: Konnektivitäts-Log nur bei echtem Wechsel
                # fortschreiben (nicht bei reinen Akku-Änderungen). `!=` deckt das tri-state
                # None/True/False sauber ab (== IS DISTINCT FROM).
                online_changed = existing.gateway_online != gateway_online
                cur.execute(
                    """
                    UPDATE tuer_schloss
                    SET lock_mac=%s, ttlock_gateway_id=%s, gateway_online=%s,
                        akku_prozent=%s, akku_stand_at=%s, version=version+1,
                        updated_at=CURRENT_TIMESTAMP, updated_by=%s
                    WHERE id=%s
                    """,
                    (lock_mac, ttlock_gateway_id, gateway_online, akku_prozent,
                     akku_stand_at, by, existing.id),
                )
                if online_changed:
                    self._log_gateway_status(cur, existing.id, gateway_online)
                return existing.id
            cur.execute(
                """
                INSERT INTO tuer_schloss
                    (ttlock_lock_id, name, lock_mac, ttlock_gateway_id, gateway_online,
                     akku_prozent, akku_stand_at, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (ttlock_lock_id, name, lock_mac, ttlock_gateway_id, gateway_online,
                 akku_prozent, akku_stand_at, by, by),
            )
            new_id = cur.fetchone()['id']
            # Ausgangsstatus als Startpunkt des Konnektivitäts-Logs festhalten (#82).
            self._log_gateway_status(cur, new_id, gateway_online)
            return new_id

    @staticmethod
    def _log_gateway_status(cur, schloss_id: int, online: Optional[bool]) -> None:
        """Einen online↔offline-Wechsel append-only protokollieren (#82). Läuft in der
        aufrufenden Transaktion, damit Schloss-Update und Log-Eintrag atomar bleiben."""
        cur.execute(
            "INSERT INTO tuer_schloss_status_log (schloss_id, online) VALUES (%s, %s)",
            (schloss_id, online),
        )

    def update_cursor_and_event(self, schloss_id: int, *, serverdate: Optional[int],
                                letztes_event_at: Optional[str],
                                letztes_event_type: Optional[int], by: str = 'SYSTEM') -> None:
        """Sync-Cursor + Status-Snapshot (letzter Schließvorgang) fortschreiben.
        Setzt nur vorwärts (verhindert Cursor-Rückschritt bei Teil-Syncs)."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE tuer_schloss
                SET letzter_log_serverdate = GREATEST(COALESCE(letzter_log_serverdate, 0), COALESCE(%s, 0)),
                    letztes_event_at = COALESCE(%s, letztes_event_at),
                    letztes_event_type = COALESCE(%s, letztes_event_type),
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s
                """,
                (serverdate, letztes_event_at, letztes_event_type, by, schloss_id),
            )

    def update_stammdaten(self, s: TuerSchloss, updated_by: str) -> Optional[TuerSchloss]:
        """User-gepflegte Felder (Name/Standort/Abteilung/Notiz/aktiv), optimistisch."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE tuer_schloss
                SET name=%s, standort=%s, abteilung_id=%s, notiz=%s, aktiv=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (s.name, s.standort, s.abteilung_id, s.notiz, s.aktiv, updated_by, s.id, s.version),
            )
            if cur.rowcount == 0:
                return None
        return self.get(s.id)

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tuer_schloss SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount > 0
