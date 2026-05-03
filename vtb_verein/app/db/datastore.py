'''
Created on 07.02.2026
Refactored on 21.02.2026
Extended on 07.03.2026 - Magic-Link Authentication
Extended on 11.03.2026 - PermissionRepository hinzugefügt
Extended on 26.03.2026 - Kassenbuch-Repositories und KassenbuchService
Extended on 27.03.2026 - KasseBerechtigungRepository (Phase 3.2)
Extended on 28.03.2026 - KasseBerechtigungRepository an KassenbuchService übergeben (Phase 3.4)
Extended on 05.04.2026 - Ticket-System Repositories und TicketService (Phase 4.1)
Extended on 06.04.2026 - TicketBereichBerechtigungRepository (Phase 4.2)

VereinsDB Facade - Maintains backward compatibility while delegating to repositories.

@author: volker
@refactored: AI Assistant
'''

import os
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.kassenbuch_service import KassenbuchService
from app.db.database import Database
from app.db.mitglied_repository import MitgliedRepository
from app.db.abteilung_repository import AbteilungRepository
from app.db.user_repository import UserRepository
from app.db.permission_repository import PermissionRepository
from app.db.auth_token_repository import AuthTokenRepository
from app.db.kasse_repository import KasseRepository
from app.db.kassenbuchung_repository import KassenbuchungRepository
from app.db.kassenbuch_export_repository import KassenbuchExportRepository
from app.db.kasse_berechtigung_repository import KasseBerechtigungRepository
from app.db.ticket_repository import TicketRepository
from app.db.ticket_kommentar_repository import TicketKommentarRepository
from app.db.ticket_anhang_repository import TicketAnhangRepository
from app.db.ticket_bereich_repository import TicketBereichRepository
from app.db.ticket_kategorie_repository import TicketKategorieRepository
from app.db.ticket_teilnehmer_repository import TicketTeilnehmerRepository
from app.db.ticket_bereich_berechtigung_repository import TicketBereichBerechtigungRepository
from app.models.mitglied import Mitglied
from app.models.abteilung import Abteilung
from app.models.user import User
from app.services.ticket_service import TicketService
from app.services.anhang_service import AnhangService


