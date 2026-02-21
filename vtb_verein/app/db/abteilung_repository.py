'''
Created on 21.02.2026

Abteilung Repository - All database operations for Abteilung entity.

@author: AI Assistant
'''

import sqlite3
from app.models.abteilung import Abteilung
from app.db.base_repository import BaseRepository


class AbteilungRepository(BaseRepository):
    """Repository for Abteilung CRUD operations.
    
    Handles:
    - Create, Read, Update operations
    - Soft-delete and restore operations
    - Dependency checks for business logic
    - History tracking (via database triggers)
    """
    
    def get_abteilung(self, id: int) -> Abteilung:
        """Get a single Abteilung by ID (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE id = ? AND deleted_at IS NULL
                """,
                (id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Abteilung {id} nicht gefunden")
            return Abteilung(**dict(row))

    def list_abteilungen(self) -> list[Abteilung]:
        """List all active (non-deleted) Abteilungen."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE deleted_at IS NULL
                ORDER BY name
                """
            )
            return [Abteilung(**dict(row)) for row in cur.fetchall()]
    
    def list_deleted_abteilungen(self) -> list[dict]:
        """List all deleted Abteilungen with deletion metadata.
        
        Returns a list of dictionaries containing the Abteilung data plus deletion info:
        - All Abteilung fields
        - deleted_at: timestamp when deleted
        - deleted_by: user who deleted it
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by,
                       deleted_at, deleted_by
                FROM abteilung
                WHERE deleted_at IS NOT NULL
                ORDER BY deleted_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def create_abteilung(self, abt: Abteilung, created_by: str) -> Abteilung:
        """Create a new Abteilung. History is written automatically via trigger."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO abteilung (name, kuerzel, beschreibung, created_by, updated_at, updated_by)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (abt.name, abt.kuerzel, abt.beschreibung, created_by, created_by),
            )
            abt.id = cur.lastrowid
    
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE id = ?
                """,
                (abt.id,),
            )
            row = cur.fetchone()
            return Abteilung(**dict(row))

    def update_abteilung(self, abt: Abteilung, updated_by: str) -> bool:
        """Update an Abteilung. History is written automatically via trigger.
        
        Returns:
            bool: True if update successful, False if version conflict or not found
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE abteilung
                SET name = ?, kuerzel = ?, beschreibung = ?,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (abt.name, abt.kuerzel, abt.beschreibung,
                 updated_by, abt.id, abt.version),
            )
            if cur.rowcount == 0:
                return False
    
            # Get new state for return
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE id = ?
                """,
                (abt.id,),
            )
            row = cur.fetchone()
            new_row = dict(row)
    
            abt.version = new_row["version"]
            abt.updated_at = new_row["updated_at"]
            abt.updated_by = updated_by
            return True
        
    def mark_abteilung_deleted(self, abteilung_id: int, deleted_by: str) -> bool:
        """Soft-delete: Mark Abteilung as deleted. History is written automatically via trigger.
        
        Note: Does NOT check for dependencies - that's business logic in the service layer.
        
        Returns:
            bool: True if marked as deleted, False if not found or already deleted
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE abteilung
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (deleted_by, abteilung_id)
            )
            return cur.rowcount == 1
    
    def restore_abteilung(self, abteilung_id: int, restored_by: str) -> bool:
        """Restore a soft-deleted Abteilung.
        
        Sets deleted_at and deleted_by to NULL and increments version.
        History is written automatically via trigger.
        
        Returns:
            bool: True if restored successfully, False if not found or not deleted
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE abteilung
                SET deleted_at = NULL,
                    deleted_by = NULL,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ? AND deleted_at IS NOT NULL
                """,
                (restored_by, abteilung_id)
            )
            return cur.rowcount == 1

    # -----------------------------------
    # Query Methods for Business Logic
    # -----------------------------------
    
    def has_active_mitglied_abteilung_references(self, abteilung_id: int) -> bool:
        """Check if there are active (non-deleted) mitglied_abteilung references."""
        with self.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM mitglied_abteilung WHERE abteilung_id = ? AND deleted_at IS NULL LIMIT 1',
                (abteilung_id,),
            )
            return cur.fetchone() is not None

    def has_active_beitragsregel_references(self, abteilung_id: int) -> bool:
        """Check if there are active (non-deleted) beitragsregel references."""
        with self.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM beitragsregel WHERE abteilung_id = ? AND deleted_at IS NULL LIMIT 1',
                (abteilung_id,),
            )
            return cur.fetchone() is not None

    def has_mitglied_abteilung_history(self, abteilung_id: int) -> bool:
        """Check if there are any mitglied_abteilung_history entries."""
        with self.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM mitglied_abteilung_history WHERE abteilung_id = ? LIMIT 1',
                (abteilung_id,),
            )
            return cur.fetchone() is not None

    def has_beitragsregel_history(self, abteilung_id: int) -> bool:
        """Check if there are any beitragsregel_history entries."""
        with self.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM beitragsregel_history WHERE abteilung_id = ? LIMIT 1',
                (abteilung_id,),
            )
            return cur.fetchone() is not None

    # -----------------------------------
    # Future: Prune Operations
    # -----------------------------------
    
    def prune_deleted_abteilungen(self, days_old: int) -> int:
        """Hard-delete Abteilungen that have been soft-deleted for more than days_old days.
        
        TODO: Implement when needed. Should check for any remaining references first.
        
        Returns:
            int: Number of records physically deleted
        """
        raise NotImplementedError("Prune operations will be implemented later")
