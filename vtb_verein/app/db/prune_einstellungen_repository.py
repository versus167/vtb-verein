"""
Repository für die Prune-Tunables (`prune_einstellungen`).

Override-Speicher: enthält nur Entitäten, für die der Admin von den Code-Defaults
abweichende Werte gesetzt hat. Der PruneService mischt diese Overrides über die Defaults
der Struktur-Registry. Seit Schema v61 folgt die Tabelle dem „History + Smart-Delete"-
Prinzip: jede Änderung ist versioniert (Trigger → `prune_einstellungen_history`), und ein
zurückgesetzter Override wird soft-deleted (nicht hart gelöscht). Ein erneutes Setzen für
dieselbe Entität reaktiviert die Zeile (deleted_at → NULL).
"""
from typing import Any, Dict

from app.db.base_repository import BaseRepository


class PruneEinstellungenRepository(BaseRepository):

    def get_all(self) -> Dict[str, Dict[str, int]]:
        """Alle aktiven Overrides als ``{entity: {retention_days, keep_min, history_retention_days}}``."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT entity, retention_days, keep_min, history_retention_days "
                "FROM prune_einstellungen WHERE deleted_at IS NULL"
            )
            return {
                r["entity"]: {
                    "retention_days": r["retention_days"],
                    "keep_min": r["keep_min"],
                    "history_retention_days": r["history_retention_days"],
                }
                for r in cur.fetchall()
            }

    def upsert(
        self,
        entity: str,
        retention_days: int,
        keep_min: int,
        history_retention_days: int,
        updated_by: str,
    ) -> Dict[str, Any]:
        """Setzt (oder aktualisiert) den Override für eine Entität.

        Bumpt bei bestehender Zeile die Version (Trigger schreibt in die History) und
        reaktiviert einen zuvor soft-gelöschten Override (deleted_at/deleted_by → NULL).
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prune_einstellungen
                    (entity, retention_days, keep_min, history_retention_days,
                     created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity) DO UPDATE SET
                    retention_days = EXCLUDED.retention_days,
                    keep_min = EXCLUDED.keep_min,
                    history_retention_days = EXCLUDED.history_retention_days,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = EXCLUDED.updated_by,
                    version = prune_einstellungen.version + 1,
                    deleted_at = NULL,
                    deleted_by = NULL
                RETURNING entity, retention_days, keep_min, history_retention_days,
                          updated_at, updated_by
                """,
                (entity, retention_days, keep_min, history_retention_days,
                 updated_by, updated_by),
            )
            return dict(cur.fetchone())

    def delete(self, entity: str, deleted_by: str) -> bool:
        """Soft-Delete des Overrides → Entität fällt auf die Code-Defaults zurück.

        Die Zeile bleibt (mit gesetztem deleted_at) erhalten; get_all() blendet sie aus.
        Der Version-Bump lässt den Update-Trigger den Vorgang in die History schreiben.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE prune_einstellungen
                   SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1
                 WHERE entity = %s AND deleted_at IS NULL
                """,
                (deleted_by, entity),
            )
            return cur.rowcount > 0