class VereinsDB:
    """Data Access Layer Facade - Delegates to specialized repositories."""

    def __init__(self, path: str, upload_path: str = 'uploads/'):
        from app.services.kassenbuch_service import KassenbuchService
        self.path = path
        self._database = Database(path)
        self.conn = self._database.conn

        self._mitglied_repo = MitgliedRepository(self.conn)
        self._abteilung_repo = AbteilungRepository(self.conn)
        self._user_repo = UserRepository(self.conn)
        self._permission_repo = PermissionRepository(self.conn)
        self._auth_token_repo = AuthTokenRepository(self._database)
        self._kasse_repo = KasseRepository(self.conn)
        self._kassenbuchung_repo = KassenbuchungRepository(self.conn)
        self._kassenbuch_export_repo = KassenbuchExportRepository(self.conn)
        self._kasse_berechtigung_repo = KasseBerechtigungRepository(self.conn)

        self._kassenbuch_service = KassenbuchService(
            kasse_repo=self._kasse_repo,
            buchung_repo=self._kassenbuchung_repo,
            export_repo=self._kassenbuch_export_repo,
            berechtigung_repo=self._kasse_berechtigung_repo,
        )

        self._ticket_repo = TicketRepository(self.conn)
        self._ticket_kommentar_repo = TicketKommentarRepository(self.conn)
        self._ticket_anhang_repo = TicketAnhangRepository(self.conn)
        self._ticket_bereich_repo = TicketBereichRepository(self.conn)
        self._ticket_kategorie_repo = TicketKategorieRepository(self.conn)
        self._ticket_teilnehmer_repo = TicketTeilnehmerRepository(self.conn)
        self._ticket_bereich_berechtigung_repo = TicketBereichBerechtigungRepository(self.conn)

        self._anhang_service = AnhangService(
            upload_path=upload_path,
            max_mb=int(os.getenv('VTB_MAX_UPLOAD_MB', '10')),
        )

        self._ticket_service = TicketService(
            ticket_repo=self._ticket_repo,
            kommentar_repo=self._ticket_kommentar_repo,
            anhang_repo=self._ticket_anhang_repo,
            bereich_repo=self._ticket_bereich_repo,
            kategorie_repo=self._ticket_kategorie_repo,
            teilnehmer_repo=self._ticket_teilnehmer_repo,
            berechtigung_repo=self._ticket_bereich_berechtigung_repo,
            user_repo=self._user_repo,
            anhang_service=self._anhang_service,
        )

    @property
    def user_repository(self) -> UserRepository:
        return self._user_repo

    @property
    def users(self) -> UserRepository:
        return self._user_repo

    @property
    def permissions(self) -> PermissionRepository:
        return self._permission_repo

    @property
    def auth_token_repository(self) -> AuthTokenRepository:
        return self._auth_token_repo

    @property
    def kassenbuch(self) -> "KassenbuchService":
        return self._kassenbuch_service

    @property
    def kassen(self) -> KasseRepository:
        """Direktzugriff auf KasseRepository (für Admin-Operationen)."""
        return self._kasse_repo

    @property
    def kasse_berechtigungen(self) -> KasseBerechtigungRepository:
        """Zugriff auf KasseBerechtigungRepository."""
        return self._kasse_berechtigung_repo

    @property
    def anhang_service(self) -> AnhangService:
        return self._anhang_service

    @property
    def tickets(self) -> TicketService:
        """Zugriff auf TicketService (Business-Logik + alle Ticket-Repos)."""
        return self._ticket_service

    @property
    def ticket_bereiche(self) -> TicketBereichRepository:
        """Direktzugriff auf TicketBereichRepository."""
        return self._ticket_bereich_repo

    @property
    def ticket_kategorien(self) -> TicketKategorieRepository:
        """Direktzugriff auf TicketKategorieRepository."""
        return self._ticket_kategorie_repo

    @property
    def ticket_bereich_berechtigungen(self) -> TicketBereichBerechtigungRepository:
        """Zugriff auf TicketBereichBerechtigungRepository."""
        return self._ticket_bereich_berechtigung_repo

    def cursor(self):
        return self._database.cursor()

    def close(self):
        self._database.close()

    # -----------------------------------
    # Mitglied Operations
    # -----------------------------------

    def get_next_mitgliedsnummer(self) -> int:
        return self._mitglied_repo.get_next_mitgliedsnummer()

    def is_mitgliedsnummer_available(self, nummer: int, exclude_id: int = None) -> bool:
        return self._mitglied_repo.is_mitgliedsnummer_available(nummer, exclude_id)

    def get_mitglied(self, id: int) -> Mitglied:
        return self._mitglied_repo.get_mitglied(id)

    def list_mitglieder(self) -> list[Mitglied]:
        return self._mitglied_repo.list_mitglieder()

    def list_mitglieder_for_standard_view(self) -> list[tuple[Mitglied, bool]]:
        return self._mitglied_repo.list_mitglieder_for_standard_view()

    def create_mitglied(self, mitglied: Mitglied, created_by: str) -> Mitglied:
        return self._mitglied_repo.create_mitglied(mitglied, created_by)

    def update_mitglied(self, mitglied: Mitglied, updated_by: str) -> bool:
        return self._mitglied_repo.update_mitglied(mitglied, updated_by)

    def mark_mitglied_deleted(self, mitglied_id: int, deleted_by: str) -> bool:
        return self._mitglied_repo.mark_mitglied_deleted(mitglied_id, deleted_by)

    # -----------------------------------
    # Abteilung Operations
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

    # -----------------------------------
    # User Operations
    # -----------------------------------

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self._user_repo.get_by_username(username)

    def get_user_by_email(self, email: str) -> Optional[User]:
        return self._user_repo.get_by_email(email)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self._user_repo.get_by_id(user_id)

    def list_users(self) -> List[User]:
        return self._user_repo.list_all()

    def count_active_admins(self) -> int:
        return self._user_repo.count_active_admins()

    def create_user(self, username: str, email: str, password_hash: str, role: str,
                    created_by: str, active: bool = True) -> User:
        return self._user_repo.create(username, email, password_hash, role, created_by, active)

    def update_user(self, user_id: int, username: str, email: str, role: str,
                    active: bool, updated_by: str, expected_version: int) -> bool:
        return self._user_repo.update(user_id, username, email, role, active, updated_by, expected_version)

    def update_user_password(self, user_id: int, password_hash: str, updated_by: str,
                             expected_version: int) -> bool:
        return self._user_repo.update_password(user_id, password_hash, updated_by, expected_version)

    def update_last_login(self, user_id: int) -> bool:
        return self._user_repo.update_last_login(user_id)

    def mark_user_deleted(self, user_id: int, deleted_by: str) -> bool:
        return self._user_repo.mark_user_deleted(user_id, deleted_by)
