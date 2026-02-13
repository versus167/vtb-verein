'''
Created on 08.02.2026

@author: volker
'''
# app/services/abteilungen_service.py
from typing import List
from app.db.datastore import VereinsDB
from app.models.abteilung import Abteilung


class AbteilungenService:
    """Business logic layer for Abteilungen.
    
    Handles validation, business rules, and orchestrates data access.
    """
    
    def __init__(self, db: VereinsDB):
        self.db = db

    def get_abteilung(self, id: int) -> Abteilung:
        """Get a single Abteilung by ID."""
        return self.db.get_abteilung(id)

    def list_abteilungen(self) -> List[Abteilung]:
        """List all active Abteilungen."""
        return self.db.list_abteilungen()

    def create_abteilung(self, name: str, kuerzel: str | None,
                         beschreibung: str | None, user: str) -> Abteilung:
        """Create a new Abteilung with validation.
        
        Args:
            name: Name of the Abteilung (required)
            kuerzel: Short code (optional)
            beschreibung: Description (optional)
            user: Username creating the Abteilung
            
        Returns:
            The newly created Abteilung with generated ID
        """
        # TODO: Add validation here
        # - name must not be empty
        # - name should be unique
        # - kuerzel should be unique if provided
        
        abt = Abteilung(name=name, kuerzel=kuerzel, beschreibung=beschreibung)
        return self.db.create_abteilung(abt, created_by=user)

    def update_abteilung(self, abt: Abteilung, user: str) -> bool:
        """Update an existing Abteilung with validation.
        
        Args:
            abt: Abteilung object with updated data (must have id and version)
            user: Username performing the update
            
        Returns:
            True if successful, False if version conflict or not found
        """
        # TODO: Add validation here
        # - name must not be empty
        # - name should be unique (excluding current abteilung)
        # - kuerzel should be unique if provided (excluding current abteilung)
        
        return self.db.update_abteilung(abt, updated_by=user)
    
    def can_delete_abteilung(self, abteilung_id: int) -> tuple[bool, str | None]:
        """Check if an Abteilung can be deleted.
        
        Business rule: Abteilung cannot be deleted if:
        - It has active mitglied_abteilung references
        - It has active beitragsregel references
        - It has any history entries in mitglied_abteilung_history
        - It has any history entries in beitragsregel_history
        
        Args:
            abteilung_id: ID of the Abteilung to check
            
        Returns:
            Tuple of (can_delete, reason)
            - can_delete: True if deletion is allowed, False otherwise
            - reason: Error message if can_delete is False, None otherwise
        """
        if self.db.has_active_mitglied_abteilung_references(abteilung_id):
            return False, "Abteilung hat aktive Mitgliederzuordnungen"
        
        if self.db.has_active_beitragsregel_references(abteilung_id):
            return False, "Abteilung hat aktive Beitragsregeln"
        
        if self.db.has_mitglied_abteilung_history(abteilung_id):
            return False, "Abteilung hat historische Mitgliederzuordnungen"
        
        if self.db.has_beitragsregel_history(abteilung_id):
            return False, "Abteilung hat historische Beitragsregeln"
        
        return True, None
    
    def delete_abteilung(self, abteilung_id: int, user: str) -> tuple[bool, str | None]:
        """Delete (soft-delete) an Abteilung after checking business rules.
        
        Args:
            abteilung_id: ID of the Abteilung to delete
            user: Username performing the deletion
            
        Returns:
            Tuple of (success, error_message)
            - success: True if deleted, False otherwise
            - error_message: Reason if deletion failed, None if successful
        """
        # Check business rules first
        can_delete, reason = self.can_delete_abteilung(abteilung_id)
        if not can_delete:
            return False, reason
        
        # Perform soft-delete
        success = self.db.mark_abteilung_deleted(abteilung_id, deleted_by=user)
        if not success:
            return False, "Abteilung nicht gefunden oder bereits gelöscht"
        
        return True, None
