'''
Created on 21.02.2026

Mitglied Repository - All database operations for Mitglied entity.

@author: AI Assistant
'''

import sqlite3
from app.models.mitglied import Mitglied
from app.db.base_repository import BaseRepository


class MitgliedRepository(BaseRepository):
    """Repository for Mitglied CRUD operations.
    
    Handles:
    - Create, Read, Update operations
    - Soft-delete (mark as deleted)
    - Mitgliedsnummer management
    - History tracking (via database triggers)
    """
    
    def get_next_mitgliedsnummer(self) -> int:
        """Get the next available Mitgliedsnummer.
        
        Returns the highest mitgliedsnummer + 1, including deleted members.
        Starts at 1 if no members exist.
        """
        with self.cursor() as cur:
            cur.execute("SELECT MAX(mitgliedsnummer) FROM mitglied")
            result = cur.fetchone()[0]
            return (result + 1) if result is not None else 1
    
    def is_mitgliedsnummer_available(self, nummer: int, exclude_id: int = None) -> bool:
        """Check if a Mitgliedsnummer is available.
        
        Args:
            nummer: The Mitgliedsnummer to check
            exclude_id: Optional member ID to exclude from check (for updates)
        
        Returns:
            bool: True if nummer is available, False if already in use
        """
        with self.cursor() as cur:
            if exclude_id:
                cur.execute(
                    "SELECT 1 FROM mitglied WHERE mitgliedsnummer = ? AND id != ? LIMIT 1",
                    (nummer, exclude_id)
                )
            else:
                cur.execute(
                    "SELECT 1 FROM mitglied WHERE mitgliedsnummer = ? LIMIT 1",
                    (nummer,)
                )
            return cur.fetchone() is None
    
    def get_mitglied(self, id: int) -> Mitglied:
        """Get a single Mitglied by ID (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, mitgliedsnummer, vorname, nachname, geburtsdatum,
                       strasse, plz, ort, land, email, telefon,
                       eintrittsdatum, austrittsdatum, status,
                       zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                       version, created_at, created_by, updated_at, updated_by
                FROM mitglied
                WHERE id = ? AND deleted_at IS NULL
                """,
                (id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Mitglied {id} nicht gefunden")
            return Mitglied(**dict(row))
    
    def list_mitglieder(self) -> list[Mitglied]:
        """List all active (non-deleted) Mitglieder."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, mitgliedsnummer, vorname, nachname, geburtsdatum,
                       strasse, plz, ort, land, email, telefon,
                       eintrittsdatum, austrittsdatum, status,
                       zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                       version, created_at, created_by, updated_at, updated_by
                FROM mitglied
                WHERE deleted_at IS NULL
                ORDER BY nachname, vorname
                """
            )
            return [Mitglied(**dict(row)) for row in cur.fetchall()]
    
    def create_mitglied(self, mitglied: Mitglied, created_by: str) -> Mitglied:
        """Create a new Mitglied.
        
        If mitgliedsnummer is None, automatically assigns the next available number.
        History is written automatically via trigger.
        """
        with self.cursor() as cur:
            # Auto-assign mitgliedsnummer if not provided
            if mitglied.mitgliedsnummer is None:
                mitglied.mitgliedsnummer = self.get_next_mitgliedsnummer()
            
            cur.execute(
                """
                INSERT INTO mitglied (
                    mitgliedsnummer, vorname, nachname, geburtsdatum,
                    strasse, plz, ort, land, email, telefon,
                    eintrittsdatum, austrittsdatum, status,
                    zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                    created_by, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    mitglied.mitgliedsnummer, mitglied.vorname, mitglied.nachname, mitglied.geburtsdatum,
                    mitglied.strasse, mitglied.plz, mitglied.ort, mitglied.land, mitglied.email, mitglied.telefon,
                    mitglied.eintrittsdatum, mitglied.austrittsdatum, mitglied.status,
                    mitglied.zahlungsart, mitglied.iban, mitglied.bic, mitglied.kontoinhaber, mitglied.abgerechnet_bis,
                    created_by, created_by
                ),
            )
            mitglied.id = cur.lastrowid
            
            # Fetch complete created record
            cur.execute(
                """
                SELECT id, mitgliedsnummer, vorname, nachname, geburtsdatum,
                       strasse, plz, ort, land, email, telefon,
                       eintrittsdatum, austrittsdatum, status,
                       zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                       version, created_at, created_by, updated_at, updated_by
                FROM mitglied
                WHERE id = ?
                """,
                (mitglied.id,),
            )
            row = cur.fetchone()
            return Mitglied(**dict(row))
    
    def update_mitglied(self, mitglied: Mitglied, updated_by: str) -> bool:
        """Update a Mitglied. History is written automatically via trigger.
        
        Returns:
            bool: True if update successful, False if version conflict or not found
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied
                SET mitgliedsnummer = ?, vorname = ?, nachname = ?, geburtsdatum = ?,
                    strasse = ?, plz = ?, ort = ?, land = ?, email = ?, telefon = ?,
                    eintrittsdatum = ?, austrittsdatum = ?, status = ?,
                    zahlungsart = ?, iban = ?, bic = ?, kontoinhaber = ?, abgerechnet_bis = ?,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (
                    mitglied.mitgliedsnummer, mitglied.vorname, mitglied.nachname, mitglied.geburtsdatum,
                    mitglied.strasse, mitglied.plz, mitglied.ort, mitglied.land, mitglied.email, mitglied.telefon,
                    mitglied.eintrittsdatum, mitglied.austrittsdatum, mitglied.status,
                    mitglied.zahlungsart, mitglied.iban, mitglied.bic, mitglied.kontoinhaber, mitglied.abgerechnet_bis,
                    updated_by, mitglied.id, mitglied.version
                ),
            )
            if cur.rowcount == 0:
                return False
            
            # Get new state
            cur.execute(
                """
                SELECT version, updated_at
                FROM mitglied
                WHERE id = ?
                """,
                (mitglied.id,),
            )
            row = cur.fetchone()
            mitglied.version = row["version"]
            mitglied.updated_at = row["updated_at"]
            mitglied.updated_by = updated_by
            return True
    
    def mark_mitglied_deleted(self, mitglied_id: int, deleted_by: str) -> bool:
        """Soft-delete: Mark Mitglied as deleted.
        
        Note: Does NOT check for dependencies - that's business logic in the service layer.
        
        Returns:
            bool: True if marked as deleted, False if not found or already deleted
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (deleted_by, mitglied_id)
            )
            return cur.rowcount == 1
