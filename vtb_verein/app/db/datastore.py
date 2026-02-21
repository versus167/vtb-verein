'''
Created on 07.02.2026
Refactored on 21.02.2026

VereinsDB Facade - Maintains backward compatibility while delegating to repositories.

@author: volker
@refactored: AI Assistant
'''

from app.db.database import Database
from app.db.mitglied_repository import MitgliedRepository
from app.db.abteilung_repository import AbteilungRepository
from app.db.user_repository import UserRepository
from app.models.mitglied import Mitglied
from app.models.abteilung import Abteilung


class VereinsDB:
    """Data Access Layer Facade - Delegates to specialized repositories.
    
    This class provides a unified interface for database access while
    delegating to specialized repositories internally. This maintains
    backward compatibility with existing code.
    
    Architecture:
    - Database: Connection and schema management
    - Repositories: Entity-specific CRUD operations
    - VereinsDB: Facade that combines all repositories
    
    Business logic belongs in the service layer.
    """
    
    def __init__(self, path: str):
        self.path = path
        self._database = Database(path)
        self.conn = self._database.conn
        
        # Initialize repositories
        self._mitglied_repo = MitgliedRepository(self.conn)
        self._abteilung_repo = AbteilungRepository(self.conn)
        self._user_repo = UserRepository(self.conn)
    
    def cursor(self):
        """Provide cursor for custom queries (use sparingly)."""
        return self._database.cursor()
    
    def close(self):
        """Close the database connection."""
        self._database.close()
    
    # -----------------------------------
    # Mitglied Operations - Delegate to MitgliedRepository
    # -----------------------------------
    
    def get_next_mitgliedsnummer(self) -> int:
        return self._mitglied_repo.get_next_mitgliedsnummer()
    
    def is_mitgliedsnummer_available(self, nummer: int, exclude_id: int = None) -> bool:
        return self._mitglied_repo.is_mitgliedsnummer_available(nummer, exclude_id)
    
    def get_mitglied(self, id: int) -> Mitglied:
        return self._mitglied_repo.get_mitglied(id)
    
    def list_mitglieder(self) -> list[Mitglied]:
        return self._mitglied_repo.list_mitglieder()
    
    def create_mitglied(self, mitglied: Mitglied, created_by: str) -> Mitglied:
        return self._mitglied_repo.create_mitglied(mitglied, created_by)
    
    def update_mitglied(self, mitglied: Mitglied, updated_by: str) -> bool:
        return self._mitglied_repo.update_mitglied(mitglied, updated_by)
    
    def mark_mitglied_deleted(self, mitglied_id: int, deleted_by: str) -> bool:
        return self._mitglied_repo.mark_mitglied_deleted(mitglied_id, deleted_by)
    
    # -----------------------------------
    # Abteilung Operations - Delegate to AbteilungRepository
    # -----------------------------------
    
    def get_abteilung(self, id: int) -> Abteilung:
        return self._abteilung_repo.get_abteilung(id)
    
    def list_abteilungen(self) -> list[Abteilung]:
        return self._abteilung_repo.list_abteilungen()
    
    def list_deleted_abteilungen(self) -> list[dict]:
        return self._abteilung_repo.list_deleted_abteilungen()
    
    def create_abteilung(self, abt: Abteilung, created_by: str) -> Abteilung:
        return self._abteilung_repo.create_abteilung(abt, created_by)
    
    def update_abteilung(self, abt: Abteilung, updated_by: str) -> bool:
        return self._abteilung_repo.update_abteilung(abt, updated_by)
    
    def mark_abteilung_deleted(self, abteilung_id: int, deleted_by: str) -> bool:
        return self._abteilung_repo.mark_abteilung_deleted(abteilung_id, deleted_by)
    
    def restore_abteilung(self, abteilung_id: int, restored_by: str) -> bool:
        return self._abteilung_repo.restore_abteilung(abteilung_id, restored_by)
    
    def has_active_mitglied_abteilung_references(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_active_mitglied_abteilung_references(abteilung_id)
    
    def has_active_beitragsregel_references(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_active_beitragsregel_references(abteilung_id)
    
    def has_mitglied_abteilung_history(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_mitglied_abteilung_history(abteilung_id)
    
    def has_beitragsregel_history(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_beitragsregel_history(abteilung_id)
    
    def prune_deleted_abteilungen(self, days_old: int) -> int:
        return self._abteilung_repo.prune_deleted_abteilungen(days_old)
