"""
Repository für die Prune-Tunables (`prune_einstellungen`).

Override-Speicher: enthält nur Entitäten, für die der Admin von den Code-Defaults
abweichende Werte gesetzt hat. Der PruneService mischt diese Overrides über die Defaults
der Struktur-Registry. Reine Config-Tabelle – kein Soft-Delete, keine History.
"""
from typing import Any, Dict

from app.db.base_repository import BaseRepository


class PruneEinstellungenRepository(BaseRepository):

    def get_all(self) -> Dict[str, Dict[str, int]]:
        """Alle gesetzten Overrides als ``{entity: {retention_days, keep_min, history_retention_days}}``."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT entity, retention_days, keep_min, history_retention_days "
                "FROM prune_einstellungen"
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
        """Setzt (oder aktualisiert) den Override für eine Entität."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prune_einstellungen
                    (entity, retention_days, keep_min, history_retention_days, updated_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (entity) DO UPDATE SET
                    retention_days = EXCLUDED.retention_days,
                    keep_min = EXCLUDED.keep_min,
                    history_retention_days = EXCLUDED.history_retention_days,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = EXCLUDED.updated_by
                RETURNING entity, retention_days, keep_min, history_retention_days,
                          updated_at, updated_by
                """,
                (entity, retention_days, keep_min, history_retention_days, updated_by),
            )
            return dict(cur.fetchone())

    def delete(self, entity: str) -> bool:
        """Entfernt den Override → Entität fällt auf die Code-Defaults zurück."""
        with self.cursor() as cur:
            cur.execute("DELETE FROM prune_einstellungen WHERE entity = %s", (entity,))
            return cur.rowcount > 0
